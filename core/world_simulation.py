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
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, ItemsView, Iterable

from core.action_registry import ActionRegistry, WorldAction

# 世界模拟统一使用本地时区（北京时间 UTC+08:00）。
# 此前误用 UTC 导致时段/光线提示词整体错位 8 小时（凌晨被判定成下午）。
LOCAL_TZ: timezone = timezone(timedelta(hours=8))


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
# 物件 = 伊塔重庆复式公寓的空间素材（与 persona 复式公寓设定对齐），
# 而非通用占位物；真实附近地点（重庆 POI）在 tick() 中与之合并为"她的家 + 她窗外的城市"。
_ENVIRONMENT_OBJECTS: dict[tuple[str, str], list[str]] = {
    ("home", "sleeping"): ["king_bed", "night_lamp", "window", "your_coat"],
    ("home", "planning"): ["password_lock", "shoe_cabinet", "gray_sofa", "bookshelf"],
    ("home", "dining"): ["double_door_fridge", "round_table", "kitchen_island"],
    ("home", "relaxing"): ["gray_sofa", "floor_lamp", "bookshelf", "pendant"],
    ("study", "working"): ["design_desk", "imac", "drawing_tablet", "corkboard"],
}

_DEFAULT_HOME_OBJECTS = ["gray_sofa", "floor_lamp", "bookshelf", "your_coat"]
_DEFAULT_STUDY_OBJECTS = ["design_desk", "imac", "drawing_tablet"]

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

# ── Weather moods (P1 设计缺口 G4) ───────────────────────────────
# weather_mood 由 seed + ts + phase 确定性派生（seed 参与环境计算 G5）。
# 固定 seed + 同一时刻 → 结果稳定可复现；不同 seed → 环境略有差异。
_WEATHER_MOODS: tuple[tuple[str, str], ...] = (
    ("clear", "晴"),
    ("partly_cloudy", "多云"),
    ("cloudy", "阴"),
    ("rain", "雨"),
    ("windy", "风"),
    ("fog", "雾"),
)
_DEFAULT_WEATHER_MOOD = "neutral"

