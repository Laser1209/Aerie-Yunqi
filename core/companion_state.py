"""Aerie · 云栖 v0.1.0-beta.1 — CompanionState: 陪伴状态模型 (Task P1-A.2).

跟踪关系阶段、挂心事项、未完话题、近期痛点和近期乐点。
是关系面板和主动关怀的前置依赖。

字段:
  - relationship_stage: 关系阶段 (stranger → acquaintance → familiar → close → intimate)
  - care_followups: 挂心事项 (记录 pain_point 后自动调度)
  - pending_topics: 未完话题
  - recent_pain_points: 近期痛点 (最近 10 条)
  - recent_joy_points: 近期乐点 (最近 10 条)

持久化: data/companion_state.json (atomic write), 路径遵循 core.paths.data_dir()
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from core.paths import data_dir

logger = logging.getLogger(__name__)

# 关系阶段顺序: 越靠后越亲密
RELATIONSHIP_STAGES: tuple[str, ...] = (
    "stranger",
    "acquaintance",
    "familiar",
    "close",
    "intimate",
)

# recent_pain_points / recent_joy_points 各自保留的最近条目数
MAX_RECENT_POINTS = 10

# add_pain_point 自动调度 care_followup 的默认到期延迟 (秒)
DEFAULT_CARE_FOLLOWUP_DELAY_SECONDS = 3600.0


# ── 条目数据类 ─────────────────────────────────────
@dataclass
class PainPoint:
    text: str
    created_at: float
    note: str = ""


@dataclass
class JoyPoint:
    text: str
    created_at: float
    note: str = ""


@dataclass
class PendingTopic:
    topic: str
    created_at: float
    done: bool = False


@dataclass
class CareFollowup:
    topic: str
    created_at: float
    due_at: float
    done: bool = False
    source: str = "pain_point"


# ── 主状态 ─────────────────────────────────────────
@dataclass
class CompanionState:
    """陪伴状态: 关系阶段 + 挂心事项 + 未完话题 + 近期痛点/乐点."""

    relationship_stage: str = "stranger"
    care_followups: list[CareFollowup] = field(default_factory=list)
    pending_topics: list[PendingTopic] = field(default_factory=list)
    recent_pain_points: list[PainPoint] = field(default_factory=list)
    recent_joy_points: list[JoyPoint] = field(default_factory=list)
    # P0 topic system: 统一沉寂时钟（time.time() epoch；0 = 从未记录）。
    last_user_active_at: float = 0.0

    STAGES: ClassVar[tuple[str, ...]] = RELATIONSHIP_STAGES
    MAX_RECENT: ClassVar[int] = MAX_RECENT_POINTS

    # ── pain / joy ─────────────────────────────────
    def add_pain_point(
        self,
        text: str,
        *,
        note: str = "",
        created_at: float | None = None,
        followup_delay_seconds: float = DEFAULT_CARE_FOLLOWUP_DELAY_SECONDS,
    ) -> PainPoint:
        """记录痛点, 并自动调度一条 care_followup."""
        ts = float(created_at) if created_at is not None else time.time()
        entry = PainPoint(text=str(text), created_at=ts, note=str(note or ""))
        self.recent_pain_points.append(entry)
        if len(self.recent_pain_points) > self.MAX_RECENT:
            self.recent_pain_points = self.recent_pain_points[-self.MAX_RECENT:]
        # 自动调度挂心事项
        self.schedule_care_followup(
            topic=str(text),
            due_at=ts + float(followup_delay_seconds),
            created_at=ts,
            source="pain_point",
        )
        return entry

    def add_joy_point(
        self,
        text: str,
        *,
        note: str = "",
        created_at: float | None = None,
    ) -> JoyPoint:
        ts = float(created_at) if created_at is not None else time.time()
        entry = JoyPoint(text=str(text), created_at=ts, note=str(note or ""))
        self.recent_joy_points.append(entry)
        if len(self.recent_joy_points) > self.MAX_RECENT:
            self.recent_joy_points = self.recent_joy_points[-self.MAX_RECENT:]
        return entry

    # ── pending_topic ──────────────────────────────
    def add_pending_topic(
        self,
        topic: str,
        *,
        created_at: float | None = None,
    ) -> PendingTopic:
        ts = float(created_at) if created_at is not None else time.time()
        entry = PendingTopic(topic=str(topic), created_at=ts, done=False)
        self.pending_topics.append(entry)
        return entry

    def complete_pending_topic(self, topic: str) -> bool:
        """按文本匹配完成并移除一条未完话题。返回是否命中."""
        target = str(topic)
        for i, item in enumerate(self.pending_topics):
            if item.topic == target:
                self.pending_topics.pop(i)
                return True
        return False

    # ── care_followup ──────────────────────────────
    def schedule_care_followup(
        self,
        topic: str,
        *,
        due_at: float,
        created_at: float | None = None,
        source: str = "pain_point",
    ) -> CareFollowup:
        ts = float(created_at) if created_at is not None else time.time()
        followup = CareFollowup(
            topic=str(topic),
            created_at=ts,
            due_at=float(due_at),
            done=False,
            source=str(source or "pain_point"),
        )
        self.care_followups.append(followup)
        return followup

    def check_due_followups(self, *, now: float | None = None) -> list[CareFollowup]:
        """返回已到期且未完成的挂心事项 (due_at <= now)."""
        current = float(now) if now is not None else time.time()
        return [f for f in self.care_followups if not f.done and f.due_at <= current]

    # ── relationship_stage ─────────────────────────
    def advance_relationship_stage(self) -> str:
        """提升到下一关系阶段, 顶阶保持不变."""
        try:
            idx = self.STAGES.index(self.relationship_stage)
        except ValueError:
            self.relationship_stage = self.STAGES[0]
            return self.relationship_stage
        if idx < len(self.STAGES) - 1:
            self.relationship_stage = self.STAGES[idx + 1]
        return self.relationship_stage

    def set_relationship_stage(self, stage: str) -> str:
        """显式设置关系阶段, 非法值抛 ValueError."""
        if stage not in self.STAGES:
            raise ValueError(f"invalid relationship_stage: {stage!r}")
        self.relationship_stage = stage
        return self.relationship_stage

    # ── 统一沉寂时钟（P0 topic system）──────────────
    def mark_user_active(self) -> None:
        """记录用户活跃（统一 time.time() 时钟）。"""
        self.last_user_active_at = time.time()

    def idle_hours(self) -> float:
        """距上次活跃的小时数；从未活跃返回 0（防误触发）。"""
        if not self.last_user_active_at:
            return 0.0
        return max(0.0, (time.time() - self.last_user_active_at) / 3600.0)

    # ── 序列化 ─────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        return {
            "relationship_stage": self.relationship_stage,
            "care_followups": [_followup_to_dict(f) for f in self.care_followups],
            "pending_topics": [_pending_to_dict(p) for p in self.pending_topics],
            "recent_pain_points": [_pain_to_dict(p) for p in self.recent_pain_points],
            "recent_joy_points": [_joy_to_dict(j) for j in self.recent_joy_points],
            "last_user_active_at": self.last_user_active_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CompanionState":
        data = data or {}
        return cls(
            relationship_stage=str(
                data.get("relationship_stage") or RELATIONSHIP_STAGES[0]
            ),
            care_followups=[
                _followup_from_dict(item)
                for item in (data.get("care_followups") or [])
            ],
            pending_topics=[
                _pending_from_dict(item)
                for item in (data.get("pending_topics") or [])
            ],
            recent_pain_points=[
                _pain_from_dict(item)
                for item in (data.get("recent_pain_points") or [])
            ],
            recent_joy_points=[
                _joy_from_dict(item)
                for item in (data.get("recent_joy_points") or [])
            ],
            last_user_active_at=float(data.get("last_user_active_at") or 0.0),
        )

    # ── 持久化 ─────────────────────────────────────
    @staticmethod
    def default_state_path() -> Path:
        return data_dir() / "companion_state.json"

    def save(self, path: str | Path | None = None) -> Path:
        """原子写 JSON。未指定路径时写入 default_state_path()."""
        target = Path(path) if path is not None else self.default_state_path()
        _atomic_write_json(target, self.to_dict())
        return target

    @classmethod
    def load(cls, path: str | Path | None = None) -> "CompanionState":
        """从 JSON 读取; 文件缺失或损坏时返回空白状态."""
        target = Path(path) if path is not None else cls.default_state_path()
        data = _load_json(target)
        if data is None:
            return cls()
        try:
            return cls.from_dict(data)
        except Exception:
            logger.warning("companion_state.json corrupt, resetting")
            return cls()


# ── 条目序列化辅助 ─────────────────────────────────
def _pain_to_dict(p: PainPoint) -> dict[str, Any]:
    return {"text": p.text, "created_at": p.created_at, "note": p.note}


def _pain_from_dict(data: dict[str, Any]) -> PainPoint:
    return PainPoint(
        text=str(data.get("text", "")),
        created_at=float(data.get("created_at", 0.0) or 0.0),
        note=str(data.get("note", "") or ""),
    )


def _joy_to_dict(j: JoyPoint) -> dict[str, Any]:
    return {"text": j.text, "created_at": j.created_at, "note": j.note}


def _joy_from_dict(data: dict[str, Any]) -> JoyPoint:
    return JoyPoint(
        text=str(data.get("text", "")),
        created_at=float(data.get("created_at", 0.0) or 0.0),
        note=str(data.get("note", "") or ""),
    )


def _pending_to_dict(p: PendingTopic) -> dict[str, Any]:
    return {"topic": p.topic, "created_at": p.created_at, "done": p.done}


def _pending_from_dict(data: dict[str, Any]) -> PendingTopic:
    return PendingTopic(
        topic=str(data.get("topic", "")),
        created_at=float(data.get("created_at", 0.0) or 0.0),
        done=bool(data.get("done", False)),
    )


def _followup_to_dict(f: CareFollowup) -> dict[str, Any]:
    return {
        "topic": f.topic,
        "created_at": f.created_at,
        "due_at": f.due_at,
        "done": f.done,
        "source": f.source,
    }


def _followup_from_dict(data: dict[str, Any]) -> CareFollowup:
    return CareFollowup(
        topic=str(data.get("topic", "")),
        created_at=float(data.get("created_at", 0.0) or 0.0),
        due_at=float(data.get("due_at", 0.0) or 0.0),
        done=bool(data.get("done", False)),
        source=str(data.get("source", "pain_point") or "pain_point"),
    )


# ── JSON 原子读写 (与 desire_engine 风格一致) ──────
def _atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON atomically (tempfile + replace)."""
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        logger.warning("companion_state.json read failed, treating as empty")
        return None
