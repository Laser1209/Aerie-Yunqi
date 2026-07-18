"""Aerie · 云栖 v13.9.8 — Send queue with frequency control and human-like pacing.

Only receives QQ replies; local chat-bar replies skip this queue.

Phase 9 Batch 2 (complete): pacing is now driven by the
persona-aware decision tree in ``core.persona_pacing``. The first
segment is sent immediately (interval = 0); subsequent segments
select from 11 pacing styles based on emotion label, threshold
state, eruption mode, and segment content. 1.5s is the baseline
(balanced mode), not a hard ceiling — yandere hesitations may
stretch to 5s, contemplative pauses to 4s.
"""

from __future__ import annotations
import asyncio
import logging
from collections import deque
from typing import Any, Awaitable, Callable, Optional

from communication.message import OutgoingReply
from communication.splitter import SemanticMessageSplitter
from core.persona_pacing import compute_persona_interval

logger = logging.getLogger(__name__)

SenderFn = Callable[[OutgoingReply], Awaitable[bool]]
# PacingFn now returns (interval_seconds, style_label)
PacingFn = Callable[..., tuple[float, str]]

_DEFAULT_MAX_QUEUE = 20


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
    ) -> None:
        self._sender = sender
        self._splitter = splitter or SemanticMessageSplitter()
        self._min_interval = min_interval  # legacy field, ignored when pacing is provided
        self._recall_manager = recall_manager
        self._db = db
        self._qq_segments = qq_with_segments
        self._pacing = pacing or compute_persona_interval
        self._cognition = cognition  # optional CognitionEngine — when set, pacing is persisted
        self._queue: deque[OutgoingReply] = deque()
        self._task: asyncio.Task | None = None
        self._running = False

    def enqueue(self, reply: OutgoingReply) -> None:
        """Add a reply to the send queue (QQ messages only)."""
        if len(self._queue) >= _DEFAULT_MAX_QUEUE:
            logger.warning("Send queue full, dropping reply to %s", reply.user_id)
            return
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

    async def _worker(self) -> None:
        """Consume queue with persona-aware pacing (Phase 9 Batch 2).

        Per-batch behaviour:
          - 1st segment: sent immediately (interval = 0).
          - 2nd+ segments: persona decision tree, gaps in 0.4-1.5s
            baseline, with 5% yandere hesitation (2-5s) and 3%
            contemplative (2.5-4s) overlays.
          - Pacing decisions are logged in memory for downstream
            analysis; they do not write to cognition_log here because
            the Pipeline has already committed the trace.
        """
        while self._running:
            if not self._queue:
                await asyncio.sleep(0.5)
                continue

            reply = self._queue.popleft()
            segments = self._splitter.split(reply.content)
            first_in_batch = True
            use_segments_sender = (
                reply.reply_to_qq_message_id
                and self._qq_segments is not None
            )

            # Resolve emotion + threshold + eruption state once per batch
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
                        ok = await self._sender(reply)
                    if not ok:
                        logger.warning("QQ send failed for user %s", reply.user_id)
                    # Phase 4: hook into recall manager on first segment
                    if first_in_batch and ok and self._recall_manager:
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

                # Phase 9 Batch 2: persona-aware pacing
                # The first segment returns (0.0, "immediate") and we
                # don't sleep at all. Subsequent segments choose from
                # the 11-style decision tree.
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
                    "source": "qq",
                })
                if interval_sec > 0:
                    await asyncio.sleep(interval_sec)

            if pacing_log:
                logger.debug(
                    "QQ pacing for user %s: %s",
                    reply.user_id, pacing_log,
                )
                # Phase 9 Batch 7 (B7.2): persist the pacing decisions
                # back into the originating cognition_log row, so the
                # brain-center UI can show the actual gaps the user
                # observed (not just the predicted ones from the local
                # path's pre-commit computation).
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

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

