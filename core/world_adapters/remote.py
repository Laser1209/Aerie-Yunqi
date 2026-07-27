"""Fail-closed HTTP and in-memory clients for the remote WorldPort."""

from __future__ import annotations

import ipaddress
import json
import logging
from typing import Any, AsyncIterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from core.world_port import Observation, WorldEvent, WorldSnapshot, _now_iso

logger = logging.getLogger(__name__)


class HttpWorldSidecarClient:
    """Synchronous loopback HTTP client used behind the async WorldPort."""

    def __init__(self, endpoint: str, *, token: str, timeout: float = 2.0) -> None:
        parsed = urlparse(str(endpoint or "").rstrip("/"))
        if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("world sidecar endpoint must be plain loopback HTTP")
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError as exc:
            raise ValueError("world sidecar endpoint must use a loopback IP") from exc
        if not address.is_loopback or parsed.query or parsed.fragment:
            raise ValueError("world sidecar endpoint must use a loopback IP")
        if not str(token):
            raise ValueError("world sidecar token is required")
        self.endpoint = str(endpoint or "").rstrip("/")
        self._token = str(token)
        self.timeout = max(0.1, float(timeout))

    def hello(self) -> dict[str, Any]:
        return self._request("GET", "/hello")

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def get_state(self) -> dict[str, Any]:
        return self._request("GET", "/state")

    def get_world_snapshot(self) -> dict[str, Any]:
        return self._request("GET", "/snapshot")

    def observe(self, observation: Any) -> dict[str, Any]:
        payload = {
            "observation_type": getattr(observation, "observation_type", "unknown"),
            "actor_id": getattr(observation, "actor_id", ""),
            "channel": getattr(observation, "channel", ""),
            "payload": getattr(observation, "payload", {}),
            "idempotency_key": getattr(observation, "idempotency_key", ""),
            "event_id": getattr(observation, "event_id", ""),
            "occurred_at": getattr(observation, "occurred_at", ""),
        }
        return self._request("POST", "/observe", payload)

    def replay_events(
        self,
        *,
        consumer_id: str = "core",
        last_seq: int | None = None,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"consumer_id": str(consumer_id or "core")}
        if last_seq is not None:
            query["last_seq"] = int(last_seq)
        result = self._request("GET", f"/events?{urlencode(query)}")
        rows = result.get("items")
        return rows if isinstance(rows, list) else []

    def ack(self, *, consumer_id: str = "core", seq: int) -> dict[str, Any]:
        return self._request(
            "POST",
            "/ack",
            {"consumer_id": str(consumer_id or "core"), "seq": int(seq)},
        )

    def checkpoint(self, *, checkpoint_id: str, state: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            "/checkpoint",
            {"checkpoint_id": str(checkpoint_id), "state": dict(state or {})},
        )

    def publish_image_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/image-candidates", dict(candidate or {}))

    def control(
        self,
        action: str,
        *,
        expected_revision: int | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "action": str(action or ""),
            "idempotencyKey": str(idempotency_key or ""),
        }
        if expected_revision is not None:
            payload["expectedRevision"] = int(expected_revision)
        return self._request("POST", "/control", payload, accept_conflict=True)

    def tick(self, *, force: bool = False) -> dict[str, Any]:
        return self._request("POST", "/tick", {"force": bool(force)}, accept_conflict=True)

    def shutdown(self) -> dict[str, Any]:
        return self._request("POST", "/shutdown", {})

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        accept_conflict: bool = False,
    ) -> dict[str, Any]:
        body = None
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = Request(self.endpoint + path, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            raw = exc.read()
            if not (accept_conflict and exc.code == 409):
                raise RuntimeError(f"world sidecar HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError("world sidecar unavailable") from exc
        try:
            value = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("invalid world sidecar response") from exc
        if not isinstance(value, dict):
            raise RuntimeError("invalid world sidecar response")
        return value


class RemoteWorldAdapter:
    """WorldPort adapter that degrades locally when transport is unavailable."""

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
                enabled=bool(state.get("enabled", True)),
                desired=str(state.get("desired") or "running"),
                actual=str(state.get("actual") or state.get("status") or "running"),
                adapter=str(state.get("adapter") or "remote"),
                world_revision=int(state.get("world_revision") or 0),
                phase=str(state.get("phase") or "unknown"),
                location=str(state.get("location") or "unknown"),
                activity=str(state.get("activity") or "idle"),
                capabilities=tuple(state.get("capabilities") or ()),
                last_tick_at=str(state.get("last_tick_at") or ""),
                last_checkpoint_at=str(state.get("last_checkpoint_at") or ""),
                error_code=str(state.get("errorCode") or state.get("error_code") or ""),
            )
        except Exception:
            logger.debug("remote world sidecar unavailable", exc_info=True)
            return WorldSnapshot(
                status="degraded",
                source="remote",
                instance_id="world-remote-unavailable",
                enabled=True,
                desired="running",
                actual="degraded",
                adapter="null",
                error_code=self.fallback_reason,
                capabilities=(),
            )

    async def observe(self, observation: Observation) -> None:
        try:
            self.client.observe(observation)
        except Exception:
            logger.debug("remote world observe skipped", exc_info=True)
        return None

    async def subscribe(self, topics: list[str]) -> AsyncIterator[WorldEvent]:
        for event in await self.replay_events():
            if "*" in topics or event.topic in set(topics or []):
                yield event

    async def pause(self) -> None:
        await self.control("pause")

    async def resume(self) -> None:
        await self.control("resume")

    async def control(
        self,
        action: str,
        *,
        expected_revision: int | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        try:
            return self.client.control(
                action,
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
            )
        except Exception:
            logger.debug("remote world control unavailable", exc_info=True)
            return {
                "accepted": False,
                "rejected": True,
                "desired": "running",
                "actual": "degraded",
                "revision": 0,
                "adapter": "null",
                "fallbackAdapter": "null",
                "errorCode": self.fallback_reason,
            }

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

    def get_world_snapshot(self) -> dict[str, Any] | None:
        try:
            getter = getattr(self.client, "get_world_snapshot", None)
            if callable(getter):
                return dict(getter())
            state = self.client.get_state()
            return {
                key: state[key]
                for key in (
                    "phase",
                    "location",
                    "activity",
                    "world_revision",
                    "last_tick_at",
                )
                if key in state
            }
        except Exception:
            return None

    def get_relationship_snapshot(self, _user_id: int | str, _persona_id: str = "default") -> None:
        return None

    def get_self_model_snapshot(
        self,
        _world_snapshot: dict[str, Any] | None,
        _relationship_snapshot: dict[str, Any] | None,
    ) -> None:
        return None

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
