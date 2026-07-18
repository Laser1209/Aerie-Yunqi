"""Aerie v0.1.0-beta.1 — Event-Driven Push Engine 事件驱动推送引擎

三类主动推送触发源：
┌─────────────────────────────────────────────┐
│  1. Cron 定时触发（已有）                    │
│     - 早安/午安/晚安/天气提醒/吃饭提醒等     │
│     - 基于 proactive.yaml 配置              │
├─────────────────────────────────────────────┤
│  2. Emotion 情绪触发（已有，增强）           │
│     - 思念值满溢/寂寞感上升/情绪爆发安抚     │
│     - 基于 ProactiveJudge 综合判定           │
├─────────────────────────────────────────────┤
│  3. Event 事件触发（新增 v13.0）             │
│     - 用户上线 / 用户长时间离线后回归        │
│     - 纪念日 / 特殊日期（生日、在一起天数）  │
│     - 天气突变（下雨、降温、高温预警）       │
│     - 系统事件（新功能上线、设置变更等）     │
│     - 外部事件（待办到期、日程提醒等）       │
└─────────────────────────────────────────────┘

EventBus 负责事件订阅/发布，PushEventEngine 负责事件→场景的映射。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """事件类型"""
    # 用户行为事件
    USER_ONLINE = "user_online"           # 用户上线
    USER_OFFLINE = "user_offline"         # 用户下线
    USER_RETURN = "user_return"           # 用户长时间离线后回归
    USER_MESSAGE = "user_message"         # 用户发消息
    USER_IDLE_LONG = "user_idle_long"     # 用户长时间未互动

    # 时间/日期事件
    ANNIVERSARY = "anniversary"           # 纪念日
    BIRTHDAY = "birthday"                 # 生日
    SPECIAL_DATE = "special_date"         # 其他特殊日期
    MORNING = "morning_time"              # 早晨时刻
    NIGHT = "night_time"                  # 深夜时刻

    # 环境事件
    WEATHER_CHANGE = "weather_change"     # 天气突变
    TEMPERATURE_DROP = "temperature_drop" # 降温提醒
    TEMPERATURE_RISE = "temperature_rise" # 升温提醒
    RAIN_ALERT = "rain_alert"             # 下雨提醒

    # 系统事件
    SYSTEM_BOOT = "system_boot"           # 系统启动
    SYSTEM_UPDATE = "system_update"       # 系统更新
    SETTING_CHANGE = "setting_change"     # 设置变更

    # 待办/日程事件
    TODO_DUE = "todo_due"                 # 待办到期
    CALENDAR_REMIND = "calendar_remind"   # 日程提醒


@dataclass
class PushEvent:
    """推送事件"""
    event_type: EventType
    payload: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = "system"  # 事件来源
    priority: int = 5  # 1-10，优先级越高越优先处理


class EventBus:
    """事件总线 — 发布/订阅模式

    轻量级事件总线，支持同步和异步订阅者。
    """

    def __init__(self) -> None:
        self._subscribers: dict[EventType, list[Callable]] = {}
        self._all_subscribers: list[Callable] = []  # 订阅所有事件
        self._history: list[PushEvent] = []
        self._max_history = 100

    def subscribe(self, event_type: EventType, handler: Callable) -> None:
        """订阅特定事件类型"""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def subscribe_all(self, handler: Callable) -> None:
        """订阅所有事件"""
        self._all_subscribers.append(handler)

    def unsubscribe(self, event_type: EventType, handler: Callable) -> None:
        """取消订阅"""
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(handler)
            except ValueError:
                pass

    def publish(self, event: PushEvent) -> None:
        """发布事件（同步）"""
        self._record_history(event)
        handlers = list(self._subscribers.get(event.event_type, []))
        handlers.extend(self._all_subscribers)
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                logger.exception("event handler failed: %s", handler)

    async def publish_async(self, event: PushEvent) -> None:
        """发布事件（异步，支持 async handler）"""
        self._record_history(event)
        handlers = list(self._subscribers.get(event.event_type, []))
        handlers.extend(self._all_subscribers)
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("async event handler failed: %s", handler)

    def _record_history(self, event: PushEvent) -> None:
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    def get_history(self, event_type: Optional[EventType] = None, limit: int = 20) -> list[PushEvent]:
        """获取事件历史"""
        events = self._history
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return events[-limit:]


class PushEventEngine:
    """事件驱动推送引擎

    负责：
    1. 监听各类事件源
    2. 将事件映射到推送场景
    3. 调用 PushScheduler 触发推送
    """

    # 事件 → 场景 映射
    EVENT_TO_SCENE: dict[EventType, list[tuple[str, float]]] = {
        # 用户行为
        EventType.USER_RETURN: [("idle_care", 0.8)],
        EventType.USER_IDLE_LONG: [("idle_care", 0.6)],

        # 时间/日期
        EventType.ANNIVERSARY: [("anniversary", 1.0)],
        EventType.BIRTHDAY: [("anniversary", 1.0)],

        # 环境
        EventType.RAIN_ALERT: [("weather_push", 0.9)],
        EventType.TEMPERATURE_DROP: [("weather_push", 0.7)],

        # 系统
        EventType.SYSTEM_BOOT: [("boot_greeting", 1.0)],

        # 待办
        EventType.TODO_DUE: [("todo_remind", 0.9)],
        EventType.CALENDAR_REMIND: [("todo_remind", 0.8)],
    }

    def __init__(self, event_bus: Optional[EventBus] = None) -> None:
        self.bus = event_bus or EventBus()
        self._scheduler = None  # 延迟绑定 PushScheduler
        self._last_user_activity: datetime = datetime.now()
        self._user_online: bool = False
        self._idle_threshold_hours = 4
        self._running = False
        self._idle_monitor_task: Optional[asyncio.Task] = None

    def bind_scheduler(self, scheduler: Any) -> None:
        """绑定 PushScheduler"""
        self._scheduler = scheduler

    async def start(self) -> None:
        """启动事件引擎"""
        if self._running:
            return
        self._running = True

        # 订阅事件
        self.bus.subscribe(EventType.USER_MESSAGE, self._on_user_message)
        self.bus.subscribe(EventType.USER_ONLINE, self._on_user_online)
        self.bus.subscribe(EventType.USER_OFFLINE, self._on_user_offline)

        # 启动空闲监控
        self._idle_monitor_task = asyncio.create_task(
            self._idle_monitor_loop(),
            name="push-idle-monitor",
        )

        logger.info("[PushEventEngine] Started")

    async def stop(self) -> None:
        """停止事件引擎"""
        self._running = False
        if self._idle_monitor_task:
            self._idle_monitor_task.cancel()
            self._idle_monitor_task = None
        logger.info("[PushEventEngine] Stopped")

    def record_user_activity(self) -> None:
        """记录用户活动（每次用户发消息时调用）"""
        self._last_user_activity = datetime.now()
        if not self._user_online:
            self._user_online = True
            self.bus.publish(PushEvent(
                event_type=EventType.USER_ONLINE,
                source="activity_monitor",
            ))

    def _on_user_message(self, event: PushEvent) -> None:
        """用户消息事件处理"""
        self._last_user_activity = datetime.now()
        if not self._user_online:
            self._user_online = True

    def _on_user_online(self, event: PushEvent) -> None:
        """用户上线事件处理"""
        self._user_online = True
        # 检查是否是长时间离线后回归
        elapsed_hours = (datetime.now() - self._last_user_activity).total_seconds() / 3600
        if elapsed_hours >= self._idle_threshold_hours:
            self.bus.publish(PushEvent(
                event_type=EventType.USER_RETURN,
                payload={"idle_hours": round(elapsed_hours, 1)},
                source="activity_monitor",
                priority=7,
            ))

    def _on_user_offline(self, event: PushEvent) -> None:
        self._user_online = False

    async def _idle_monitor_loop(self) -> None:
        """空闲监控循环"""
        while self._running:
            try:
                await asyncio.sleep(600)  # 每 10 分钟检查一次
                if not self._running:
                    break

                elapsed_hours = (datetime.now() - self._last_user_activity).total_seconds() / 3600

                # 长时间空闲触发
                if self._user_online and elapsed_hours >= self._idle_threshold_hours:
                    self.bus.publish(PushEvent(
                        event_type=EventType.USER_IDLE_LONG,
                        payload={"idle_hours": round(elapsed_hours, 1)},
                        source="idle_monitor",
                        priority=5,
                    ))
                    # 触发后延迟，避免重复
                    await asyncio.sleep(3600)

            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("idle monitor error")
                await asyncio.sleep(60)

    async def trigger_event(self, event_type: EventType, payload: dict | None = None) -> bool:
        """手动触发事件并尝试推送"""
        event = PushEvent(
            event_type=event_type,
            payload=payload or {},
            source="manual",
            priority=8,
        )
        await self.bus.publish_async(event)
        return await self._try_push_for_event(event)

    async def _try_push_for_event(self, event: PushEvent) -> bool:
        """根据事件尝试推送"""
        if self._scheduler is None:
            return False

        mappings = self.EVENT_TO_SCENE.get(event.event_type, [])
        pushed = False

        for scene_name, trigger_prob in mappings:
            # 根据优先级和概率决定是否触发
            import random
            if event.priority >= 8 or random.random() < trigger_prob:
                try:
                    success = await self._scheduler.trigger_scene(scene_name)
                    if success:
                        pushed = True
                        logger.info(
                            "[PushEventEngine] Event %s triggered scene %s",
                            event.event_type.value, scene_name,
                        )
                        break  # 一个事件只触发一个主要场景
                except Exception:
                    logger.exception(
                        "[PushEventEngine] Failed to trigger scene %s", scene_name
                    )

        return pushed

    def get_status(self) -> dict:
        """获取当前状态"""
        elapsed = (datetime.now() - self._last_user_activity).total_seconds()
        return {
            "running": self._running,
            "user_online": self._user_online,
            "idle_minutes": round(elapsed / 60, 1),
            "idle_threshold_hours": self._idle_threshold_hours,
            "event_types": [e.value for e in EventType],
            "event_history_count": len(self.bus._history),
        }


# ── 单例 ──────────────────────────────────────

_event_engine_instance: Optional[PushEventEngine] = None


def get_event_engine() -> PushEventEngine:
    global _event_engine_instance
    if _event_engine_instance is None:
        _event_engine_instance = PushEventEngine()
    return _event_engine_instance


def get_event_bus() -> EventBus:
    return get_event_engine().bus
