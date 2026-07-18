"""Aerie · 云栖 v13.9.8 — 四层记忆架构 DTO (S3 M3.1).

四层记忆模型：
  1. Transient  (瞬时层) — 单会话临时状态，会话结束即清空
  2. Working    (工作层) — 当前会话上下文、最近 N 轮、活跃工具状态
  3. Long-term  (长期层) — 持久化用户偏好、重要事实、关系图谱
  4. Permanent  (永久层) — 经过验证的核心知识、人格设定、不可遗忘信息

每一层都有统一的 CRUD 接口，由 LayeredMemory 统一调度。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Memory Layer Enum ────────────────────────────────

class MemoryLayer(str, Enum):
    TRANSIENT = "transient"
    WORKING = "working"
    LONG_TERM = "long_term"
    PERMANENT = "permanent"


# ── Memory Types ─────────────────────────────────────

class MemoryType(str, Enum):
    FACT = "fact"              # 客观事实
    PREFERENCE = "preference"  # 用户偏好
    EMOTION = "emotion"        # 情绪记忆
    RELATION = "relation"      # 关系图谱
    EXPERIENCE = "experience"  # 经验/经历
    EVENT = "event"            # 事件
    KNOWLEDGE = "knowledge"    # 知识
    PERSONA = "persona"        # 人格设定
    SKILL = "skill"            # 技能记忆


# ── Memory Item DTO ──────────────────────────────────

@dataclass
class MemoryItem:
    """统一的记忆条目."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    user_id: int = 0
    layer: MemoryLayer = MemoryLayer.LONG_TERM
    memory_type: MemoryType = MemoryType.FACT
    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    importance: float = 5.0      # 0-10 重要度
    access_count: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    accessed_at: float = field(default_factory=time.time)
    embedding: Optional[List[float]] = None  # 向量嵌入（仅 long-term/permanent）
    source: str = ""  # 来源：conversation/dream/reflect/import/manual

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.embedding is None:
            d.pop("embedding", None)
        if isinstance(self.layer, MemoryLayer):
            d["layer"] = self.layer.value
        if isinstance(self.memory_type, MemoryType):
            d["memory_type"] = self.memory_type.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryItem":
        d = dict(data)
        if "layer" in d and isinstance(d["layer"], str):
            d["layer"] = MemoryLayer(d["layer"])
        if "memory_type" in d and isinstance(d["memory_type"], str):
            d["memory_type"] = MemoryType(d["memory_type"])
        return cls(**d)


# ── Search Result ────────────────────────────────────

@dataclass
class MemorySearchResult:
    """记忆搜索结果."""
    item: MemoryItem
    score: float = 0.0  # 相关度 0-1
    layer: MemoryLayer = MemoryLayer.LONG_TERM
    match_reason: str = ""


# ── Base Memory Layer Interface ──────────────────────

class BaseMemoryLayer:
    """记忆层基类接口."""

    layer: MemoryLayer = MemoryLayer.LONG_TERM

    async def store(self, item: MemoryItem) -> str:
        """存储一条记忆，返回记忆 ID."""
        raise NotImplementedError

    async def retrieve(
        self,
        user_id: int,
        query: str = "",
        limit: int = 5,
        memory_type: Optional[MemoryType] = None,
    ) -> List[MemorySearchResult]:
        """检索相关记忆."""
        raise NotImplementedError

    async def get(self, memory_id: str) -> Optional[MemoryItem]:
        """按 ID 获取记忆."""
        raise NotImplementedError

    async def update(self, memory_id: str, **kwargs) -> bool:
        """更新记忆."""
        raise NotImplementedError

    async def delete(self, memory_id: str) -> bool:
        """删除记忆."""
        raise NotImplementedError

    async def list_by_user(
        self,
        user_id: int,
        limit: int = 50,
        memory_type: Optional[MemoryType] = None,
    ) -> List[MemoryItem]:
        """列出用户的记忆."""
        raise NotImplementedError

    async def decay(self) -> int:
        """衰减（降低旧记忆重要度），返回衰减条数."""
        return 0

    async def consolidate(self, target_layer: "BaseMemoryLayer") -> int:
        """巩固：将本层的重要记忆迁移到目标层，返回迁移条数."""
        return 0
