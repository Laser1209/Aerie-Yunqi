"""投递回执台账：让"文件/图片到底发出去没"能回到下一轮对话。

**为什么需要它**

文件投递是**异步入队**的（工具返回 `status="queued"`，真正的发送发生在发送队列
的 worker 里）。历史上失败只进日志：

```python
except Exception:
    logger.exception("微信文件发送异常: %s", path)   # ← 只进日志，不回写模型
```

于是模型看到的永远是"已入队"，它**没有撒谎的动机，只是没有渠道知道失败**，
下一轮照旧宣称"已经发给你了"（实测 2026-09-28 的三端假成功）。

本模块把投递结果落成**回执**，由 pipeline 在下一轮注入系统提示 —— 模型于是
能如实说"那个文件没发出去，因为……"。

**设计取舍**

* 进程内台账（不落盘）：投递结果只在"紧接着的下一轮"有意义；
  重启后旧回执已过期，报出来反而误导。
* 只报**失败**与**长时间未决**：成功无需打扰模型（它已经说了"我发过去了"）。
* 用户维度隔离：A 会话的失败不该出现在 B 会话的上下文里。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# 未决回执超过该秒数后，下一轮按"结果未知"上报 —— 总比永远沉默好。
PENDING_GRACE_SECONDS = 90.0

# 同一用户最多保留的回执条数（防止长期运行内存无界增长）。
_MAX_RECEIPTS_PER_USER = 20


@dataclass
class DeliveryReceipt:
    """一次投递的回执。``ok is None`` 表示尚未得到结果。"""

    delivery_id: str
    user_id: int
    channel: str
    path: str = ""
    note: str = ""
    ok: bool | None = None
    detail: str = ""
    created_at: float = field(default_factory=time.time)
    resolved_at: float | None = None
    reported: bool = False

    def to_prompt_line(self) -> str:
        """渲染成给模型看的一行中文说明。"""
        name = self.path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] if self.path else "那份文件"
        where = {"qq": "QQ", "ilink": "微信", "local_chat": "桌面端"}.get(
            self.channel, self.channel or "会话"
        )
        if self.ok is False:
            reason = f"（{self.detail}）" if self.detail else ""
            return (
                f"你刚才想通过{where}发给用户的「{name}」**并没有送达**{reason}。"
                f"如果用户还在等这个文件，请如实告知失败，不要再说已经发过去了。"
            )
        # ok is None：入队后迟迟没有结果 —— 如实说明不确定，而不是替它断言成功。
        return (
            f"你之前通过{where}发给用户「{name}」的投递**结果未知**（队列未见回执）。"
            f"若用户追问是否收到，请说「我不确定，可以再发一次」，不要断言已送达。"
        )


class DeliveryLedger:
    """进程内投递回执台账（按用户分桶，线程安全）。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_user: dict[int, list[DeliveryReceipt]] = {}
        self._index: dict[str, DeliveryReceipt] = {}

    @staticmethod
    def new_id() -> str:
        return f"dlv_{uuid.uuid4().hex[:12]}"

    def record_pending(
        self,
        *,
        user_id: int,
        channel: str,
        path: str = "",
        note: str = "",
        delivery_id: str = "",
    ) -> str:
        """登记一次"已入队、结果待定"的投递，返回 delivery_id 供回执时对账。"""
        delivery_id = delivery_id or self.new_id()
        receipt = DeliveryReceipt(
            delivery_id=delivery_id,
            user_id=int(user_id or 0),
            channel=str(channel or ""),
            path=str(path or ""),
            note=str(note or ""),
        )
        with self._lock:
            self._index[delivery_id] = receipt
            bucket = self._by_user.setdefault(receipt.user_id, [])
            bucket.append(receipt)
            if len(bucket) > _MAX_RECEIPTS_PER_USER:
                for stale in bucket[:-_MAX_RECEIPTS_PER_USER]:
                    self._index.pop(stale.delivery_id, None)
                del bucket[:-_MAX_RECEIPTS_PER_USER]
        return delivery_id

    def record_outcome(
        self,
        delivery_id: str,
        *,
        ok: bool,
        detail: str = "",
    ) -> None:
        """回填投递结果。未知 delivery_id 时静默忽略（调用方可能没登记）。"""
        if not delivery_id:
            return
        with self._lock:
            receipt = self._index.get(delivery_id)
            if receipt is None:
                return
            receipt.ok = bool(ok)
            receipt.detail = str(detail or "")
            receipt.resolved_at = time.time()

    def get(self, delivery_id: str) -> DeliveryReceipt | None:
        """按 id 取回执；不存在返回 None（测试与诊断用）。"""
        with self._lock:
            return self._index.get(str(delivery_id or ""))

    async def wait_outcome(
        self,
        delivery_id: str,
        *,
        timeout: float,
        poll_interval: float = 0.2,
    ) -> DeliveryReceipt | None:
        """等到该投递有结论（成功 / 失败）为止。

        §十四 #67：`send_file_to_user` 需要"真等送达"才能如实回话，而发送发生在
        同一个事件循环的发送队列 worker 里 —— 所以只能异步轮询，不能阻塞等待。

        返回：已落定的回执；**超时则返回当前（仍未决）的回执**（``ok is None``），
        由调用方区分"结果未知"与"失败"。台账里没有该 id 时返回 None。
        """
        if not delivery_id:
            return None
        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            receipt = self.get(delivery_id)
            if receipt is None or receipt.ok is not None:
                return receipt
            if time.monotonic() >= deadline:
                return receipt
            await asyncio.sleep(poll_interval)

    def drain_unreported(self, user_id: int) -> list[DeliveryReceipt]:
        """取出该用户尚未上报的回执（失败 + 长时间未决），并标记为已上报。

        成功且已上报的不再重复打扰模型。

        同时包含 ``user_id=0`` 桶：那是"入队时无法定位接收方"（例如主动配图时
        没有近期会话通道）的记录。这类记录**同样意味着没发出去**，而它恰恰最
        需要被说出来 —— 否则模型会照旧宣称已送达。
        """
        now = time.time()
        out: list[DeliveryReceipt] = []
        with self._lock:
            buckets = [self._by_user.get(int(user_id or 0), [])]
            if int(user_id or 0) != 0:
                buckets.append(self._by_user.get(0, []))
            for bucket in buckets:
                for receipt in bucket:
                    if receipt.reported:
                        continue
                    if receipt.ok is True:
                        # 成功无需上报：模型已经说过"我发过去了"。
                        receipt.reported = True
                        continue
                    if receipt.ok is None and (now - receipt.created_at) < PENDING_GRACE_SECONDS:
                        # 刚入队，还没到可以下结论的时间 —— 留到下一轮再看。
                        continue
                    receipt.reported = True
                    out.append(receipt)
        return out

    def pending_count(self, user_id: int = 0) -> int:
        """未决回执条数（测试与诊断用）。"""
        with self._lock:
            buckets = (
                [self._by_user.get(int(user_id), [])]
                if user_id
                else list(self._by_user.values())
            )
            return sum(1 for b in buckets for r in b if r.ok is None)

    def has_recent_success(self, user_id: int, *, within_seconds: float = 600.0) -> bool:
        """该用户近期是否有**成功**的投递。

        用于"声称已发"的事实核查：短时间内真的投递成功过，就不该拦截
        模型的完成态表述（它说的是实情）。
        """
        cutoff = time.time() - max(1.0, float(within_seconds))
        with self._lock:
            for receipt in self._by_user.get(int(user_id or 0), []):
                if receipt.ok is True and (receipt.resolved_at or receipt.created_at) >= cutoff:
                    return True
        return False

    def has_pending(self, user_id: int) -> bool:
        """该用户是否有"已入队、结果未定"的投递（在途）。

        在途意味着"确实发了、只是还没结果"，此时模型的"我发过去了"是诚实的。
        """
        with self._lock:
            for receipt in self._by_user.get(int(user_id or 0), []):
                if receipt.ok is None:
                    return True
        return False

    def clear(self) -> None:
        """测试/停机清理。"""
        with self._lock:
            self._by_user.clear()
            self._index.clear()


