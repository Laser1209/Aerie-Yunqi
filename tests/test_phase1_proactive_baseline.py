from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest


@pytest.mark.asyncio
async def test_desire_engine_uses_public_scheduler_trigger():
    from core.desire_engine import DesireEngine

    scheduler = SimpleNamespace(trigger=AsyncMock(return_value=True))
    engine = DesireEngine.__new__(DesireEngine)
    engine.companion = SimpleNamespace(push_scheduler=scheduler)

    await engine._trigger_scene("idle_care")

    scheduler.trigger.assert_awaited_once_with("idle_care")


@pytest.mark.asyncio
async def test_push_event_engine_uses_public_scheduler_trigger():
    from core.push_event_engine import EventType, PushEvent, PushEventEngine

    scheduler = SimpleNamespace(trigger=AsyncMock(return_value=True))
    engine = PushEventEngine()
    engine.bind_scheduler(scheduler)

    pushed = await engine._try_push_for_event(
        PushEvent(event_type=EventType.SYSTEM_BOOT, priority=8)
    )

    assert pushed is True
    scheduler.trigger.assert_awaited_once_with("boot_greeting")


def test_proactive_judge_reads_companion_desire_attribute():
    from core.proactive_judge import ProactiveJudge

    desire = MagicMock()
    desire.get_state.return_value = {
        "score": 80,
        "user_absence_hours": 2,
    }
    companion = SimpleNamespace(
        desire=desire,
        emotion=None,
        push_scheduler=None,
    )

    decision = ProactiveJudge(companion=companion).evaluate("idle_care")

    assert decision.components["desire_score"] == 80
    assert decision.components["user_minutes_since_last"] == 120


@pytest.mark.asyncio
async def test_companion_manages_push_event_engine_lifecycle():
    from core.companion import Companion

    companion = Companion.__new__(Companion)
    companion.push_scheduler = MagicMock()
    companion.push_event_engine = SimpleNamespace(
        bind_scheduler=MagicMock(),
        start=AsyncMock(),
        stop=AsyncMock(),
    )

    await companion._start_push_event_engine()
    await companion._stop_push_event_engine()

    companion.push_event_engine.bind_scheduler.assert_called_once_with(
        companion.push_scheduler
    )
    companion.push_event_engine.start.assert_awaited_once()
    companion.push_event_engine.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_inbound_message_records_event_engine_activity():
    from core.companion import Companion

    companion = Companion.__new__(Companion)
    companion.pipeline = SimpleNamespace(handle=AsyncMock())
    companion.desire = None
    companion.push_event_engine = SimpleNamespace(
        record_user_activity=MagicMock()
    )
    message = SimpleNamespace(user_id=7, content="你好")

    await companion._on_qq_message(message)

    companion.push_event_engine.record_user_activity.assert_called_once_with()


@pytest.mark.asyncio
async def test_idle_and_threshold_hooks_await_public_trigger():
    from core.companion import Companion

    companion = Companion.__new__(Companion)
    companion.push_scheduler = SimpleNamespace(
        trigger=AsyncMock(return_value=True)
    )

    idle_result = await companion.check_idle(7, 4 * 3600)
    await companion.check_threshold_break()

    assert idle_result is True
    assert companion.push_scheduler.trigger.await_args_list == [
        (("idle_care",), {}),
        (("emotion_comfort",), {}),
    ]


def test_proactive_config_keeps_single_idle_care_definition():
    from pathlib import Path

    config_text = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "proactive.yaml"
    ).read_text(encoding="utf-8")

    assert config_text.count("\n  idle_care:\n") == 1


def _make_push_companion(*, flag_enabled: bool, qq_online: bool = True):
    from core.companion import Companion

    companion = Companion.__new__(Companion)
    companion.settings = {
        "qq": {"self_qq": 7},
        "proactive": {"system_notifications": True},
    }
    companion.feature_flags = SimpleNamespace(
        is_enabled=MagicMock(return_value=flag_enabled)
    )
    companion.qq = SimpleNamespace(
        is_logged_in=qq_online,
        self_id=7,
        send_message=AsyncMock(return_value=qq_online),
    )
    companion.emotion = SimpleNamespace(
        get_state=MagicMock(return_value={"label": "neutral"})
    )
    companion.brain = SimpleNamespace(
        generate_push=AsyncMock(return_value="记得休息。")
    )
    companion.db = SimpleNamespace(insert=MagicMock(return_value=42))
    return companion


