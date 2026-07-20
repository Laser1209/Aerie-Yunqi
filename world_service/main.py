"""Local world sidecar service baseline for Phase 13.

This module intentionally exposes an in-process callable service instead of
starting an HTTP server in tests.  It owns ``world.db`` and mirrors the RPC
shape needed by ``RemoteWorldAdapter``; later phases can replace the client
transport without changing Core call sites.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from world_service.storage.sqlite_store import WorldSidecarStore


class LocalWorldSidecarService:
    protocol = "aerie.world"
    protocol_version = "1.0"
    service_version = "0.1.0"

    def __init__(self, *, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = WorldSidecarStore(self.data_dir / "world.db")
        self.running = True
        self.instance_id = "world-local-sidecar"
        self.capabilities = (
            "world.read",
            "world.control",
            "events.subscribe",
            "checkpoint",
            "message.candidate.publish",
        )
        self.store.heartbeat(status="ready", detail={"instance_id": self.instance_id})

    def hello(self) -> dict[str, Any]:
        self._ensure_running()
        return {
            "type": "hello",
            "protocol": self.protocol,
            "protocol_version": self.protocol_version,
            "service_version": self.service_version,
            "instance_id": self.instance_id,
            "capabilities": list(self.capabilities),
        }

    def health(self) -> dict[str, Any]:
        if not self.running:
            return {"ok": False, "status": "crashed", "instance_id": self.instance_id}
        heartbeat = self.store.heartbeat(
            status="ready",
            detail={"instance_id": self.instance_id},
        )
        return {
            "ok": True,
            "status": "ready",
            "instance_id": self.instance_id,
            "heartbeat": heartbeat,
        }

    def get_state(self) -> dict[str, Any]:
        self._ensure_running()
        return {
            "status": "running",
            "source": "remote",
            "instance_id": self.instance_id,
            "sequence": self.store.cursor("core"),
            "capabilities": list(self.capabilities),
        }

    def observe(self, observation: Any) -> dict[str, Any]:
        self._ensure_running()
        payload = {
            "observation_type": getattr(observation, "observation_type", "unknown"),
            "actor_id": getattr(observation, "actor_id", ""),
            "channel": getattr(observation, "channel", ""),
            "payload": getattr(observation, "payload", {}),
            "source_event_id": getattr(observation, "event_id", ""),
        }
        return self.store.append_event(
            topic="observations",
            event_type="world.observation.recorded",
            payload=payload,
            idempotency_key=getattr(observation, "idempotency_key", "") or payload["source_event_id"],
        )

    def replay_events(
        self,
        *,
        consumer_id: str = "core",
        last_seq: int | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_running()
        return self.store.events_after(consumer_id=consumer_id, last_seq=last_seq)

    def ack(self, *, consumer_id: str = "core", seq: int) -> dict[str, Any]:
        self._ensure_running()
        return self.store.ack(consumer_id=consumer_id, seq=seq)

    def checkpoint(self, *, checkpoint_id: str, state: dict[str, Any]) -> dict[str, Any]:
        self._ensure_running()
        return self.store.checkpoint(checkpoint_id=checkpoint_id, state=state)

    def publish_image_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        self._ensure_running()
        return self.store.append_image_candidate(candidate)

    def crash(self) -> None:
        self.running = False
        self.store.heartbeat(status="crashed", detail={"instance_id": self.instance_id})

    def restart(self) -> None:
        self.running = True
        self.store.heartbeat(status="ready", detail={"instance_id": self.instance_id})

    def _ensure_running(self) -> None:
        if not self.running:
            raise RuntimeError("world sidecar unavailable")
