"""P1-D.5 TDD tests for KnowledgeIndexer (专用向量知识库激活).

覆盖:
  - 写入知识块到 ChromaDB 向量集合
  - 语义检索, 至少 3 个融合概念可检索
  - 去重 (同一 id 不重复写入)
  - 失败降级 (chromadb/embedding 不可用时优雅降级)
"""
from __future__ import annotations

import hashlib
import json

import pytest

from core.knowledge_indexer import KnowledgeIndexer, _hash_embedding


def _fake_embedding(text: str) -> list[float]:
    """确定性本地哈希向量 (离线测试用, 不依赖网络/模型)."""
    return _hash_embedding(text)


def _chunks(*, prefix: str = "chunk") -> list[dict]:
    return [
        {"id": f"{prefix}_1", "text": "主动陪伴与关怀治理是 Aerie 的核心情绪价值", "metadata": {"topic": "companion"}},
        {"id": f"{prefix}_2", "text": "向量知识库是语义检索底座, 承载融合知识", "metadata": {"topic": "vector"}},
        {"id": f"{prefix}_3", "text": "世界快照 WorldSnapshot 描述角色的当前状态", "metadata": {"topic": "world"}},
        {"id": f"{prefix}_4", "text": "语音与表情包扩展了陪伴的表达通道", "metadata": {"topic": "channels"}},
    ]


def test_indexer_available_when_chroma_and_embedding(tmp_path):
    indexer = KnowledgeIndexer(
        chroma_dir=str(tmp_path / "chroma"),
        collection_name="test_knowledge",
        embedding_fn=_fake_embedding,
    )
    assert indexer.is_available() is True


def test_index_chunks_writes_to_vector_index(tmp_path):
    indexer = KnowledgeIndexer(
        chroma_dir=str(tmp_path / "chroma"),
        collection_name="test_knowledge",
        embedding_fn=_fake_embedding,
    )
    result = indexer.index_chunks(_chunks(prefix="a"))
    assert result["available"] is True
    assert result["indexed"] == 4


def test_index_dedup_same_id_not_reindexed(tmp_path):
    indexer = KnowledgeIndexer(
        chroma_dir=str(tmp_path / "chroma"),
        collection_name="test_knowledge",
        embedding_fn=_fake_embedding,
    )
    indexer.index_chunks(_chunks(prefix="b"))
    second = indexer.index_chunks(_chunks(prefix="b"))
    assert second["indexed"] == 0
    assert second["deduped"] == 4


def test_search_retrieves_at_least_three_concepts(tmp_path):
    indexer = KnowledgeIndexer(
        chroma_dir=str(tmp_path / "chroma"),
        collection_name="test_knowledge",
        embedding_fn=_fake_embedding,
    )
    indexer.index_chunks(_chunks(prefix="c"))

    # 用与写入文本高度相关但表述不同的查询, 验证语义检索命中
    hit = indexer.search("情绪价值与主动陪伴", k=3)
    assert len(hit) >= 1

    combined = set()
    for q in ["陪伴与关怀", "向量语义检索", "世界快照"]:
        for r in indexer.search(q, k=3):
            combined.add(r["id"])
    assert len(combined) >= 3, "至少 3 个融合概念可检索"


def test_search_returns_empty_when_unavailable(tmp_path):
    # embedding_fn 为 None 时视为不可用, 优雅降级返回空
    indexer = KnowledgeIndexer(
        chroma_dir=str(tmp_path / "chroma"),
        collection_name="test_knowledge",
        embedding_fn=None,
    )
    assert indexer.is_available() is False
    assert indexer.search("任意查询", k=3) == []
    assert indexer.index_chunks(_chunks(prefix="d"))["indexed"] == 0


def test_hash_embedding_is_deterministic():
    a = _hash_embedding("同一段文本")
    b = _hash_embedding("同一段文本")
    assert a == b
    assert len(a) > 0
