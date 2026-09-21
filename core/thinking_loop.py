"""Aerie · 云栖 — 后台思考循环骨架（默认关闭）。

定位：把"脱离用户请求、持续自省/思考"收成一个**可启停、可观测、有预算上限**
的骨架。本模块只负责"什么时候想、还能不能想、想了多少"，不含任何认知架构。

默认关闭：``enabled=False``（默认值）时 ``start()`` 直接返回 False，不创建
任何 asyncio 任务、不消耗任何 token。接线（谁在什么时候 start/stop、step
里到底做什么）由后续步骤在 ``companion`` 侧完成，本模块不主动启动。

预算控制（用户明确担心"很费 TOKEN"，因此预算是一等公民）：
  - ``interval_seconds``      两次思考之间的间隔（下限 0.05s，防热循环）
  - ``max_steps_per_hour``    每小时最多几步（<=0 表示不限）
  - ``max_steps_per_day``     每天最多几步（<=0 表示不限）
  - ``max_tokens_per_day``    token 预算。语义：``0`` = **禁用**（零额度，任何 step
                              都不执行，防止"以为设了 0 就安全、其实无限烧 token"）；
                              ``<0`` = 显式不限（放弃保护）；未配置 = 安全默认
                              ``DEFAULT_MAX_TOKENS_PER_DAY``
  - ``step_timeout_seconds``  单步超时；同步/异步 step 都生效，超时按失败计，不阻塞后续轮次
  超预算时本轮直接跳过（skip），循环不退出——不会因为额度用光就静默死掉。

``run_once()`` 与后台循环受同一套约束：``enabled=False`` 时不会执行 step、不计 token。

可插拔：构造时传入 ``step`` 回调（sync / async 均可，建议 async）。
回调返回的 dict 若含 ``"tokens": int``，会累加进当日 token 消耗。

异常隔离：单步异常与超时都被捕获并计入 ``errors_total``，循环继续；循环体自身
的异常同样被捕获，不会把主进程或事件循环带崩。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)

MIN_INTERVAL_SECONDS = 0.05
_HISTORY_LIMIT = 20
_DEFAULT_INTERVAL_SECONDS = 900.0  # 15 分钟
_DEFAULT_STEP_TIMEOUT_SECONDS = 120.0
# 未配置 token 预算时的安全默认上限（防止"0 视为不限"导致无限烧 token）
DEFAULT_MAX_TOKENS_PER_DAY = 100_000


@dataclass
class ThinkingBudget:
    """节奏与预算上限。

    ``max_steps_per_hour`` / ``max_steps_per_day``：``<=0`` 表示不限制。
    ``max_tokens_per_day``：``0`` 表示禁用（零额度），``<0`` 表示不限制。
    """

    interval_seconds: float = _DEFAULT_INTERVAL_SECONDS
    max_steps_per_hour: int = 4
    max_steps_per_day: int = 24
    max_tokens_per_day: int = DEFAULT_MAX_TOKENS_PER_DAY
    step_timeout_seconds: float = _DEFAULT_STEP_TIMEOUT_SECONDS

    def normalized(self) -> "ThinkingBudget":
        return ThinkingBudget(
            interval_seconds=max(MIN_INTERVAL_SECONDS, float(self.interval_seconds)),
            max_steps_per_hour=int(self.max_steps_per_hour),
            max_steps_per_day=int(self.max_steps_per_day),
            max_tokens_per_day=int(self.max_tokens_per_day),
            step_timeout_seconds=max(0.1, float(self.step_timeout_seconds)),
        )


async def default_step() -> dict:
    """默认思考步骤：零 token 空转，仅用于验证循环骨架本身。

    真实的思考（读反思队列 / 目标队列 / 调用模型）属于后续接线，不在本模块。
    """
    return {"status": "idle", "reason": "no thinking step wired", "tokens": 0}


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class ThinkingLoop:
    """可启停的后台思考循环。

    用法::

        loop = ThinkingLoop(step=my_step, enabled=True, interval_seconds=900)
        await loop.start()      # 已启用才真的启动，否则返回 False
        ...
        await loop.stop()       # 幂等
        print(loop.status())
    """

    def __init__(
        self,
        step: Callable[[], Any] | None = None,
        *,
        enabled: bool = False,
        interval_seconds: float = _DEFAULT_INTERVAL_SECONDS,
        max_steps_per_hour: int = 4,
        max_steps_per_day: int = 24,
        max_tokens_per_day: int = DEFAULT_MAX_TOKENS_PER_DAY,
        step_timeout_seconds: float = _DEFAULT_STEP_TIMEOUT_SECONDS,
        on_event: Callable[[dict], Any] | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.step: Callable[[], Any] = step or default_step
        self.budget = ThinkingBudget(
            interval_seconds=interval_seconds,
            max_steps_per_hour=max_steps_per_hour,
            max_steps_per_day=max_steps_per_day,
            max_tokens_per_day=max_tokens_per_day,
            step_timeout_seconds=step_timeout_seconds,
        ).normalized()
        self._on_event = on_event

        self._running = False
        self._task: asyncio.Task | None = None

        self._steps_total = 0
        self._steps_hour = 0
        self._steps_day = 0
        self._tokens_day = 0
        self._errors_total = 0
        self._skips_total = 0
        self._last_step_at: str | None = None
        self._last_error: str = ""
        self._last_skip_reason: str = ""
        now = datetime.now()
        self._day_key = now.strftime("%Y-%m-%d")
        self._hour_key = now.strftime("%Y-%m-%dT%H")
        self._history: deque[dict] = deque(maxlen=_HISTORY_LIMIT)

    # ── 配置 ─────────────────────────────────────────

    @classmethod
    def from_config(
        cls,
        cfg: dict | None,
        step: Callable[[], Any] | None = None,
        *,
        on_event: Callable[[dict], Any] | None = None,
    ) -> "ThinkingLoop":
        """从配置字典构造（键名与 settings.yaml 段落一致）。

        未提供的键走默认值；``enabled`` 缺省即 False（默认关闭）。
        """
        data = cfg if isinstance(cfg, dict) else {}
        return cls(
            step=step,
            enabled=bool(data.get("enabled", False)),
            interval_seconds=float(data.get("interval_seconds", _DEFAULT_INTERVAL_SECONDS)),
            max_steps_per_hour=int(data.get("max_steps_per_hour", 4)),
            max_steps_per_day=int(data.get("max_steps_per_day", 24)),
            max_tokens_per_day=int(
                data.get("max_tokens_per_day", DEFAULT_MAX_TOKENS_PER_DAY)
            ),
            step_timeout_seconds=float(
                data.get("step_timeout_seconds", _DEFAULT_STEP_TIMEOUT_SECONDS)
            ),
            on_event=on_event,
        )

    # ── 生命周期 ─────────────────────────────────────

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> bool:
        """启动循环。返回是否真的启动（已启用且此前未运行）。"""
        if self._running:
            return False
        if not self.enabled:
            logger.info("后台思考循环未启用（enabled=False），不启动")
            return False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as e:  # 必须在事件循环内 await start()
            raise RuntimeError("ThinkingLoop.start() 必须在运行中的事件循环内 await") from e

        self._running = True
        self._task = loop.create_task(self._run(), name="aerie-thinking-loop")
        logger.info(
            "后台思考循环已启动（interval=%.1fs, 上限 %d 步/时, %d 步/天, token/天=%s）",
            self.budget.interval_seconds,
            self.budget.max_steps_per_hour,
            self.budget.max_steps_per_day,
            (
                "禁用"
                if self.budget.max_tokens_per_day == 0
                else (
                    "不限"
                    if self.budget.max_tokens_per_day < 0
                    else self.budget.max_tokens_per_day
                )
            ),
        )
        return True

    async def stop(self) -> None:
        """停止循环（幂等，可重复调用）。"""
        if not self._running and self._task is None:
            return
        self._running = False
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("后台思考循环停止时异常")
        logger.info("后台思考循环已停止（累计 %d 步）", self._steps_total)

    # ── 循环体 ───────────────────────────────────────

    async def _run(self) -> None:
        try:
            while self._running:
                await asyncio.sleep(self.budget.interval_seconds)  # 先等一轮再想，避免启动瞬时打扰
                if not self._running:
                    break
                try:
                    await self._tick()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # 循环体自身的意外异常也要隔离，否则任务会静默死掉。
                    self._errors_total += 1
                    self._last_error = "loop tick crashed (see logs)"
                    logger.exception("后台思考循环单轮异常（已隔离，循环继续）")
        except asyncio.CancelledError:
            raise
        finally:
            self._running = False

    async def run_once(self) -> dict | None:
        """立即执行一步（受同样的预算/超时约束）。便于手动触发与测试。

        与后台循环一致：``enabled=False`` 时直接跳过，不执行 step、不计 token。
        """
        if not self.enabled:
            logger.debug("后台思考循环未启用，忽略手动触发")
            return None
        return await self._tick()

    async def _tick(self) -> dict | None:
        self._roll_buckets()

        reason = self._budget_block_reason()
        if reason:
            self._skips_total += 1
            self._last_skip_reason = reason
            logger.debug("后台思考循环本轮跳过：%s", reason)
            self._emit({"type": "skip", "reason": reason})
            return None

        started = time.monotonic()
        try:
            # T2: 同步 step 不能在事件循环里直接调用——否则 step_timeout_seconds
            # 形同虚设（wait_for 拿到的是已求值结果）、还会阻塞整个事件循环。
            # 因此同步 step 丢线程池执行，异步 step 直接 await，二者都受 wait_for 约束。
            if inspect.iscoroutinefunction(self.step):
                work: Any = self.step()
            else:
                work = asyncio.to_thread(self.step)
            result = await asyncio.wait_for(
                _maybe_await(work),
                timeout=self.budget.step_timeout_seconds,
            )
        except asyncio.TimeoutError:
            self._errors_total += 1
            self._last_error = f"step timeout ({self.budget.step_timeout_seconds}s)"
            logger.warning("后台思考步骤超时（%.1fs）", self.budget.step_timeout_seconds)
            self._emit({"type": "error", "kind": "timeout", "message": self._last_error})
            return None
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._errors_total += 1
            self._last_error = f"{type(e).__name__}: {e}"
            logger.exception("后台思考步骤失败（已隔离）")
            self._emit({"type": "error", "kind": "exception", "message": self._last_error})
            return None

        self._steps_total += 1
        self._steps_hour += 1
        self._steps_day += 1
        self._last_step_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tokens = result.get("tokens") if isinstance(result, dict) else None
        if isinstance(tokens, int) and tokens > 0:
            self._tokens_day += tokens
        self._emit({
            "type": "step",
            "duration_ms": int((time.monotonic() - started) * 1000),
            "tokens": tokens if isinstance(tokens, int) else 0,
            "state": result.get("status") if isinstance(result, dict) else None,
        })
        return result

    # ── 预算 ─────────────────────────────────────────

    def record_tokens(self, tokens: int) -> None:
        """外部上报 token 消耗（step 不方便在返回值里带 tokens 时用）。"""
        if isinstance(tokens, int) and tokens > 0:
            self._roll_buckets()
            self._tokens_day += tokens

    def _budget_block_reason(self) -> str:
        if self.budget.max_steps_per_hour > 0 and self._steps_hour >= self.budget.max_steps_per_hour:
            return "hourly_step_limit"
        if self.budget.max_steps_per_day > 0 and self._steps_day >= self.budget.max_steps_per_day:
            return "daily_step_limit"
        # T3: token 预算语义——0 = 禁用（零额度立即拦截，避免出厂值 0 被当成"不限"
        # 而无限烧 token）；<0 = 显式不限。
        limit = self.budget.max_tokens_per_day
        if limit >= 0 and self._tokens_day >= limit:
            return "daily_token_limit"
        return ""

    def _roll_buckets(self) -> None:
        now = datetime.now()
        day_key = now.strftime("%Y-%m-%d")
        hour_key = now.strftime("%Y-%m-%dT%H")
        if day_key != self._day_key:
            self._day_key = day_key
            self._steps_day = 0
            self._tokens_day = 0
        if hour_key != self._hour_key:
            self._hour_key = hour_key
            self._steps_hour = 0

    # ── 观测 ─────────────────────────────────────────

    def status(self) -> dict:
        """状态快照（可观测接口）。"""
        return {
            "enabled": self.enabled,
            "running": self._running,
            "interval_seconds": self.budget.interval_seconds,
            "budget": {
                "max_steps_per_hour": self.budget.max_steps_per_hour,
                "max_steps_per_day": self.budget.max_steps_per_day,
                "max_tokens_per_day": self.budget.max_tokens_per_day,
                "step_timeout_seconds": self.budget.step_timeout_seconds,
            },
            "steps_total": self._steps_total,
            "steps_this_hour": self._steps_hour,
            "steps_today": self._steps_day,
            "tokens_today": self._tokens_day,
            "errors_total": self._errors_total,
            "skips_total": self._skips_total,
            "last_step_at": self._last_step_at,
            "last_error": self._last_error,
            "last_skip_reason": self._last_skip_reason,
            "history": list(self._history),
        }

    def _emit(self, event: dict) -> None:
        entry = {"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), **event}
        self._history.append(entry)
        if self._on_event is None:
            return
        try:
            outcome = self._on_event(entry)
            if inspect.isawaitable(outcome):
                asyncio.create_task(_maybe_await(outcome))
        except Exception:
            logger.exception("思考循环事件回调异常（已忽略）")
