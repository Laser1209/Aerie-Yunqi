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

    def latest_sequence(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COALESCE(MAX(seq), 0) AS seq FROM world_outbox").fetchone()
            return int(row["seq"]) if row else 0

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

    def save_runtime_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """Persist only the public world runtime fields needed for restart."""

        now = _now_ms()
        sanitized = _runtime_state_payload(state)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO world_runtime_state (id, ts_ms, state_json)
                VALUES (1, ?, ?)
                ON CONFLICT(id)
                DO UPDATE SET ts_ms = excluded.ts_ms,
                              state_json = excluded.state_json
                """,
                (now, json.dumps(sanitized, ensure_ascii=False, sort_keys=True)),
            )
        return {"ts_ms": now, **sanitized}

    def load_runtime_state(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT ts_ms, state_json FROM world_runtime_state WHERE id = 1"
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["state_json"]) if row["state_json"] else {}
        return {"ts_ms": int(row["ts_ms"]), **payload}

    def table_names(self) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            return {str(row["name"]) for row in rows}

    def prune(
        self,
        *,
        keep_snapshots: int = 200,
        keep_outbox: int = 2000,
    ) -> dict[str, int]:
        """保留窗口修剪：把 world.db 从「无界增长」改为有界。

        背景（2026-09-27 实测）：tick 默认 1s，每个 tick 都往
        ``world_outbox`` 与 ``world_state_snapshot`` 各插一行且**从不清理**，
        一天 8.6 万行/表，实测库已到 1.07 GB。Electron 的启动握手有超时，
        GB 级库直接拖死 sidecar 启动，表现为「第二波起不来」，
        同时把生图投递的世界闸门一起卡住。

        修剪规则：
          - ``world_state_snapshot``：只保留最近 ``keep_snapshots`` 条
            （快照是「当前状态」的连续覆盖，历史价值低）
          - ``world_outbox``：只删**所有消费者都已 ACK** 的那段
            （``events_after`` 按 ``seq > cursor`` 读，删掉 ``seq <= 最小 cursor``
            不影响任何消费者）；并始终保留最近 ``keep_outbox`` 条作为安全窗口。

        不在此处 VACUUM：VACUUM 会重写整个文件，代价随库大小增长，
        由调用方按更长的周期单独触发（见 :meth:`vacuum`）。
        """
        keep_snap = max(1, int(keep_snapshots))
        keep_out = max(0, int(keep_outbox))
        with self._connect() as conn:
            snap = conn.execute(
                """
                DELETE FROM world_state_snapshot
                WHERE seq NOT IN (
                    SELECT seq FROM world_state_snapshot
                    ORDER BY seq DESC LIMIT ?
                )
                """,
                (keep_snap,),
            )
            floor_row = conn.execute(
                "SELECT MIN(last_seq) AS floor FROM world_ack_cursor"
            ).fetchone()
            floor = floor_row["floor"] if floor_row else None
            if floor is None:
                # 没有任何消费者 ACK：只能按条数保留最近一段，避免无界增长。
                out = conn.execute(
                    """
                    DELETE FROM world_outbox
                    WHERE seq NOT IN (
                        SELECT seq FROM world_outbox ORDER BY seq DESC LIMIT ?
                    )
                    """,
                    (keep_out,),
                )
            else:
                hi_row = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) AS hi FROM world_outbox"
                ).fetchone()
                hi = int(hi_row["hi"] or 0)
                # 双保险：既不超过 ACK 底线，也永远留住最近 keep_out 条。
                cutoff = min(int(floor), max(0, hi - keep_out))
                out = conn.execute(
                    "DELETE FROM world_outbox WHERE seq <= ?", (cutoff,)
                )
            return {
                "snapshots_deleted": max(0, snap.rowcount),
                "outbox_deleted": max(0, out.rowcount),
            }

    def vacuum(self) -> None:
        """回收被 prune 释放的磁盘空间（重写整库，按长周期调用）。"""
        conn = sqlite3.connect(str(self.db_path), isolation_level=None)
        try:
            conn.execute("VACUUM")
        finally:
            conn.close()

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

                CREATE TABLE IF NOT EXISTS world_runtime_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
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
        "size": _safe_text(payload.get("size") or ""),
        # 生图指令与参考图是提示词模块化的输入：丢掉它们，消费端只能拿 intent
        # 关键字拼死板模板（分部位/景别全部失效）。这里按公开字段透传，非凭据。
        "user_raw": _safe_text(payload.get("user_raw") or "", 500),
        "reference_assets": [
            _safe_text(item, 200)
            for item in (payload.get("reference_assets") or [])
            if isinstance(item, str) and item.strip()
        ],
        "expires_at": _safe_text(payload.get("expires_at") or ""),
        "created_at": _safe_text(payload.get("created_at") or ""),
        # 多端口投递意图与角色归属必须随事件一起透传：主动消息的文本可能同时发往
        # QQ / 微信 / 桌面，配图要跟到同样的端口集合；persona_id 决定图片历史行的
        # 角色归属。消费端按显式白名单重建 —— 这里漏一个字段就是静默丢弃。
        "delivery_channels": [
            _safe_text(item).lower()
            for item in (payload.get("delivery_channels") or [])
            if isinstance(item, str) and item.strip()
        ],
        "persona_id": _safe_text(payload.get("persona_id") or ""),
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


def _json_default(value: Any) -> Any:
    """json.dumps 兜底: 把可序列化的领域对象(WorldSnapshot 等)转成 dict.

    WorldSnapshot 是 dict-style dataclass, 支持 to_dict()/keys()/items(),
    但 json.dumps 不会自动调用它们, 导致 "Object of type WorldSnapshot is
    not JSON serializable"。统一在此递归兜底, 一处覆盖
    heartbeat / append_event / checkpoint 全部序列化路径。
    """
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, (set, frozenset)):
        return list(value)
    raise TypeError(
        f"Object of type {type(value).__name__} is not JSON serializable"
    )


def _redacted_payload(payload: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(str(key) for key in (payload or {}).keys())
    raw = json.dumps(
        payload or {},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )
    return {
        "payload_keys": keys,
        "payload_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    }


def _runtime_state_payload(state: dict[str, Any]) -> dict[str, Any]:
    source = state if isinstance(state, dict) else {}
    snapshot_source = source.get("snapshot")
    snapshot = snapshot_source if isinstance(snapshot_source, dict) else {}
    safe_snapshot = {
        key: snapshot[key]
        for key in (
            "ts",
            "iso_time",
            "phase",
            "location",
            "activity",
            "energy",
            "social",
            "source",
            "revision",
            "seed_sha256",
            "snapshot_id",
        )
        if key in snapshot
    }
    desired = _safe_text(source.get("desired") or "stopped")
    if desired not in {"running", "paused", "stopped"}:
        desired = "stopped"
    actual = _safe_text(source.get("actual") or "stopped")
    if actual not in {"running", "paused", "stopped"}:
        actual = "stopped"
    return {
        "enabled": bool(source.get("enabled", False)),
        "desired": desired,
        "actual": actual,
        "revision": max(0, int(source.get("revision") or 0)),
        "last_tick_at": _safe_text(source.get("last_tick_at") or ""),
        "last_checkpoint_at": _safe_text(source.get("last_checkpoint_at") or ""),
        "snapshot": safe_snapshot,
    }


def _safe_text(value: Any, limit: int = 200) -> str:
    return str(value or "").replace("\x00", "").strip()[:limit]


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
