"""Aerie · admin_service — 后台管理平台核心服务（P4b, §3.5.2）.

职责（只做存储层确定性逻辑，不接 LLM）：
- 解锁门闩：`admin_unlocked` 服务端持久化（runtime_config）+ 随机 token 落本地文件。
- 聊天记录软删回收站：级联 消息 → 摘要分桶 → long_term_memory（Chroma purge 期才真删）。
- 分层记忆管理：long_term_memory 表（long_term 层）列表/查看/修改/软删/恢复。
- 知识库删除：确认 + undo 快照（快照行落 audit_log，非回收站）。
- 审计日志：audit_log 表 append-only（action/target_id/reason_code/timestamp/actor）。
- 定时 purge：RETENTION 参数化（默认 7 天），按批物理删除（≤500/批）。

软删纪律：messages/buckets 置 `deleted_at` 保持 rowid 游标稳定；
向量删除不可逆，软删期只标记、purge 期才 `collection.delete`。
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_HOURS = 24 * 7  # 回收站默认保留期（小时），48h 为下限
PURGE_BATCH_SIZE = 500
_TS_FMT = "%Y-%m-%d %H:%M:%S"


def _now_str() -> str:
    return datetime.now().strftime(_TS_FMT)


def _iso_ts() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class AdminService:
    """后台管理平台存储层服务（线程安全：全部走 Database 连接上下文）。"""

    def __init__(
        self,
        db: Any = None,
        data_dir: Optional[Path] = None,
        runtime_config: Any = None,
        memory: Any = None,
        retention_hours: int = DEFAULT_RETENTION_HOURS,
    ) -> None:
        self._db = db
        self._data_dir = Path(data_dir) if data_dir else Path("data")
        self._runtime_config = runtime_config
        self._memory = memory  # LayeredMemory（Chroma purge 用）
        self.retention_hours = max(48, int(retention_hours))
        self._token_path = self._data_dir / "admin_unlock.token"
        self._unlocked: Optional[bool] = None

    # ── 解锁门闩（服务端持久化） ──────────────────────────
    def is_unlocked(self) -> bool:
        if self._unlocked is None:
            self._unlocked = self._read_unlock_flag()
        return self._unlocked

    def _read_unlock_flag(self) -> bool:
        if self._runtime_config is None:
            return False
        try:
            snap = self._runtime_config.snapshot()
            values = (snap or {}).get("values") or {}
            return bool(values.get("admin_unlocked"))
        except Exception:
            logger.debug("read admin_unlocked failed", exc_info=True)
            return False

    def unlock(self) -> str:
        """置位服务端门闩并生成随机 token（写本地文件），返回 token。"""
        token = secrets.token_urlsafe(32)
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            self._token_path.write_text(token, encoding="utf-8")
        except OSError:
            logger.exception("failed to write admin unlock token")
        self._persist_unlock_flag(True)
        return token

    def lock(self) -> None:
        self._persist_unlock_flag(False)
        try:
            if self._token_path.exists():
                self._token_path.unlink()
        except OSError:
            pass

    def _persist_unlock_flag(self, value: bool) -> None:
        self._unlocked = value
        if self._runtime_config is None:
            return
        try:
            snap = self._runtime_config.snapshot() or {}
            expected = int(snap.get("revision") or 0)
            self._runtime_config.update(
                {"admin_unlocked": bool(value)},
                expected_revision=expected,
            )
        except Exception:
            logger.warning("persist admin_unlocked failed (revision conflict?)", exc_info=True)

    def verify_token(self, token: str) -> bool:
        if not token or not self.is_unlocked():
            return False
        try:
            if not self._token_path.exists():
                return False
            return self._token_path.read_text(encoding="utf-8").strip() == token.strip()
        except OSError:
            return False

    # ── 审计 ────────────────────────────────────────────
    def audit(
        self,
        action: str,
        target_id: str = "",
        reason_code: str = "manual",
    ) -> None:
        if self._db is None:
            return
        try:
            self._db.insert(
                "audit_log",
                {
                    "action": str(action),
                    "target_id": str(target_id or ""),
                    "reason_code": str(reason_code or "manual"),
                    "timestamp": _iso_ts(),
                    "actor": "local_user",
                },
            )
        except Exception:
            logger.exception("audit write failed")

    def recent_audit(self, limit: int = 20) -> list[dict[str, Any]]:
        if self._db is None:
            return []
        try:
            return self._db.query(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
                (int(limit),),
            )
        except Exception:
            logger.exception("audit read failed")
            return []

    def overview(self) -> dict[str, Any]:
        """概览 KPI 真实总量（SQL COUNT，非列表分页截断）。"""
        if self._db is None:
            return {
                "conversations": 0,
                "messages": 0,
                "memory": 0,
                "trashed_messages": 0,
                "audit": 0,
                "total_tokens": 0,
            }

        def _count(sql: str) -> int:
            try:
                rows = self._db.query(sql)
                return int(rows[0]["n"]) if rows else 0
            except Exception:
                logger.exception("overview count failed: %s", sql)
                return 0

        return {
            "conversations": _count(
                "SELECT COUNT(DISTINCT conversation_id) AS n FROM messages"
            ),
            "messages": _count(
                "SELECT COUNT(*) AS n FROM messages WHERE deleted_at IS NULL"
            ),
            "memory": _count(
                "SELECT COUNT(*) AS n FROM long_term_memory WHERE deleted_at IS NULL"
            ),
            "trashed_messages": _count(
                "SELECT COUNT(*) AS n FROM messages WHERE deleted_at IS NOT NULL"
            ),
            "audit": _count("SELECT COUNT(*) AS n FROM audit_log"),
            "total_tokens": _count(
                "SELECT COALESCE(SUM(total_tokens), 0) AS n FROM token_usage"
            ),
        }

    # ── 聊天记录：列表 ───────────────────────────────────
    def list_conversations(
        self,
        channel: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        if self._db is None:
            return {"items": [], "total": 0}
        try:
            where = "WHERE channel = ?" if channel else ""
            params: tuple = (channel,) if channel else ()
            total_rows = self._db.query(
                f"SELECT COUNT(DISTINCT conversation_id) AS n FROM messages {where}",
                params,
            )
            total = int(total_rows[0]["n"]) if total_rows else 0
            rows = self._db.query(
                f"""SELECT conversation_id,
                           COUNT(*) AS total,
                           SUM(CASE WHEN deleted_at IS NULL THEN 1 ELSE 0 END) AS active,
                           SUM(CASE WHEN deleted_at IS NOT NULL THEN 1 ELSE 0 END) AS trashed,
                           MAX(created_at) AS last_ts
                    FROM messages {where}
                    GROUP BY conversation_id
                    ORDER BY last_ts DESC
                    LIMIT ? OFFSET ?""",
                params + (int(limit), int(offset)),
            )
            items = []
            for row in rows:
                preview = self._db.query_one(
                    """SELECT role, content FROM messages
                       WHERE conversation_id = ? AND deleted_at IS NULL
                       ORDER BY rowid DESC LIMIT 1""",
                    (row["conversation_id"],),
                )
                items.append(
                    {
                        "conversation_id": row["conversation_id"],
                        "channel": channel,
                        "message_count": int(row["total"] or 0),
                        "active_count": int(row["active"] or 0),
                        "trashed_count": int(row["trashed"] or 0),
                        "last_at": row["last_ts"],
                        "preview": {
                            "role": (preview or {}).get("role"),
                            "content": str((preview or {}).get("content") or "")[:120],
                        },
                    }
                )
            return {"items": items, "total": total}
        except Exception:
            logger.exception("list conversations failed")
            return {"items": [], "total": 0}

    # ── 聊天记录：单条消息（精确到每一条的查看/编辑/软删/恢复） ─
    def list_messages(
        self,
        conversation_id: str,
        limit: int = 200,
        offset: int = 0,
        include_trashed: bool = True,
    ) -> dict[str, Any]:
        if self._db is None:
            return {"items": [], "total": 0}
        try:
            where = "conversation_id = ?"
            params: list[Any] = [str(conversation_id)]
            if not include_trashed:
                where += " AND deleted_at IS NULL"
            total_rows = self._db.query(
                f"SELECT COUNT(*) AS n FROM messages WHERE {where}",
                tuple(params),
            )
            total = int(total_rows[0]["n"]) if total_rows else 0
            rows = self._db.query(
                f"SELECT * FROM messages WHERE {where} "
                "ORDER BY created_at DESC, sequence DESC, rowid DESC LIMIT ? OFFSET ?",
                tuple(params + [int(limit), int(offset)]),
            )
            return {"items": rows, "total": total}
        except Exception:
            logger.exception("list messages failed")
            return {"items": [], "total": 0}

    def update_message(self, message_id: str, content: str) -> Optional[dict[str, Any]]:
        """编辑单条消息正文（只改 content，其余字段不变）。"""
        if self._db is None:
            return None
        try:
            self._db.execute(
                "UPDATE messages SET content = ? WHERE message_id = ?",
                (str(content), str(message_id)),
            )
            row = self._db.query_one(
                "SELECT * FROM messages WHERE message_id = ?",
                (str(message_id),),
            )
            self.audit("update_message", str(message_id))
            return row
        except Exception:
            logger.exception("update message failed")
            return None

    def trash_message(self, message_id: str) -> bool:
        if self._db is None:
            return False
        try:
            n = self._db.execute(
                "UPDATE messages SET deleted_at = ? WHERE message_id = ? AND deleted_at IS NULL",
                (_now_str(), str(message_id)),
            ).rowcount
            if n:
                self.audit("trash_message", str(message_id))
            return bool(n)
        except Exception:
            logger.exception("trash message failed")
            return False

    def restore_message(self, message_id: str) -> bool:
        if self._db is None:
            return False
        try:
            n = self._db.execute(
                "UPDATE messages SET deleted_at = NULL WHERE message_id = ? AND deleted_at IS NOT NULL",
                (str(message_id),),
            ).rowcount
            if n:
                self.audit("restore_message", str(message_id))
            return bool(n)
        except Exception:
            logger.exception("restore message failed")
            return False

    # ── 聊天记录：级联软删 / 恢复 / 清空 ─────────────────
    def trash_conversations(self, conversation_ids: list[str]) -> dict[str, Any]:
        """级联软删：消息 + 摘要分桶 + 关联 long_term_memory（Chroma purge 期才删）。
        chat_log 同步打标记，保证 /api/chat/poll 与 /api/chat/history 不再露出已清空记录。"""
        if self._db is None or not conversation_ids:
            return {"trashed_messages": 0, "trashed_buckets": 0, "trashed_memories": 0, "trashed_chat_log": 0}
        ids = [str(i) for i in conversation_ids if i]
        placeholders = ",".join("?" * len(ids))
        ts = _now_str()
        memory_ts = time.time()
        try:
            n_msg = self._db.execute(
                f"UPDATE messages SET deleted_at = ? "
                f"WHERE conversation_id IN ({placeholders}) AND deleted_at IS NULL",
                (ts, *ids),
            ).rowcount
            n_log = self._db.execute(
                f"""UPDATE chat_log SET deleted_at = ?
                    WHERE deleted_at IS NULL AND id IN (
                        SELECT legacy_chat_log_id FROM messages
                        WHERE conversation_id IN ({placeholders})
                          AND legacy_chat_log_id IS NOT NULL
                    )""",
                (ts, *ids),
            ).rowcount
            n_bucket = self._db.execute(
                f"UPDATE conversation_summary_buckets SET deleted_at = ? "
                f"WHERE conversation_id IN ({placeholders}) AND deleted_at IS NULL",
                (ts, *ids),
            ).rowcount
            mem_rows = self._db.query(
                f"""SELECT id FROM long_term_memory
                    WHERE deleted_at IS NULL AND source_message_id IN (
                        SELECT message_id FROM messages
                        WHERE conversation_id IN ({placeholders}))""",
                (*ids,),
            )
            mem_ids = [r["id"] for r in mem_rows]
            n_mem = 0
            if mem_ids:
                mem_ph = ",".join("?" * len(mem_ids))
                n_mem = self._db.execute(
                    f"UPDATE long_term_memory SET deleted_at = ? "
                    f"WHERE id IN ({mem_ph})",
                    (memory_ts, *mem_ids),
                ).rowcount
            self.audit("trash", ",".join(ids))
            return {
                "trashed_messages": int(n_msg or 0),
                "trashed_chat_log": int(n_log or 0),
                "trashed_buckets": int(n_bucket or 0),
                "trashed_memories": int(n_mem or 0),
            }
        except Exception:
            logger.exception("trash conversations failed")
            self.audit("trash", ",".join(ids), reason_code="error")
            return {"trashed_messages": 0, "trashed_buckets": 0, "trashed_memories": 0, "trashed_chat_log": 0}

    def restore_conversations(self, conversation_ids: list[str]) -> dict[str, Any]:
        """级联恢复（软删反向：清 deleted_at）。"""
        if self._db is None or not conversation_ids:
            return {"restored_messages": 0, "restored_buckets": 0, "restored_memories": 0, "restored_chat_log": 0}
        ids = [str(i) for i in conversation_ids if i]
        placeholders = ",".join("?" * len(ids))
        try:
            n_msg = self._db.execute(
                f"UPDATE messages SET deleted_at = NULL "
                f"WHERE conversation_id IN ({placeholders})",
                (*ids,),
            ).rowcount
            n_log = self._db.execute(
                f"""UPDATE chat_log SET deleted_at = NULL
                    WHERE deleted_at IS NOT NULL AND id IN (
                        SELECT legacy_chat_log_id FROM messages
                        WHERE conversation_id IN ({placeholders})
                          AND legacy_chat_log_id IS NOT NULL
                    )""",
                (*ids,),
            ).rowcount
            n_bucket = self._db.execute(
                f"UPDATE conversation_summary_buckets SET deleted_at = NULL "
                f"WHERE conversation_id IN ({placeholders})",
                (*ids,),
            ).rowcount
            mem_rows = self._db.query(
                f"""SELECT id FROM long_term_memory
                    WHERE deleted_at IS NOT NULL AND source_message_id IN (
                        SELECT message_id FROM messages
                        WHERE conversation_id IN ({placeholders}))""",
                (*ids,),
            )
            mem_ids = [r["id"] for r in mem_rows]
            n_mem = 0
            if mem_ids:
                mem_ph = ",".join("?" * len(mem_ids))
                n_mem = self._db.execute(
                    f"UPDATE long_term_memory SET deleted_at = NULL "
                    f"WHERE id IN ({mem_ph})",
                    (*mem_ids,),
                ).rowcount
            self.audit("restore", ",".join(ids))
            return {
                "restored_messages": int(n_msg or 0),
                "restored_chat_log": int(n_log or 0),
                "restored_buckets": int(n_bucket or 0),
                "restored_memories": int(n_mem or 0),
            }
        except Exception:
            logger.exception("restore conversations failed")
            return {"restored_messages": 0, "restored_buckets": 0, "restored_memories": 0, "restored_chat_log": 0}

    def purge_expired(self, limit: int = PURGE_BATCH_SIZE) -> dict[str, Any]:
        """物理删除超过保留期的已软删数据（幂等，按批 ≤limit）。"""
        return self._purge(limit=limit, expired_only=True)

    def purge_all(self) -> dict[str, Any]:
        """手动"立即清空回收站"（弹警告后调用）。"""
        return self._purge(limit=100000, expired_only=False)

    def _purge(self, limit: int, expired_only: bool) -> dict[str, Any]:
        if self._db is None:
            return {"messages": 0, "buckets": 0, "memories": 0, "vectors": 0}
        try:
            cutoff_str = (
                (datetime.now() - timedelta(hours=self.retention_hours)).strftime(_TS_FMT)
                if expired_only
                else _now_str()
            )
            cutoff_ts = time.time() - self.retention_hours * 3600 if expired_only else time.time()

            # 1) 先取待物理删除的消息 id（软删后 rowid 稳定，物理删除前先收集关联记忆）
            msg_rows = self._db.query(
                """SELECT message_id FROM messages
                   WHERE deleted_at IS NOT NULL AND deleted_at <= ?
                   LIMIT ?""",
                (cutoff_str, int(limit)),
            )
            msg_ids = [r["message_id"] for r in msg_rows]
            mem_ids: list[str] = []
            if msg_ids:
                msg_ph = ",".join("?" * len(msg_ids))
                # 2) 收集这些消息关联的已软删长期记忆（Chroma 真删前先留 id）
                mem_rows = self._db.query(
                    f"""SELECT id FROM long_term_memory
                        WHERE deleted_at IS NOT NULL AND deleted_at <= ? AND source_message_id IN ({msg_ph})""",
                    (cutoff_ts, *msg_ids),
                )
                mem_ids = [r["id"] for r in mem_rows]
                # 3) 物理删除前先把 chat_log 对应行打上删除标记（删除后
                #    legacy_chat_log_id 关联会丢失，只能在此刻同步）
                self._db.execute(
                    f"""UPDATE chat_log SET deleted_at = ?
                        WHERE deleted_at IS NULL AND id IN (
                            SELECT legacy_chat_log_id FROM messages
                            WHERE message_id IN ({msg_ph})
                              AND legacy_chat_log_id IS NOT NULL
                        )""",
                    (cutoff_str, *msg_ids),
                )
                # 4) 再物理删除消息
                self._db.delete("messages", f"message_id IN ({msg_ph})", tuple(msg_ids))

            n_msg = len(msg_ids)
            # 4) 删除过期的摘要分桶
            n_bucket = self._db.delete(
                "conversation_summary_buckets",
                "deleted_at IS NOT NULL AND deleted_at <= ?",
                (cutoff_str,),
            )

            # 5) 孤立记忆（无来源消息）一并清理
            orphan_rows = self._db.query(
                """SELECT id FROM long_term_memory
                   WHERE deleted_at IS NOT NULL AND deleted_at <= ?
                   AND (source_message_id IS NULL OR source_message_id = '')
                   LIMIT ?""",
                (cutoff_ts, int(limit)),
            )
            for r in orphan_rows:
                if r["id"] not in mem_ids:
                    mem_ids.append(r["id"])

            n_mem = 0
            vectors = 0
            if mem_ids:
                mem_ph = ",".join("?" * len(mem_ids))
                n_mem = self._db.delete(
                    "long_term_memory",
                    f"id IN ({mem_ph})",
                    tuple(mem_ids),
                )
                vectors = self._delete_chroma_vectors(mem_ids)

            self.audit(
                "purge",
                ",".join(msg_ids[:20]),
                reason_code="expired" if expired_only else "manual",
            )
            return {
                "messages": n_msg,
                "buckets": int(n_bucket or 0),
                "memories": int(n_mem or 0),
                "vectors": vectors,
            }
        except Exception:
            logger.exception("purge failed")
            return {"messages": 0, "buckets": 0, "memories": 0, "vectors": 0}

    def _delete_chroma_vectors(self, memory_ids: list[str]) -> int:
        """物理删除 long_term_memory 集合向量（软删期不调用，仅 purge 期）。"""
        if not memory_ids or self._memory is None:
            return 0
        try:
            layer = getattr(self._memory, "long_term", None)
            collection = getattr(layer, "_collection", None)
            if collection is None:
                return 0
            collection.delete(ids=list(memory_ids))
            return len(memory_ids)
        except Exception:
            logger.exception("chroma vector delete failed")
            return 0

    # ── 分层记忆（long_term_memory 表维度） ──────────────
    def list_memory(
        self,
        user_id: Optional[int] = None,
        layer: str = "long_term",
        limit: int = 100,
        offset: int = 0,
        include_trashed: bool = True,
    ) -> dict[str, Any]:
        if self._db is None:
            return {"items": [], "total": 0}
        try:
            # 管理平台为系统级视角：默认列出全部记忆（含 persona 的 user_id=0 记录），
            # 仅在显式传入 user_id 时按用户过滤。
            base = "SELECT * FROM long_term_memory"
            where: list[str] = []
            params: list[Any] = []
            if user_id is not None:
                where.append("user_id = ?")
                params.append(int(user_id))
            if layer in ("permanent",):
                where.append("memory_type = 'permanent'")
            elif layer in ("long_term", "working", "transient"):
                # transient/working 为内存态不落库，统一按 long_term 表管理
                where.append("memory_type != 'permanent'")
            else:
                return {"items": [], "total": 0, "layer": layer}
            if not include_trashed:
                where.append("(deleted_at IS NULL OR deleted_at = 0)")
            if where:
                base += " WHERE " + " AND ".join(where)
            total = self._db.query(
                f"SELECT COUNT(*) AS n FROM ({base})",
                tuple(params),
            )
            rows = self._db.query(
                base + " ORDER BY importance DESC, created_at DESC LIMIT ? OFFSET ?",
                tuple(params + [int(limit), int(offset)]),
            )
            return {
                "items": rows,
                "total": int(total[0]["n"]) if total else 0,
                "layer": layer,
            }
        except Exception:
            logger.exception("list memory failed")
            return {"items": [], "total": 0, "layer": layer}

    def get_memory(self, memory_id: str) -> Optional[dict[str, Any]]:
        if self._db is None:
            return None
        try:
            return self._db.query_one(
                "SELECT * FROM long_term_memory WHERE id = ?",
                (str(memory_id),),
            )
        except Exception:
            logger.exception("get memory failed")
            return None

    def update_memory(
        self,
        memory_id: str,
        changes: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        if self._db is None:
            return None
        row = self.get_memory(memory_id)
        if not row:
            return None
        allowed = {"content", "importance", "memory_type", "metadata", "confidence"}
        data: dict[str, Any] = {}
        for key, value in changes.items():
            if key not in allowed:
                continue
            if key == "importance":
                try:
                    data["importance"] = max(0, min(10, int(value)))
                except (TypeError, ValueError):
                    continue
            elif key == "metadata" and isinstance(value, dict):
                data["metadata"] = json.dumps(value, ensure_ascii=False)
            elif key in ("content", "memory_type", "confidence"):
                data[key] = value
        if not data:
            return row
        try:
            data["updated_at"] = time.time()
            self._db.update("long_term_memory", data, "id = ?", (str(memory_id),))
            self.audit("update_memory", str(memory_id))
            return self.get_memory(memory_id)
        except Exception:
            logger.exception("update memory failed")
            return None

    def delete_memory(self, memory_id: str) -> bool:
        """软删单条记忆（回收站可恢复）。"""
        if self._db is None:
            return False
        try:
            n = self._db.execute(
                "UPDATE long_term_memory SET deleted_at = ? WHERE id = ? AND (deleted_at IS NULL OR deleted_at = 0)",
                (time.time(), str(memory_id)),
            ).rowcount
            if n:
                self.audit("trash", str(memory_id))
            return bool(n)
        except Exception:
            logger.exception("delete memory failed")
            return False

    def restore_memory(self, memory_id: str) -> bool:
        if self._db is None:
            return False
        try:
            n = self._db.execute(
                "UPDATE long_term_memory SET deleted_at = NULL WHERE id = ?",
                (str(memory_id),),
            ).rowcount
            if n:
                self.audit("restore", str(memory_id))
            return bool(n)
        except Exception:
            logger.exception("restore memory failed")
            return False

    # ── 知识库：确认 + undo 快照（非回收站） ──────────────
    def list_kb(self, category: Optional[str] = None, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        if self._db is None:
            return {"items": [], "total": 0}
        try:
            where = "WHERE deleted_at IS NULL"
            params: list[Any] = []
            if category:
                where += " AND category = ?"
                params.append(str(category))
            rows = self._db.query(
                f"SELECT * FROM knowledge_base {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                tuple(params + [int(limit), int(offset)]),
            )
            total = self._db.query(
                f"SELECT COUNT(*) AS n FROM knowledge_base {where}",
                tuple(params),
            )
            return {"items": rows, "total": int(total[0]["n"]) if total else 0}
        except Exception:
            logger.exception("list kb failed")
            return {"items": [], "total": 0}

    def delete_kb_with_undo(self, item_id: int) -> Optional[dict[str, Any]]:
        """删除前把整行快照进 audit_log（JSON），返回快照供 undo。"""
        if self._db is None:
            return None
        try:
            row = self._db.query_one(
                "SELECT * FROM knowledge_base WHERE id = ?",
                (int(item_id),),
            )
            if not row:
                return None
            # 快照先落审计，再物理删除（确认 + undo）
            self.audit(
                "delete_kb",
                f"kb:{int(item_id)}",
                reason_code="manual",
            )
            self._db.execute(
                "UPDATE knowledge_base SET deleted_at = ? WHERE id = ?",
                (_now_str(), int(item_id)),
            )
            return row
        except Exception:
            logger.exception("delete kb failed")
            return None

    def undo_kb_delete(self, item_id: int) -> bool:
        if self._db is None:
            return False
        try:
            n = self._db.execute(
                "UPDATE knowledge_base SET deleted_at = NULL WHERE id = ?",
                (int(item_id),),
            ).rowcount
            if n:
                self.audit("restore", f"kb:{int(item_id)}")
            return bool(n)
        except Exception:
            logger.exception("undo kb delete failed")
            return False

    # ── 状态文件：只读查看（重置走引擎方法，运行时验证） ──────
    _STATE_FILES: dict[str, str] = {
        "desire": "desire_state.json",
        "proactive": "proactive_policy_state.json",
        "topic": "topic_state.json",
        "runtime": "runtime_config.json",
    }

    def list_state(self) -> dict[str, Any]:
        out: list[dict[str, Any]] = []
        for kind, filename in self._STATE_FILES.items():
            path = self._data_dir / filename
            info: dict[str, Any] = {"kind": kind, "exists": False, "size": 0, "modified_at": None}
            try:
                if path.exists():
                    stat = path.stat()
                    info.update(
                        {
                            "exists": True,
                            "size": int(stat.st_size),
                            "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
                        }
                    )
            except OSError:
                pass
            out.append(info)
        return {"items": out}

    def get_state(self, kind: str) -> Optional[dict[str, Any]]:
        filename = self._STATE_FILES.get(kind)
        if not filename:
            return None
        path = self._data_dir / filename
        try:
            if not path.exists():
                return {"kind": kind, "exists": False}
            data: Any = {}
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, TypeError):
                data = path.read_text(encoding="utf-8", errors="replace")
            return {"kind": kind, "exists": True, "content": data}
        except OSError:
            logger.exception("read state file failed: %s", kind)
            return None

    def reset_state(self, kind: str, companion: Any = None) -> dict[str, Any]:
        """状态重置：先落 undo 快照，再走引擎方法复位。

        - desire：写引擎默认状态（确定性 default）
        - topic：调 companion.topic_tracker.reset()（引擎方法）
        - proactive/runtime：无确定性默认 → 仅快照，返回 unavailable
        """
        filename = self._STATE_FILES.get(kind)
        if not filename:
            return {"status": "unknown_kind", "kind": kind}
        path = self._data_dir / filename
        snapshotted = False
        try:
            if path.exists():
                self._data_dir.mkdir(parents=True, exist_ok=True)
                snapshot_path = self._data_dir / f"{kind}.undo.json"
                snapshot_path.write_text(
                    path.read_text(encoding="utf-8"), encoding="utf-8"
                )
                snapshotted = True
        except OSError:
            logger.exception("state reset snapshot failed: %s", kind)

        if kind == "desire":
            from core.desire_engine import _atomic_write_json, _default_state

            _atomic_write_json(path, _default_state())
            self.audit("reset_state", kind)
            return {"status": "ok", "kind": kind, "snapshot": snapshotted}

        if kind == "topic" and companion is not None:
            tracker = getattr(companion, "topic_tracker", None)
            if tracker is not None and hasattr(tracker, "reset"):
                try:
                    tracker.reset()
                    self.audit("reset_state", kind)
                    return {"status": "ok", "kind": kind, "snapshot": snapshotted}
                except Exception:
                    logger.exception("topic reset failed")
            return {"status": "unavailable", "kind": kind, "reason": "no_topic_tracker"}

        self.audit("reset_state", kind)
        return {
            "status": "unavailable",
            "kind": kind,
            "reason": "engine_reset_not_implemented",
            "snapshot": snapshotted,
        }

    def undo_state(self, kind: str) -> dict[str, Any]:
        """恢复最近一次重置前的状态快照（{kind}.undo.json）。"""
        if kind not in self._STATE_FILES:
            return {"status": "unknown_kind", "kind": kind}
        snapshot_path = self._data_dir / f"{kind}.undo.json"
        try:
            if not snapshot_path.exists():
                return {"status": "no_snapshot", "kind": kind}
            target = self._data_dir / self._STATE_FILES[kind]
            target.write_text(snapshot_path.read_text(encoding="utf-8"), encoding="utf-8")
            snapshot_path.unlink()
            self.audit("restore", f"state:{kind}")
            return {"status": "ok", "kind": kind}
        except OSError:
            logger.exception("undo state failed: %s", kind)
            return {"status": "error", "kind": kind}
