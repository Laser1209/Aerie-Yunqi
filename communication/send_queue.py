"""Aerie · 云栖 v0.1.0-beta.1 — Send queue with frequency control and human-like pacing.

Supports both single replies and batched replies. The sender function
is injectable, so the queue works for QQ, local chat, or any other
channel that needs paced message delivery.

Phase 9 Batch 2 (complete): pacing is now driven by the
persona-aware decision tree in ``core.persona_pacing``. The first
segment is sent immediately (interval = 0); subsequent segments
select from 11 pacing styles based on emotion label, threshold
state, eruption mode, and segment content. 1.5s is the baseline
(balanced mode), not a hard ceiling — yandere hesitations may
stretch to 5s, contemplative pauses to 4s.

Task 6: Adds SendQueue batch sending with character-count proportional
intervals. Batch replies (with batch_id set) follow these rules:
  - sequence_index == 0: sent immediately (interval = 0).
  - sequence_index > 0: wait BEFORE sending; interval is
    max(base_interval + char_count/cps, persona_interval) with ±30%
    jitter, clamped to [min_interval, max_interval].
  - Batch replies are split by the same splitter as the legacy path (one
    bubble per segment), so QQ 收到的条数与落库/桌面一致，裸分隔符不外发。
  - Non-batch replies (no batch_id) retain the legacy persona_pacing
    segment-splitting logic unchanged.
"""

from __future__ import annotations
import asyncio
import logging
import random
from collections import deque
from typing import Any, Awaitable, Callable, Optional

from communication.message import OutgoingReply
from communication.qq_client import strip_thought_action_tags
from communication.splitter import SemanticMessageSplitter
from config.persona_loader import get_message_batching_config
from core.persona_pacing import compute_persona_interval

logger = logging.getLogger(__name__)

SenderFn = Callable[[OutgoingReply], Awaitable[bool]]
# PacingFn now returns (interval_seconds, style_label)
PacingFn = Callable[..., tuple[float, str]]

_DEFAULT_MAX_QUEUE = 20
# 硬上限：只有 worker 卡死这类极端积压才丢弃，避免内存无界。
# 软上限（_DEFAULT_MAX_QUEUE）只告警、不丢件——静默丢消息会让用户
# 「发了但收不到」，且事后无从排查（含任务进度与审批通知）。
_DEFAULT_HARD_QUEUE = 200
_BALANCED_INTERVAL_MID = 0.675


