from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from communication.message import IncomingMessage
from core.context_builder import ContextBuilder
from core.pipeline import Pipeline


class _MemoryDouble:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def retrieve(
        self,
        user_id: int,
        query: str = "",
        limit: int = 5,
        *,
        actor_id: str | None = None,
    ) -> list[dict]:
        self.calls.append(
            {
                "user_id": user_id,
                "query": query,
                "limit": limit,
                "actor_id": actor_id,
            }
        )
        return [
            {
                "id": 1,
                "memory_type": "preference",
                "content": "用户喜欢猫和无糖拿铁",
                "importance": 9,
            }
        ]


class _KnowledgeDouble:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def search(self, query: str, limit: int = 5) -> list[dict]:
        self.calls.append({"query": query, "limit": limit})
        return [
            {
                "id": 7,
                "category": "world",
                "title": "猫护理",
                "content": "猫需要稳定饮水和固定作息。",
                "tags": "cat",
            }
        ]


def test_context_budget_injects_actor_scoped_memory_and_knowledge_without_audit_leakage():
    memory = _MemoryDouble()
    knowledge = _KnowledgeDouble()
    builder = ContextBuilder(memory=memory, knowledge=knowledge)

    messages = builder.build(
        3998874040,
        "猫今天不喝水怎么办",
        "FULL",
        actor_id="actor_primary",
        channel="desktop",
        channel_account_id="local",
        context_budget_enabled=True,
    )

    system = messages[0]["content"]
    assert "长期记忆" in system
    assert "用户喜欢猫和无糖拿铁" in system
    assert "知识库" in system
    assert "猫护理" in system
    assert memory.calls == [
        {
            "user_id": 3998874040,
            "query": "猫今天不喝水怎么办",
            "limit": 3,
            "actor_id": "actor_primary",
        }
    ]
    assert knowledge.calls == [{"query": "猫今天不喝水怎么办", "limit": 3}]

    audit = builder.get_last_context_audit()
    assert audit["enabled"] is True
    assert audit["memory_hits"] == 1
    assert audit["knowledge_hits"] == 1
    assert audit["actor_id"] == "actor_primary"
    assert "用户喜欢猫和无糖拿铁" not in str(audit)
    assert "猫需要稳定饮水" not in str(audit)


def test_context_budget_merges_multi_bubble_assistant_history_into_complete_turns():
    builder = ContextBuilder()
    history = [
        {"role": "user", "content": "讲讲猫"},
        {
            "role": "assistant",
            "content": "第一段",
            "turn_id": "turn_1",
            "response_group_id": "group_1",
            "sequence": 1,
        },
        {
            "role": "assistant",
            "content": "第二段",
            "turn_id": "turn_1",
            "response_group_id": "group_1",
            "sequence": 2,
        },
    ]

    messages = builder.build(
        3998874040,
        "继续",
        "FULL",
        history_msgs=history,
        context_budget_enabled=True,
    )

    assistant_messages = [
        msg for msg in messages if msg["role"] == "assistant"
    ]
    assert len(assistant_messages) == 1
    assert assistant_messages[0]["content"] == "第一段\n第二段"
    assert builder.get_last_context_audit()["merged_history_messages"] == 1


class _Cognition:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict]] = []

    def begin(self, *_args, **_kwargs) -> dict:
        return {"id": "trace_phase6", "stages": {}}

    def record(self, _trace: dict, stage: str, payload) -> None:
        self.records.append((stage, payload))

    def record_decision(self, *_args, **_kwargs) -> None:
        pass

    def record_react(self, *_args, **_kwargs) -> None:
        pass

    def commit(self, *_args, **_kwargs) -> None:
        pass


def _pipeline(monkeypatch, *, flag_enabled: bool):
    import core.pipeline as pipeline_module

    monkeypatch.setattr(
        pipeline_module,
        "FeatureFlags",
        lambda: SimpleNamespace(
            is_enabled=lambda name: flag_enabled
            if name == "context_budget_v1"
            else False
        ),
        raising=False,
    )

    router = MagicMock()
    router.route.return_value = "FULL"
    emotion = MagicMock()
    emotion.update_trajectory_async = AsyncMock()
    emotion.get_state.return_value = {
        "label": "neutral",
        "pad": {},
        "thresholds": {},
        "eruption": None,
    }
    emotion.tune.side_effect = lambda text, **_kwargs: text

    ctx_builder = MagicMock()
    ctx_builder.build.return_value = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "hello"},
    ]
    ctx_builder.get_last_context_audit.return_value = {
        "enabled": True,
        "estimated_tokens": 12,
        "memory_hits": 1,
        "knowledge_hits": 1,
        "history_messages": 2,
    }

    brain = MagicMock()
    brain.chat = AsyncMock(
        return_value=MagicMock(
            text="嗯。",
            model="test",
            usage={"prompt_tokens": 1, "completion_tokens": 1},
            react_trace=None,
            tool_results=[],
        )
    )
    db = MagicMock()
    db.query.return_value = []
    db.query_one.return_value = None
    db.insert.return_value = 1
    tool_registry = MagicMock()
    tool_registry.get_openai_schema.return_value = []
    cognition = _Cognition()

    identity_resolver = MagicMock()

    def resolve_message(msg):
        msg.actor_id = "actor_primary"
        return msg

    identity_resolver.resolve_message.side_effect = resolve_message

    pipeline = Pipeline(
        router=router,
        emotion_engine=emotion,
        context_builder=ctx_builder,
        brain=brain,
        send_queue=MagicMock(),
        tool_registry=tool_registry,
        db=db,
        cognition=cognition,
        identity_resolver=identity_resolver,
    )
    pipeline.validator = MagicMock()
    pipeline.validator.validate = AsyncMock(
        return_value=SimpleNamespace(issues=[])
    )
    return pipeline, ctx_builder, cognition


@pytest.mark.asyncio
async def test_pipeline_passes_context_budget_identity_and_records_sanitized_audit(
    monkeypatch,
):
    pipeline, ctx_builder, cognition = _pipeline(
        monkeypatch,
        flag_enabled=True,
    )

    await pipeline.handle(
        IncomingMessage.from_local("hello", 3998874040),
        force_full=True,
    )

    kwargs = ctx_builder.build.call_args.kwargs
    assert kwargs["context_budget_enabled"] is True
    assert kwargs["actor_id"] == "actor_primary"
    assert kwargs["channel"] == "desktop"
    assert kwargs["channel_account_id"] == "local"

    context_payloads = [
        payload for stage, payload in cognition.records if stage == "context"
    ]
    assert context_payloads
    assert context_payloads[0]["context_budget"]["estimated_tokens"] == 12
    assert context_payloads[0]["context_budget"]["memory_hits"] == 1
    assert "hello" not in str(context_payloads[0]["context_budget"])


@pytest.mark.asyncio
async def test_pipeline_context_budget_flag_off_keeps_legacy_builder_kwargs(
    monkeypatch,
):
    pipeline, ctx_builder, _cognition = _pipeline(
        monkeypatch,
        flag_enabled=False,
    )

    await pipeline.handle(
        IncomingMessage.from_local("hello", 3998874040),
        force_full=True,
    )

    kwargs = ctx_builder.build.call_args.kwargs
    assert "context_budget_enabled" not in kwargs
    assert "actor_id" not in kwargs
    assert ctx_builder.get_last_context_audit.call_count == 0
