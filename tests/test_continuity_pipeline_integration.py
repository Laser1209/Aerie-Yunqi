import asyncio
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


class RecordingAttachmentService:
    def __init__(self, *, snippet_error=False):
        self.snippet_error = snippet_error
        self.bound = []
        self.resolve_calls = []

    def resolve_ready_for_send(self, attachment_ids):
        self.resolve_calls.append(list(attachment_ids))
        return [
            {
                "id": attachment_id,
                "attachmentId": attachment_id,
                "name": "sentinel.txt",
                "size": 18,
                "category": "text",
                "type": "text",
                "state": "ready",
                "contentType": "text/plain",
                "sha256": "a" * 64,
                "downloadUrl": f"/api/attachments/{attachment_id}/download",
                "metadata": {},
            }
            for attachment_id in attachment_ids
        ]

    def context_snippets(self, attachment_ids, *, max_chars, query=None):
        if self.snippet_error:
            raise RuntimeError("parser unavailable")
        return ["[sentinel.txt] ATTACHMENT_SENTINEL"][:max_chars]

    def bind_message(self, attachment_ids, *, message_id, conversation_id):
        self.bound.append((list(attachment_ids), message_id, conversation_id))


class RecordingAssembler:
    def __init__(self):
        self.calls = []

    def assemble(self, **kwargs):
        from core.conversation_continuity import ContextAssembly

        self.calls.append(kwargs)
        supplemental = "\n".join(
            [*kwargs["memories"], *kwargs["attachment_snippets"]]
        )
        messages = [
            {
                "role": "system",
                "content": kwargs["system_prompt"] + "\n" + supplemental,
            },
            {"role": "user", "content": kwargs["current_user_content"]},
        ]
        return ContextAssembly(
            messages=messages,
            audit={"bounded": True, "total_chars": 200},
        )


class BlockingSummaryPlanner:
    def __init__(self):
        self.complete_started = Event()
        self.release = Event()
        self.saved = None

    def prepare(self, conversation_id):
        return {
            "conversation_id": conversation_id,
            "messages": [{"role": "user", "content": "EARLY_SENTINEL"}],
        }

    def complete(self, job, summarizer):
        self.complete_started.set()
        self.release.wait(timeout=2)
        self.saved = summarizer("", job["messages"])


def _pipeline(*, attachment_service, assembler, summary_planner):
    from core.pipeline import Pipeline

    router = MagicMock()
    router.route.return_value = "FULL"

    emotion = MagicMock()
    emotion.update_trajectory_async = AsyncMock()
    emotion.get_state.return_value = {
        "label": "neutral",
        "pad": {"P": 0.0, "A": 0.0, "D": 0.0},
        "thresholds": {},
        "eruption": None,
    }
    emotion.tune.side_effect = lambda text, **kwargs: text

    context_builder = MagicMock()
    context_builder.build.return_value = [
        {"role": "system", "content": "PERSONA_SYSTEM_PROMPT"},
        {"role": "user", "content": "question"},
    ]

    brain = MagicMock()
    brain.chat = AsyncMock(return_value=SimpleNamespace(
        text="answer",
        model="test-model",
        react_trace=None,
        tool_results=[],
        usage={},
    ))

    tool_registry = MagicMock()
    tool_registry.get_openai_schema.return_value = []

    next_id = iter(range(101, 1000))
    database = MagicMock()
    database.insert.side_effect = lambda *args, **kwargs: next(next_id)
    database.query.return_value = []

    def query_one(sql, params=()):
        if "SELECT message_id FROM messages" in sql:
            return {"message_id": "msg_canonical_user"}
        return None

    database.query_one.side_effect = query_one

    conversations = MagicMock()
    conversations.enabled = True
    conversations.recent_turn_history.return_value = []
    conversations.persist_turn.return_value = {
        "conversation_id": "conv_desktop",
        "turn_id": "turn_desktop",
        "request_id": "req_desktop",
        "response_group_id": "group_desktop",
    }

    memory = MagicMock()
    memory.retrieve.return_value = [{"content": "MEMORY_SENTINEL"}]

    pipeline = Pipeline(
        router=router,
        emotion_engine=emotion,
        context_builder=context_builder,
        brain=brain,
        send_queue=MagicMock(),
        tool_registry=tool_registry,
        db=database,
        cognition=MagicMock(begin=MagicMock(return_value={"id": 1})),
        conversation_repository=conversations,
        context_assembler=assembler,
        summary_planner=summary_planner,
        attachment_service=attachment_service,
        memory_store=memory,
    )
    pipeline.validator.validate = AsyncMock(return_value=SimpleNamespace(
        issues=[],
        passed=True,
        guard_passed=True,
        judge_score=1.0,
        rewrite_count=0,
    ))
    return pipeline, brain, conversations


