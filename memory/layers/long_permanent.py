"""Aerie · 云栖 v11.2 — Long-term + Permanent 记忆层 (S3 M3.1).

Long-term (长期层):
    - ChromaDB 向量数据库存储嵌入，SQLite 存元数据
    - 持久化用户偏好、重要事实、关系图谱
    - 支持语义检索 + 关键词检索混合

Permanent (永久层):
    - Markdown 文件存储，Git 版本控制
    - 经过验证的核心知识、人格设定、不可遗忘信息
    - 只读为主，修改需要审批和版本记录
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from memory.layers.base import (
    BaseMemoryLayer, MemoryItem, MemoryLayer, MemoryType,
    MemorySearchResult,
)

logger = logging.getLogger(__name__)


# ── Long-term Memory Layer ──────────────────────────

class LongTermMemoryLayer(BaseMemoryLayer):
    """
    长期记忆层 —— ChromaDB 向量 + SQLite 元数据。

    优先级：
    1. 向量语义检索（主路径）
    2. SQLite 关键词检索（fallback）
    3. 混合排序

    如果 ChromaDB 不可用（未安装），自动降级为纯 SQLite 模式。
    """

    layer = MemoryLayer.LONG_TERM

    def __init__(
        self,
        db: Any = None,
        chroma_persist_dir: str = "data/chroma",
        embedding_fn: Any = None,
        collection_name: str = "long_term_memory",
    ) -> None:
        self.db = db
        self.chroma_persist_dir = chroma_persist_dir
        self.embedding_fn = embedding_fn
        self.collection_name = collection_name

        self._collection: Any = None
        self._chroma_available = False

        # 尝试初始化 ChromaDB
        self._init_chroma()

        # 确保 SQLite 表存在
        self._ensure_schema()

    def _init_chroma(self) -> None:
        """尝试初始化 ChromaDB."""
        try:
            import chromadb  # type: ignore
            from chromadb.config import Settings  # type: ignore

            os.makedirs(self.chroma_persist_dir, exist_ok=True)
            client = chromadb.PersistentClient(
                path=self.chroma_persist_dir,
                settings=Settings(anonymized_telemetry=False),
            )
            self._collection = client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            self._chroma_available = True
            logger.info("ChromaDB initialized: %s", self.chroma_persist_dir)
        except ImportError:
            logger.warning("ChromaDB not installed, falling back to SQLite only")
        except Exception:
            logger.exception("Failed to initialize ChromaDB, falling back to SQLite")

    def _ensure_schema(self) -> None:
        """确保 SQLite 表存在."""
        if not self.db:
            return
        try:
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS long_term_memory (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    memory_type TEXT NOT NULL DEFAULT 'fact',
                    content TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}',
                    importance REAL DEFAULT 5.0,
                    access_count INTEGER DEFAULT 0,
                    created_at REAL DEFAULT 0,
                    updated_at REAL DEFAULT 0,
                    accessed_at REAL DEFAULT 0,
                    source TEXT DEFAULT '',
                    has_embedding INTEGER DEFAULT 0
                )
            """)
            self.db.execute(
                "CREATE INDEX IF NOT EXISTS idx_ltm_user_id ON long_term_memory(user_id)"
            )
            self.db.execute(
                "CREATE INDEX IF NOT EXISTS idx_ltm_importance ON long_term_memory(importance DESC)"
            )
        except Exception:
            logger.exception("Failed to create long_term_memory table")

    def _get_embedding(self, text: str) -> Optional[List[float]]:
        """获取文本的向量嵌入."""
        if self.embedding_fn:
            try:
                return self.embedding_fn(text)
            except Exception:
                logger.exception("Embedding function failed")
                return None
        return None

    async def store(self, item: MemoryItem) -> str:
        item.layer = MemoryLayer.LONG_TERM
        now = time.time()
        item.created_at = item.created_at or now
        item.updated_at = now
        item.accessed_at = now

        has_embedding = 0

        # 存 ChromaDB
        if self._chroma_available and self.embedding_fn:
            try:
                embedding = self._get_embedding(item.content)
                if embedding:
                    self._collection.add(
                        ids=[item.id],
                        embeddings=[embedding],
                        documents=[item.content],
                        metadatas=[{
                            "user_id": item.user_id,
                            "memory_type": item.memory_type.value if isinstance(item.memory_type, MemoryType) else item.memory_type,
                            "importance": item.importance,
                            "source": item.source,
                        }],
                    )
                    has_embedding = 1
                    item.embedding = embedding
            except Exception:
                logger.exception("Failed to store in ChromaDB")

        # 存 SQLite
        if self.db:
            try:
                data = {
                    "user_id": item.user_id,
                    "memory_type": item.memory_type.value if isinstance(item.memory_type, MemoryType) else item.memory_type,
                    "content": item.content,
                    "metadata": json.dumps(item.metadata, ensure_ascii=False),
                    "importance": item.importance,
                    "access_count": item.access_count,
                    "created_at": item.created_at,
                    "updated_at": item.updated_at,
                    "accessed_at": item.accessed_at,
                    "source": item.source,
                    "has_embedding": has_embedding,
                }

                # 判断 id 是否为数字（兼容 INTEGER PRIMARY KEY）
                id_is_int = False
                int_id = None
                try:
                    if item.id and str(item.id).isdigit():
                        int_id = int(item.id)
                        id_is_int = True
                except (ValueError, TypeError):
                    pass

                if id_is_int and hasattr(self.db, "update"):
                    # 有数字 id：先尝试 update，失败再 insert
                    data["id"] = int_id
                    updated = self.db.update(
                        "long_term_memory",
                        {k: v for k, v in data.items() if k != "id"},
                        "id = ?",
                        (int_id,),
                    )
                    if updated == 0:
                        # 不存在，插入
                        new_id = self.db.insert("long_term_memory", data)
                        if new_id:
                            item.id = str(new_id)
                elif hasattr(self.db, "insert"):
                    # 无数字 id 或无 update 方法：直接 insert
                    if id_is_int:
                        data["id"] = int_id
                    new_id = self.db.insert("long_term_memory", data)
                    if new_id:
                        item.id = str(new_id)
                else:
                    # fallback：直接用 execute
                    self.db.execute(
                        """
                        INSERT INTO long_term_memory
                        (user_id, memory_type, content, metadata, importance,
                         access_count, created_at, updated_at, accessed_at, source, has_embedding)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        tuple(data[k] for k in [
                            "user_id", "memory_type", "content", "metadata", "importance",
                            "access_count", "created_at", "updated_at", "accessed_at", "source", "has_embedding",
                        ]),
                    )
            except Exception:
                logger.exception("Failed to store in SQLite")

        return item.id

    async def retrieve(
        self,
        user_id: int,
        query: str = "",
        limit: int = 5,
        memory_type: Optional[MemoryType] = None,
    ) -> List[MemorySearchResult]:
        results: List[MemorySearchResult] = []

        # 优先 ChromaDB 向量检索
        if self._chroma_available and self.embedding_fn and query:
            try:
                query_embedding = self._get_embedding(query)
                if query_embedding:
                    where = {"user_id": user_id}
                    if memory_type:
                        where["memory_type"] = memory_type.value

                    chroma_result = self._collection.query(
                        query_embeddings=[query_embedding],
                        n_results=limit * 2,
                        where=where,
                    )
                    ids = chroma_result.get("ids", [[]])[0]
                    distances = chroma_result.get("distances", [[]])[0]
                    documents = chroma_result.get("documents", [[]])[0]

                    for mid, dist, doc in zip(ids, distances, documents):
                        # cosine distance → similarity score
                        score = max(0.0, 1.0 - dist)
                        # 从 SQLite 取完整数据
                        item = await self.get(mid)
                        if item:
                            results.append(MemorySearchResult(
                                item=item, score=score,
                                layer=MemoryLayer.LONG_TERM,
                                match_reason="semantic_similarity",
                            ))

                    if results:
                        # 更新访问计数
                        for r in results:
                            await self._bump_access(r.item.id)
                        return results[:limit]
            except Exception:
                logger.exception("ChromaDB query failed, falling back to SQLite")

        # Fallback: SQLite 关键词 + importance 排序
        if self.db:
            try:
                sql = """
                    SELECT * FROM long_term_memory
                    WHERE user_id = ?
                """
                params: List[Any] = [user_id]

                if memory_type:
                    sql += " AND memory_type = ?"
                    params.append(memory_type.value)

                if query:
                    sql += " AND content LIKE ?"
                    params.append(f"%{query}%")

                sql += " ORDER BY importance DESC, accessed_at DESC LIMIT ?"
                params.append(limit)

                rows = self.db.query(sql, tuple(params))
                for row in rows:
                    item = self._row_to_item(row)
                    score = 0.5 + (item.importance / 20.0)  # 0.5-1.0
                    results.append(MemorySearchResult(
                        item=item, score=score,
                        layer=MemoryLayer.LONG_TERM,
                        match_reason="importance_keyword",
                    ))
                    await self._bump_access(item.id)
            except Exception:
                logger.exception("SQLite query failed")

        return results[:limit]

    async def get(self, memory_id: str) -> Optional[MemoryItem]:
        if not self.db:
            return None
        try:
            row = self.db.query_one(
                "SELECT * FROM long_term_memory WHERE id = ?",
                (memory_id,),
            )
            if row:
                return self._row_to_item(row)
        except Exception:
            logger.exception("Failed to get memory item")
        return None

    async def update(self, memory_id: str, **kwargs) -> bool:
        if not self.db:
            return False
        try:
            kwargs["updated_at"] = time.time()
            if "metadata" in kwargs and isinstance(kwargs["metadata"], dict):
                kwargs["metadata"] = json.dumps(kwargs["metadata"], ensure_ascii=False)

            sets = ", ".join(f"{k} = ?" for k in kwargs.keys())
            params = list(kwargs.values()) + [memory_id]
            self.db.execute(f"UPDATE long_term_memory SET {sets} WHERE id = ?", tuple(params))

            # 同步更新 ChromaDB
            if self._chroma_available:
                try:
                    update_data: Dict[str, Any] = {}
                    if "content" in kwargs:
                        update_data["documents"] = [kwargs["content"]]
                    meta = {}
                    for k in ("importance", "source", "memory_type"):
                        if k in kwargs:
                            meta[k] = kwargs[k]
                    if meta:
                        update_data["metadatas"] = [meta]
                    if update_data:
                        update_data["ids"] = [memory_id]
                        self._collection.update(**update_data)
                except Exception:
                    logger.exception("Failed to update ChromaDB")

            return True
        except Exception:
            logger.exception("Failed to update memory item")
            return False

    async def delete(self, memory_id: str) -> bool:
        if not self.db:
            return False
        try:
            self.db.execute("DELETE FROM long_term_memory WHERE id = ?", (memory_id,))
            if self._chroma_available:
                try:
                    self._collection.delete(ids=[memory_id])
                except Exception:
                    logger.exception("Failed to delete from ChromaDB")
            return True
        except Exception:
            logger.exception("Failed to delete memory item")
            return False

    async def list_by_user(
        self,
        user_id: int,
        limit: int = 50,
        memory_type: Optional[MemoryType] = None,
    ) -> List[MemoryItem]:
        if not self.db:
            return []
        try:
            sql = "SELECT * FROM long_term_memory WHERE user_id = ?"
            params: List[Any] = [user_id]
            if memory_type:
                sql += " AND memory_type = ?"
                params.append(memory_type.value)
            sql += " ORDER BY importance DESC, created_at DESC LIMIT ?"
            params.append(limit)
            rows = self.db.query(sql, tuple(params))
            return [self._row_to_item(r) for r in rows]
        except Exception:
            logger.exception("Failed to list memory items")
            return []

    async def decay(self) -> int:
        """衰减 14 天未访问、重要度 > 1 的记忆."""
        if not self.db:
            return 0
        try:
            self.db.execute("""
                UPDATE long_term_memory
                SET importance = MAX(0, importance - 0.5)
                WHERE importance > 1.0
                  AND accessed_at < strftime('%s', 'now', '-14 days')
            """)
            # TODO: 同步 ChromaDB metadata
            return self.db.changes() if hasattr(self.db, "changes") else 0
        except Exception:
            logger.exception("Memory decay failed")
            return 0

    def _row_to_item(self, row: Dict[str, Any]) -> MemoryItem:
        item = MemoryItem(
            id=row["id"],
            user_id=row["user_id"],
            layer=MemoryLayer.LONG_TERM,
            memory_type=MemoryType(row.get("memory_type", "fact")),
            content=row.get("content", ""),
            importance=row.get("importance", 5.0),
            access_count=row.get("access_count", 0),
            created_at=row.get("created_at", 0),
            updated_at=row.get("updated_at", 0),
            accessed_at=row.get("accessed_at", 0),
            source=row.get("source", ""),
        )
        meta_str = row.get("metadata", "{}")
        if meta_str:
            try:
                item.metadata = json.loads(meta_str)
            except Exception:
                item.metadata = {}
        return item

    async def _bump_access(self, memory_id: str) -> None:
        """更新访问计数和时间."""
        if not self.db:
            return
        try:
            self.db.execute(
                "UPDATE long_term_memory SET access_count = access_count + 1, accessed_at = ? WHERE id = ?",
                (time.time(), memory_id),
            )
        except Exception:
            pass


# ── Permanent Memory Layer ──────────────────────────

class PermanentMemoryLayer(BaseMemoryLayer):
    """
    永久记忆层 —— Markdown 文件 + Git 版本控制。

    存储经过验证的核心知识、人格设定、不可遗忘信息。
    只读为主，修改需要审批，所有变更都有 Git 版本记录。
    """

    layer = MemoryLayer.PERMANENT

    def __init__(self, storage_dir: str = "memory/permanent") -> None:
        self.storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)
        self._cache: Dict[str, MemoryItem] = {}
        self._load_all()

    def _load_all(self) -> None:
        """加载所有永久记忆文件."""
        try:
            for filename in os.listdir(self.storage_dir):
                if not filename.endswith(".md"):
                    continue
                filepath = os.path.join(self.storage_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                    mid = filename[:-3]  # 去掉 .md
                    item = MemoryItem(
                        id=mid,
                        user_id=0,  # 全局记忆，无用户区分
                        layer=MemoryLayer.PERMANENT,
                        memory_type=MemoryType.KNOWLEDGE,
                        content=content,
                        importance=10.0,  # 永久记忆重要度最高
                        source="permanent_file",
                    )
                    self._cache[mid] = item
                except Exception:
                    continue
            logger.info("Loaded %d permanent memories", len(self._cache))
        except Exception:
            logger.exception("Failed to load permanent memories")

    async def store(self, item: MemoryItem) -> str:
        """
        存储永久记忆 —— 写入 Markdown 文件。
        注意：正式环境下应该有审批流程，这里提供基础功能。
        """
        item.layer = MemoryLayer.PERMANENT
        item.importance = 10.0
        item.id = item.id or f"perm_{int(time.time())}"

        filepath = os.path.join(self.storage_dir, f"{item.id}.md")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(item.content)
            self._cache[item.id] = item
            self._git_commit(f"Add permanent memory: {item.id}")
        except Exception:
            logger.exception("Failed to store permanent memory")

        return item.id

    async def retrieve(
        self,
        user_id: int,
        query: str = "",
        limit: int = 5,
        memory_type: Optional[MemoryType] = None,
    ) -> List[MemorySearchResult]:
        results: List[MemorySearchResult] = []
        for item in self._cache.values():
            if memory_type and item.memory_type != memory_type:
                continue
            score = 0.6  # 永久记忆基础分高
            if query and query.lower() in item.content.lower():
                score = 0.95
            results.append(MemorySearchResult(
                item=item, score=score, layer=MemoryLayer.PERMANENT,
                match_reason="permanent_knowledge",
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    async def get(self, memory_id: str) -> Optional[MemoryItem]:
        return self._cache.get(memory_id)

    async def update(self, memory_id: str, **kwargs) -> bool:
        if memory_id not in self._cache:
            return False
        item = self._cache[memory_id]
        for k, v in kwargs.items():
            if hasattr(item, k):
                setattr(item, k, v)
        item.updated_at = time.time()

        # 重写文件
        filepath = os.path.join(self.storage_dir, f"{memory_id}.md")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(item.content)
            self._git_commit(f"Update permanent memory: {memory_id}")
            return True
        except Exception:
            logger.exception("Failed to update permanent memory")
            return False

    async def delete(self, memory_id: str) -> bool:
        if memory_id not in self._cache:
            return False
        filepath = os.path.join(self.storage_dir, f"{memory_id}.md")
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
            del self._cache[memory_id]
            self._git_commit(f"Delete permanent memory: {memory_id}")
            return True
        except Exception:
            logger.exception("Failed to delete permanent memory")
            return False

    async def list_by_user(
        self,
        user_id: int,
        limit: int = 50,
        memory_type: Optional[MemoryType] = None,
    ) -> List[MemoryItem]:
        items = list(self._cache.values())
        if memory_type:
            items = [i for i in items if i.memory_type == memory_type]
        return items[:limit]

    def _git_commit(self, message: str) -> None:
        """提交 Git 版本（可选，失败不影响功能）."""
        try:
            import subprocess
            # 检查是否是 git 仓库
            git_dir = os.path.join(self.storage_dir, ".git")
            if not os.path.exists(git_dir):
                # 初始化
                subprocess.run(
                    ["git", "init"], cwd=self.storage_dir,
                    capture_output=True, timeout=10,
                )
            # add + commit
            subprocess.run(
                ["git", "add", "."], cwd=self.storage_dir,
                capture_output=True, timeout=10,
            )
            subprocess.run(
                ["git", "commit", "-m", message, "--allow-empty"],
                cwd=self.storage_dir,
                capture_output=True, timeout=10,
            )
        except Exception:
            # Git 不可用也没关系
            pass
