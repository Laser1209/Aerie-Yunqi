"""Aerie · 云栖 v0.1.0-beta.1 — 四层记忆统一调度器 (S3 M3.1).

LayeredMemory 统一管理四层记忆，对外提供统一的 API。
自动处理记忆的流动：
  Transient → Working → Long-term → Permanent

每一层都有自己的存储和检索策略，调度器负责：
- 写入时根据重要度决定存入哪一层
- 检索时从多层联合检索，合并排序
- 定期 consolidate（巩固）和 decay（衰减）
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from memory.layers.base import (
    BaseMemoryLayer, MemoryItem, MemoryLayer, MemoryType,
    MemorySearchResult,
)
from memory.layers.memory_layers import TransientMemory, WorkingMemory
from memory.layers.long_permanent import LongTermMemoryLayer, PermanentMemoryLayer

logger = logging.getLogger(__name__)


class LayeredMemory:
    """
    四层记忆统一调度器 (v11.2.0 S3 M3.1).

    四层架构：
      Transient (瞬时)   — 内存，会话级临时状态
      Working   (工作)   — 内存 + LRU，当前会话上下文
      Long-term (长期)   — ChromaDB + SQLite，持久化记忆
      Permanent (永久)   — Markdown + Git，核心知识/人格

    用法::

        mem = LayeredMemory(db=db, chroma_dir="data/chroma")
        await mem.store(user_id=1, content="用户喜欢猫", importance=7.0)
        results = await mem.search(user_id=1, query="用户喜欢什么")
        for r in results:
            print(r.score, r.item.content)
    """

    def __init__(
        self,
        db: Any = None,
        chroma_persist_dir: str = "data/chroma",
        permanent_dir: str = "memory/permanent",
        embedding_fn: Any = None,
        max_working_items: int = 50,
    ) -> None:
        self.db = db
        self.embedding_fn = embedding_fn

        # 初始化四层
        self.transient = TransientMemory()
        self.working = WorkingMemory(max_items_per_user=max_working_items)
        self.long_term = LongTermMemoryLayer(
            db=db,
            chroma_persist_dir=chroma_persist_dir,
            embedding_fn=embedding_fn,
        )
        self.permanent = PermanentMemoryLayer(storage_dir=permanent_dir)

        # 层的引用映射
        self._layers: Dict[MemoryLayer, BaseMemoryLayer] = {
            MemoryLayer.TRANSIENT: self.transient,
            MemoryLayer.WORKING: self.working,
            MemoryLayer.LONG_TERM: self.long_term,
            MemoryLayer.PERMANENT: self.permanent,
        }

    # ── 写入 ───────────────────────────────────────

    async def store(
        self,
        user_id: int,
        content: str,
        memory_type: MemoryType = MemoryType.FACT,
        importance: float = 5.0,
        layer: Optional[MemoryLayer] = None,
        metadata: Optional[Dict[str, Any]] = None,
        source: str = "conversation",
        session_id: Optional[str] = None,
    ) -> str:
        """
        存储一条记忆。

        如果指定了 layer，直接存入对应层。
        否则根据重要度自动决定：
          - importance < 3  → transient（临时）
          - importance < 7  → working（工作）
          - importance >= 7 → long_term（长期）
          - importance = 10 → 需要明确指定 permanent
        """
        item = MemoryItem(
            user_id=user_id,
            memory_type=memory_type,
            content=content,
            importance=importance,
            metadata=metadata or {},
            source=source,
        )
        if session_id:
            item.metadata["session_id"] = session_id

        # 决定目标层
        if layer is None:
            if importance >= 7.0:
                target_layer = MemoryLayer.LONG_TERM
            elif importance >= 3.0:
                target_layer = MemoryLayer.WORKING
            else:
                target_layer = MemoryLayer.TRANSIENT
        else:
            target_layer = layer

        item.layer = target_layer
        layer_obj = self._layers[target_layer]
        memory_id = await layer_obj.store(item)

        # 同时在 working 层留个引用（方便当前会话访问）
        if target_layer == MemoryLayer.LONG_TERM and importance >= 5.0:
            working_item = MemoryItem(**{k: v for k, v in item.__dict__.items()})
            working_item.layer = MemoryLayer.WORKING
            working_item.id = memory_id  # 共用 ID
            await self.working.store(working_item)

        return memory_id

    # ── 检索 ───────────────────────────────────────

    async def search(
        self,
        user_id: int,
        query: str = "",
        limit: int = 5,
        layers: Optional[List[MemoryLayer]] = None,
        memory_type: Optional[MemoryType] = None,
    ) -> List[MemorySearchResult]:
        """
        多层联合检索。

        从指定的层（默认所有层）并行检索，合并结果后排序返回。
        各层的结果会按层级权重加权：
          permanent: 1.0
          long_term: 0.9
          working:   0.7
          transient: 0.5
        """
        if layers is None:
            layers = [
                MemoryLayer.PERMANENT,
                MemoryLayer.LONG_TERM,
                MemoryLayer.WORKING,
                MemoryLayer.TRANSIENT,
            ]

        layer_weights = {
            MemoryLayer.PERMANENT: 1.0,
            MemoryLayer.LONG_TERM: 0.9,
            MemoryLayer.WORKING: 0.75,
            MemoryLayer.TRANSIENT: 0.5,
        }

        # 并行检索所有层
        async def _search_layer(layer_enum: MemoryLayer) -> List[MemorySearchResult]:
            layer_obj = self._layers[layer_enum]
            weight = layer_weights.get(layer_enum, 0.5)
            try:
                results = await layer_obj.retrieve(
                    user_id=user_id,
                    query=query,
                    limit=limit,
                    memory_type=memory_type,
                )
                for r in results:
                    r.score = min(1.0, r.score * weight)
                return results
            except Exception:
                logger.exception("Search failed in layer %s", layer_enum.value)
                return []

        tasks = [_search_layer(l) for l in layers]
        all_results_lists = await asyncio.gather(*tasks)

        # 合并 + 去重 + 排序
        seen_ids: set[str] = set()
        merged: List[MemorySearchResult] = []
        for results in all_results_lists:
            for r in results:
                if r.item.id in seen_ids:
                    continue
                seen_ids.add(r.item.id)
                merged.append(r)

        merged.sort(key=lambda r: r.score, reverse=True)
        return merged[:limit]

    async def get(self, memory_id: str) -> Optional[MemoryItem]:
        """按 ID 查找记忆（遍历所有层）."""
        for layer in self._layers.values():
            item = await layer.get(memory_id)
            if item:
                return item
        return None

    async def update(self, memory_id: str, **kwargs) -> bool:
        """更新记忆（找到所在层并更新）."""
        for layer in self._layers.values():
            if await layer.update(memory_id, **kwargs):
                return True
        return False

    async def delete(self, memory_id: str) -> bool:
        """删除记忆（从所有层删除）."""
        deleted = False
        for layer in self._layers.values():
            if await layer.delete(memory_id):
                deleted = True
        return deleted

    # ── 列表 ───────────────────────────────────────

    async def list_by_user(
        self,
        user_id: int,
        layer: MemoryLayer = MemoryLayer.LONG_TERM,
        limit: int = 50,
        memory_type: Optional[MemoryType] = None,
    ) -> List[MemoryItem]:
        """列出指定层中用户的记忆."""
        layer_obj = self._layers[layer]
        return await layer_obj.list_by_user(user_id, limit, memory_type)

    # ── 记忆流动（巩固 + 衰减）─────────────────────

    async def consolidate_working_to_long(self) -> int:
        """将工作记忆中重要的内容巩固到长期记忆."""
        count = await self.working.consolidate(self.long_term)
        if count > 0:
            logger.info("Consolidated %d working memories to long-term", count)
        return count

    async def decay_long_term(self) -> int:
        """长期记忆衰减."""
        count = await self.long_term.decay()
        if count > 0:
            logger.info("Decayed %d long-term memories", count)
        return count

    async def run_maintenance(self) -> Dict[str, int]:
        """运行所有维护任务（巩固 + 衰减）."""
        results: Dict[str, int] = {}
        results["consolidated"] = await self.consolidate_working_to_long()
        results["decayed"] = await self.decay_long_term()
        return results

    # ── 兼容旧接口 ─────────────────────────────────

    async def memory_search(self, query: str, top_k: int = 5, user_id: int = 0) -> List[Dict[str, Any]]:
        """
        兼容旧 LongTermMemory.search 接口。

        返回 dict 列表，保持旧接口格式。
        """
        results = await self.search(
            user_id=user_id,
            query=query,
            limit=top_k,
        )
        return [
            {
                "id": r.item.id,
                "content": r.item.content,
                "memory_type": r.item.memory_type.value if isinstance(r.item.memory_type, MemoryType) else r.item.memory_type,
                "importance": r.item.importance,
                "score": r.score,
                "layer": r.layer.value,
                "source": r.item.source,
                "created_at": r.item.created_at,
            }
            for r in results
        ]
