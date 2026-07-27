"""Phase 12 deterministic in-process world simulation.

P1-C.1 扩展:
  - WorldSnapshot dataclass: phase/location/activity/energy/social/
    nearby_objects/available_visual_topics/instance_id/timestamp
  - WorldSimulation.tick() 返回 WorldSnapshot(同时兼容 dict 访问)
  - 同一秒内 tick() 幂等返回缓存快照
  - 确定性时段映射 morning/noon/afternoon/evening/night
  - energy 随时间衰减/恢复
  - nearby_objects / available_visual_topics 基于 phase/location/activity 派生
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, ItemsView, Iterable

from core.action_registry import ActionRegistry, WorldAction


# ── Phase definitions ────────────────────────────────────────────
# 新的 5 段时段映射(基于小时):
#   night      23:00 – 06:00
#   morning    06:00 – 12:00
#   noon       12:00 – 14:00
#   afternoon  14:00 – 19:00
#   evening    19:00 – 23:00
# energy 在 morning 最高, afternoon 衰减, evening 进一步下降, night 最低(恢复中)
DEFAULT_WORLD_PHASES: dict[str, dict[str, Any]] = {
    "night": {
        "start": "23:00",
        "end": "06:00",
        "location": "home",
        "activity": "sleeping",
        "energy": 0.22,
        "social": "private",
    },
    "morning": {
        "start": "06:00",
        "end": "12:00",
        "location": "home",
        "activity": "planning",
        "energy": 0.78,
        "social": "private",
    },
    "noon": {
        "start": "12:00",
        "end": "14:00",
        "location": "home",
        "activity": "dining",
        "energy": 0.62,
        "social": "private",
    },
    "afternoon": {
        "start": "14:00",
        "end": "19:00",
        "location": "study",
        "activity": "working",
        "energy": 0.55,
        "social": "focused",
    },
    "evening": {
        "start": "19:00",
        "end": "23:00",
        "location": "home",
        "activity": "relaxing",
        "energy": 0.42,
        "social": "private",
    },
}


# ── Environment objects per (location, activity) ─────────────────
_ENVIRONMENT_OBJECTS: dict[tuple[str, str], list[str]] = {
    ("home", "sleeping"): ["bed", "night_lamp", "window", "alarm_clock"],
    ("home", "planning"): ["desk", "notebook", "coffee_mug", "window", "calendar"],
    ("home", "dining"): ["dining_table", "plate", "tea_cup", "kitchen_counter"],
    ("home", "relaxing"): ["sofa", "tv_remote", "blanket", "bookshelf", "mug"],
    ("study", "working"): ["laptop", "monitor", "keyboard", "notebook", "pen_holder"],
}

_DEFAULT_HOME_OBJECTS = ["sofa", "desk", "window", "bookshelf"]
_DEFAULT_STUDY_OBJECTS = ["laptop", "notebook", "desk"]

# ── Visual topic derivation rules ────────────────────────────────
# 每个 activity 可选的视觉话题前缀; 与 nearby_objects 组合后去重
_ACTIVITY_TOPIC_PREFIXES: dict[str, list[str]] = {
    "sleeping": ["good_night", "starry_window"],
    "planning": ["morning_plan", "coffee_break"],
    "dining": ["lunch_time", "tea_break"],
    "working": ["deep_focus", "desk_view"],
    "relaxing": ["evening_chill", "reading_time"],
    "idle": ["quiet_moment"],
}


@dataclass
class WorldSnapshot:
    """角色当前世界状态的不可变快照.

    同时支持属性访问和 dict 风格下标访问以保持向后兼容
    (历史调用方仍在使用 snapshot["phase"] 等).
    """

    phase: str = "unknown"
    location: str = "home"
    activity: str = "idle"
    energy: float = 0.5
    social: str = "private"
    nearby_objects: list[str] = field(default_factory=list)
    available_visual_topics: list[str] = field(default_factory=list)
    instance_id: str = ""
    timestamp: float = 0.0

    # 兼容字段 (历史 API)
    ts: int = 0
    iso_time: str = ""
    source: str = "simulated"
    revision: int = 0
    seed_sha256: str = ""
    snapshot_id: str = ""

    # ── dict-style backward compatibility ───────────────────────
    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def __contains__(self, key: object) -> bool:
        return hasattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def keys(self) -> Iterable[str]:
        return asdict(self).keys()

    def items(self) -> ItemsView[str, Any]:
        return asdict(self).items()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    # 允许 dict(snapshot)
    def __iter__(self):
        return iter(asdict(self))

    def __len__(self) -> int:
        return len(asdict(self))


class WorldSimulation:
    """A deterministic clock-driven snapshot generator.

    No LLM calls, no external facts, no database writes.  Given the same
    config seed and clock, a fresh simulator produces the same snapshot.
    """

    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        clock: Callable[[], datetime] | None = None,
        action_registry: ActionRegistry | None = None,
    ) -> None:
        self.config = config or {}
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.action_registry = action_registry or ActionRegistry()
        self.seed = str(self.config.get("seed") or "aerie-world")
        self._ticks = 0
        self._snapshot: WorldSnapshot | None = None
        self._cached_second: int | None = None  # 秒级缓存键

    @staticmethod
    def minute(value: str) -> int:
        hour, minute = str(value).split(":", 1)
        return int(hour) * 60 + int(minute)

    def phase_for(self, now: datetime) -> tuple[str, dict[str, Any]]:
        current = now.hour * 60 + now.minute
        phases = self.config.get("phases")
        if not isinstance(phases, dict) or not phases:
            phases = DEFAULT_WORLD_PHASES
        for name, phase in phases.items():
            if not isinstance(phase, dict):
                continue
            start = self.minute(phase.get("start", "00:00"))
            end = self.minute(phase.get("end", "23:59"))
            if start <= end and start <= current < end:
                return str(name), phase
            if start > end and (current >= start or current < end):
                return str(name), phase
        return "unknown", {
            "location": "home",
            "activity": "idle",
            "energy": 0.5,
            "social": "private",
        }

    # ── deterministic helpers ───────────────────────────────────
    def _compute_phase(self, now: datetime) -> str:
        name, _ = self.phase_for(now)
        return name

    def _compute_activity(self, phase: str, phase_data: dict[str, Any]) -> str:
        return str(phase_data.get("activity", "idle"))

    def _compute_energy(
        self,
        phase: str,
        phase_data: dict[str, Any],
        now: datetime,
    ) -> float:
        """Energy follows a gentle curve within each phase — decays during
        active phases, recovers at night."""
        base = _clamp01(float(phase_data.get("energy", 0.5)))
        start = self.minute(phase_data.get("start", "00:00"))
        end = self.minute(phase_data.get("end", "23:59"))
        current = now.hour * 60 + now.minute
        if end <= start:  # overnight wrap
            span = (24 * 60 - start) + end
            elapsed = (current - start) if current >= start else (24 * 60 - start + current)
        else:
            span = max(1, end - start)
            elapsed = max(0, min(span, current - start))
        ratio = elapsed / span

        if phase == "night":
            # 恢复: 从低能量向 0.6 靠拢
            return _clamp01(base + (0.6 - base) * ratio)
        # 活动期: 从 base 缓慢衰减 15%
        return _clamp01(base - 0.15 * ratio * base)

    def _compute_nearby_objects(
        self, location: str, activity: str
    ) -> list[str]:
        key = (location, activity)
        if key in _ENVIRONMENT_OBJECTS:
            return list(_ENVIRONMENT_OBJECTS[key])
        if location == "study":
            return list(_DEFAULT_STUDY_OBJECTS)
        return list(_DEFAULT_HOME_OBJECTS)

    def _derive_visual_topics(
        self, activity: str, nearby_objects: list[str]
    ) -> list[str]:
        prefixes = list(_ACTIVITY_TOPIC_PREFIXES.get(activity, _ACTIVITY_TOPIC_PREFIXES["idle"]))
        topics: list[str] = []
        for p in prefixes:
            topics.append(p)
        # 把环境物件衍生为 "object_<name>" 话题, 让主动消息有可发图片素材
        for obj in nearby_objects[:3]:
            topic = f"object_{obj}"
            if topic not in topics:
                topics.append(topic)
        return topics

    # ── main tick ───────────────────────────────────────────────
    def tick(self, action: WorldAction | None = None) -> WorldSnapshot:
        now = self.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        ts = int(now.timestamp())

        # 秒级幂等: 同一秒内再次 tick 直接返回缓存
        if (
            self._snapshot is not None
            and self._cached_second == ts
            and action is None
        ):
            return self._snapshot

        phase_name, phase_data = self.phase_for(now)
        location = str(phase_data.get("location", "home"))
        activity = self._compute_activity(phase_name, phase_data)

        action_result = None
        if action is not None:
            action_result = self.action_registry.execute(
                action,
                world_snapshot={"activity": activity},
            )
            if action_result.get("action") == "set_activity":
                activity = str(action_result.get("activity") or activity)

        self._ticks += 1
        energy = self._compute_energy(phase_name, phase_data, now)
        social = str(phase_data.get("social", "private"))
        nearby_objects = self._compute_nearby_objects(location, activity)
        visual_topics = self._derive_visual_topics(activity, nearby_objects)

        instance_id = _sha256(
            json.dumps(
                {
                    "seed": self.seed,
                    "ts": ts,
                    "phase": phase_name,
                    "revision": self._ticks,
                    "activity": activity,
                    "objects": nearby_objects,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )[:16]

        snap = WorldSnapshot(
            phase=phase_name,
            location=location,
            activity=activity,
            energy=energy,
            social=social,
            nearby_objects=nearby_objects,
            available_visual_topics=visual_topics,
            instance_id=instance_id,
            timestamp=float(ts),
            ts=ts,
            iso_time=now.isoformat(),
            source="simulated",
            revision=self._ticks,
            seed_sha256=_sha256(self.seed),
            snapshot_id=instance_id,
        )
        if action_result:
            # 兼容旧行为: 把 last_action 注入
            object.__setattr__(snap, "last_action", action.to_public_dict())  # type: ignore[attr-defined]

        self._snapshot = snap
        self._cached_second = ts
        return snap

    def get_snapshot(self) -> WorldSnapshot:
        if self._snapshot is None:
            return self.tick()
        return self._snapshot

    def restore(self, snapshot: dict[str, Any] | None) -> dict[str, Any]:
        """Restore a previously whitelisted checkpoint without advancing time."""

        source = snapshot if isinstance(snapshot, dict) else {}
        restored = {
            key: source[key]
            for key in (
                "ts",
                "iso_time",
                "phase",
                "location",
                "activity",
                "energy",
                "social",
                "source",
                "revision",
                "seed_sha256",
                "snapshot_id",
                "nearby_objects",
                "available_visual_topics",
                "instance_id",
                "timestamp",
            )
            if key in source
        }
        if not restored:
            return {}
        self._ticks = max(0, int(restored.get("revision") or 0))
        snap = WorldSnapshot(**{k: v for k, v in restored.items() if k in WorldSnapshot.__dataclass_fields__})
        self._snapshot = snap
        self._cached_second = int(restored.get("ts") or 0) or None
        return snap.to_dict()


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
