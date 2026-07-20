import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from communication.message import (
    CancellationToken,
    CancellationTooLate,
    IncomingMessage,
)
from core.chat_request_repository import RequestContext, RequestIdentity
from core.pipeline import Pipeline


class _BoundaryToken(CancellationToken):
    def __init__(self, boundary: str) -> None:
        super().__init__()
        self.boundary = boundary
        self.seen: list[str] = []

    def throw_if_cancelled(
        self,
        *,
        boundary: str | None = None,
        terminal_side_effect_committed: bool = False,
        completed: bool = False,
    ) -> None:
        if boundary:
            self.seen.append(boundary)
        if boundary == self.boundary:
            self.cancel()
        super().throw_if_cancelled(
            boundary=boundary,
            terminal_side_effect_committed=terminal_side_effect_committed,
            completed=completed,
        )


class _RecordingDb:
    def __init__(self) -> None:
        self.rows: list[tuple[str, dict]] = []
        self.next_id = 100

    def query(self, *_args, **_kwargs):
        return []

    def query_one(self, *_args, **_kwargs):
        return None

    def insert(self, table: str, data: dict) -> int:
        self.next_id += 1
        self.rows.append((table, dict(data)))
        return self.next_id


class _Cognition:
    def begin(self, *_args, **_kwargs):
        return {"id": 1, "stages": {}}

    def record(self, *_args, **_kwargs):
        return None

    def record_decision(self, *_args, **_kwargs):
        return None

    def record_react(self, *_args, **_kwargs):
        return None

    def commit(self, trace, *_args, **_kwargs):
        trace["id"] = 1

    def append_pacing_decisions(self, *_args, **_kwargs):
        return None


class _Validator:
    async def validate(self, *_args, **_kwargs):
        return SimpleNamespace(issues=[])


class _Brain:
    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    async def chat(self, messages, **_kwargs):
        self.calls.append(messages)
        return SimpleNamespace(
            text="助手回复",
            model="phase4-model",
            usage={},
            react_trace=None,
            tool_results=[],
        )


class _ConversationRepository:
    def __init__(self) -> None:
        self.enabled = True
        self.persisted: list[dict] = []

    def recent_turn_history(self, **_kwargs):
        return []

    def persist_turn(self, **kwargs):
        self.persisted.append(dict(kwargs))
        return {
            "request_id": kwargs["request_id"],
            "conversation_id": kwargs["conversation_id"],
            "turn_id": kwargs["turn_id"],
            "response_group_id": "group_phase4_pipeline",
        }


@pytest.fixture
def request_context():
    return RequestContext(
        request_id="req_phase4_pipeline",
        conversation_id="conv_phase4_pipeline",
        turn_id="turn_phase4_pipeline",
        identity=RequestIdentity(
            actor_id="actor_phase4",
            channel="desktop",
            channel_account_id="local",
            user_id=7,
        ),
        input_content="用户可见文本",
        effective_content="内部模型文本",
        attachments=[
            {
                "name": "phase4.txt",
                "url": "/uploads/phase4.txt",
                "state": "ready",
                "size": 12,
                "type": "text/plain",
            }
        ],
    )


