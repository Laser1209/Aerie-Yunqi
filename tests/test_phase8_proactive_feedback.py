from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def _policy_config(state_path):
    return {
        "proactive": {
            "enabled": True,
            "max_per_day": 5,
            "min_interval_min": 30,
            "quiet_start": "00:00",
            "quiet_end": "00:00",
            "exempt_scenes": [],
            "state_path": str(state_path),
        }
    }


def test_push_policy_persists_frequency_state_across_restart(tmp_path):
    from core.push_scheduler import PushPolicy

    cfg = _policy_config(tmp_path / "policy-state.json")

    policy = PushPolicy(cfg)
    assert policy.can_push("idle_care") == (True, "ok")

    policy.record("idle_care")
    reloaded = PushPolicy(cfg)

    assert reloaded.daily_count == 1
    assert reloaded.last_push_at is not None
    assert reloaded.can_push("idle_care") == (False, "interval")


def test_negative_feedback_persists_scene_cooldown_across_restart(tmp_path):
    from core.push_scheduler import PushPolicy

    cfg = _policy_config(tmp_path / "feedback-state.json")

    policy = PushPolicy(cfg)
    snapshot = policy.record_feedback("idle_care", "negative", hours=3)

    assert snapshot["scene"] == "idle_care"
    assert snapshot["action"] == "negative"
    assert snapshot["negative_count"] == 1
    assert policy.can_push("idle_care") == (False, "feedback_cooldown")

    reloaded = PushPolicy(cfg)

    assert reloaded.feedback["idle_care"]["negative"] == 1
    assert reloaded.can_push("idle_care") == (False, "feedback_cooldown")


def test_mute_postpone_and_enabled_settings_persist(tmp_path):
    from core.push_scheduler import PushPolicy

    enabled_cfg = _policy_config(tmp_path / "enabled-state.json")
    enabled_policy = PushPolicy(enabled_cfg)

    enabled_policy.set_enabled(False)
    assert PushPolicy(enabled_cfg).can_push("idle_care") == (
        False,
        "globally_disabled",
    )

    mute_cfg = _policy_config(tmp_path / "mute-state.json")
    mute_policy = PushPolicy(mute_cfg)
    mute_policy.mute(hours=2)
    assert PushPolicy(mute_cfg).can_push("weather_push") == (False, "muted")

    postpone_cfg = _policy_config(tmp_path / "postpone-state.json")
    postpone_policy = PushPolicy(postpone_cfg)
    postpone_policy.postpone("idle_care", hours=2)
    assert PushPolicy(postpone_cfg).can_push("idle_care") == (
        False,
        "postponed",
    )


def test_flag_off_legacy_pause_preserves_persistent_policy_state(tmp_path):
    from communication.qq_client import STATE_DISCONNECTED
    from core.companion import Companion
    from core.push_scheduler import PushPolicy, PushScheduler

    state_path = tmp_path / "rollback-state.json"
    cfg = _policy_config(state_path)
    cfg["scenes"] = {"idle_care": {"trigger": "idle"}}
    policy = PushPolicy(cfg)
    policy.record_feedback("idle_care", "negative", hours=3)

    scheduler = PushScheduler(cfg)
    companion = Companion.__new__(Companion)
    companion.settings = {"qq": {"push_pause_when_offline": True}}
    companion.feature_flags = SimpleNamespace(is_enabled=lambda _name: False)
    companion.push_scheduler = scheduler

    companion._on_qq_state_change(STATE_DISCONNECTED)

    assert scheduler.is_paused is True
    assert scheduler.paused_reason == "qq_offline"
    reloaded = PushPolicy(cfg)
    assert reloaded.feedback["idle_care"]["negative"] == 1
    assert reloaded.can_push("idle_care") == (False, "feedback_cooldown")


@pytest.mark.asyncio
async def test_proactive_policy_api_exposes_feedback_and_user_controls(
    monkeypatch,
    tmp_path,
):
    from core import api_server
    import core.companion as companion_module
    from core.push_scheduler import PushScheduler

    cfg = _policy_config(tmp_path / "api-state.json")
    cfg["scenes"] = {
        "idle_care": {"trigger": "idle"},
        "weather_push": {"cron": "0 7 * * *"},
    }
    scheduler = PushScheduler(cfg)
    companion = SimpleNamespace(push_scheduler=scheduler)
    monkeypatch.setattr(companion_module, "get_companion", lambda: companion)

    policy_status = await api_server.proactive_policy()
    assert policy_status["policy"]["enabled"] is True
    assert policy_status["policy"]["daily_count"] == 0

    feedback = await api_server.proactive_feedback(
        SimpleNamespace(
            json=AsyncMock(
                return_value={
                    "scene": "idle_care",
                    "action": "negative",
                    "hours": 1,
                }
            )
        )
    )
    assert feedback["scene"] == "idle_care"
    assert feedback["negative_count"] == 1
    assert scheduler.policy.can_push("idle_care") == (
        False,
        "feedback_cooldown",
    )

    muted = await api_server.proactive_mute(
        SimpleNamespace(json=AsyncMock(return_value={"hours": 1}))
    )
    assert muted["muted_until"]
    assert scheduler.policy.can_push("weather_push") == (False, "muted")

    scheduler.policy.clear_mute()
    postponed = await api_server.proactive_postpone(
        SimpleNamespace(
            json=AsyncMock(return_value={"scene": "weather_push", "hours": 1})
        )
    )
    assert postponed["scene"] == "weather_push"
    assert scheduler.policy.can_push("weather_push") == (False, "postponed")
