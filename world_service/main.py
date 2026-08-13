"""Authenticated loopback HTTP sidecar for the 24-hour world simulation."""

from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlparse

from core.world_simulation import WorldSimulation
from world_service.storage.sqlite_store import WorldSidecarStore


MAX_REQUEST_BYTES = 1024 * 1024


class LocalWorldSidecarService:
    """World domain service used by both contract tests and the HTTP server."""

    protocol = "aerie.world"
    protocol_version = "1.0"
    service_version = "0.3.1-Beta.1"

    def __init__(
        self,
        *,
        data_dir: str | Path,
        clock: Callable[[], datetime] | None = None,
        initial_enabled: bool = True,
        tick_interval_seconds: float = 1.0,
        checkpoint_interval_seconds: float = 60.0,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = WorldSidecarStore(self.data_dir / "world.db")
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.world = WorldSimulation(clock=self.clock)
        self.running = True
        self.instance_id = f"world-sidecar-{uuid.uuid4().hex}"
        self.startup_epoch_ms = int(time.time() * 1000)
        self.capabilities = (
            "world.read",
            "world.control",
            "events.subscribe",
            "checkpoint",
            "message.candidate.publish",
        )
        self.tick_interval_seconds = max(0.05, float(tick_interval_seconds))
        self.checkpoint_interval_seconds = max(1.0, float(checkpoint_interval_seconds))
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._loop_thread: threading.Thread | None = None
        self._idempotent_controls: dict[str, dict[str, Any]] = {}
        self._last_checkpoint_monotonic = 0.0

        restored = self.store.load_runtime_state()
        if restored:
            self.enabled = bool(restored.get("enabled", False))
            self.desired = _desired(restored.get("desired"))
            self.actual = self.desired if self.enabled else "stopped"
            self.revision = max(0, int(restored.get("revision") or 0))
            self.last_tick_at = str(restored.get("last_tick_at") or "")
            self.last_checkpoint_at = str(restored.get("last_checkpoint_at") or "")
            self.world.restore(restored.get("snapshot"))
        else:
            self.enabled = bool(initial_enabled)
            self.desired = "running" if self.enabled else "stopped"
            self.actual = self.desired
            self.revision = 0
            self.last_tick_at = ""
            self.last_checkpoint_at = ""

        self.store.heartbeat(status="ready", detail={"instance_id": self.instance_id})
        self._persist_runtime_state()

    def hello(self) -> dict[str, Any]:
        self._ensure_running()
        return {
            "type": "hello",
            "protocol": self.protocol,
            "protocol_version": self.protocol_version,
            "service_version": self.service_version,
            "instance_id": self.instance_id,
            "startup_epoch_ms": self.startup_epoch_ms,
            "capabilities": list(self.capabilities),
        }

    def health(self) -> dict[str, Any]:
        if not self.running:
            return {
                "ok": False,
                "status": "crashed",
                "instance_id": self.instance_id,
            }
        heartbeat = self.store.heartbeat(
            status="ready",
            detail={"instance_id": self.instance_id, "actual": self.actual},
        )
        return {
            "ok": True,
            "status": "ready",
            "instance_id": self.instance_id,
            "actual": self.actual,
            "revision": self.revision,
            "heartbeat": heartbeat,
        }

    def get_state(self) -> dict[str, Any]:
        self._ensure_running()
        with self._lock:
            snapshot = self.world.get_snapshot()
            return {
                "status": self.actual if self.enabled else "disabled",
                "desired": self.desired,
                "actual": self.actual,
                "enabled": self.enabled,
                "source": "remote",
                "adapter": "remote",
                "instance_id": self.instance_id,
                "revision": self.revision,
                "world_revision": int(snapshot.get("revision") or 0),
                "sequence": self.store.latest_sequence(),
                "paused": self.actual == "paused",
                "phase": str(snapshot.get("phase") or "unknown"),
                "location": str(snapshot.get("location") or "unknown"),
                "activity": str(snapshot.get("activity") or "idle"),
                "last_tick_at": self.last_tick_at,
                "last_checkpoint_at": self.last_checkpoint_at,
                "capabilities": list(self.capabilities),
            }

    def get_world_snapshot(self) -> dict[str, Any]:
        self._ensure_running()
        return self.world.get_snapshot()

    def control(
        self,
        action: str,
        *,
        expected_revision: int | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        self._ensure_running()
        command = str(action or "").strip().lower()
        idem = str(idempotency_key or "").strip()
        with self._lock:
            if idem and idem in self._idempotent_controls:
                return dict(self._idempotent_controls[idem])
            if expected_revision is not None and int(expected_revision) != self.revision:
                result = self._control_result(
                    accepted=False,
                    error_code="revision_conflict",
                )
                if idem:
                    self._remember_control(idem, result)
                return result

            previous = (self.enabled, self.desired, self.actual)
            error_code = ""
            if command == "enable":
                self.enabled = True
            elif command == "disable":
                self.enabled = False
                self.desired = "stopped"
                self.actual = "stopped"
            elif command == "start":
                if not self.enabled:
                    error_code = "world_disabled"
                else:
                    self.desired = "running"
                    self.actual = "running"
            elif command == "stop":
                self.desired = "stopped"
                self.actual = "stopped"
            elif command == "pause":
                if not self.enabled:
                    error_code = "world_disabled"
                elif self.actual == "stopped":
                    error_code = "world_not_running"
                else:
                    self.desired = "paused"
                    self.actual = "paused"
            elif command == "resume":
                if not self.enabled:
                    error_code = "world_disabled"
                elif self.actual != "paused":
                    error_code = "world_not_paused"
                else:
                    self.desired = "running"
                    self.actual = "running"
            elif command == "restart":
                if not self.enabled:
                    error_code = "world_disabled"
                else:
                    self.desired = "running"
                    self.actual = "running"
            else:
                error_code = "unsupported_action"

            current = (self.enabled, self.desired, self.actual)
            if error_code:
                result = self._control_result(accepted=False, error_code=error_code)
            else:
                if current != previous or command == "restart":
                    self.revision += 1
                    self._persist_runtime_state()
                    self.store.append_event(
                        topic="lifecycle",
                        event_type=f"world.{command}",
                        payload={
                            "enabled": self.enabled,
                            "desired": self.desired,
                            "actual": self.actual,
                            "revision": self.revision,
                        },
                        idempotency_key=idem or f"control:{command}:{self.revision}",
                    )
                result = self._control_result(accepted=True)
            if idem:
                self._remember_control(idem, result)
            return result

    def pause(self) -> dict[str, Any]:
        return self.control("pause")

    def resume(self) -> dict[str, Any]:
        return self.control("resume")

    def tick(self, *, force: bool = False) -> dict[str, Any]:
        self._ensure_running()
        with self._lock:
            if self.actual != "running" and not force:
                return {
                    "accepted": False,
                    "errorCode": "world_not_running",
                    **self.get_state(),
                }
            snapshot = self.world.tick()
            self.last_tick_at = str(snapshot.get("iso_time") or _now_iso(self.clock))
            event = self.store.append_event(
                topic="world.state",
                event_type="world.snapshot.updated",
                payload=snapshot,
                idempotency_key=f"tick:{snapshot.get('snapshot_id') or snapshot.get('iso_time')}",
            )
            now_monotonic = time.monotonic()
            if (
                not self.last_checkpoint_at
                or now_monotonic - self._last_checkpoint_monotonic >= self.checkpoint_interval_seconds
            ):
                self.last_checkpoint_at = self.last_tick_at
                self._last_checkpoint_monotonic = now_monotonic
                self.store.checkpoint(
                    checkpoint_id=f"world-runtime-{snapshot.get('revision', 0)}",
                    state=snapshot,
                )
            self._persist_runtime_state()
            return {
                "accepted": True,
                "sequence": int(event.get("seq") or 0),
                "snapshot": snapshot,
                **self.get_state(),
            }

    def observe(self, observation: Any) -> dict[str, Any]:
        self._ensure_running()
        payload = {
            "observation_type": _field(observation, "observation_type", "unknown"),
            "actor_id": _field(observation, "actor_id", ""),
            "channel": _field(observation, "channel", ""),
            "payload": _field(observation, "payload", {}),
            "source_event_id": _field(observation, "event_id", ""),
        }
        return self.store.append_event(
            topic="observations",
            event_type="world.observation.recorded",
            payload=payload,
            idempotency_key=_field(observation, "idempotency_key", "")
            or payload["source_event_id"],
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

    def start_loop(self) -> None:
        with self._lock:
            if self._loop_thread and self._loop_thread.is_alive():
                return
            self._stop_event.clear()
            self._loop_thread = threading.Thread(
                target=self._run_loop,
                name="aerie-world-tick",
                daemon=True,
            )
            self._loop_thread.start()

    def stop_loop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        thread = self._loop_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
        self._loop_thread = None

    def crash(self) -> None:
        self.running = False
        self.stop_loop()
        self.store.heartbeat(status="crashed", detail={"instance_id": self.instance_id})

    def restart(self) -> None:
        self.running = True
        with self._lock:
            self.actual = self.desired if self.enabled else "stopped"
        self.store.heartbeat(status="ready", detail={"instance_id": self.instance_id})

    def _run_loop(self) -> None:
        while not self._stop_event.wait(self.tick_interval_seconds):
            try:
                if self.running and self.actual == "running":
                    self.tick()
                elif self.running:
                    self.store.heartbeat(
                        status="ready",
                        detail={"instance_id": self.instance_id, "actual": self.actual},
                    )
            except Exception:
                self.store.heartbeat(status="degraded", detail={"error": "tick_failed"})

    def _persist_runtime_state(self) -> None:
        snapshot = self.world.get_snapshot()
        self.store.save_runtime_state(
            {
                "enabled": self.enabled,
                "desired": self.desired,
                "actual": self.actual,
                "revision": self.revision,
                "last_tick_at": self.last_tick_at,
                "last_checkpoint_at": self.last_checkpoint_at,
                "snapshot": snapshot,
            }
        )

    def _control_result(self, *, accepted: bool, error_code: str = "") -> dict[str, Any]:
        return {
            "accepted": bool(accepted),
            "rejected": not bool(accepted),
            "desired": self.desired,
            "actual": self.actual,
            "enabled": self.enabled,
            "revision": self.revision,
            "adapter": "remote",
            "fallbackAdapter": "in_process",
            "errorCode": str(error_code),
        }

    def _remember_control(self, key: str, result: dict[str, Any]) -> None:
        self._idempotent_controls[key] = dict(result)
        while len(self._idempotent_controls) > 200:
            self._idempotent_controls.pop(next(iter(self._idempotent_controls)))

    def _ensure_running(self) -> None:
        if not self.running:
            raise RuntimeError("world sidecar unavailable")


class WorldSidecarHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        service: LocalWorldSidecarService,
        *,
        token: str,
        token_expires_at_ms: int = 0,
        auth_now_ms: Callable[[], int] | None = None,
    ) -> None:
        self.service = service
        self.token = str(token)
        self.token_expires_at_ms = max(0, int(token_expires_at_ms or 0))
        self.auth_now_ms = auth_now_ms or (lambda: int(time.time() * 1000))
        super().__init__(server_address, WorldSidecarRequestHandler)


class WorldSidecarRequestHandler(BaseHTTPRequestHandler):
    server: WorldSidecarHTTPServer

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        if not self._authenticate():
            return
        parsed = urlparse(self.path)
        if parsed.path == "/hello":
            self._json(HTTPStatus.OK, self.server.service.hello())
        elif parsed.path == "/health":
            payload = self.server.service.health()
            self._json(HTTPStatus.OK if payload.get("ok") else HTTPStatus.SERVICE_UNAVAILABLE, payload)
        elif parsed.path == "/state":
            self._json(HTTPStatus.OK, self.server.service.get_state())
        elif parsed.path == "/snapshot":
            self._json(HTTPStatus.OK, self.server.service.get_world_snapshot())
        elif parsed.path == "/events":
            query = parse_qs(parsed.query)
            last_seq_raw = query.get("last_seq", [None])[0]
            self._json(
                HTTPStatus.OK,
                {
                    "items": self.server.service.replay_events(
                        consumer_id=str(query.get("consumer_id", ["core"])[0]),
                        last_seq=int(last_seq_raw) if last_seq_raw not in (None, "") else None,
                    )
                },
            )
        else:
            self._json(HTTPStatus.NOT_FOUND, {"errorCode": "not_found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        if not self._authenticate():
            return
        try:
            body = self._read_json()
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"errorCode": str(exc)})
            return
        path = urlparse(self.path).path
        if path == "/control":
            expected = body.get("expectedRevision", body.get("expected_revision"))
            result = self.server.service.control(
                str(body.get("action") or ""),
                expected_revision=int(expected) if expected is not None else None,
                idempotency_key=str(body.get("idempotencyKey") or body.get("idempotency_key") or ""),
            )
            self._json(HTTPStatus.OK if result.get("accepted") else HTTPStatus.CONFLICT, result)
        elif path == "/tick":
            result = self.server.service.tick(force=body.get("force") is True)
            self._json(HTTPStatus.OK if result.get("accepted") else HTTPStatus.CONFLICT, result)
        elif path == "/observe":
            self._json(HTTPStatus.ACCEPTED, self.server.service.observe(body))
        elif path == "/ack":
            self._json(
                HTTPStatus.OK,
                self.server.service.ack(
                    consumer_id=str(body.get("consumer_id") or "core"),
                    seq=int(body.get("seq") or 0),
                ),
            )
        elif path == "/checkpoint":
            state = body.get("state") if isinstance(body.get("state"), dict) else {}
            self._json(
                HTTPStatus.OK,
                self.server.service.checkpoint(
                    checkpoint_id=str(body.get("checkpoint_id") or ""),
                    state=state,
                ),
            )
        elif path == "/image-candidates":
            self._json(HTTPStatus.ACCEPTED, self.server.service.publish_image_candidate(body))
        elif path == "/shutdown":
            self._json(HTTPStatus.ACCEPTED, {"accepted": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._json(HTTPStatus.NOT_FOUND, {"errorCode": "not_found"})

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _authenticate(self) -> bool:
        expected = self.server.token
        supplied = self.headers.get("Authorization", "")
        if self.server.token_expires_at_ms and self.server.auth_now_ms() >= self.server.token_expires_at_ms:
            self._json(HTTPStatus.UNAUTHORIZED, {"errorCode": "token_expired"})
            return False
        prefix = "Bearer "
        if not supplied.startswith(prefix) or not hmac.compare_digest(supplied[len(prefix):], expected):
            self._json(HTTPStatus.UNAUTHORIZED, {"errorCode": "unauthorized"})
            return False
        return True

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("request_too_large")
        if length == 0:
            return {}
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid_json") from exc
        if not isinstance(value, dict):
            raise ValueError("invalid_json_object")
        return value

    def _json(self, status: HTTPStatus, payload: Mapping[str, Any]) -> None:
        raw = json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)


def create_http_server(
    *,
    service: LocalWorldSidecarService,
    host: str = "127.0.0.1",
    port: int = 0,
    token: str,
    token_expires_at_ms: int = 0,
    auth_now_ms: Callable[[], int] | None = None,
) -> WorldSidecarHTTPServer:
    _require_loopback(host)
    if not str(token):
        raise ValueError("world sidecar bearer token is required")
    return WorldSidecarHTTPServer(
        (host, int(port)),
        service,
        token=token,
        token_expires_at_ms=token_expires_at_ms,
        auth_now_ms=auth_now_ms,
    )


def _require_loopback(host: str) -> None:
    try:
        address = ipaddress.ip_address(str(host))
    except ValueError as exc:
        raise ValueError("world sidecar host must be a loopback IP") from exc
    if not address.is_loopback:
        raise ValueError("world sidecar refuses non-loopback binding")


def _field(source: Any, name: str, default: Any) -> Any:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _desired(value: Any) -> str:
    normalized = str(value or "stopped").strip().lower()
    return normalized if normalized in {"running", "paused", "stopped"} else "stopped"


def _now_iso(clock: Callable[[], datetime]) -> str:
    now = clock()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).isoformat()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aerie world loopback sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--tick-interval", type=float, default=1.0)
    parser.add_argument("--checkpoint-interval", type=float, default=60.0)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    token = os.environ.get("AERIE_WORLD_TOKEN", "")
    expires_at = int(os.environ.get("AERIE_WORLD_TOKEN_EXPIRES_AT_MS", "0") or 0)
    service = LocalWorldSidecarService(
        data_dir=args.data_dir,
        initial_enabled=True,
        tick_interval_seconds=args.tick_interval,
        checkpoint_interval_seconds=args.checkpoint_interval,
    )
    server = create_http_server(
        service=service,
        host=args.host,
        port=args.port,
        token=token,
        token_expires_at_ms=expires_at,
    )
    port = int(server.server_address[1])
    print(
        json.dumps(
            {
                "type": "world-sidecar-ready",
                "host": args.host,
                "port": port,
                "instanceId": service.instance_id,
                "startupEpochMs": service.startup_epoch_ms,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )
    service.start_loop()
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        service.stop_loop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
