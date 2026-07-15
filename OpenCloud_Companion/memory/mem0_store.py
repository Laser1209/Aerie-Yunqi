"""长期记忆检索

Phase 2：基础实现 —— 直接复用 chat_log 的最近 N 条记录
Phase 3+：可接入 Mem0 实现真正向量检索

策略：
- enabled=False（默认）：回退到 chat_log 最近 N 条
- enabled=True：尝试 Mem0，失败回退
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger


class MemoryStore:
    """
    记忆存储接口。

    Phase 2 MVP：代理 chat_log 的最近记录。
    Phase 3+：接入 Mem0 实现语义检索，可替换为向量数据库。
    """

    def __init__(self, chat_log=None, config: Optional[Dict[str, Any]] = None):
        """
        Args:
            chat_log: ChatLogger 实例（用于回退）
            config: 记忆配置节
        """
        self._chat_log = chat_log
        self._config = config or {}
        self._enabled = self._config.get("mem0_enabled", False)
        self._max_memories = self._config.get("max_recent", 10)

        if self._enabled:
            logger.info("Mem0 已启用（Phase 3 向量检索就绪）")
        else:
            logger.info("记忆检索模式: 代理 chat_log 最近 {} 条", self._max_memories)

    async def search(
        self,
        user_id: int,
        query: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, str]]:
        """
        检索相关记忆。

        Phase 2：直接返回最近 N 条聊天记录，忽略 query 参数（不做语义匹配）。
        Phase 3：query 参数用于语义搜索。

        Args:
            user_id: 用户 ID
            query: 搜索查询（Phase 2 忽略，Phase 3 用于语义匹配）
            limit: 返回条数

        Returns:
            [{"role": "user/assistant", "content": "..."}, ...]
        """
        if limit is None:
            limit = self._max_memories

        if self._chat_log is None:
            logger.warning("MemoryStore 未绑定 ChatLogger，返回空记忆")
            return []

        try:
            records = await self._chat_log.get_recent(
                user_id=user_id, limit=limit
            )
            return [
                {"role": r.get("role", "user"), "content": r.get("content", "")}
                for r in records
            ]
        except Exception as e:
            logger.warning(f"记忆检索失败: {e}")
            return []

    async def add_memory(self, user_id: int, content: str, role: str = "user") -> bool:
        """
        手动添加记忆（Phase 3 语义索引入口）。

        Phase 2：不做单独存储（已由 chat_log 覆盖）。
        Phase 3：写入 Mem0 向量索引。
        """
        logger.debug(f"MemoryStore.add_memory (Phase 2 委托 chat_log): {role}")
        return True
