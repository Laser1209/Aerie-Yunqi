"""Aerie · 云栖 v13.9.8 — Transient + Working 记忆层 (S3 M3.1).

Transient (瞬时层): 单会话临时状态，会话结束即清空。
    - 存储在内存 dict 中，按 user_id + session_id 隔离
    - 用于临时计算中间状态、当前正在处理的消息等

Working (工作层): 当前会话上下文、最近 N 轮对话、活跃工具状态。
    - 存储在内存中，带 LRU 淘汰
    - 用于当前对话的上下文管理
    - 重要内容会 consolidate 到 long-term
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from memory.layers.base import (
    BaseMemoryLayer, MemoryItem, MemoryLayer, MemoryType,
    MemorySearchResult,
)


# ── Transient Memory Layer ──────────────────────────

class TransientMemory(BaseMemoryLayer):
    """
    瞬时记忆层 —— 单会话内的临时状态。

    数据结构: {session_id: {key: value}}
    会话结束后自动清空。
    """

    layer = MemoryLayer.TRANSIENT

    def __init__(self) -> None:
        # {session_id: {key: MemoryItem}}
        self._sessions: Dict[str, Dict[str, MemoryItem]] = {}

    def _ensure_session(self, session_id: str) -> Dict[str, MemoryItem]:
        if session_id not in self._sessions:
            self._sessions[session_id] = {}
        return self._sessions[session_id]

    async def store(self, item: MemoryItem) -> str:
        session_id = item.metadata.get("session_id", "default")
        sess = self._ensure_session(session_id)
        item.layer = MemoryLayer.TRANSIENT
        if item.id is None:
            item.id = _gen_id()
        sess[item.id] = item
        return item.id

    async def retrieve(
        self,
        user_id: int,
        query: str = "",
        limit: int = 5,
        memory_type: Optional[MemoryType] = None,
    ) -> List[MemorySearchResult]:
        results: List[MemorySearchResult] = []
        for sess in self._sessions.values():
            for item in sess.values():
                if user_id and item.user_id != user_id:
                    continue
                if memory_type and item.memory_type != memory_type:
                    continue
                score = 0.5  # transient 不做语义匹配
                if query and query in item.content:
                    score = 0.9
                results.append(MemorySearchResult(
                    item=item, score=score, layer=MemoryLayer.TRANSIENT,
                    match_reason="transient_match",
                ))
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    async def get(self, memory_id: str) -> Optional[MemoryItem]:
        for sess in self._sessions.values():
            if memory_id in sess:
                return sess[memory_id]
        return None

    async def update(self, memory_id: str, **kwargs) -> bool:
        for sess in self._sessions.values():
            if memory_id in sess:
                item = sess[memory_id]
                for k, v in kwargs.items():
                    if hasattr(item, k):
                        setattr(item, k, v)
                item.updated_at = time.time()
                return True
        return False

    async def delete(self, memory_id: str) -> bool:
        for sess in self._sessions.values():
            if memory_id in sess:
                del sess[memory_id]
                return True
        return False

    async def list_by_user(
        self,
        user_id: int,
        limit: int = 50,
        memory_type: Optional[MemoryType] = None,
    ) -> List[MemoryItem]:
        items: List[MemoryItem] = []
        for sess in self._sessions.values():
            for item in sess.values():
                if item.user_id == user_id:
                    if memory_type and item.memory_type != memory_type:
                        continue
                    items.append(item)
                    if len(items) >= limit:
                        break
            if len(items) >= limit:
                break
        return items

    def clear_session(self, session_id: str) -> None:
        """清空某个会话的瞬时记忆."""
        self._sessions.pop(session_id, None)

    def clear_all(self) -> None:
        """清空所有瞬时记忆."""
        self._sessions.clear()


# ── Working Memory Layer ─────────────────────────────

class WorkingMemory(BaseMemoryLayer):
    """
    工作记忆层 —— 当前会话上下文、最近 N 轮对话。

    使用 OrderedDict 实现 LRU 淘汰，每个用户最多保留 N 条工作记忆。
    重要的工作记忆会 consolidate 到 long-term。
    """

    layer = MemoryLayer.WORKING

    def __init__(self, max_items_per_user: int = 50) -> None:
        # {user_id: OrderedDict[memory_id, MemoryItem]}
        self._users: Dict[int, "OrderedDict[str, MemoryItem]"] = {}
        self.max_items_per_user = max_items_per_user

    def _ensure_user(self, user_id: int) -> "OrderedDict[str, MemoryItem]":
        if user_id not in self._users:
            self._users[user_id] = OrderedDict()
        return self._users[user_id]

    async def store(self, item: MemoryItem) -> str:
        user_items = self._ensure_user(item.user_id)
        item.layer = MemoryLayer.WORKING

        # LRU: 移到最后（最新）
        if item.id in user_items:
            user_items.move_to_end(item.id)
        user_items[item.id] = item

        # 超限淘汰最旧的
        while len(user_items) > self.max_items_per_user:
            user_items.popitem(last=False)

        return item.id

    async def retrieve(
        self,
        user_id: int,
        query: str = "",
        limit: int = 5,
        memory_type: Optional[MemoryType] = None,
    ) -> List[MemorySearchResult]:
        user_items = self._users.get(user_id)
        if not user_items:
            return []

        results: List[MemorySearchResult] = []
        for item in reversed(user_items.values()):  # 最新的在前
            if memory_type and item.memory_type != memory_type:
                continue
            score = 0.3 + min(item.importance / 10.0, 0.5)
            if query:
                # 简单的关键词匹配
                if query in item.content:
                    score = max(score, 0.8)
            results.append(MemorySearchResult(
                item=item, score=score, layer=MemoryLayer.WORKING,
                match_reason="working_recency",
            ))
            if len(results) >= limit:
                break

        return results

    async def get(self, memory_id: str) -> Optional[MemoryItem]:
        for user_items in self._users.values():
            if memory_id in user_items:
                # LRU: 移到最后
                user_items.move_to_end(memory_id)
                item = user_items[memory_id]
                item.access_count += 1
                item.accessed_at = time.time()
                return item
        return None

    async def update(self, memory_id: str, **kwargs) -> bool:
        for user_items in self._users.values():
            if memory_id in user_items:
                item = user_items[memory_id]
                for k, v in kwargs.items():
                    if hasattr(item, k):
                        setattr(item, k, v)
                item.updated_at = time.time()
                user_items.move_to_end(memory_id)
                return True
        return False

    async def delete(self, memory_id: str) -> bool:
        for user_items in self._users.values():
            if memory_id in user_items:
                del user_items[memory_id]
                return True
        return False

    async def list_by_user(
        self,
        user_id: int,
        limit: int = 50,
        memory_type: Optional[MemoryType] = None,
    ) -> List[MemoryItem]:
        user_items = self._users.get(user_id)
        if not user_items:
            return []
        items: List[MemoryItem] = []
        for item in reversed(user_items.values()):
            if memory_type and item.memory_type != memory_type:
                continue
            items.append(item)
            if len(items) >= limit:
                break
        return items

    async def consolidate(self, target_layer: BaseMemoryLayer) -> int:
        """
        将工作记忆中重要度 >= threshold 的条目巩固到目标层（通常是 long-term）。

        返回迁移的条数。
        """
        count = 0
        for user_id, user_items in list(self._users.items()):
            for item in list(user_items.values()):
                if item.importance >= 7.0 and item.access_count >= 2:
                    # 复制到目标层
                    new_item = MemoryItem(**{k: v for k, v in item.__dict__.items()})
                    new_item.id = item.id  # 保持 ID 一致
                    new_item.layer = MemoryLayer.LONG_TERM
                    new_item.source = item.source or "working_consolidation"
                    await target_layer.store(new_item)
                    count += 1
        return count
