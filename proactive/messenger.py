"""Aerie · 云栖 v9.0 — Proactive messenger.

Coordinates PushPolicy → Brain → SendQueue → push_log for any
proactive scene.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from communication.message import MessageType, OutgoingReply
from communication.send_queue import SendQueue
from core.brain import Brain
from core.database import Database
from core.emotion_engine import EmotionEngine
from proactive.policy import PushPolicy
from config.persona_loader import load_proactive


class ProactiveMessenger:
    """Drives end-to-end proactive push pipeline."""

    def __init__(
        self,
        policy: PushPolicy,
        brain: Brain,
        emotion_engine: EmotionEngine,
        send_queue: SendQueue,
        db: Optional[Database] = None,
        config: Optional[dict] = None,
    ) -> None:
        self.policy = policy
        self.brain = brain
        self.emotion = emotion_engine
        self.queue = send_queue
        self.db = db or Database()
        self.config = config or load_proactive()

    def _log(self, scene: str, user_id: int, content: str, status: str, reason: str = "") -> None:
        try:
            self.db.insert(
                "push_log",
                {
                    "scene": scene,
                    "user_id": user_id,
                    "content": content,
                    "status": status,
                    "reason": reason,
                    "skip_reason": reason if status.startswith("skipped") else None,
                },
            )
        except Exception:
            pass

    async def push(
        self,
        scene: str,
        master_id: int,
        template: str,
        skip_policy: bool = False,
        **kwargs: Any,
    ) -> dict:
        """Execute a proactive push for the given scene.

        Returns {status, content, reason}.
        """
        if not skip_policy:
            allowed, reason = self.policy.can_push(scene)
            if not allowed:
                self._log(scene, master_id, "", f"skipped_{reason}", reason)
                return {"status": f"skipped_{reason}", "content": "", "reason": reason}

        try:
            mood = self.emotion.get_current_mood(master_id)
            content = await self.brain.generate_push(
                template=template,
                mood=mood,
                user_id=master_id,
                **kwargs,
            )
            if not content:
                content = template

            reply = OutgoingReply(
                user_id=master_id,
                content=content,
                msg_type=MessageType.PROACTIVE,
                scene="proactive",
                mood=mood,
            )
            self.queue.enqueue(reply, splitter=True)
            self.policy.record(scene)
            self._log(scene, master_id, content, "success")
            return {"status": "success", "content": content, "reason": ""}
        except Exception as e:
            self._log(scene, master_id, "", "failed", str(e)[:200])
            return {"status": "failed", "content": "", "reason": str(e)[:200]}

    def get_recent_logs(self, limit: int = 20) -> list[dict]:
        return self.db.query(
            "SELECT scene, user_id, content, status, reason, created_at "
            "FROM push_log ORDER BY id DESC LIMIT ?",
            (limit,),
        )
