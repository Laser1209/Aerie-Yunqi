"""Phase 11 WorldPort contracts and first adapters.

Core depends on this file only: stable DTOs, a five-method WorldPort,
feature-flagged Null/InProcess adapters, and a small capability broker.
The adapters intentionally avoid world-domain rules; deterministic
simulation, relationship state, image decisions, Sidecar RPC, and
world.db ownership arrive in later phases.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Protocol

logger = logging.getLogger(__name__)

WORLD_PROTOCOL = "aerie.world"
WORLD_PROTOCOL_VERSION = "1.0"

WORLD_CAPABILITY_WHITELIST: tuple[str, ...] = (
    "world.read",
    "world.control",
    "relationship.read",
    "image.preview",
    "events.subscribe",
    "checkpoint",
    "message.candidate.publish",
)


@dataclass(frozen=True)
class Observation:
    """Core-to-world observation DTO.

    The raw payload is accepted by an adapter boundary, but public events
    and audit records only expose payload keys plus a digest.  This keeps
    Phase 11 contract tests from accidentally creating a new message-text
    leakage path before later phases define exact world memory rules.
    """

    observation_type: str
    actor_id: str
    channel: str
    payload: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    event_id: str = ""
    occurred_at: str = ""

    def __post_init__(self) -> None:
        if not self.occurred_at:
            object.__setattr__(self, "occurred_at", _now_iso())
        if not self.event_id:
            object.__setattr__(self, "event_id", f"obs_{uuid.uuid4().hex}")

    def payload_digest(self) -> str:
        return _stable_digest(self.payload)

    def redacted_payload(self) -> dict[str, Any]:
        return {
            "payload_keys": sorted(str(key) for key in self.payload.keys()),
            "payload_sha256": self.payload_digest(),
        }


@dataclass(frozen=True)
class WorldSnapshot:
    protocol: str = WORLD_PROTOCOL
    protocol_version: str = WORLD_PROTOCOL_VERSION
    status: str = "disabled"
    source: str = "null"
    instance_id: str = "world-null"
    revision: int = 0
    sequence: int = 0
    paused: bool = False
    phase: str = "unknown"
    location: str = "unknown"
    activity: str = "idle"
    capabilities: tuple[str, ...] = ()
    generated_at: str = ""

    def __post_init__(self) -> None:
        if not self.generated_at:
            object.__setattr__(self, "generated_at", _now_iso())

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "protocol_version": self.protocol_version,
            "status": self.status,
            "source": self.source,
            "instance_id": self.instance_id,
            "revision": self.revision,
            "sequence": self.sequence,
            "paused": self.paused,
            "phase": self.phase,
            "location": self.location,
            "activity": self.activity,
            "capabilities": list(self.capabilities),
            "generated_at": self.generated_at,
        }


@dataclass(frozen=True)
class WorldEvent:
    event_id: str
    topic: str
    event_type: str
    sequence: int
    occurred_at: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "topic": self.topic,
            "event_type": self.event_type,
            "sequence": self.sequence,
            "occurred_at": self.occurred_at,
            "payload": self.payload,
        }


class WorldPort(Protocol):
    async def get_state(self) -> WorldSnapshot:
        ...

    async def observe(self, observation: Observation) -> None:
        ...

    async def subscribe(self, topics: list[str]) -> AsyncIterator[WorldEvent]:
        ...

    async def pause(self) -> None:
        ...

    async def resume(self) -> None:
        ...


class NullWorldAdapter:
    """No-op adapter used when world flags are disabled or unavailable."""

    def __init__(self, *, reason: str = "disabled") -> None:
        self.reason = reason

    async def get_state(self) -> WorldSnapshot:
        return WorldSnapshot(
            status="disabled",
            source="null",
            instance_id="world-null",
            capabilities=(),
        )

    async def observe(self, observation: Observation) -> None:
        return None

    async def subscribe(self, topics: list[str]) -> AsyncIterator[WorldEvent]:
        if False:  # pragma: no cover - keeps this an async generator
            yield WorldEvent(
                event_id="never",
                topic="never",
                event_type="never",
                sequence=0,
                occurred_at=_now_iso(),
            )
        return

    async def pause(self) -> None:
        return None

    async def resume(self) -> None:
        return None


class InProcessWorldAdapter:
    """In-memory adapter for Phase 11 host contracts.

    This adapter is intentionally small: it proves the WorldPort boundary,
    idempotency, redacted event emission, and pause/resume semantics without
    starting a long-running simulation loop or owning a world database.
    """

    def __init__(
        self,
        *,
        instance_id: str | None = None,
        capabilities: tuple[str, ...] | None = None,
    ) -> None:
        requested = capabilities or (
            "world.read",
            "world.control",
            "events.subscribe",
            "checkpoint",
        )
        self.capabilities = tuple(
            cap for cap in requested if cap in WORLD_CAPABILITY_WHITELIST
        )
        self.instance_id = instance_id or f"world_{uuid.uuid4().hex}"
        self._revision = 0
        self._sequence = 0
        self._paused = False
        self._subscribers: dict[str, tuple[set[str], asyncio.Queue[WorldEvent]]] = {}
        self._observed_keys: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def get_state(self) -> WorldSnapshot:
        async with self._lock:
            status = "paused" if self._paused else "running"
            return WorldSnapshot(
                status=status,
                source="in_process",
                instance_id=self.instance_id,
                revision=self._revision,
                sequence=self._sequence,
                paused=self._paused,
                phase="unknown",
                location="unknown",
                activity="idle",
                capabilities=self.capabilities,
            )

    async def observe(self, observation: Observation) -> None:
        if not isinstance(observation, Observation):
            raise TypeError("observation must be an Observation")
        async with self._lock:
            idem = observation.idempotency_key.strip()
            if idem and idem in self._observed_keys:
                return None
            self._revision += 1
            self._sequence += 1
            event = WorldEvent(
                event_id=f"world_evt_{uuid.uuid4().hex}",
                topic="observations",
                event_type="world.observation.recorded",
                sequence=self._sequence,
                occurred_at=observation.occurred_at,
                payload={
                    "observation_type": observation.observation_type,
                    "actor_id": observation.actor_id,
                    "channel": observation.channel,
                    "source_event_id": observation.event_id,
                    **observation.redacted_payload(),
                },
            )
            if idem:
                self._observed_keys[idem] = event.event_id
            subscribers = list(self._subscribers.values())

        self._publish(event, subscribers)
        return None

    async def subscribe(self, topics: list[str]) -> AsyncIterator[WorldEvent]:
        topic_set = _normalize_topics(topics)
        subscriber_id = f"sub_{uuid.uuid4().hex}"
        queue: asyncio.Queue[WorldEvent] = asyncio.Queue()
        async with self._lock:
            self._subscribers[subscriber_id] = (topic_set, queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            async with self._lock:
                self._subscribers.pop(subscriber_id, None)

    async def pause(self) -> None:
        async with self._lock:
            if self._paused:
                return None
            self._paused = True
            self._revision += 1
            self._sequence += 1
            event = self._lifecycle_event("world.paused")
            subscribers = list(self._subscribers.values())
        self._publish(event, subscribers)
        return None

    async def resume(self) -> None:
        async with self._lock:
            if not self._paused:
                return None
            self._paused = False
            self._revision += 1
            self._sequence += 1
            event = self._lifecycle_event("world.resumed")
            subscribers = list(self._subscribers.values())
        self._publish(event, subscribers)
        return None

    def _lifecycle_event(self, event_type: str) -> WorldEvent:
        return WorldEvent(
            event_id=f"world_evt_{uuid.uuid4().hex}",
            topic="lifecycle",
            event_type=event_type,
            sequence=self._sequence,
            occurred_at=_now_iso(),
            payload={
                "status": "paused" if self._paused else "running",
                "revision": self._revision,
            },
        )

    @staticmethod
    def _publish(
        event: WorldEvent,
        subscribers: list[tuple[set[str], asyncio.Queue[WorldEvent]]],
    ) -> None:
        for topics, queue in subscribers:
            if "*" in topics or event.topic in topics:
                queue.put_nowait(event)


@dataclass(frozen=True)
class CapabilityNegotiation:
    plugin_id: str
    granted: tuple[str, ...]
    denied: tuple[str, ...]
    audit_record: dict[str, Any]


class WorldCapabilityBroker:
    """Deterministic capability whitelist for world plugin handshakes."""

    def __init__(self, whitelist: tuple[str, ...] = WORLD_CAPABILITY_WHITELIST) -> None:
        self.whitelist = tuple(dict.fromkeys(whitelist))

    def negotiate(
        self,
        *,
        plugin_id: str,
        requested: list[str] | tuple[str, ...],
        metadata: dict[str, Any] | None = None,
    ) -> CapabilityNegotiation:
        plugin = str(plugin_id or "").strip() or "unknown"
        unique_requested = tuple(dict.fromkeys(str(cap) for cap in requested or ()))
        allowed = set(self.whitelist)
        granted = tuple(cap for cap in unique_requested if cap in allowed)
        denied = tuple(cap for cap in unique_requested if cap not in allowed)
        metadata_keys = sorted(str(key) for key in (metadata or {}).keys())
        audit_record = {
            "plugin_id": plugin,
            "requested_count": len(unique_requested),
            "granted": list(granted),
            "denied": list(denied),
            "metadata_keys": metadata_keys,
            "metadata_keys_sha256": _stable_digest(metadata_keys),
            "created_at": _now_iso(),
        }
        return CapabilityNegotiation(
            plugin_id=plugin,
            granted=granted,
            denied=denied,
            audit_record=audit_record,
        )


def build_world_port(
    *,
    feature_flags: Any,
    instance_id: str | None = None,
) -> WorldPort:
    try:
        enabled = bool(feature_flags.is_enabled("world_inprocess_v1"))
    except Exception:
        logger.exception("failed to read world_inprocess_v1 feature flag")
        enabled = False
    if not enabled:
        return NullWorldAdapter(reason="flag_off")
    return InProcessWorldAdapter(instance_id=instance_id)


def _normalize_topics(topics: list[str] | tuple[str, ...]) -> set[str]:
    normalized = {
        str(topic).strip()
        for topic in (topics or [])
        if str(topic).strip()
    }
    return normalized or {"*"}


def _stable_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