@pytest.mark.asyncio
async def test_pipeline_uses_bounded_continuity_binds_then_summarizes_nonblocking():
    from core.chat_request_repository import RequestContext, RequestIdentity

    attachments = RecordingAttachmentService()
    assembler = RecordingAssembler()
    planner = BlockingSummaryPlanner()
    pipeline, brain, conversations = _pipeline(
        attachment_service=attachments,
        assembler=assembler,
        summary_planner=planner,
    )
    context = RequestContext(
        request_id="req_desktop",
        conversation_id="conv_desktop",
        turn_id="turn_desktop",
        identity=RequestIdentity(
            actor_id="actor_desktop",
            channel="desktop",
            channel_account_id="local",
            user_id=7,
        ),
        input_content="question",
        effective_content="question",
        attachments=[{"attachmentId": "att_ready", "state": "ready"}],
    )

    result = await pipeline.handle(request_context=context)

    assert result["canonical_completed"] is True
    assert attachments.bound == [
        (["att_ready"], "msg_canonical_user", "conv_desktop")
    ]
    assert conversations.persist_turn.called
    assembly = assembler.calls[0]
    assert assembly["conversation_id"] == "conv_desktop"
    assert assembly["memories"] == ["MEMORY_SENTINEL"]
    assert assembly["attachment_snippets"] == [
        "[sentinel.txt] ATTACHMENT_SENTINEL"
    ]
    model_messages = brain.chat.await_args.args[0]
    assert "MEMORY_SENTINEL" in model_messages[0]["content"]
    assert "ATTACHMENT_SENTINEL" in model_messages[0]["content"]

    for _ in range(100):
        if planner.complete_started.is_set():
            break
        await asyncio.sleep(0.01)
    assert planner.complete_started.is_set()
    assert pipeline._summary_tasks
    planner.release.set()
    await pipeline.wait_for_background_tasks()
    assert "EARLY_SENTINEL" in planner.saved


def test_attachment_snippet_failure_falls_back_to_metadata_without_breaking_send():
    attachments = RecordingAttachmentService(snippet_error=True)
    pipeline, _, _ = _pipeline(
        attachment_service=attachments,
        assembler=RecordingAssembler(),
        summary_planner=None,
    )

    context_items, ids, snippets, persisted = pipeline._prepare_attachments(
        [{"attachmentId": "att_ready", "state": "ready"}],
        request_context=None,
    )

    assert ids == ["att_ready"]
    assert snippets == []
    assert context_items[0]["state"] == "ready"
    assert persisted[0]["attachmentId"] == "att_ready"


def test_default_rolling_summary_keeps_early_sentinel_across_200_turns():
    from core.pipeline import Pipeline

    summary = ""
    for batch in range(10):
        messages = []
        for turn in range(20):
            marker = "EARLY_SENTINEL" if batch == 0 and turn == 0 else ""
            messages.extend([
                {"role": "user", "content": f"question {batch}-{turn} {marker}"},
                {"role": "assistant", "content": f"answer {batch}-{turn}"},
            ])
        summary = Pipeline._default_rolling_summary(summary, messages)

    assert "EARLY_SENTINEL" in summary
    assert len(summary) <= 11_500
