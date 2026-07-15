"""知识库 Facade：对外统一接口

整合存储、采集、分类、重组四大子系统。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
from loguru import logger

from knowledge.store import KnowledgeStore
from knowledge.ingest import KnowledgeIngestor
from knowledge.classifier import KnowledgeClassifier
from knowledge.reorganizer import KnowledgeReorganizer


class KnowledgeBase:
    """自主知识库 Facade"""

    def __init__(
        self,
        db_path: str = "data/knowledge.db",
        embedding_dim: int = 1024,
        brain=None,
        embedder=None,
    ):
        """
        Args:
            db_path: SQLite 数据库路径
            embedding_dim: 嵌入向量维度
            brain: AIBrain 实例（用于 LLM 分类/重组）
            embedder: 嵌入函数 async (text: str) -> np.ndarray
        """
        self.store = KnowledgeStore(db_path, embedding_dim)
        self.ingestor = KnowledgeIngestor(self.store, embedder)
        self.classifier = KnowledgeClassifier(self.store, brain)
        self.reorganizer = KnowledgeReorganizer(self.store, brain)
        self._brain = brain

    async def initialize(self) -> None:
        await self.store.initialize()
        logger.info("自主知识库已就绪")

    async def close(self) -> None:
        await self.store.close()

    # ===== 搜索（ContextBuilder 注入用） =====
    async def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 5,
        min_similarity: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """语义检索知识库（供 context_builder 调用）"""
        return await self.store.search(query_embedding, top_k=top_k, min_similarity=min_similarity)

    # ===== 采集 =====
    async def ingest_conversation(self, messages: list, user_id: int = 0) -> List[str]:
        return await self.ingestor.ingest_from_conversation(messages, user_id)

    async def ingest_file(self, file_path: str, user_id: int = 0) -> List[str]:
        return await self.ingestor.ingest_from_file(file_path, user_id)

    async def ingest_web(self, url: str, content: str, user_id: int = 0) -> List[str]:
        return await self.ingestor.ingest_from_web(url, content, user_id)

    async def ingest_direct(self, content: str, tags: list = None, user_id: int = 0) -> Optional[str]:
        return await self.ingestor.ingest_direct(content, tags, user_id)

    # ===== 分类 =====
    async def classify_batch(self, limit: int = 50) -> int:
        return await self.classifier.classify_batch(limit)

    # ===== 重组 =====
    async def reorganize(self) -> Dict[str, Any]:
        return await self.reorganizer.check_and_reorganize()

    async def get_reorg_log(self, limit: int = 20) -> list:
        return await self.reorganizer.get_reorg_log(limit)

    # ===== 统计 =====
    async def get_stats(self) -> Dict[str, Any]:
        return await self.store.get_stats()