class SendQueue:
    def __init__(
        self,
        sender: SenderFn,
        splitter: SemanticMessageSplitter | None = None,
        min_interval: float | None = None,  # kept for back-compat (unused when pacing is set)
        recall_manager: Any = None,
        db: Any = None,
        qq_with_segments: Any = None,
        pacing: PacingFn | None = None,
        cognition: Any = None,  # Phase 9 Batch 7 (B7.2): used to persist pacing_decisions
        on_reply_sent: Any = None,  # async/sync callback fired after a reply is delivered
        channel_senders: dict[str, SenderFn] | None = None,
    ) -> None:
        self._sender = sender
        self._channel_senders = {"qq": sender, **(channel_senders or {})}
        self._splitter = splitter or SemanticMessageSplitter()
        self._min_interval = min_interval  # legacy field, ignored when pacing is provided
        self._recall_manager = recall_manager
        self._db = db
        self._qq_segments = qq_with_segments
        self._pacing = pacing or compute_persona_interval
        self._cognition = cognition  # optional CognitionEngine — when set, pacing is persisted
        self._on_reply_sent = on_reply_sent  # post-delivery hook (e.g. sticker sender)
        self._queue: deque[OutgoingReply] = deque()
        self._task: asyncio.Task | None = None
        self._running = False
        self._dropped = 0  # 硬上限触发的累计丢件数（诊断用）

    @property
    def splitter(self) -> SemanticMessageSplitter:
        """本队列使用的切分器（对外只读）。

        Pipeline 与本队列共用同一个实例，保证「落库/桌面分段」与
        「实际发出的分段」切点一致；上限也只有一个所有者。
        """
        return self._splitter

    def _sender_for(self, reply: OutgoingReply) -> SenderFn:
        return self._channel_senders[reply.channel]

    def _admit(self, reply: OutgoingReply) -> bool:
        """入队准入：软上限只告警，硬上限才丢弃。返回是否入队。"""
        depth = len(self._queue)
        if depth >= _DEFAULT_HARD_QUEUE:
            self._dropped += 1
            logger.error(
                "Send queue 深度 %d 已达硬上限，丢弃一条（累计丢弃 %d）→ user=%s；"
                "worker 可能卡住，请查日志确认发送链路",
                depth, self._dropped, reply.user_id,
            )
            return False
        if depth >= _DEFAULT_MAX_QUEUE:
            logger.warning(
                "Send queue 积压 %d 条（软上限 %d），本条仍入队（不丢件）",
                depth, _DEFAULT_MAX_QUEUE,
            )
        return True

    def enqueue(self, reply: OutgoingReply) -> None:
        """Add a single reply to the send queue (QQ messages only)."""
        if self._admit(reply):
            self._queue.append(reply)

    def enqueue_batch(self, replies: list[OutgoingReply]) -> None:
        """Add a batch of replies to the send queue, preserving order.

        Each reply in the list must already have ``batch_id`` and
        ``sequence_index`` set by the caller. The list is assumed to
        be in chronological (ascending sequence_index) order.
        """
        if not replies:
            return
        for reply in replies:
            if not self._admit(reply):
                # 已到硬上限：后续条目同样进不来，直接收尾
                break
            self._queue.append(reply)

    def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._worker())

    def _resolve_emotion_label(self, user_id: int) -> Optional[str]:
        """Look up the most recent emotion label from persistence."""
        if not self._db or not user_id:
            return None
        try:
            row = self._db.query_one(
                "SELECT label FROM emotion_state_snapshot WHERE user_id = ? "
                "ORDER BY id DESC LIMIT 1",
                (user_id,),
            )
            if row:
                return row.get("label")
        except Exception:
            pass
        return None

    def _resolve_threshold_summary(self, user_id: int) -> dict:
        """Look up the most recent threshold summary from persistence.

        Falls back to an empty dict when the snapshot is missing — the
        persona_pacing tree treats missing slots as inactive.
        """
        if not self._db or not user_id:
            return {}
        try:
            row = self._db.query_one(
                "SELECT patience_value, anxiety_value, desire_value, "
                "tenderness_value, active_eruption FROM emotion_state_snapshot "
                "WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (user_id,),
            )
            if not row:
                return {}
            return {
                "patience": {"value": float(row.get("patience_value") or 0.0),
                             "active": bool(row.get("active_eruption") == "patience")},
                "anxiety":  {"value": float(row.get("anxiety_value")  or 0.0),
                             "active": bool(row.get("active_eruption") == "anxiety")},
                "desire":   {"value": float(row.get("desire_value")   or 0.0),
                             "active": bool(row.get("active_eruption") == "desire")},
                "tenderness":{"value": float(row.get("tenderness_value") or 0.0),
                             "active": bool(row.get("active_eruption") == "tenderness")},
            }
        except Exception:
            return {}

    def _compute_batch_interval(
        self,
        reply_content: str,
        emotion_label: Optional[str],
        threshold_summary: dict,
        is_eruption: bool,
        batch_id: Optional[str],
        sequence_index: int,
    ) -> tuple[float, str]:
        """Compute the send interval for a batch reply (sequence_index > 0).

        Implements the character-count proportional interval formula:
          1. Strip <thought>/<action> tags to get plain body.
          2. char_count = len(plain_body).
          3. char_interval = base_interval + char_count / chars_per_second.
          4. Compute persona_interval via persona_pacing (segment_index=1,
             because this is a "subsequent" message within the batch).
          5. Take MAX(char_interval, persona_interval) to respect both
             typing speed and emotional pacing.
          6. Apply ±30% random jitter for natural human feel.
          7. Clamp to [min_interval, max_interval].
          8. If body is empty (fallback reply), use min_interval.

        Returns:
            (interval_seconds, style_label)
        """
        cfg = get_message_batching_config()
        base_interval = cfg["base_interval_seconds"]
        cps = cfg["chars_per_second"]
        min_interval = cfg["min_interval_seconds"]
        max_interval = cfg["max_interval_seconds"]

        plain = strip_thought_action_tags(reply_content or "")
        char_count = len(plain)

        if not plain or char_count == 0:
            logger.info(
                "batch interval fallback (empty body): batch_id=%s seq=%s -> min=%.3fs",
                batch_id, sequence_index, min_interval,
            )
            return (min_interval, "batch_fallback_empty")

        char_interval = base_interval + (char_count / max(cps, 1))

        persona_interval, persona_style = self._pacing(
            segment_index=1,
            emotion_label=emotion_label,
            threshold=threshold_summary,
            is_eruption=is_eruption,
            segment_content=plain,
        )

        interval = max(char_interval, persona_interval)
        jitter = random.uniform(0.7, 1.3)
        interval = interval * jitter
        interval = max(min_interval, min(interval, max_interval))

        logger.debug(
            "batch interval: batch_id=%s seq=%s chars=%d char_interval=%.3f "
            "persona_style=%s persona_interval=%.3f jitter=%.2f -> %.3fs",
            batch_id, sequence_index, char_count, char_interval,
            persona_style, persona_interval, jitter, interval,
        )

        return (interval, f"batch_{persona_style}")

    async def _worker(self) -> None:
        """Consume queue with persona-aware pacing (Phase 9 Batch 2 + Task 6).

        Two modes of operation:

        1. LEGACY MODE (no batch_id):
           - The reply is split into semantic segments.
           - 1st segment: sent immediately (interval = 0).
           - 2nd+ segments: wait AFTER sending; persona decision tree
             selects gaps in 0.4-1.5s baseline, with 5% yandere
             hesitation (2-5s) and 3% contemplative (2.5-4s) overlays.

        2. BATCH MODE (batch_id is set):
           - The reply is NOT re-split (it is already a discrete reply
             within the batch; the splitter is intentionally NOT called
             to preserve the reply boundaries produced by the batch
             processor).
           - sequence_index == 0: sent immediately (interval = 0).
           - sequence_index > 0: wait BEFORE sending; interval computed
             by _compute_batch_interval (max of char-count proportional
             and persona interval, with ±30% jitter, clamped to bounds).
           - Pacing decisions are persisted to cognition_log for
             downstream analysis.
        """
        while self._running:
            if not self._queue:
                await asyncio.sleep(0.5)
                continue

            reply = self._queue.popleft()
            batch_id = getattr(reply, "batch_id", None)

            if batch_id is not None:
                await self._send_batch_reply(reply, batch_id)
            else:
                await self._send_legacy_reply(reply)

    def _backfill_qq_message_id(self, row_id: int, send_result: Any) -> None:
        """Quote V2: persist the platform message_id on the chat_log row.

        Senders now return the OneBot11 message_id (int) on success. Storing
        it lets inbound QQ quotes map QQ message_id -> chat_log.id, and lets
        outbound replies attach a real reply segment.

        ``True`` 表示「发成功但平台没回 message_id」——bool 是 int 的子类，
        不加区分会把成功标志写成伪 id 1，与真实平台 id 1 撞号。
        """
        mid = send_result if isinstance(send_result, int) and not isinstance(
            send_result, bool
        ) else 0
        if not mid or not self._db or not row_id:
            return
        try:
            self._db.update(
                "chat_log",
                {"qq_message_id": int(mid)},
                "id = ?",
                (row_id,),
            )
        except Exception:
            logger.exception(
                "backfill qq_message_id failed for chat_log %s", row_id
            )

    @staticmethod
    def _segment_row_id(reply: OutgoingReply, idx: int) -> int:
        """第 ``idx`` 段对应的 chat_log 行 id。

        落库侧是「一段一行」（Pipeline 逐段 insert），故每段的 qq_message_id
        只能回填到自己那一行；若把所有段都写到首段行上，后写的会覆盖先写的，
        引用映射最终指向最后一段。缺失分段行 id 时只回填首段（msg_id），
        其余段不写——宁可少一次映射，也不写错行。
        """
        row_ids = getattr(reply, "segment_msg_ids", None) or []
        if idx < len(row_ids):
            return int(row_ids[idx] or 0)
        return int(reply.msg_id or 0) if idx == 0 else 0

    def _fire_on_reply_sent(self, reply: OutgoingReply) -> None:
        """Fire the post-delivery hook (e.g. sticker sender) without blocking."""
        if not self._on_reply_sent:
            return
        try:
            result = self._on_reply_sent(reply)
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
        except Exception:
            logger.exception("on_reply_sent hook error for user %s", reply.user_id)

    async def _send_legacy_reply(self, reply: OutgoingReply) -> None:
        """Legacy single-reply path with semantic segment splitting."""
        segments = self._splitter.split(reply.content)
        if not segments:
            # 纯分隔符/空白：没有可发内容，直接收口（绝不把分隔符原文发出去）
            logger.info(
                "skip empty reply for user %s (no outbound content)", reply.user_id
            )
            return
        first_in_batch = True
        use_segments_sender = (
            reply.channel == "qq"
            and
            reply.reply_to_qq_message_id
            and self._qq_segments is not None
        )

        emotion_label = self._resolve_emotion_label(reply.user_id)
        threshold_summary = self._resolve_threshold_summary(reply.user_id)
        is_eruption = bool(getattr(reply, "eruption_mode", None))

        pacing_log: list[dict] = []

        for idx, seg in enumerate(segments):
            reply.content = seg
            ok = False
            try:
                if first_in_batch and use_segments_sender:
                    ok = await self._qq_segments(
                        reply.user_id,
                        seg,
                        reply.reply_to_qq_message_id,
                    )
                else:
                    ok = await self._sender_for(reply)(reply)
                if not ok:
                    logger.warning("QQ send failed for user %s", reply.user_id)
                else:
                    self._backfill_qq_message_id(
                        self._segment_row_id(reply, idx), ok
                    )
                if first_in_batch and ok and reply.channel == "qq" and self._recall_manager:
                    try:
                        self._recall_manager.record_sent(
                            user_id=reply.user_id,
                            content=reply.content,
                            msg_id=reply.msg_id,
                            segments=segments,
                        )
                    except Exception:
                        pass
                first_in_batch = False
            except Exception:
                logger.exception("send worker error")

            interval_sec, style = self._pacing(
                segment_index=idx,
                emotion_label=emotion_label,
                threshold=threshold_summary,
                is_eruption=is_eruption,
                segment_content=seg,
            )
            pacing_log.append({
                "seg_idx": idx,
                "style": style,
                "interval_ms": int(interval_sec * 1000),
                "source": reply.channel,
            })
            if interval_sec > 0:
                await asyncio.sleep(interval_sec)

        if pacing_log:
            logger.debug(
                "QQ pacing for user %s: %s",
                reply.user_id, pacing_log,
            )
            cognition_id = int(getattr(reply, "cognition_id", 0) or 0)
            if self._cognition and cognition_id:
                try:
                    self._cognition.append_pacing_decisions(
                        cognition_id, pacing_log
                    )
                except Exception:
                    logger.exception(
                        "send_queue pacing persist error cognition_id=%s",
                        cognition_id,
                    )

        if reply.channel == "qq":
            self._fire_on_reply_sent(reply)

    async def _send_batch_reply(self, reply: OutgoingReply, batch_id: str) -> None:
        """Send one reply that is part of a batch (Task 6).

        与落库/桌面同切：Pipeline 批量路径已按 ``segments`` 一段一行落库、
        一段一气泡推送桌面，这里用同一个 splitter 实例再切一次，逐段发送，
        绝不把带裸 ``---`` 的整段原样丢给 QQ 用户，保证两端条数一致。
        第一条回复（sequence_index == 0）立即发；后续回复先等一段由字符数与
        情绪共同决定的间隔（``_compute_batch_interval``）再发；条内各段之间
        不再额外停顿——条与条之间的间隔才是批处理的语义。
        """
        seq = getattr(reply, "sequence_index", 0)

        emotion_label = self._resolve_emotion_label(reply.user_id)
        threshold_summary = self._resolve_threshold_summary(reply.user_id)
        is_eruption = bool(getattr(reply, "eruption_mode", None))

        interval_sec = 0.0
        style = "batch_immediate"

        # 间隔按整条原文的字符数算，必须在逐段改写 reply.content 之前得出
        if seq > 0:
            interval_sec, style = self._compute_batch_interval(
                reply_content=reply.content,
                emotion_label=emotion_label,
                threshold_summary=threshold_summary,
                is_eruption=is_eruption,
                batch_id=batch_id,
                sequence_index=seq,
            )
            if interval_sec > 0:
                logger.debug(
                    "batch waiting before send: batch_id=%s seq=%s user=%s interval=%.3fs style=%s",
                    batch_id, seq, reply.user_id, interval_sec, style,
                )
                await asyncio.sleep(interval_sec)
        else:
            logger.debug(
                "batch first reply sending immediately: batch_id=%s seq=%s user=%s",
                batch_id, seq, reply.user_id,
            )

        segments = self._splitter.split(reply.content)
        if not segments:
            # 纯分隔符/空白：没有可发内容，直接收口（绝不把分隔符原文发出去）
            logger.info(
                "skip empty batch reply: batch_id=%s seq=%s user=%s",
                batch_id, seq, reply.user_id,
            )
            return

        use_segments_sender = (
            reply.channel == "qq"
            and
            reply.reply_to_qq_message_id
            and self._qq_segments is not None
        )

        for idx, seg in enumerate(segments):
            reply.content = seg
            ok = False
            try:
                if idx == 0 and use_segments_sender:
                    ok = await self._qq_segments(
                        reply.user_id,
                        seg,
                        reply.reply_to_qq_message_id,
                    )
                else:
                    ok = await self._sender_for(reply)(reply)
                if not ok:
                    logger.warning(
                        "batch send failed: batch_id=%s seq=%s user=%s",
                        batch_id, seq, reply.user_id,
                    )
                else:
                    self._backfill_qq_message_id(
                        self._segment_row_id(reply, idx), ok
                    )
                if (
                    idx == 0
                    and seq == 0
                    and ok
                    and reply.channel == "qq"
                    and self._recall_manager
                ):
                    try:
                        self._recall_manager.record_sent(
                            user_id=reply.user_id,
                            content=seg,
                            msg_id=reply.msg_id,
                            segments=segments,
                        )
                    except Exception:
                        pass
            except Exception:
                logger.exception(
                    "send worker batch error: batch_id=%s seq=%s",
                    batch_id, seq,
                )

        pacing_log = [{
            "seg_idx": seq,
            "style": style,
            "interval_ms": int(interval_sec * 1000),
            "source": "batch",
            "batch_id": batch_id,
        }]
        logger.debug(
            "batch pacing for user %s batch %s seq=%s: %s",
            reply.user_id, batch_id, seq, pacing_log,
        )

        cognition_id = int(getattr(reply, "cognition_id", 0) or 0)
        if self._cognition and cognition_id:
            try:
                self._cognition.append_pacing_decisions(
                    cognition_id, pacing_log
                )
            except Exception:
                logger.exception(
                    "send_queue batch pacing persist error cognition_id=%s batch=%s",
                    cognition_id, batch_id,
                )

        if reply.channel == "qq":
            self._fire_on_reply_sent(reply)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
