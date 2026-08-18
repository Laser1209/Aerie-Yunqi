"""P1-D.5 专用向量知识库激活模块 (KnowledgeIndexer).

提供 Obsidian 知识总览摘要的向量索引、语义检索、去重与失败降级:
  - 使用 ChromaDB 持久化向量集合
  - embedding 解析: 远程 OpenAI 兼容 > chromadb 本地 ONNX > 确定性哈希兜底
  - chromadb/embedding 不可用时优雅降级 (返回空, 不崩溃)
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Callable, Optional

from core.paths import data_dir

logger = logging.getLogger(__name__)

_EMBEDDING_DIM = 64


def _hash_embedding(text: str) -> list[float]:
    """确定性本地哈希向量 (离线兜底, 对任意文本返回固定维度向量)."""
    token = str(text or "")
    vec = [0.0] * _EMBEDDING_DIM
    for i, ch in enumerate(token):
        byte = ord(ch)
        idx = i % _EMBEDDING_DIM
        vec[idx] += (byte % 32) / 32.0
        vec[(idx + byte) % _EMBEDDING_DIM] += ((byte >> 3) % 16) / 16.0
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [round(v / norm, 6) for v in vec]


def _chromadb_local_embedding() -> Optional[Callable[[str], list[float]]]:
    """尝试使用 chromadb 本地 ONNX MiniLM 模型 (需可联网首次下载)."""
    try:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        fn = DefaultEmbeddingFunction()

        def _embed(text: str) -> list[float]:
            vec = fn([str(text)])[0]
            return [float(x) for x in vec]

        return _embed
    except Exception:
        logger.warning("chromadb local embedding unavailable, fallback to hash")
        return None


def _remote_embedding() -> Optional[Callable[[str], list[float]]]:
    """尝试使用远程 OpenAI 兼容 embedding (需配置 API Key)."""
    api_key = os.getenv("AERIE_EMBEDDING_API_KEY") or os.getenv("OPENAI_EMBEDDING_API_KEY")
    if not api_key:
        return None
    base_url = os.getenv("AERIE_EMBEDDING_BASE_URL") or os.getenv("OPENAI_EMBEDDING_BASE_URL") or "https://api.openai.com/v1"
    model = os.getenv("AERIE_EMBEDDING_MODEL") or os.getenv("OPENAI_EMBEDDING_MODEL") or "text-embedding-3-small"
    timeout = float(os.getenv("AERIE_EMBEDDING_TIMEOUT_SECONDS", "60"))

    def _embed(text: str) -> list[float]:
        import httpx

        url = f"{base_url.rstrip('/')}/embeddings"
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "input": [str(text)]},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return list(data[0]["embedding"])

    return _embed


def resolve_embedding_fn() -> Optional[Callable[[str], list[float]]]:
    """按优先级解析 embedding 函数: 远程 > chromadb 本地 > 哈希兜底."""
    remote = _remote_embedding()
    if remote is not None:
        logger.info("knowledge indexer: using remote embedding")
        return remote
    local = _chromadb_local_embedding()
    if local is not None:
        logger.info("knowledge indexer: using chromadb local embedding")
        return local
    logger.warning("knowledge indexer: using deterministic hash embedding fallback")
    return _hash_embedding


class KnowledgeIndexer:
    """基于 ChromaDB 的专用向量知识库索引器."""

    def __init__(
        self,
        *,
        chroma_dir: str | None = None,
        collection_name: str = "aerie_knowledge",
        embedding_fn: Optional[Callable[[str], list[float]]] = None,
    ) -> None:
        self.chroma_dir = chroma_dir or str(data_dir() / "chroma")
        self.collection_name = collection_name
        self.embedding_fn = embedding_fn
        self._collection: Any = None
        self._chroma_available = False
        self._init_collection()

    def _init_collection(self) -> None:
        try:
            import chromadb  # type: ignore
            from chromadb.config import Settings  # type: ignore

            os.makedirs(self.chroma_dir, exist_ok=True)
            client = chromadb.PersistentClient(
                path=self.chroma_dir,
                settings=Settings(anonymized_telemetry=False),
            )
            self._collection = client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            self._chroma_available = True
        except Exception:
            self._chroma_available = False
            logger.exception("KnowledgeIndexer: ChromaDB init failed, degraded mode")

    def is_available(self) -> bool:
        return self._chroma_available and self.embedding_fn is not None

    def index_chunks(self, chunks: list[dict[str, Any]]) -> dict[str, Any]:
        """写入知识块到向量索引; 按 id 去重. chunks: [{"id","text","metadata"}]."""
        if not self.is_available() or not chunks:
            return {"indexed": 0, "available": self.is_available(), "deduped": 0}

        existing = self._collection.get(ids=[str(c["id"]) for c in chunks])["ids"]
        existing_set = set(existing)
        new_chunks = [c for c in chunks if str(c["id"]) not in existing_set]

        if not new_chunks:
            return {"indexed": 0, "available": True, "deduped": len(chunks)}

        embeddings = [self.embedding_fn(str(c["text"])) for c in new_chunks]
        self._collection.upsert(
            ids=[str(c["id"]) for c in new_chunks],
            documents=[str(c["text"]) for c in new_chunks],
            embeddings=embeddings,
            metadatas=[dict(c.get("metadata") or {}) for c in new_chunks],
        )
        return {
            "indexed": len(new_chunks),
            "available": True,
            "deduped": len(chunks) - len(new_chunks),
        }

    def search(
        self,
        query: str,
        k: int = 3,
        where: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """语义检索, 返回 top-k 匹配知识块.

        ``where`` 透传给 ChromaDB 的 metadata 过滤 (例如按 attachment_id 限定).
        """
        if not self.is_available() or not query:
            return []
        try:
            qemb = self.embedding_fn(str(query))
            query_kwargs: dict[str, Any] = {"n_results": int(k)}
            if where:
                query_kwargs["where"] = where
            res = self._collection.query(
                query_embeddings=[qemb],
                **query_kwargs,
            )
            ids = res.get("ids", [[]])[0]
            docs = res.get("documents", [[]])[0]
            metas = res.get("metadatas", [[]])[0]
            return [
                {"id": str(i), "text": str(d), "metadata": dict(m or {})}
                for i, d, m in zip(ids, docs, metas)
            ]
        except Exception:
            logger.exception("KnowledgeIndexer: semantic search failed, degraded to empty")
            return []
