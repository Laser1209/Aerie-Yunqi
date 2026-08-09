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
import os
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
    enabled: bool = False
    desired: str = "stopped"
    actual: str = "stopped"
    adapter: str = "null"
    world_revision: int = 0
    phase: str = "unknown"
    location: str = "unknown"
    activity: str = "idle"
    capabilities: tuple[str, ...] = ()
    last_tick_at: str = ""
    last_checkpoint_at: str = ""
    error_code: str = ""
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
            "enabled": self.enabled,
            "desired": self.desired,
            "actual": self.actual,
            "adapter": self.adapter,
            "world_revision": self.world_revision,
            "phase": self.phase,
            "location": self.location,
            "activity": self.activity,
            "capabilities": list(self.capabilities),
            "last_tick_at": self.last_tick_at,
            "last_checkpoint_at": self.last_checkpoint_at,
            "error_code": self.error_code,
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

    async def control(
        self,
        action: str,
        *,
        expected_revision: int | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        ...

    async def publish_image_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        ...

    async def replay_events(self, *, last_seq: int | None = None) -> list[WorldEvent]:
        ...

    async def ack(self, seq: int) -> dict[str, Any]:
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
            enabled=False,
            desired="stopped",
            actual="stopped",
            adapter="null",
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

    async def control(
        self,
        action: str,
        *,
        expected_revision: int | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        command = str(action or "").strip().lower()
        accepted = command in {"disable", "stop"}
        return {
            "accepted": accepted,
            "rejected": not accepted,
            "enabled": False,
            "desired": "stopped",
            "actual": "stopped",
            "revision": 0,
            "adapter": "null",
            "fallbackAdapter": "null",
            "errorCode": "" if accepted else "world_disabled",
        }

    async def publish_image_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "disabled",
            "reason": "world_disabled",
            "candidate_id": str((candidate or {}).get("candidate_id") or ""),
        }

    async def replay_events(self, *, last_seq: int | None = None) -> list[WorldEvent]:
        return []

    async def ack(self, seq: int) -> dict[str, Any]:
        return {"status": "ok", "consumer_id": "core", "last_seq": 0}

    def get_world_snapshot(self) -> dict[str, Any] | None:
        return None

    def get_relationship_snapshot(self, user_id: int | str, persona_id: str = "default") -> dict[str, Any] | None:
        return None

    def get_self_model_snapshot(
        self,
        world_snapshot: dict[str, Any] | None,
        relationship_snapshot: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
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
        world: Any | None = None,
        relationship: Any | None = None,
        self_model: Any | None = None,
    ) -> None:
        if world is None:
            from core.world_simulation import WorldSimulation

            world = WorldSimulation()
        if relationship is None:
            from core.relationship_engine import RelationshipEngine

            relationship = RelationshipEngine()
        if self_model is None:
            from core.self_model import SelfModel

            self_model = SelfModel()
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
        self.world = world
        self.relationship = relationship
        self.self_model = self_model
        self._revision = 0
        self._sequence = 0
        self._paused = False
        self._enabled = True
        self._desired = "running"
        self._actual = "running"
        self._control_results: dict[str, dict[str, Any]] = {}
        self._subscribers: dict[str, tuple[set[str], asyncio.Queue[WorldEvent]]] = {}
        self._observed_keys: dict[str, str] = {}
        # Phase 14: durable-in-memory ImageCandidate outbox + consumer cursor.
        # The consumer pulls via replay_events(last_seq) and ACKs via ack(seq),
        # so proactive image delivery works identically to the Sidecar path.
        self._outbox: list[WorldEvent] = []
        self._ack_seq = 0
        self._lock = asyncio.Lock()

    async def get_state(self) -> WorldSnapshot:
        async with self._lock:
            status = "disabled" if not self._enabled else self._actual
            world_snapshot = self.get_world_snapshot() or {}
            return WorldSnapshot(
                status=status,
                source="in_process",
                instance_id=self.instance_id,
                revision=max(self._revision, int(world_snapshot.get("revision") or 0)),
                sequence=self._sequence,
                paused=self._paused,
                enabled=self._enabled,
                desired=self._desired,
                actual=self._actual,
                adapter="in_process",
                world_revision=int(world_snapshot.get("revision") or 0),
                phase=str(world_snapshot.get("phase") or "unknown"),
                location=str(world_snapshot.get("location") or "unknown"),
                activity=str(world_snapshot.get("activity") or "idle"),
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

        if observation.observation_type == "user_message":
            try:
                persona_id = str(observation.payload.get("persona_id") or "default")
                text = str(observation.payload.get("text") or "")
                if text:
                    self.relationship.observe_user_message(
                        user_id=observation.actor_id or "unknown",
                        persona_id=persona_id,
                        text=text,
                    )
            except Exception:
                logger.exception("world relationship observation failed")

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
        await self.control("pause")
        return None

    async def resume(self) -> None:
        await self.control("resume")
        return None

    async def control(
        self,
        action: str,
        *,
        expected_revision: int | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        command = str(action or "").strip().lower()
        idem = str(idempotency_key or "").strip()
        async with self._lock:
            if idem and idem in self._control_results:
                return dict(self._control_results[idem])
            if expected_revision is not None and int(expected_revision) != self._revision:
                return self._control_result(False, "revision_conflict")

            previous = (self._enabled, self._desired, self._actual, self._paused)
            error_code = ""
            if command == "enable":
                self._enabled = True
            elif command == "disable":
                self._enabled = False
                self._desired = "stopped"
                self._actual = "stopped"
                self._paused = False
            elif command == "start":
                if not self._enabled:
                    error_code = "world_disabled"
                else:
                    self._desired = "running"
                    self._actual = "running"
                    self._paused = False
            elif command == "stop":
                self._desired = "stopped"
                self._actual = "stopped"
                self._paused = False
            elif command == "pause":
                if not self._enabled:
                    error_code = "world_disabled"
                elif self._actual == "stopped":
                    error_code = "world_not_running"
                else:
                    self._desired = "paused"
                    self._actual = "paused"
                    self._paused = True
            elif command == "resume":
                if not self._enabled:
                    error_code = "world_disabled"
                elif self._actual != "paused":
                    error_code = "world_not_paused"
                else:
                    self._desired = "running"
                    self._actual = "running"
                    self._paused = False
            elif command == "restart":
                if not self._enabled:
                    error_code = "world_disabled"
                else:
                    self._desired = "running"
                    self._actual = "running"
                    self._paused = False
            else:
                error_code = "unsupported_action"

            current = (self._enabled, self._desired, self._actual, self._paused)
            if error_code:
                result = self._control_result(False, error_code)
            else:
                if current != previous or command == "restart":
                    self._revision += 1
                    self._sequence += 1
                    event = self._lifecycle_event(f"world.{command}")
                    subscribers = list(self._subscribers.values())
                else:
                    event = None
                    subscribers = []
                result = self._control_result(True, "")
            if idem:
                self._control_results[idem] = dict(result)
            if event is not None:
                self._publish(event, subscribers)
            return result

    def _control_result(self, accepted: bool, error_code: str) -> dict[str, Any]:
        return {
            "accepted": accepted,
            "rejected": not accepted,
            "enabled": self._enabled,
            "desired": self._desired,
            "actual": self._actual,
            "revision": self._revision,
            "adapter": "in_process",
            "fallbackAdapter": "null",
            "errorCode": error_code,
        }

    def _lifecycle_event(self, event_type: str) -> WorldEvent:
        return WorldEvent(
            event_id=f"world_evt_{uuid.uuid4().hex}",
            topic="lifecycle",
            event_type=event_type,
            sequence=self._sequence,
            occurred_at=_now_iso(),
            payload={
                "status": self._actual if self._enabled else "disabled",
                "revision": self._revision,
            },
        )

    def tick(self) -> dict[str, Any]:
        return dict(self.world.tick())

    def set_reality(self, reality: dict[str, Any] | None) -> None:
        """注入真实天气/附近地点/实时事件到世界模拟（best-effort）。"""
        setter = getattr(self.world, "set_reality", None)
        if callable(setter):
            setter(reality)

    def get_world_snapshot(self) -> dict[str, Any] | None:
        return dict(self.world.get_snapshot())

    def get_relationship_snapshot(
        self,
        user_id: int | str,
        persona_id: str = "default",
    ) -> dict[str, Any] | None:
        return dict(
            self.relationship.get_state(
                user_id=user_id,
                persona_id=persona_id,
            )
        )

    def get_self_model_snapshot(
        self,
        world_snapshot: dict[str, Any] | None,
        relationship_snapshot: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        return dict(
            self.self_model.snapshot(
                world_snapshot=world_snapshot,
                relationship_snapshot=relationship_snapshot,
            )
        )

    @staticmethod
    def _publish(
        event: WorldEvent,
        subscribers: list[tuple[set[str], asyncio.Queue[WorldEvent]]],
    ) -> None:
        for topics, queue in subscribers:
            if "*" in topics or event.topic in topics:
                queue.put_nowait(event)

    async def publish_image_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Append a redacted ImageCandidate to the in-memory outbox.

        This is the in-process equivalent of the Sidecar's
        ``publish_image_candidate``: the payload is normalized/redacted, an
        event is appended to ``world.image_candidates``, and subscribers are
        notified.  Returns the public event id + sequence so callers can
        consume from exactly this event.
        """
        public = redact_image_candidate(candidate)
        async with self._lock:
            self._sequence += 1
            event = WorldEvent(
                event_id=f"world_evt_{uuid.uuid4().hex}",
                topic="image_candidates",
                event_type="world.image_candidate.published",
                sequence=self._sequence,
                occurred_at=_now_iso(),
                payload=public,
            )
            self._outbox.append(event)
            subscribers = list(self._subscribers.values())
        self._publish(event, subscribers)
        return {
            "status": "accepted",
            "candidate_id": str(public.get("candidate_id") or ""),
            "idempotency_key": str(public.get("idempotency_key") or ""),
            "channel": str(public.get("channel") or ""),
            "target": str(public.get("target") or ""),
            "sequence": event.sequence,
            "event_id": event.event_id,
        }

    async def replay_events(
        self,
        *,
        last_seq: int | None = None,
    ) -> list[WorldEvent]:
        """Return ImageCandidate events after ``last_seq`` (default: ACK cursor)."""
        start = max(0, int(last_seq if last_seq is not None else self._ack_seq))
        async with self._lock:
            return [event for event in self._outbox if event.sequence > start]

    async def ack(self, seq: int) -> dict[str, Any]:
        """Advance the consumer ACK cursor past ``seq``."""
        async with self._lock:
            self._ack_seq = max(self._ack_seq, int(seq or 0))
            return {"status": "ok", "consumer_id": "core", "last_seq": self._ack_seq}


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
    world_config: dict[str, Any] | None = None,
    relationship_config: dict[str, Any] | None = None,
) -> WorldPort:
    try:
        sidecar_enabled = bool(feature_flags.is_enabled("world_sidecar_v1"))
    except Exception:
        logger.exception("failed to read world_sidecar_v1 feature flag")
        sidecar_enabled = False
    if sidecar_enabled:
        try:
            from core.world_adapters.remote import HttpWorldSidecarClient, RemoteWorldAdapter

            endpoint = str(os.environ.get("AERIE_WORLD_SIDECAR_ENDPOINT") or "").strip()
            token = str(os.environ.get("AERIE_WORLD_SIDECAR_TOKEN") or "").strip()
            if endpoint and token:
                return RemoteWorldAdapter(HttpWorldSidecarClient(endpoint, token=token))
            raise RuntimeError("world sidecar endpoint is unavailable")
        except Exception:
            logger.exception("failed to initialize remote world adapter")
            # Process ownership belongs to Electron.  Core never starts a
            # hidden second Sidecar when the supervised endpoint is missing.

    try:
        enabled = bool(feature_flags.is_enabled("world_inprocess_v1"))
    except Exception:
        logger.exception("failed to read world_inprocess_v1 feature flag")
        enabled = False
    if not enabled:
        return NullWorldAdapter(reason="flag_off")
    from core.relationship_engine import RelationshipEngine
    from core.self_model import SelfModel
    from core.world_simulation import WorldSimulation

    rel_cfg = relationship_config or {}
    defaults = rel_cfg.get("defaults") if isinstance(rel_cfg, dict) else None
    learning_rate = rel_cfg.get("learning_rate", 0.08) if isinstance(rel_cfg, dict) else 0.08
    return InProcessWorldAdapter(
        instance_id=instance_id,
        world=WorldSimulation(config=world_config or {}),
        relationship=RelationshipEngine(
            defaults=defaults if isinstance(defaults, dict) else None,
            learning_rate=float(learning_rate),
        ),
        self_model=SelfModel(),
    )


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


_IMAGE_CANDIDATE_SENSITIVE_KEYS = (
    "prompt",
    "raw_prompt",
    "message_text",
    "raw_text",
    "caption",
    "credential",
    "token",
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def redact_image_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Normalize + redact an ImageCandidate payload to its public fields.

    Mirrors the Sidecar sqlite_store contract so in-process and sidecar
    candidates are byte-for-byte equivalent from the consumer's viewpoint.
    Raw prompt/message text is never stored as-is; it is collapsed into
    ``sensitive_keys`` plus a digest.
    """
    payload = candidate if isinstance(candidate, dict) else {}
    candidate_id = str(
        payload.get("candidate_id")
        or payload.get("id")
        or f"cand_{uuid.uuid4().hex}"
    )
    idempotency_key = str(payload.get("idempotency_key") or candidate_id)
    sensitive = {
        key: payload.get(key)
        for key in _IMAGE_CANDIDATE_SENSITIVE_KEYS
        if key in payload
    }
    public = {
        "candidate_id": candidate_id,
        "idempotency_key": idempotency_key,
        "scene": str(payload.get("scene") or "idle_care"),
        "owner_id": str(payload.get("owner_id") or "master"),
        "channel": str(payload.get("channel") or "local_chat"),
        "target": str(payload.get("target") or ""),
        "prompt_key": str(payload.get("prompt_key") or "default"),
        "reason_code": str(payload.get("reason_code") or ""),
        "source": str(payload.get("source") or "generated"),
        "score": _safe_float(payload.get("score"), 0.0),
        "expires_at": str(payload.get("expires_at") or ""),
        "created_at": str(payload.get("created_at") or ""),
    }
    if sensitive:
        public["sensitive_keys"] = sorted(str(key) for key in sensitive.keys())
        public["sensitive_sha256"] = _stable_digest(sensitive)
    return public
