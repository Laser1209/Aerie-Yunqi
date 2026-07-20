"""Remote WorldPort adapter baseline for Phase 13."""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from core.world_port import (
    Observation,
    WorldEvent,
    WorldSnapshot,
    _now_iso,
)

logger = logging.getLogger(__name__)


class RemoteWorldAdapter:
    """Adapter over a sidecar client/service.

    The client is intentionally duck-typed.  Tests use
    ``LocalWorldSidecarService``; production can later provide an HTTP/RPC
    client with the same methods.
    """

    def __init__(
        self,
        client: Any,
        *,
        consumer_id: str = "core",
        fallback_reason: str = "sidecar_unavailable",
    ) -> None:
        self.client = client
        self.consumer_id = consumer_id
        self.fallback_reason = fallback_reason

    async def get_state(self) -> WorldSnapshot:
        try:
            state = self.client.get_state()
            return WorldSnapshot(
                status=str(state.get("status") or "running"),
                source="remote",
                instance_id=str(state.get("instance_id") or "world-remote"),
                revision=int(state.get("revision") or 0),
                sequence=int(state.get("sequence") or 0),
                paused=bool(state.get("paused", False)),
                phase=str(state.get("phase") or "unknown"),
                location=str(state.get("location") or "unknown"),
                activity=str(state.get("activity") or "idle"),
                capabilities=tuple(state.get("capabilities") or ()),
            )
        except Exception:
            logger.debug("remote world sidecar unavailable", exc_info=True)
            return WorldSnapshot(
                status="degraded",
                source="remote",
                instance_id="world-remote-unavailable",
                capabilities=(),
            )

    async def observe(self, observation: Observation) -> None:
        try:
            self.client.observe(observation)
        except Exception:
            logger.debug("remote world observe skipped", exc_info=True)
        return None

    async def subscribe(self, topics: list[str]) -> AsyncIterator[WorldEvent]:
        # Phase 13 baseline exposes replay_events(); live transport arrives
        # with the real sidecar protocol. Keep the five-interface contract.
        for event in await self.replay_events():
            if "*" in topics or event.topic in set(topics or []):
                yield event

    async def pause(self) -> None:
        # Sidecar control RPC will be expanded later; no-op is safe.
        return None

    async def resume(self) -> None:
        return None

    async def replay_events(self, *, last_seq: int | None = None) -> list[WorldEvent]:
        try:
            rows = self.client.replay_events(
                consumer_id=self.consumer_id,
                last_seq=last_seq,
            )
        except Exception:
            logger.debug("remote world replay unavailable", exc_info=True)
            return []
        return [self._event_from_payload(row) for row in rows]

    async def ack(self, seq: int) -> dict[str, Any]:
        try:
            return self.client.ack(consumer_id=self.consumer_id, seq=seq)
        except Exception:
            logger.debug("remote world ack unavailable", exc_info=True)
            return {"consumer_id": self.consumer_id, "last_seq": 0, "status": "degraded"}

    @staticmethod
    def _event_from_payload(payload: dict[str, Any]) -> WorldEvent:
        return WorldEvent(
            event_id=str(payload.get("event_id") or ""),
            topic=str(payload.get("topic") or "world"),
            event_type=str(payload.get("event_type") or "world.event"),
            sequence=int(payload.get("seq") or payload.get("sequence") or 0),
            occurred_at=str(payload.get("occurred_at") or _now_iso()),
            payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
        )
