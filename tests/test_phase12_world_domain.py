"""Phase 12 deterministic world, relationship, and SelfModel contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from communication.message import IncomingMessage


def _world_config() -> dict:
    return {
        "seed": "phase12-seed",
        "phases": {
            "morning": {
                "start": "06:30",
                "end": "12:00",
                "location": "home",
                "activity": "planning",
                "energy": 0.72,
                "social": "private",
            },
            "night": {
                "start": "23:00",
                "end": "06:30",
                "location": "home",
                "activity": "sleeping",
                "energy": 0.20,
                "social": "private",
            },
        },
    }


def test_world_tick_same_seed_and_clock_produce_same_snapshot():
    from core.world_simulation import WorldSimulation

    clock = lambda: datetime(2026, 7, 21, 8, 15, tzinfo=timezone.utc)
    first = WorldSimulation(config=_world_config(), clock=clock)
    second = WorldSimulation(config=_world_config(), clock=clock)

    assert first.tick() == second.tick()
    snapshot = first.tick()
    assert snapshot["phase"] == "morning"
    assert snapshot["activity"] == "planning"
    assert snapshot["source"] == "simulated"
    assert snapshot["seed_sha256"]


def test_world_phase_supports_cross_midnight():
    from core.world_simulation import WorldSimulation

    world = WorldSimulation(
        config=_world_config(),
        clock=lambda: datetime(2026, 7, 21, 1, 0, tzinfo=timezone.utc),
    )

    assert world.tick()["phase"] == "night"


def test_action_registry_rejects_unknown_and_executes_wait_deterministically():
    from core.action_registry import ActionRegistry

    registry = ActionRegistry()
    parsed = registry.parse({"type": "teleport", "params": {"secret": "do not leak"}})
    fallback = registry.choose_safe_action(reason="unknown_action")
    result = registry.execute(fallback, world_snapshot={"activity": "planning"})

    assert parsed.action_type == "wait"
    assert parsed.reason == "unknown_action"
    assert fallback.action_type == "wait"
    assert result["status"] == "ok"
    assert result["action"] == "wait"
    assert "do not leak" not in str(result)


def test_relationship_is_persona_isolated_and_resettable():
    from core.relationship_engine import RelationshipEngine

    engine = RelationshipEngine()

    engine.observe_user_message(
        user_id=7,
        persona_id="ita",
        text="谢谢你，我很喜欢这样聊天",
    )
    engine.observe_user_message(
        user_id=7,
        persona_id="mira",
        text="烦死了，别这样",
    )

    ita = engine.get_state(user_id=7, persona_id="ita")
    mira = engine.get_state(user_id=7, persona_id="mira")
    assert ita["agent_to_user"]["trust"] > mira["agent_to_user"]["trust"]
    assert mira["conflict"] > ita["conflict"]

    reset = engine.reset(user_id=7, persona_id="ita")
    still_mira = engine.get_state(user_id=7, persona_id="mira")
    assert reset["agent_to_user"]["trust"] == engine.defaults["trust"]
    assert still_mira == mira


def test_self_model_snapshot_is_deterministic_and_redacted():
    from core.self_model import SelfModel

    model = SelfModel(seed="self-seed")
    world = {"phase": "morning", "energy": 0.72, "activity": "planning"}
    relationship = {"security": 0.66, "conflict": 0.02}

    first = model.snapshot(world_snapshot=world, relationship_snapshot=relationship)
    second = model.snapshot(world_snapshot=world, relationship_snapshot=relationship)

    assert first == second
    assert first["source"] == "computed"
    assert 0 <= first["focus"] <= 1
    assert "secret" not in str(first).lower()


def test_context_builder_contains_world_relationship_and_self_model_only_in_full(monkeypatch):
    from core.context_builder import ContextBuilder

    builder = ContextBuilder()
    monkeypatch.setattr(
        builder._persona_mgr,
        "get_active",
        lambda: {
            "basic": {"name": "伊塔"},
            "personality": {},
            "relationship": {},
            "emotion": {},
            "behavior": {},
        },
    )

    full = builder.build(
        user_id=1,
        current_msg="在做什么",
        route_mode="FULL",
        world_snapshot={
            "phase": "morning",
            "location": "home",
            "activity": "planning",
            "energy": 0.72,
            "social": "private",
            "source": "simulated",
        },
        relationship_snapshot={
            "security": 0.68,
            "conflict": 0.08,
            "agent_to_user": {"attachment": 0.72, "trust": 0.81, "care": 0.76},
            "user_to_agent": {"warmth": 0.64, "engagement": 0.58, "trust": 0.61},
            "user_emotion": {"label": "neutral"},
        },
        self_model_snapshot={
            "source": "computed",
            "focus": 0.77,
            "social_need": 0.31,
            "energy": 0.72,
        },
    )
    basic = builder.build(
        user_id=1,
        current_msg="在做什么",
        route_mode="BASIC",
        world_snapshot={"phase": "morning"},
        relationship_snapshot={"security": 0.68},
        self_model_snapshot={"focus": 0.77},
    )

    system = full[0]["content"]
    assert "【世界状态·模拟】" in system
    assert "planning" in system
    assert "不得把模拟内容声称为现实世界已验证事实" in system
    assert "【双向关系状态】" in system
    assert "安全感：0.68" in system
    assert "【SelfModel·计算状态】" in system
    assert "专注：0.77" in system
    assert "【世界状态·模拟】" not in basic[0]["content"]


@pytest.mark.asyncio
async def test_pipeline_passes_optional_world_context_snapshots():
    from core.pipeline import Pipeline

    ctx_builder = MagicMock()
    ctx_builder.build.return_value = [{"role": "system", "content": "system"}]
    ctx_builder.get_last_context_audit.return_value = {"enabled": False}
    brain = SimpleNamespace(
        chat=AsyncMock(
            return_value=SimpleNamespace(
                text="好的",
                react_trace=None,
                tool_results=[],
                model="fake",
                usage={},
            )
        )
    )
    db = SimpleNamespace(
        query=MagicMock(return_value=[]),
        query_one=MagicMock(return_value=None),
        insert=MagicMock(return_value=1),
    )
    pipeline = Pipeline(
        router=SimpleNamespace(route=lambda _user_id: "FULL"),
        emotion_engine=SimpleNamespace(
            update_trajectory_async=AsyncMock(),
            get_state=MagicMock(return_value={"label": "neutral", "pad": {}}),
            tune=lambda text, actor_id=None: text,
        ),
        context_builder=ctx_builder,
        brain=brain,
        send_queue=SimpleNamespace(enqueue=AsyncMock()),
        tool_registry=SimpleNamespace(get_openai_schema=MagicMock(return_value=[])),
        db=db,
        cognition=SimpleNamespace(
            begin=MagicMock(return_value={"id": 1}),
            record=MagicMock(),
            record_decision=MagicMock(),
            record_react=MagicMock(),
            commit=MagicMock(),
        ),
        settings={},
    )
    pipeline.world_snapshot_provider = lambda: {"phase": "morning"}
    pipeline.relationship_snapshot_provider = lambda user_id: {"security": 0.68, "user_id": user_id}
    pipeline.self_model_snapshot_provider = lambda world, relationship: {
        "focus": 0.77,
        "phase": world["phase"],
        "security": relationship["security"],
    }

    await pipeline.handle(
        IncomingMessage(user_id=7, content="你好", source="desktop"),
        force_full=True,
    )

    kwargs = ctx_builder.build.call_args.kwargs
    assert kwargs["world_snapshot"] == {"phase": "morning"}
    assert kwargs["relationship_snapshot"]["user_id"] == 7
    assert kwargs["self_model_snapshot"]["focus"] == 0.77