_LEDGER: DeliveryLedger | None = None


def get_ledger() -> DeliveryLedger:
    global _LEDGER
    if _LEDGER is None:
        _LEDGER = DeliveryLedger()
    return _LEDGER


def build_feedback_note(user_id: int) -> str:
    """生成给模型的投递反馈片段；无内容时返回空串。"""
    try:
        receipts = get_ledger().drain_unreported(user_id)
    except Exception:
        logger.debug("delivery ledger drain failed", exc_info=True)
        return ""
    if not receipts:
        return ""
    lines = [r.to_prompt_line() for r in receipts]
    return "[投递回执] " + "\n".join(lines)


def describe_failure(exc: BaseException | str) -> str:
    """把投递异常收敛成一句人话，便于写进回执。"""
    text = str(exc or "")
    lowered = text.lower()
    # 顺序有讲究：具体判断必须排在泛化判断之前。
    # "readtimeout" 里也含 "timeout"，若先判 timeout 就会把它吞成笼统的"上传超时"。
    if "readtimeout" in lowered or "read timeout" in lowered:
        return "上传读超时"
    if "writetimeout" in lowered or "write timeout" in lowered:
        return "上传写超时"
    if "timeout" in lowered or "timed out" in lowered:
        return "上传超时"
    if "401" in text or "403" in text or "auth" in lowered:
        return "鉴权失败"
    if "connection" in lowered or "network" in lowered or "unreachable" in lowered:
        return "网络不可达"
    if "too large" in lowered or "413" in text:
        return "文件超出通道体积上限"
    return text[:120] if text else "原因未知"