@pytest.fixture
def pipeline_factory(monkeypatch):
    def build(route_mode: str = "FULL"):
        router = MagicMock()
        router.route.return_value = route_mode
        emotion = MagicMock()
        emotion.update_trajectory = MagicMock()
        emotion.update_trajectory_async = MagicMock(
            side_effect=lambda *_args, **_kwargs: asyncio.sleep(0)
        )
        emotion.get_state.return_value = {
            "label": "neutral",
            "pad": {},
            "thresholds": {},
            "eruption": None,
        }
        emotion.tune.side_effect = lambda text, **_kwargs: text
        ctx_builder = MagicMock()

        def build_context(_user_id, current_msg, _route_mode, **kwargs):
            return [
                {"role": "system", "content": "system"},
                {
                    "role": "user",
                    "content": current_msg,
                    "attachments": kwargs.get("attachments"),
                },
            ]

        ctx_builder.build.side_effect = build_context
        brain = _Brain()
        send_queue = MagicMock()
        tool_registry = MagicMock()
        tool_registry.get_openai_schema.return_value = []
        db = _RecordingDb()
        conversation_repository = _ConversationRepository()
        pipeline = Pipeline(
            router=router,
            emotion_engine=emotion,
            context_builder=ctx_builder,
            brain=brain,
            send_queue=send_queue,
            tool_registry=tool_registry,
            db=db,
            cognition=_Cognition(),
            conversation_repository=conversation_repository,
        )
        pipeline.validator = _Validator()
        pipeline._splitter.split = MagicMock(return_value=["助手一", "助手二"])
        events: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            "core.pipeline.emit",
            lambda event_type, **payload: events.append((event_type, payload)),
        )
        return SimpleNamespace(
            pipeline=pipeline,
            ctx_builder=ctx_builder,
            brain=brain,
            send_queue=send_queue,
            db=db,
            conversation_repository=conversation_repository,
            events=events,
        )

    return build


@pytest.mark.asyncio
@pytest.mark.parametrize("route_mode", ["FULL", "BASIC"])
async def test_pipeline_uses_effective_content_for_model_but_visible_content_for_persistence(
    pipeline_factory,
    request_context,
    route_mode,
):
    deps = pipeline_factory(route_mode)
    msg = IncomingMessage.from_local(
        request_context.input_content,
        request_context.identity.user_id,
        attachments=request_context.attachments,
    )

    await deps.pipeline.handle(
        msg,
        request_context=request_context,
    )

    assert deps.ctx_builder.build.call_args.args[1] == "内部模型文本"
    chat_rows = [row for table, row in deps.db.rows if table == "chat_log"]
    assert chat_rows[0]["role"] == "user"
    assert chat_rows[0]["content"] == "用户可见文本"
    assert chat_rows[0]["attachments"]
    assert deps.conversation_repository.persisted[0]["user_content"] == "用户可见文本"
    assert deps.events[0][1]["content"] == "用户可见文本"
    assert deps.ctx_builder.build.call_args.kwargs["attachments"]


@pytest.mark.asyncio
async def test_pipeline_uses_existing_request_turn_and_conversation_for_canonical_mirror(
    pipeline_factory,
    request_context,
):
    deps = pipeline_factory("FULL")

    result = await deps.pipeline.handle(request_context=request_context)

    persisted = deps.conversation_repository.persisted[0]
    assert persisted["request_id"] == request_context.request_id
    assert persisted["conversation_id"] == request_context.conversation_id
    assert persisted["turn_id"] == request_context.turn_id
    assert result["canonical_completed"] is True
    assert result["request_id"] == request_context.request_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "boundary",
    [
        "before_model",
        "after_model",
        "before_legacy_user",
        "before_legacy_assistant",
        "before_canonical",
        "before_event",
        "before_qq_enqueue",
    ],
)
async def test_pipeline_cancellation_stops_before_named_side_effect(
    pipeline_factory,
    request_context,
    boundary,
):
    deps = pipeline_factory("FULL")
    token = _BoundaryToken(boundary)
    qq_context = RequestContext(
        request_id=request_context.request_id,
        conversation_id=request_context.conversation_id,
        turn_id=request_context.turn_id,
        identity=RequestIdentity(
            actor_id="actor_phase4",
            channel="qq",
            channel_account_id="3998874040",
            user_id=3998874040,
        ),
        input_content=request_context.input_content,
        effective_content=request_context.effective_content,
        attachments=request_context.attachments,
    )

    if boundary in {
        "before_model",
        "after_model",
        "before_legacy_user",
    }:
        with pytest.raises(asyncio.CancelledError):
            await deps.pipeline.handle(
                request_context=qq_context,
                cancellation_token=token,
            )
    elif boundary in {"before_legacy_assistant", "before_canonical"}:
        with pytest.raises(CancellationTooLate) as exc_info:
            await deps.pipeline.handle(
                request_context=qq_context,
                cancellation_token=token,
            )
        assert exc_info.value.reason == "terminal_side_effect_committed"
    else:
        result = await deps.pipeline.handle(
            request_context=qq_context,
            cancellation_token=token,
        )
        assert result["canonical_completed"] is True

    chat_rows = [row for table, row in deps.db.rows if table == "chat_log"]
    if boundary in {"before_model", "after_model", "before_legacy_user"}:
        assert chat_rows == []
    if boundary == "before_legacy_assistant":
        assert [row["role"] for row in chat_rows] == ["user"]
    if boundary == "before_canonical":
        assert [row["role"] for row in chat_rows] == [
            "user",
            "assistant",
            "assistant",
        ]
        assert deps.conversation_repository.persisted == []
    if boundary == "before_event":
        assert deps.conversation_repository.persisted
        assert deps.events == []
    if boundary == "before_qq_enqueue":
        assert deps.events
        deps.send_queue.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_irreversible_terminal_side_effect_prevents_fake_cancelled(
    pipeline_factory,
    request_context,
):
    deps = pipeline_factory("FULL")

    with pytest.raises(CancellationTooLate) as exc_info:
        await deps.pipeline.handle(
            request_context=request_context,
            cancellation_token=_BoundaryToken("before_legacy_assistant"),
        )

    assert exc_info.value.reason == "terminal_side_effect_committed"
    assert [row["role"] for table, row in deps.db.rows if table == "chat_log"] == [
        "user",
    ]
    assert deps.conversation_repository.persisted == []
    assert deps.events == []


