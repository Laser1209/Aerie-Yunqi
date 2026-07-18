"""Aerie v13.9.8 — QQ 白名单管理器。

仅白名单内的 QQ 用户可触发 Agent 回复。
非白名单消息静默忽略，不消耗 Token。
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)


class QQWhitelistManager:
    """QQ 用户白名单管理器。

    设计原则：
    - 白名单为空时 = 全部放行（兼容旧行为，避免误拦截）
    - 白名单有数据时 = 严格模式，仅白名单内用户可触发回复
    - 支持备注、启用/禁用单个条目
    """

    def __init__(self, db) -> None:
        self.db = db
        self._ensure_table()
        self._cache: set[int] = set()
        self._cache_dirty = True
        self._enabled: bool = True

    def _ensure_table(self) -> None:
        """确保 qq_whitelist 表存在。"""
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS qq_whitelist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                qq_number INTEGER NOT NULL UNIQUE,
                remark TEXT DEFAULT '',
                enabled INTEGER DEFAULT 1,
                added_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                last_message_at TEXT
            );
            """,
        )
        try:
            self.db.execute(
                "CREATE INDEX IF NOT EXISTS idx_qq_whitelist_number ON qq_whitelist(qq_number);"
            )
        except Exception:
            pass

    def is_enabled(self) -> bool:
        """白名单机制是否启用。"""
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """启用/禁用白名单机制。"""
        self._enabled = enabled
        self._cache_dirty = True

    def _refresh_cache(self) -> None:
        """刷新内存缓存。"""
        try:
            rows = self.db.query(
                "SELECT qq_number FROM qq_whitelist WHERE enabled = 1"
            )
            self._cache = {int(row["qq_number"]) for row in rows}
            self._cache_dirty = False
        except Exception:
            logger.exception("QQ whitelist cache refresh failed")
            self._cache = set()

    def is_allowed(self, user_id: int | str) -> bool:
        """检查用户是否在白名单内。

        规则：
        - 白名单机制禁用 → 全部放行
        - 白名单为空 → 全部放行（兼容模式，避免没人能用）
        - 白名单非空 → 严格检查
        """
        if not self._enabled:
            return True

        if self._cache_dirty:
            self._refresh_cache()

        # 空白名单 = 兼容模式，全部放行
        if not self._cache:
            return True

        try:
            uid = int(user_id)
        except (ValueError, TypeError):
            return False

        return uid in self._cache

    def list_all(self) -> list[dict]:
        """列出所有白名单条目。"""
        try:
            rows = self.db.query(
                "SELECT * FROM qq_whitelist ORDER BY added_at DESC"
            )
            return [dict(row) for row in rows]
        except Exception:
            logger.exception("list whitelist failed")
            return []

    def add(self, qq_number: int | str, remark: str = "") -> bool:
        """添加白名单用户。"""
        try:
            qq = int(qq_number)
            self.db.execute(
                "INSERT OR IGNORE INTO qq_whitelist (qq_number, remark, enabled) VALUES (?, ?, 1)",
                (qq, remark or ""),
            )
            # 如果已存在，更新备注和启用状态
            self.db.execute(
                "UPDATE qq_whitelist SET remark = ?, enabled = 1 WHERE qq_number = ?",
                (remark or "", qq),
            )
            self._cache_dirty = True
            return True
        except Exception:
            logger.exception("add whitelist failed")
            return False

    def remove(self, qq_number: int | str) -> bool:
        """移除白名单用户。"""
        try:
            qq = int(qq_number)
            self.db.execute(
                "DELETE FROM qq_whitelist WHERE qq_number = ?",
                (qq,),
            )
            self._cache_dirty = True
            return True
        except Exception:
            logger.exception("remove whitelist failed")
            return False

    def toggle(self, qq_number: int | str, enabled: bool) -> bool:
        """启用/禁用单个白名单条目。"""
        try:
            qq = int(qq_number)
            self.db.execute(
                "UPDATE qq_whitelist SET enabled = ? WHERE qq_number = ?",
                (1 if enabled else 0, qq),
            )
            self._cache_dirty = True
            return True
        except Exception:
            logger.exception("toggle whitelist failed")
            return False

    def update_remark(self, qq_number: int | str, remark: str) -> bool:
        """更新备注。"""
        try:
            qq = int(qq_number)
            self.db.execute(
                "UPDATE qq_whitelist SET remark = ? WHERE qq_number = ?",
                (remark or "", qq),
            )
            return True
        except Exception:
            logger.exception("update remark failed")
            return False

    def update_last_message(self, qq_number: int | str) -> None:
        """更新最后消息时间。"""
        try:
            qq = int(qq_number)
            self.db.execute(
                "UPDATE qq_whitelist SET last_message_at = datetime('now', 'localtime') WHERE qq_number = ?",
                (qq,),
            )
        except Exception:
            pass

    def bulk_add(self, qq_numbers: list[int | str], remark_prefix: str = "") -> int:
        """批量添加白名单，返回成功数量。"""
        count = 0
        for qq in qq_numbers:
            if self.add(qq, remark_prefix):
                count += 1
        return count

    def clear(self) -> bool:
        """清空白名单（恢复兼容模式）。"""
        try:
            self.db.execute("DELETE FROM qq_whitelist")
            self._cache_dirty = True
            return True
        except Exception:
            logger.exception("clear whitelist failed")
            return False

    def stats(self) -> dict:
        """统计信息。"""
        try:
            total = self.db.query_one(
                "SELECT COUNT(*) as cnt FROM qq_whitelist"
            )
            active = self.db.query_one(
                "SELECT COUNT(*) as cnt FROM qq_whitelist WHERE enabled = 1"
            )
            return {
                "enabled": self._enabled,
                "total": int(total["cnt"]) if total else 0,
                "active": int(active["cnt"]) if active else 0,
                "mode": "strict" if self._cache and self._enabled else "compatible",
            }
        except Exception:
            return {"enabled": self._enabled, "total": 0, "active": 0, "mode": "compatible"}
