"""上下文构建器

统一编排：性格(System Prompt) + 长期记忆 + 知识库 + 近期对话 + 当前消息
输出：OpenAI API 格式的 messages 列表

数据流：
  人格引擎 → System Prompt (含记忆注入 + 知识库条目)
  + MemoryStore → 长期记忆条目
  + KnowledgeBase → 知识库语义检索结果（Phase 4+）
  + ChatLogger → 最近 N 条对话
  + 当前消息 → user message
  = 完整 messages 列表 → AIBrain.generate_reply()
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
from loguru import logger

from core.personality import PersonalityEngine
from communication.message import IncomingMessage


class ContextBuilder:
    """
    上下文构建器：编排 System Prompt + 记忆 + 知识库 + 历史 → messages 列表
    """

    def __init__(
        self,
        personality: PersonalityEngine,
        chat_log=None,
        memory_store=None,
        knowledge_base=None,  # Phase 4: KnowledgeBase 实例
        embedder=None,        # Phase 4: 嵌入函数
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            personality: PersonalityEngine 实例
            chat_log: ChatLogger 实例
            memory_store: MemoryStore 实例
            knowledge_base: KnowledgeBase 实例（Phase 4+）
            embedder: 嵌入函数 async (text: str) -> np.ndarray（Phase 4+）
            config: 上下文配置
        """
        self._personality = personality
        self._chat_log = chat_log
        self._memory = memory_store
        self._knowledge_base = knowledge_base
        self._embedder = embedder
        self._config = config or {}
        self._max_history = self._config.get("max_history", 8)
        self._max_memories = self._config.get("max_memories", 6)
        self._max_knowledge = self._config.get("max_knowledge", 4)

    async def build(
        self,
        msg: IncomingMessage,
        capability_level: str = "phase1",
        include_memories: bool = True,
        include_history: bool = True,
        include_knowledge: bool = False,
    ) -> List[Dict[str, str]]:
        """
        构建完整的 messages 列表。

        Args:
            msg: 当前收到的消息
            capability_level: 能力等级 "phase1" | "phase3" | "phase4"
            include_memories: 是否包含长期记忆
            include_history: 是否包含近期对话历史
            include_knowledge: 是否包含知识库检索（Phase 4+）

        Returns:
            [{"role": "system", "content": "..."},
             {"role": "user", "content": "..."},   ← 历史 (可选)
             {"role": "assistant", "content": "..."}, ← 历史 (可选)
             ...
             {"role": "user", "content": "..."}]   ← 当前消息
        """
        messages: List[Dict[str, str]] = []

        # 1. System Prompt（含记忆注入 + 知识库条目）
        memories_list: Optional[List[Dict[str, str]]] = None
        if include_memories and self._memory:
            try:
                memories_list = await self._memory.search(
                    msg.user_id, query=msg.content, limit=self._max_memories
                )
                if memories_list:
                    logger.debug(f"注入 {len(memories_list)} 条长期记忆")
            except Exception as e:
                logger.warning(f"记忆检索失败，跳过注入: {e}")

        # Phase 4: 知识库检索
        knowledge_entries: Optional[List[Dict[str, Any]]] = None
        if include_knowledge and self._knowledge_base and self._embedder:
            try:
                query_emb = await self._embedder(msg.content)
                knowledge_entries = await self._knowledge_base.search(
                    query_emb, top_k=self._max_knowledge, min_similarity=0.5,
                )
                if knowledge_entries:
                    logger.debug(f"注入 {len(knowledge_entries)} 条知识库结果")
            except Exception as e:
                logger.warning(f"知识库检索失败: {e}")

        system_msg = self._personality.build_system_message(
            memories=memories_list,
            capability_level=capability_level,
            knowledge_entries=knowledge_entries,
        )
        messages.append(system_msg)

        # 2. 近期对话历史
        if include_history and self._chat_log:
            try:
                history = await self._chat_log.get_recent(
                    msg.user_id, limit=self._max_history
                )
                for entry in history:
                    # 跳过当前消息本身（避免重复）
                    entry_content = entry.get("content", "")
                    entry_role = entry.get("role", "")
                    if entry_content == msg.content and entry_role == "user":
                        continue
                    messages.append({
                        "role": entry_role,
                        "content": entry_content,
                    })
                if history:
                    logger.debug(f"注入 {len(history)} 条对话历史")
            except Exception as e:
                logger.warning(f"对话历史检索失败: {e}")

        # 3. 当前消息（永远在最后）
        messages.append({"role": "user", "content": msg.content})

        return messages

    async def build_compact(
        self,
        msg: IncomingMessage,
    ) -> List[Dict[str, str]]:
        """
        构建精简 messages（仅 System Prompt + 当前消息，无历史/记忆）。

        用于意图分类等低 token 消耗场景。
        """
        system_msg = self._personality.build_system_message(
            memories=None, capability_level="phase1"
        )
        return [
            system_msg,
            {"role": "user", "content": msg.content},
        ]

    @property
    def personality(self) -> PersonalityEngine:
        return self._personality