@pytest.mark.asyncio
async def test_request_events_include_complete_envelope_ids_and_monotonic_sequence(
    pipeline_factory,
    request_context,
):
    deps = pipeline_factory("FULL")

    await deps.pipeline.handle(request_context=request_context)

    sequences = [payload["sequence"] for _event, payload in deps.events]
    assert sequences == sorted(sequences)
    assert sequences == list(range(1, len(sequences) + 1))
    for _event, payload in deps.events:
        assert payload["event_id"].startswith("event_")
        assert payload["request_id"] == request_context.request_id
        assert payload["conversation_id"] == request_context.conversation_id
        assert payload["turn_id"] == request_context.turn_id
        assert payload["message_id"]
    assistant_payloads = [
        payload for event, payload in deps.events if event == "assistant"
    ]
    assert {
        payload["response_group_id"] for payload in assistant_payloads
    } == {"group_phase4_pipeline"}


@pytest.mark.asyncio
async def test_document_markdown_is_reextracted_from_trusted_upload_url(
    pipeline_factory,
    request_context,
    monkeypatch,
):
    deps = pipeline_factory("FULL")
    calls: list[str] = []

    def extract_markdown(path, **_kwargs):
        calls.append(str(path).replace("\\", "/"))
        return "trusted markdown"

    monkeypatch.setattr("core.pipeline.extract_markdown", extract_markdown)
    unsafe_context = RequestContext(
        request_id=request_context.request_id,
        conversation_id=request_context.conversation_id,
        turn_id=request_context.turn_id,
        identity=request_context.identity,
        input_content=request_context.input_content,
        effective_content=request_context.effective_content,
        attachments=[
            {
                "name": "phase4.txt",
                "url": "/uploads/phase4.txt",
                "state": "ready",
                "size": 12,
                "type": "text/plain",
                "markdown": "client supplied markdown",
                "content": "client supplied content",
                "path": "C:/secret.txt",
            }
        ],
    )

    await deps.pipeline.handle(request_context=unsafe_context)

    attachments = deps.ctx_builder.build.call_args.kwargs["attachments"]
    assert calls and calls[0].endswith("/uploads/phase4.txt")
    assert attachments[0]["markdown"] == "trusted markdown"
    assert "content" not in attachments[0]
    assert "path" not in attachments[0]
