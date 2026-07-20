"""SQLite world.db store owned exclusively by the world sidecar."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


class WorldSidecarStore:
    """Owns world.db tables, Outbox events, ACK cursors, and heartbeat rows."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def append_event(
        self,
        *,
        topic: str,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        redact_payload: bool = True,
    ) -> dict[str, Any]:
        idem = str(idempotency_key or "").strip()
        if not idem:
            idem = f"auto:{uuid.uuid4().hex}"
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM world_outbox WHERE idempotency_key = ?",
                (idem,),
            ).fetchone()
            if existing:
                return self._event_from_row(existing)

            sanitized = _redacted_payload(payload) if redact_payload else dict(payload or {})
            event_id = f"world_evt_{uuid.uuid4().hex}"
            now = _now_ms()
            cursor = conn.execute(
                """
                INSERT INTO world_outbox (
                    event_id, topic, event_type, payload_json,
                    idempotency_key, occurred_at_ms, delivered
                ) VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    event_id,
                    str(topic),
                    str(event_type),
                    json.dumps(sanitized, ensure_ascii=False, sort_keys=True),
                    idem,
                    now,
                ),
            )
            seq = int(cursor.lastrowid)
            if str(topic) == "world.state":
                conn.execute(
                    """
                    INSERT INTO world_state_snapshot (
                        seq, ts_ms, phase, payload_json
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        seq,
                        now,
                        str((payload or {}).get("phase") or "unknown"),
                        json.dumps(sanitized, ensure_ascii=False, sort_keys=True),
                    ),
                )
            row = conn.execute(
                "SELECT * FROM world_outbox WHERE seq = ?",
                (seq,),
            ).fetchone()
            return self._event_from_row(row)

    def append_image_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Append a public ImageCandidate event for Core approval.

        Candidate events are not blanket-redacted like observations because
        Core must read prompt_key, scene, expiry, and ownership fields to
        approve or suppress them.  Raw prompt/message fields are never stored;
        they are collapsed into sensitive_keys plus a digest.
        """

        payload = _image_candidate_payload(candidate)
        return self.append_event(
            topic="image_candidates",
            event_type="world.image_candidate.published",
            payload=payload,
            idempotency_key=payload["idempotency_key"],
            redact_payload=False,
        )

    def events_after(
        self,
        *,
        consumer_id: str,
        last_seq: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        consumer = str(consumer_id or "core")
        if last_seq is None:
            last_seq = self.cursor(consumer)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM world_outbox
                WHERE seq > ?
                ORDER BY seq ASC
                LIMIT ?
                """,
                (int(last_seq or 0), int(limit)),
            ).fetchall()
            return [self._event_from_row(row) for row in rows]

    def ack(self, *, consumer_id: str, seq: int) -> dict[str, Any]:
        consumer = str(consumer_id or "core")
        cursor = max(0, int(seq or 0))
        now = _now_ms()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT last_seq FROM world_ack_cursor WHERE consumer_id = ?",
                (consumer,),
            ).fetchone()
            previous = int(existing["last_seq"]) if existing else 0
            last_seq = max(previous, cursor)
            conn.execute(
                """
                INSERT INTO world_ack_cursor (consumer_id, last_seq, updated_at_ms)
                VALUES (?, ?, ?)
                ON CONFLICT(consumer_id)
                DO UPDATE SET last_seq = excluded.last_seq,
                              updated_at_ms = excluded.updated_at_ms
                """,
                (consumer, last_seq, now),
            )
        return {"consumer_id": consumer, "last_seq": last_seq, "updated_at_ms": now}

    def cursor(self, consumer_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT last_seq FROM world_ack_cursor WHERE consumer_id = ?",
                (str(consumer_id or "core"),),
            ).fetchone()
            return int(row["last_seq"]) if row else 0

    def heartbeat(self, *, status: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        now = _now_ms()
        detail_payload = detail if isinstance(detail, dict) else {}
        sanitized = _redacted_payload(detail_payload)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO world_heartbeat (id, ts_ms, status, detail_json)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id)
                DO UPDATE SET ts_ms = excluded.ts_ms,
                              status = excluded.status,
                              detail_json = excluded.detail_json
                """,
                (
                    now,
                    str(status or "unknown"),
                    json.dumps(sanitized, ensure_ascii=False, sort_keys=True),
                ),
            )
        return {"ts_ms": now, "status": str(status or "unknown"), "detail": sanitized}

    def checkpoint(self, *, checkpoint_id: str, state: dict[str, Any]) -> dict[str, Any]:
        now = _now_ms()
        cp_id = str(checkpoint_id or f"cp_{uuid.uuid4().hex}")
        sanitized = _redacted_payload(state if isinstance(state, dict) else {})
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO world_checkpoint (checkpoint_id, ts_ms, state_json)
                VALUES (?, ?, ?)
                ON CONFLICT(checkpoint_id)
                DO UPDATE SET ts_ms = excluded.ts_ms,
                              state_json = excluded.state_json
                """,
                (
                    cp_id,
                    now,
                    json.dumps(sanitized, ensure_ascii=False, sort_keys=True),
                ),
            )
        return {"checkpoint_id": cp_id, "ts_ms": now, "state": sanitized}

    def table_names(self) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            return {str(row["name"]) for row in rows}

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS world_state_snapshot (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    seq INTEGER NOT NULL,
                    ts_ms INTEGER NOT NULL,
                    phase TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_world_state_seq
                    ON world_state_snapshot(seq);

                CREATE TABLE IF NOT EXISTS world_outbox (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    topic TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    occurred_at_ms INTEGER NOT NULL,
                    delivered INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_world_outbox_topic_seq
                    ON world_outbox(topic, seq);

                CREATE TABLE IF NOT EXISTS world_ack_cursor (
                    consumer_id TEXT PRIMARY KEY,
                    last_seq INTEGER NOT NULL DEFAULT 0,
                    updated_at_ms INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS world_heartbeat (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    ts_ms INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    detail_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS world_checkpoint (
                    checkpoint_id TEXT PRIMARY KEY,
                    ts_ms INTEGER NOT NULL,
                    state_json TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
        return {
            "seq": int(row["seq"]),
            "event_id": str(row["event_id"]),
            "topic": str(row["topic"]),
            "event_type": str(row["event_type"]),
            "payload": payload,
            "occurred_at_ms": int(row["occurred_at_ms"]),
        }


def _now_ms() -> int:
    return int(time.time() * 1000)


def _image_candidate_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    payload = candidate if isinstance(candidate, dict) else {}
    candidate_id = _safe_text(payload.get("candidate_id") or payload.get("id") or f"cand_{uuid.uuid4().hex}")
    idempotency_key = _safe_text(payload.get("idempotency_key") or candidate_id)
    sensitive = {
        key: payload.get(key)
        for key in (
            "prompt",
            "raw_prompt",
            "message_text",
            "raw_text",
            "caption",
            "credential",
            "token",
        )
        if key in payload
    }
    public = {
        "candidate_id": candidate_id,
        "idempotency_key": idempotency_key,
        "scene": _safe_text(payload.get("scene") or "idle_care"),
        "owner_id": _safe_text(payload.get("owner_id") or "master"),
        "channel": _safe_text(payload.get("channel") or "local_chat"),
        "target": _safe_text(payload.get("target") or ""),
        "prompt_key": _safe_text(payload.get("prompt_key") or "default"),
        "reason_code": _safe_text(payload.get("reason_code") or ""),
        "source": _safe_text(payload.get("source") or "generated"),
        "score": _safe_float(payload.get("score"), 0.0),
        "expires_at": _safe_text(payload.get("expires_at") or ""),
        "created_at": _safe_text(payload.get("created_at") or ""),
    }
    if sensitive:
        public["sensitive_keys"] = sorted(str(key) for key in sensitive.keys())
        public["sensitive_sha256"] = hashlib.sha256(
            json.dumps(
                sensitive,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    return public


def _redacted_payload(payload: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(str(key) for key in (payload or {}).keys())
    raw = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "payload_keys": keys,
        "payload_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    }


def _safe_text(value: Any, limit: int = 200) -> str:
    return str(value or "").replace("\x00", "").strip()[:limit]


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