@pytest.mark.asyncio
async def test_v2_delivery_attempts_qq_bubble_and_notification(monkeypatch):
    from core import chat_events

    companion = _make_push_companion(flag_enabled=True)
    emitted = MagicMock()
    monkeypatch.setattr(chat_events, "emit", emitted)

    result = await companion._dispatch_push(
        "idle_care",
        {"template": "在干嘛。", "tone_hint": "warm"},
    )

    assert result is True
    companion.qq.send_message.assert_awaited_once_with(7, "记得休息。")
    companion.db.insert.assert_called_once_with(
        "chat_log",
        {
            "user_id": 7,
            "role": "assistant",
            "content": "记得休息。",
            "msg_type": "proactive",
            "route_mode": "PROACTIVE",
            "scene": "idle_care",
        },
    )
    assert emitted.call_args_list[:2] == [
        call(
            "assistant",
            role="assistant",
            id=42,
            user_id=7,
            content="记得休息。",
            source="proactive",
            scene="idle_care",
            channel="desktop",
        ),
        call(
            "proactive_message",
            title="云栖",
            text="记得休息。",
            content="记得休息。",
            scene="idle_care",
            tone="warm",
            notify_system=True,
            channel="notification",
        ),
    ]
    assert emitted.call_args_list[2] == call(
        "proactive_delivery",
        scene="idle_care",
        results={
            "qq": "sent",
            "desktop": "queued",
            "notification": "queued",
        },
        channel="delivery",
    )


@pytest.mark.asyncio
async def test_v2_delivery_succeeds_locally_when_qq_is_offline(monkeypatch):
    from core import chat_events

    companion = _make_push_companion(flag_enabled=True, qq_online=False)
    emitted = MagicMock()
    monkeypatch.setattr(chat_events, "emit", emitted)

    result = await companion._dispatch_push("idle_care", {"template": "在干嘛。"})

    assert result is True
    companion.qq.send_message.assert_not_awaited()
    assert [item.args[0] for item in emitted.call_args_list] == [
        "assistant",
        "proactive_message",
        "proactive_delivery",
    ]
    assert emitted.call_args_list[2].kwargs["results"] == {
        "qq": "offline",
        "desktop": "queued",
        "notification": "queued",
    }


@pytest.mark.asyncio
async def test_v2_system_notification_can_be_disabled(monkeypatch):
    from core import chat_events

    companion = _make_push_companion(flag_enabled=True)
    companion.settings["proactive"]["system_notifications"] = False
    emitted = MagicMock()
    monkeypatch.setattr(chat_events, "emit", emitted)

    result = await companion._dispatch_push("idle_care", {"template": "在干嘛。"})

    assert result is True
    proactive_event = emitted.call_args_list[1]
    assert proactive_event.args[0] == "proactive_message"
    assert proactive_event.kwargs["notify_system"] is False
    assert emitted.call_args_list[2].kwargs["results"] == {
        "qq": "sent",
        "desktop": "queued",
        "notification": "disabled",
    }


@pytest.mark.asyncio
async def test_flag_off_restores_legacy_qq_only_delivery(monkeypatch):
    from core import chat_events

    companion = _make_push_companion(flag_enabled=False)
    emitted = MagicMock()
    monkeypatch.setattr(chat_events, "emit", emitted)

    result = await companion._dispatch_push("idle_care", {"template": "在干嘛。"})

    assert result is True
    companion.feature_flags.is_enabled.assert_called_once_with(
        "proactive_delivery_v2"
    )
    companion.qq.send_message.assert_awaited_once_with(7, "记得休息。")
    companion.db.insert.assert_not_called()
    emitted.assert_not_called()


def test_v2_qq_disconnect_does_not_pause_local_delivery():
    from communication.qq_client import STATE_DISCONNECTED
    from core.companion import Companion

    companion = Companion.__new__(Companion)
    companion.settings = {"qq": {"push_pause_when_offline": True}}
    companion.feature_flags = SimpleNamespace(
        is_enabled=MagicMock(return_value=True)
    )
    companion.push_scheduler = SimpleNamespace(
        is_paused=False,
        paused_reason="",
        pause=MagicMock(),
        resume=MagicMock(),
    )

    companion._on_qq_state_change(STATE_DISCONNECTED)

    companion.push_scheduler.pause.assert_not_called()


def test_chat_renderer_ignores_events_without_a_chat_role():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "electron"
        / "src"
        / "renderer"
        / "js"
        / "chat.js"
    ).read_text(encoding="utf-8")

    assert '["user", "assistant"].includes(msg.role)' in source


