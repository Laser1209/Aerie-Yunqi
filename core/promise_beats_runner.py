"""Aerie · PromiseBeatsRunner — 承诺节拍的自驱动兑现循环（Promise Beats 子系统）.

轮询 BeatStore 中到期的 ScheduledBeat，按 kind 兑现（第一版仅 go_out）：

1. **世界状态先行**：调 world.go_out(source="self_promise")，她真的出门，
   世界快照（outdoor/outdoor_place/activity）随之改变；
2. **出图**：发布 role_in_scene 图片候选（图生图锁她本人形象），
   复用现有 publish_image_candidate → consumer 链路；
3. **出图失败的分流**（用户明确要求）：不弹失败窗、不显示重拍按钮，
   改为让 LLM 生成一段符合表达规范的合理化解释（短、无句号、无破折号），
   作为普通消息投递——承诺以"解释/岔开"兑现，beat 仍标 fired；
4. **彻底无法兑现**（连续 max_attempts 轮）：标 failed，不静默丢失、不永生重试。

本模块不依赖 Companion：世界动作/快照/投递上下文/出图/投递均以端口
（闭包）注入，Companion 只在组合根接线，行为逻辑可脱离重型对象测试。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import re
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

from core.scheduled_beats import BeatStore, ScheduledBeat

logger = logging.getLogger(__name__)

_RESTART_DELAY_SEC = 5.0
_MIN_POLL_SEC = 30.0

_FALLBACK_SYSTEM = (
    "你是伊塔本人。你本来想把出门的样子拍给对方看，但照片没发出来。"
    "不要解释技术原因、不要提照片生成、别说对不起。"
    "像真人发微信一样，自然地解释一句或顺手岔开：比如路上不太方便、"
    "先处理下手头的事、一会儿就回。\n"
    "硬要求：只输出要发给对方的话；一到两条，每条不超过15字；"
    "不打句号，不用破折号，换行就是另一条；口语、亲昵。"
)


def sanitize_fallback_text(value: Any) -> str:
    """把 LLM 输出规整成可直接外发的解释文段（确定性兜底）。

    - 去破折号；句号/感叹/问号/换行统一切成多条硬边界；
    - 最多两条，每条硬截 20 字（规范 15，LLM 偶发超长的兜底）；
    - 全空 → ""。
    """
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace("——", "").replace("–", "").replace("—", "")
    raw_lines = [
        segment.strip(" \t。！!？?，,、；;")
        for segment in re.split(r"[。！!？?\n]+", text)
    ]
    lines = [line for line in raw_lines if line][:2]
    return "\n".join(line[:20] for line in lines)


class PromiseBeatsRunner:
    """承诺节拍轮询与兑现的编排器（Companion 注入端口后调用 run_forever）。"""

    def __init__(
        self,
        *,
        brain: Any,
        feature_flags: Any,
        settings: Optional[dict],
        world_action: Callable[[str], Any],
        world_snapshot: Callable[[], dict],
        delivery_context: Callable[[], dict],
        image_publisher: Callable[[dict], Awaitable[dict]],
        text_deliverer: Callable[[str], Awaitable[bool]],
        store: Optional[BeatStore] = None,
        max_attempts: int = 3,
    ) -> None:
        self._brain = brain
        self._feature_flags = feature_flags
        self._settings = settings if isinstance(settings, dict) else {}
        self._world_action = world_action
        self._world_snapshot = world_snapshot
        self._delivery_context = delivery_context
        self._image_publisher = image_publisher
        self._text_deliverer = text_deliverer
        self._cfg = self._settings.get("promise_beats", {}) or {}
        self._store = store or BeatStore(
            max_pending=int(self._cfg.get("max_pending", 2)),
        )
        self._max_attempts = max(1, int(max_attempts))

    # ── 生命周期 ───────────────────────────────────────

    async def run_forever(self) -> None:
        """看门狗：内层轮询任务异常退出时重启（仿 _supervise_world_loop）。"""
        while True:
            task = asyncio.create_task(self._run())
            try:
                await task
            except asyncio.CancelledError:
                task.cancel()
                raise
            except Exception:
                logger.error("[BeatLoop] task died, restarting", exc_info=True)
            await asyncio.sleep(_RESTART_DELAY_SEC)

    async def _run(self) -> None:
        poll_sec = max(_MIN_POLL_SEC, float(self._cfg.get("poll_sec", 60)))
        while True:
            await asyncio.sleep(poll_sec)
            await self.tick()

    # ── 单轮行为（也供测试直接驱动）────────────────────

    async def tick(self) -> None:
        """一次轮询：flag 关闭则跳过；重载磁盘 → 兑现全部到期 beat。"""
        if not self._feature_flags.is_enabled("promise_beats_v1"):
            return
        self._store.reload()
        for beat in self._store.due():
            try:
                await self.fire(beat)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("[BeatLoop] fire failed beat=%s", beat.id, exc_info=True)

    async def fire(self, beat: ScheduledBeat) -> None:
        """兑现单条 beat：出门 → 出图；出图失败 → 解释文段；都失败 → 记尝试。"""
        # 1) 世界状态先行（她真的出门，出图以世界为上下文）。
        try:
            outcome = self._world_action(str(beat.place_hint or ""))
            if inspect.isawaitable(outcome):
                await outcome
        except Exception:
            logger.debug("[BeatLoop] world action failed beat=%s", beat.id, exc_info=True)

        snapshot = self._safe_snapshot()

        # 2) 出图：她本人入镜（role_in_scene，走图生图锁形象）。
        published = False
        try:
            result = await self._image_publisher(self._image_payload(beat))
            published = self._image_completed(result)
        except Exception:
            logger.warning("[BeatLoop] image publish failed beat=%s", beat.id, exc_info=True)
        if published:
            self._store.mark_fired(beat.id)
            logger.info("[BeatLoop] fired beat=%s topic=%s", beat.id, beat.topic)
            return

        # 3) 出图失败：合理化解释文段（不弹窗、不重拍）。
        text = await self._compose_fallback(beat, snapshot)
        delivered = False
        if text:
            try:
                delivered = bool(await self._text_deliverer(text))
            except Exception:
                logger.warning("[BeatLoop] fallback delivery failed", exc_info=True)
        if delivered:
            self._store.mark_fired(beat.id)
            logger.info("[BeatLoop] fired via fallback beat=%s", beat.id)
            return

        # 4) 本轮彻底没兑现：记尝试；超过窗口标 failed（不静默丢失、不永生）。
        self._store.mark_attempt(beat.id)
        fresh = self._store.get(beat.id)
        if fresh is not None and fresh.attempts >= self._max_attempts:
            self._store.mark_failed(beat.id)
            logger.warning("[BeatLoop] beat failed after %d attempts id=%s",
                           fresh.attempts, beat.id)

    # ── 出图 ───────────────────────────────────────────

    def _image_payload(self, beat: ScheduledBeat) -> dict:
        delivery = self._safe_delivery_context()
        master_id = str(delivery.get("master_id") or "")
        persona_id = str(delivery.get("persona_id") or "")
        payload: dict[str, Any] = {
            "candidate_id": f"promise-beat-{beat.id}",
            "idempotency_key": f"promise-beat:{beat.id}",
            "scene": "promise_beat",
            "owner_id": master_id,
            "channel": str(delivery.get("channel") or "local_chat"),
            "target": master_id,
            "prompt_key": "role_in_scene",
            "reason_code": f"promise_beat:{beat.id}",
            "source": "promise",
            "score": 0.8,
            "size": "portrait_4_3",
            "user_raw": beat.topic or beat.source_text,
        }
        if persona_id:
            payload["persona_id"] = persona_id
        return payload

    @staticmethod
    def _image_completed(result: Any) -> bool:
        """publish_image_candidate 返回中是否有消费完成（completed）的结果。"""
        if not isinstance(result, dict):
            return False
        consumed = result.get("consumed")
        if not isinstance(consumed, list) or not consumed:
            return False
        return any(
            isinstance(item, dict) and str(item.get("status")) == "completed"
            for item in consumed
        )

    # ── 失败解释 ───────────────────────────────────────

    async def _compose_fallback(
        self, beat: ScheduledBeat, snapshot: dict
    ) -> str:
        place = str(snapshot.get("outdoor_place") or "")
        situation = "、".join(
            part
            for part in (
                str(snapshot.get("phase") or ""),
                str(snapshot.get("activity") or ""),
                f"在{place}" if place else "",
            )
            if part
        )
        prompt = (
            f"你之前说过：{beat.source_text}\n"
            f"现在的情况：{situation or '在家'}，大约{datetime.now().hour}点\n"
            "给对方发一到两句话"
        )
        try:
            raw = await self._brain.chat(
                [
                    {"role": "system", "content": _FALLBACK_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                preferred_provider="siliconflow-light",
                temperature=0.8,
            )
        except Exception:
            logger.debug("[BeatLoop] fallback LLM failed", exc_info=True)
            return ""
        return sanitize_fallback_text(getattr(raw, "text", raw))

    # ── 端口安全读取 ───────────────────────────────────

    def _safe_snapshot(self) -> dict:
        try:
            snapshot = self._world_snapshot()
            return snapshot if isinstance(snapshot, dict) else {}
        except Exception:
            logger.debug("[BeatLoop] snapshot read failed", exc_info=True)
            return {}

    def _safe_delivery_context(self) -> dict:
        try:
            context = self._delivery_context()
            return context if isinstance(context, dict) else {}
        except Exception:
            logger.debug("[BeatLoop] delivery context failed", exc_info=True)
            return {}
