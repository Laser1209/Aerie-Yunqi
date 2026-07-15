"""知识库存储层：SQLite 结构化存储 + 向量索引

数据模型：
- knowledge_entries: 知识条目（content/category/tags/source/confidence/version/status）
- knowledge_categories: 分类树（层级结构）
- knowledge_changelog: 重组日志
"""
from __future__ import annotations

import json
import os
import sqlite3
import struct
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from loguru import logger


# ===== SQL 建表 =====
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS knowledge_entries (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    category TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    source TEXT DEFAULT 'unknown',
    source_ref TEXT DEFAULT '',
    confidence REAL DEFAULT 1.0,
    embedding BLOB,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_accessed TEXT,
    version INTEGER DEFAULT 1,
    previous_id TEXT DEFAULT '',
    status TEXT DEFAULT 'active',
    user_id INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS knowledge_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    parent_id INTEGER DEFAULT 0,
    description TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_changelog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    detail TEXT DEFAULT '',
    affected_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entries_status ON knowledge_entries(status);
CREATE INDEX IF NOT EXISTS idx_entries_category ON knowledge_entries(category);
CREATE INDEX IF NOT EXISTS idx_entries_updated ON knowledge_entries(updated_at);
CREATE INDEX IF NOT EXISTS idx_entries_user ON knowledge_entries(user_id);
"""


def _serialize_vector(vec: np.ndarray) -> bytes:
    """将 numpy 向量序列化为 BLOB（float32 little-endian）"""
    return vec.astype(np.float32).tobytes()


def _deserialize_vector(blob: bytes, dim: int) -> np.ndarray:
    """从 BLOB 反序列化 numpy 向量"""
    arr = np.frombuffer(blob, dtype=np.float32)
    if len(arr) != dim:
        raise ValueError(f"向量维度不匹配: 期望 {dim}, 实际 {len(arr)}")
    return arr.copy()


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """余弦相似度"""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


class KnowledgeStore:
    """知识库 SQLite 存储 + 向量检索"""

    def __init__(self, db_path: str = "data/knowledge.db", embedding_dim: int = 1024):
        self._db_path = db_path
        self._embedding_dim = embedding_dim
        self._conn: Optional[sqlite3.Connection] = None

    async def initialize(self) -> None:
        """初始化数据库连接和表结构"""
        db_dir = Path(self._db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()
        logger.info(f"知识库已初始化: {self._db_path} (dim={self._embedding_dim})")

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ===== CRUD =====

    async def add_entry(
        self,
        content: str,
        embedding: Optional[np.ndarray] = None,
        category: str = "",
        tags: Optional[List[str]] = None,
        source: str = "unknown",
        source_ref: str = "",
        confidence: float = 1.0,
        user_id: int = 0,
    ) -> str:
        """添加知识条目，返回 entry_id"""
        entry_id = str(uuid.uuid4())[:12]
        now = datetime.now().isoformat()
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        emb_blob = _serialize_vector(embedding) if embedding is not None else None

        self._conn.execute(
            """INSERT INTO knowledge_entries
               (id, content, category, tags, source, source_ref, confidence,
                embedding, created_at, updated_at, last_accessed, user_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (entry_id, content, category, tags_json, source, source_ref,
             confidence, emb_blob, now, now, now, user_id),
        )
        self._conn.commit()
        logger.debug(f"知识条目已添加: {entry_id} ({source})")
        return entry_id

    async def update_entry(self, entry_id: str, **fields) -> bool:
        """更新条目字段"""
        allowed = {"content", "category", "tags", "confidence", "status",
                   "version", "previous_id", "embedding"}
        updates = {}
        for k, v in fields.items():
            if k in allowed:
                if k == "tags" and isinstance(v, list):
                    updates[k] = json.dumps(v, ensure_ascii=False)
                elif k == "embedding" and isinstance(v, np.ndarray):
                    updates[k] = _serialize_vector(v)
                else:
                    updates[k] = v

        if not updates:
            return False

        updates["updated_at"] = datetime.now().isoformat()
        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [entry_id]

        cur = self._conn.execute(
            f"UPDATE knowledge_entries SET {set_clause} WHERE id=?",
            values,
        )
        self._conn.commit()
        return cur.rowcount > 0

    async def get_entry(self, entry_id: str) -> Optional[Dict[str, Any]]:
        """获取单条知识条目"""
        row = self._conn.execute(
            "SELECT * FROM knowledge_entries WHERE id=?", (entry_id,)
        ).fetchone()
        if row is None:
            return None
        entry = self._row_to_dict(row)
        self._touch(entry_id)
        return entry

    async def delete_entry(self, entry_id: str) -> bool:
        """软删除（status='deleted'）"""
        return await self.update_entry(entry_id, status="deleted")

    async def list_entries(
        self,
        category: Optional[str] = None,
        status: str = "active",
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """列表查询"""
        where = "WHERE status=?"
        params: List[Any] = [status]
        if category:
            where += " AND category=?"
            params.append(category)

        rows = self._conn.execute(
            f"SELECT * FROM knowledge_entries {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # ===== 向量检索 =====

    async def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 5,
        status: str = "active",
        min_similarity: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """
        语义检索：遍历所有活跃条目，计算余弦相似度，返回 Top-K。
        """
        rows = self._conn.execute(
            "SELECT * FROM knowledge_entries WHERE status=? AND embedding IS NOT NULL",
            (status,),
        ).fetchall()

        results = []
        for row in rows:
            entry = self._row_to_dict(row)
            emb = _deserialize_vector(row["embedding"], self._embedding_dim)
            sim = _cosine_similarity(query_embedding, emb)
            if sim >= min_similarity:
                entry["similarity"] = sim
                results.append(entry)

        results.sort(key=lambda x: x["similarity"], reverse=True)
        top = results[:top_k]
        for entry in top:
            self._touch(entry["id"])
        return top

    # ===== 批量操作 =====

    async def get_active_entries(self) -> List[Dict[str, Any]]:
        """获取所有活跃条目（用于重组）"""
        rows = self._conn.execute(
            "SELECT * FROM knowledge_entries WHERE status='active'"
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    async def get_all_vectors(self) -> Dict[str, np.ndarray]:
        """获取所有有向量的条目 {id: vector}"""
        rows = self._conn.execute(
            "SELECT id, embedding FROM knowledge_entries WHERE embedding IS NOT NULL AND status='active'"
        ).fetchall()
        result = {}
        for row in rows:
            try:
                result[row["id"]] = _deserialize_vector(row["embedding"], self._embedding_dim)
            except Exception:
                continue
        return result

    async def find_duplicates(self, threshold: float = 0.92) -> List[List[str]]:
        """
        查找重复条目：向量相似度 > threshold 视为重复。
        返回 [[id1, id2], [id3, id4, id5], ...]
        """
        vectors = await self.get_all_vectors()
        if len(vectors) < 2:
            return []

        ids = list(vectors.keys())
        n = len(ids)
        visited = set()
        groups = []

        for i in range(n):
            if ids[i] in visited:
                continue
            group = [ids[i]]
            for j in range(i + 1, n):
                if ids[j] in visited:
                    continue
                sim = _cosine_similarity(vectors[ids[i]], vectors[ids[j]])
                if sim > threshold:
                    group.append(ids[j])
                    visited.add(ids[j])
            if len(group) > 1:
                groups.append(group)
                visited.add(ids[i])

        return groups

    async def find_cold_entries(self, days: int = 90) -> List[Dict[str, Any]]:
        """查找冷数据（超过 days 天未被访问）"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            """SELECT * FROM knowledge_entries
               WHERE status='active' AND (last_accessed IS NULL OR last_accessed < ?)""",
            (cutoff,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # ===== 分类 =====

    async def get_categories(self) -> List[Dict[str, Any]]:
        """获取所有分类"""
        rows = self._conn.execute(
            "SELECT * FROM knowledge_categories ORDER BY parent_id, id"
        ).fetchall()
        return [{key: r[key] for key in r.keys()} for r in rows]

    async def add_category(self, name: str, parent_id: int = 0, description: str = "") -> int:
        """添加分类，返回 category_id"""
        now = datetime.now().isoformat()
        cur = self._conn.execute(
            "INSERT INTO knowledge_categories (name, parent_id, description, created_at) VALUES (?, ?, ?, ?)",
            (name, parent_id, description, now),
        )
        self._conn.commit()
        return cur.lastrowid

    async def batch_update_category(self, entry_ids: List[str], category: str) -> int:
        """批量更新条目分类，返回更新数量"""
        now = datetime.now().isoformat()
        placeholders = ",".join("?" * len(entry_ids))
        cur = self._conn.execute(
            f"UPDATE knowledge_entries SET category=?, updated_at=? WHERE id IN ({placeholders})",
            [category, now] + entry_ids,
        )
        self._conn.commit()
        return cur.rowcount

    # ===== 变更日志 =====

    async def add_changelog(self, action: str, detail: str = "", affected_count: int = 0) -> None:
        """记录重组日志"""
        now = datetime.now().isoformat()
        self._conn.execute(
            "INSERT INTO knowledge_changelog (action, detail, affected_count, created_at) VALUES (?, ?, ?, ?)",
            (action, detail, affected_count, now),
        )
        self._conn.commit()

    async def get_changelog(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取最近的重组日志"""
        rows = self._conn.execute(
            "SELECT * FROM knowledge_changelog ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [{key: r[key] for key in r.keys()} for r in rows]

    # ===== 统计 =====

    async def get_stats(self) -> Dict[str, Any]:
        """知识库统计"""
        total = self._conn.execute(
            "SELECT COUNT(*) FROM knowledge_entries WHERE status='active'"
        ).fetchone()[0]
        archived = self._conn.execute(
            "SELECT COUNT(*) FROM knowledge_entries WHERE status='archived'"
        ).fetchone()[0]
        categories = self._conn.execute(
            "SELECT COUNT(DISTINCT category) FROM knowledge_entries WHERE status='active' AND category!=''"
        ).fetchone()[0]
        with_embedding = self._conn.execute(
            "SELECT COUNT(*) FROM knowledge_entries WHERE embedding IS NOT NULL AND status='active'"
        ).fetchone()[0]

        return {
            "total_active": total,
            "total_archived": archived,
            "categories": categories,
            "with_embedding": with_embedding,
        }

    # ===== 辅助 =====

    def _touch(self, entry_id: str) -> None:
        """更新 last_accessed"""
        now = datetime.now().isoformat()
        self._conn.execute(
            "UPDATE knowledge_entries SET last_accessed=? WHERE id=?",
            (now, entry_id),
        )
        self._conn.commit()

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """将 SQLite Row 转为字典"""
        d = {key: row[key] for key in row.keys()}
        if "tags" in d and isinstance(d["tags"], str):
            try:
                d["tags"] = json.loads(d["tags"])
            except json.JSONDecodeError:
                d["tags"] = []
        if "embedding" in d:
            d["embedding"] = None  # 不返回原始 BLOB
        return d