def test_dynamic_island_consumes_flat_proactive_event_and_notifies_system():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "electron"
        / "src"
        / "renderer"
        / "js"
        / "dynamic-island.js"
    ).read_text(encoding="utf-8")

    assert "const data = payload.data || payload;" in source
    assert "data.notify_system" in source
    assert "api?.systemNotify?." in source


def test_push_policy_blocks_quiet_non_exempt_scene(monkeypatch):
    from datetime import datetime as real_datetime

    import core.push_scheduler as module

    class QuietDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 7, 20, 23, 45)

    monkeypatch.setattr(module, "datetime", QuietDatetime)
    policy = module.PushPolicy(
        {
            "proactive": {
                "quiet_start": "23:30",
                "quiet_end": "07:00",
                "exempt_scenes": ["goodnight"],
            }
        }
    )

    assert policy.can_push("idle_care") == (False, "quiet_period")
    assert policy.can_push("goodnight") == (True, "ok")


@pytest.mark.asyncio
async def test_force_scene_bypasses_policy_and_judge():
    from core.push_scheduler import CronScheduler

    scheduler = CronScheduler(
        {
            "proactive": {"enabled": True},
            "scenes": {},
        }
    )
    scheduler.policy.can_push = MagicMock(return_value=(False, "daily_limit"))
    scheduler.policy.record = MagicMock()
    scheduler.judge = MagicMock()
    dispatcher = AsyncMock(return_value=True)
    scheduler.set_dispatcher(dispatcher)

    result = await scheduler._dispatch(
        "boot_greeting",
        {"template": "刚醒。", "force": True},
    )

    assert result is True
    scheduler.judge.evaluate.assert_not_called()
    dispatcher.assert_awaited_once()


def test_push_scheduler_exposes_status_contract_for_proactive_api():
    from core.push_scheduler import PushScheduler

    scheduler = PushScheduler(
        {
            "proactive": {"enabled": True},
            "scenes": {"idle_care": {"trigger": "idle"}},
        }
    )

    assert scheduler.running is False
    assert set(scheduler.scenes) == {"idle_care"}
    assert scheduler.policy.enabled is True


@pytest.mark.asyncio
async def test_proactive_api_uses_public_scheduler_contract(monkeypatch):
    from core import api_server
    import core.companion as companion_module
    import core.push_event_engine as event_engine_module
    from core.push_scheduler import PushScheduler

    scheduler = PushScheduler(
        {
            "proactive": {"enabled": True},
            "scenes": {"idle_care": {"trigger": "idle"}},
        }
    )
    scheduler.trigger = AsyncMock(return_value=True)
    companion = SimpleNamespace(push_scheduler=scheduler)
    engine = SimpleNamespace(get_status=MagicMock(return_value={"running": True}))
    monkeypatch.setattr(companion_module, "get_companion", lambda: companion)
    monkeypatch.setattr(event_engine_module, "get_event_engine", lambda: engine)

    status = await api_server.proactive_status()
    scenes = await api_server.proactive_scenes()
    triggered = await api_server.proactive_trigger(
        SimpleNamespace(json=AsyncMock(return_value={"scene": "idle_care"}))
    )
    toggled = await api_server.proactive_toggle(
        SimpleNamespace(json=AsyncMock(return_value={"enabled": False}))
    )

    assert status["scheduler"] == {
        "running": False,
        "scene_count": 1,
        "daily_count": 0,
    }
    assert set(scenes["scenes"]) == {"idle_care"}
    assert triggered == {"success": True, "scene": "idle_care"}
    scheduler.trigger.assert_awaited_once_with("idle_care")
    assert toggled == {"enabled": False}
    assert scheduler.policy.enabled is False


def test_flag_off_qq_disconnect_keeps_legacy_pause_behavior():
    from communication.qq_client import STATE_DISCONNECTED
    from core.companion import Companion

    companion = Companion.__new__(Companion)
    companion.settings = {"qq": {"push_pause_when_offline": True}}
    companion.feature_flags = SimpleNamespace(
        is_enabled=MagicMock(return_value=False)
    )
    companion.push_scheduler = SimpleNamespace(
        is_paused=False,
        paused_reason="",
        pause=MagicMock(),
        resume=MagicMock(),
    )

    companion._on_qq_state_change(STATE_DISCONNECTED)

    companion.push_scheduler.pause.assert_called_once_with("qq_offline")
