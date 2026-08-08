"""P1-D.5 激活验证脚本: 将 Obsidian 知识总览摘要写入向量索引并语义检索.

运行: .venv\\Scripts\\python.exe scripts/p1d5_activate_knowledge.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from core.knowledge_indexer import KnowledgeIndexer, resolve_embedding_fn

# ── 知识总览摘要块 (源于 Aerie_Obsidian_Vault 融合概念) ──
CHUNKS = [
    {
        "id": "kb_companion",
        "text": "主动陪伴是 Aerie 的核心情绪价值, 通过主动候选意图、关怀治理与主动消息+图片联合调度为用户提供被在乎的感觉。",
        "metadata": {"topic": "companion", "vault": "Aerie_Obsidian_Vault"},
    },
    {
        "id": "kb_vector",
        "text": "专用向量知识库是 Echo/Pyisland/Aerie 融合知识的语义检索底座, 使用 ChromaDB 持久化向量并提供语义检索。",
        "metadata": {"topic": "vector_kb", "vault": "Aerie_Obsidian_Vault"},
    },
    {
        "id": "kb_world",
        "text": "世界快照 WorldSnapshot 描述角色当前时段、地点、活动、能量、社交与可见视觉话题, 驱动主动陪伴决策。",
        "metadata": {"topic": "world", "vault": "Aerie_Obsidian_Vault"},
    },
    {
        "id": "kb_channels",
        "text": "语音 ASR/TTS、表情包与 QQ/ClawBot 通道扩展了陪伴的表达方式, 通过统一通道抽象接入。",
        "metadata": {"topic": "channels", "vault": "Aerie_Obsidian_Vault"},
    },
    {
        "id": "kb_empathy",
        "text": "共情策略与情绪价值调研融合, 让角色能识别用户情绪变化并给出有温度的回应。",
        "metadata": {"topic": "empathy", "vault": "Aerie_Obsidian_Vault"},
    },
    {
        "id": "kb_persona",
        "text": "人格配置 PersonaConfig 与视觉身份绑定, 在主动图片生成时冻结角色形象以保证一致性。",
        "metadata": {"topic": "persona", "vault": "Aerie_Obsidian_Vault"},
    },
]

QUERIES = [
    ("主动陪伴与情绪价值", "companion"),
    ("向量语义检索底座", "vector_kb"),
    ("角色世界状态快照", "world"),
    ("语音表情包通道表达", "channels"),
    ("共情与情绪回应", "empathy"),
]


def main() -> int:
    chroma_dir = os.getenv("AERIE_CHROMA_DIR", "data/chroma")
    collection = os.getenv("AERIE_KNOWLEDGE_COLLECTION", "aerie_knowledge")
    embedding_fn = resolve_embedding_fn()

    indexer = KnowledgeIndexer(
        chroma_dir=chroma_dir,
        collection_name=collection,
        embedding_fn=embedding_fn,
    )
    print("chromadb available:", indexer.is_available())

    result = indexer.index_chunks(CHUNKS)
    print("index result:", result)

    retrieved_topics = set()
    for query, expect_topic in QUERIES:
        hits = indexer.search(query, k=2)
        print(f"query={query!r} -> hits={[h['id'] for h in hits]}")
        for h in hits:
            if h["metadata"].get("topic"):
                retrieved_topics.add(h["metadata"]["topic"])

    print("retrieved distinct topics:", len(retrieved_topics))
    print("topics:", sorted(retrieved_topics))
    ok = len(retrieved_topics) >= 3
    print(">=3 fusion concepts retrievable:", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