# 每日随机生活事件池（配合 random_events_per_day 使用；纯文本占位，非 LLM）。
_RANDOM_EVENT_POOL: tuple[str, ...] = (
    "今天路过常去的那家店，发现换了新的招牌",
    "傍晚窗外天色很好看，适合发张照片给你",
    "想起一个只有我们知道的小玩笑，嘴角不自觉上扬",
    "午睡时做了个有点长的梦，醒来有点恍惚",
    "路上看到一只猫在晒太阳，蹲下来看了好一会儿",
    "今天耳机里单曲循环了一首很耳熟的老歌",
    "阳台的花今天开了，颜色比想象中更亮",
    "刚喝完一杯水，突然就想到你了",
)


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
    weather: str = ""
    weather_mood: str = "neutral"
    weather_detail: str = ""
    city: str = ""
    random_events: list[str] = field(default_factory=list)
    city_events: list[dict[str, str]] = field(default_factory=list)

    # 兼容字段 (历史 API)
    ts: int = 0
    iso_time: str = ""
    source: str = "simulated"
    revision: int = 0
    seed_sha256: str = ""
    snapshot_id: str = ""
    world_snapshot_id: str = ""
    tick_id: str = ""
    created_at: str = ""

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
        self.clock = clock or (lambda: datetime.now(LOCAL_TZ))
        self.action_registry = action_registry or ActionRegistry()
        self.seed = str(self.config.get("seed") or "aerie-world")
        self._ticks = 0
        self._snapshot: WorldSnapshot | None = None
        self._cached_second: int | None = None  # 秒级缓存键
        self._reality: dict[str, Any] = {}  # 真实世界数据（weather/nearby/events）

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
        # 把环境物件（含重庆 POI）衍生为 "object_<name>" 话题, 让主动消息有可发图片素材。
        for obj in nearby_objects[:6]:
            topic = f"object_{obj}"
            if topic not in topics:
                topics.append(topic)
        return topics

    def _compute_weather(self, phase: str, ts: int) -> str:
        """确定性天气派生：seed + ts + phase 决定 weather_mood (G4/G5)。

        开启条件由 config 的 ``weather_enabled`` 控制（默认开启）。
        关闭或数据缺失时回退 ``neutral``，保证后端兼容不报错。
        """
        enabled = bool(self.config.get("weather_enabled", True))
        if not enabled:
            return _DEFAULT_WEATHER_MOOD
        digest = _sha256(
            json.dumps(
                {"seed": self.seed, "ts": ts, "phase": phase},
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        idx = int(digest[:8], 16) % len(_WEATHER_MOODS)
        mood, _label = _WEATHER_MOODS[idx]
        return mood

    # ── 真实世界注入（world_reality 提供，best-effort） ─────────────
    def set_reality(self, reality: dict[str, Any] | None) -> None:
        """注入真实天气/附近地点/实时事件；任何时刻缺失都保留既有回退逻辑。"""
        self._reality = reality if isinstance(reality, dict) else {}

    def _real_weather_mood(self) -> str:
        """把真实天气描述映射为世界天气情绪；无真实天气则回退确定性派生。"""
        weather = self._reality.get("weather") if isinstance(self._reality, dict) else None
        desc = (weather or {}).get("desc") if isinstance(weather, dict) else ""
        desc = str(desc or "").strip()
        if "晴" in desc:
            return "clear"
        if "雨" in desc:
            return "rain"
        if "雾" in desc:
            return "fog"
        if "风" in desc:
            return "windy"
        if "阴" in desc:
            return "cloudy"
        if "云" in desc:
            return "partly_cloudy"
        return _DEFAULT_WEATHER_MOOD

    def _real_weather_detail(self) -> str:
        weather = self._reality.get("weather") if isinstance(self._reality, dict) else None
        if not isinstance(weather, dict):
            return ""
        parts = [str(weather.get("temp") or "").strip(), str(weather.get("desc") or "").strip()]
        detail = " ".join(p for p in parts if p)
        if weather.get("city"):
            detail = f"{weather.get('city')} {detail}".strip()
        return detail

    def _compute_random_events(self, now: datetime) -> list[str]:
        """每日随机生活事件：seed + 日期 派生 → 同一天稳定、跨天不同。

        ``random_events_per_day`` 为 0 时关闭。事件池按日洗牌后取前 N 条。
        """
        count = int(self.config.get("random_events_per_day", 3) or 0)
        if count <= 0:
            return []
        key = json.dumps(
            {"seed": self.seed, "date": now.strftime("%Y-%m-%d")},
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = _sha256(key)
        pool = list(_RANDOM_EVENT_POOL)
        # 用日种子洗牌（Fisher-Yates，纯确定性）
        pool_len = len(pool)
        a = int(digest[:16], 16)
        for i in range(pool_len - 1, 0, -1):
            a = (a * 1103515245 + 12345) & 0xFFFFFFFF
            j = a % (i + 1)
            pool[i], pool[j] = pool[j], pool[i]
        return pool[:count]

    def _reality_nearby_objects(self) -> list[str]:
        places = self._reality.get("nearby_places") if isinstance(self._reality, dict) else None
        if not isinstance(places, list):
            return []
        names = []
        for p in places:
            if isinstance(p, dict) and str(p.get("name") or "").strip():
                names.append(str(p["name"]).strip())
        return names

    def _reality_city_events(self) -> list[dict[str, str]]:
        events = self._reality.get("city_events") if isinstance(self._reality, dict) else None
        if not isinstance(events, list):
            return []
        return [dict(e) for e in events if isinstance(e, dict)]

    # ── main tick ───────────────────────────────────────────────
    def tick(self, action: WorldAction | None = None) -> WorldSnapshot:
        now = self.clock()
        # 无论时钟返回 naive 还是 aware（含 UTC），一律归一化到本地时区，
        # 否则 phase/energy/iso_time 会用 UTC 小时（如 10:26Z 被误判成 morning）。
        if now.tzinfo is None:
            now = now.replace(tzinfo=LOCAL_TZ)
        else:
            now = now.astimezone(LOCAL_TZ)
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

        # 真实天气情绪（有真实天气则优先，否则确定性派生）。
        real_mood = self._real_weather_mood()
        weather_mood = real_mood if real_mood != _DEFAULT_WEATHER_MOOD else self._compute_weather(phase_name, ts)
        weather_detail = self._real_weather_detail()

        # 房间物件（她的重庆公寓）在前，窗外/附近的真实城市地点（重庆 POI）在后，
        # 合并去重：视觉素材既有"她的家"，也有"她窗外的重庆"，与 location 语义一致。
        room_objects = self._compute_nearby_objects(location, activity)
        real_nearby = self._reality_nearby_objects()
        nearby_objects = list(dict.fromkeys(room_objects + real_nearby))[:6]
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
            world_snapshot_id=instance_id,
            tick_id=f"tick-{ts}",
            created_at=now.isoformat(),
            weather_mood=weather_mood,
            weather=weather_mood,
            weather_detail=weather_detail,
            city=str((self._reality.get("city") if isinstance(self._reality, dict) else "") or ""),
            random_events=self._compute_random_events(now),
            city_events=self._reality_city_events(),
        )
        if action_result:
            # 兼容旧行为: 把 last_action 注入
            object.__setattr__(snap, "last_action", action.to_public_dict())  # type: ignore[attr-defined]

        self._snapshot = snap
        self._cached_second = ts
        return snap

    def get_snapshot(self, *, max_age_sec: float | None = None) -> WorldSnapshot:
        """返回当前世界快照。

        传 ``max_age_sec`` 时，若缓存快照超过该秒数未刷新，则强制调用
        ``tick()`` 随真实时钟重算时段/话题——保证世界循环停摆时，
        主动发图等读快照方仍能拿到"当前时段"，杜绝旧时段/旧话题导致的去重空转。
        """
        if self._snapshot is None:
            return self.tick()
        if max_age_sec is None:
            return self._snapshot
        try:
            current = int(self.clock().timestamp())
        except Exception:
            return self._snapshot
        if self._cached_second is not None and (current - self._cached_second) > max_age_sec:
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
                "world_snapshot_id",
                "tick_id",
                "created_at",
                "weather",
                "weather_mood",
                "weather_detail",
                "city",
                "random_events",
                "city_events",
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
