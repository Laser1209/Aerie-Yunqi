import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest


class _PassiveQQ:
    order: list[str] | None = None

    def __init__(self, _cfg):
        self.is_connected = False

    def set_whitelist(self, *_args):
        return None

    def set_message_handler(self, *_args):
        return None

    def on_state_change(self, *_args):
        return None

    async def connect(self):
        return None

    async def wait_until_ready(self, *, timeout):
        del timeout
        if _PassiveQQ.order is not None:
            _PassiveQQ.order.append("qq_wait")
        return False

    async def stop(self):
        return None


class _PassiveQueue:
    def __init__(self, **_kwargs):
        self.started = False

    def start(self):
        self.started = True

    async def stop(self):
        self.started = False


class _PassiveScheduler:
    def __init__(self, *_args, **_kwargs):
        self.is_paused = False
        self.paused_reason = None
        self.judge = None

    def set_dispatcher(self, *_args):
        return None

    async def start(self):
        return None

    def pause(self, reason):
        self.is_paused = True
        self.paused_reason = reason

    def resume(self):
        self.is_paused = False
        self.paused_reason = None


class _PassiveEventEngine:
    def bind_scheduler(self, *_args):
        return None

    async def start(self):
        return None

    async def stop(self):
        return None


class _PassiveAsyncTaskManager:
    def __init__(self, *_args, **_kwargs):
        self.registered = {}

    def register_task_func(self, name, func):
        self.registered[name] = func

    def start(self):
        return None


class _PassiveDesire:
    def __init__(self, *_args, **_kwargs):
        pass

    async def start(self):
        return None

    async def stop(self):
        return None


class _PassiveSkillRouter:
    def __init__(self, *_args, **_kwargs):
        pass


class _PassiveSkillLoader:
    def __init__(self, *_args, **_kwargs):
        pass

    def discover(self):
        return 0

    def register_all(self):
        return 0


def _feature_env(
    monkeypatch,
    *,
    queue: bool,
    migration: bool = True,
    conversation: bool = True,
) -> None:
    monkeypatch.setenv("AERIE_FEATURE_CHAT_REQUEST_QUEUE_V1", str(queue).lower())
    monkeypatch.setenv("AERIE_FEATURE_MIGRATION_FRAMEWORK_V1", str(migration).lower())
    monkeypatch.setenv("AERIE_FEATURE_CONVERSATION_MODEL_V1", str(conversation).lower())
    monkeypatch.setenv("AERIE_FEATURE_IDENTITY_CONTRACT_V1", "true")


def _patch_companion(monkeypatch, *, order: list[str] | None = None):
    import sys
    import core.async_task_manager as async_task_manager
    from core import companion as companion_module

    _PassiveQQ.order = order
    monkeypatch.setattr(companion_module, "_COMPANION", None)
    monkeypatch.setattr(companion_module, "QQClient", _PassiveQQ)
    monkeypatch.setattr(companion_module, "SendQueue", _PassiveQueue)
    monkeypatch.setattr(companion_module, "PushScheduler", _PassiveScheduler)
    monkeypatch.setattr(
        companion_module,
        "get_event_engine",
        lambda: _PassiveEventEngine(),
    )
    monkeypatch.setattr(companion_module, "register_all_tools", lambda _registry: None)
    monkeypatch.setattr(
        companion_module.Companion,
        "_warmup_threshold_from_history",
        lambda _self: None,
    )
    monkeypatch.setattr(
        companion_module.Companion,
        "_register_async_task_handlers",
        lambda _self: None,
    )
    monkeypatch.setattr(
        async_task_manager,
        "AsyncTaskManager",
        _PassiveAsyncTaskManager,
    )
    monkeypatch.setitem(
        sys.modules,
        "core.desire_engine",
        SimpleNamespace(DesireEngine=_PassiveDesire),
    )
    monkeypatch.setitem(
        sys.modules,
        "core.skill_router",
        SimpleNamespace(SkillRouter=_PassiveSkillRouter),
    )
    monkeypatch.setitem(
        sys.modules,
        "core.skill_loader",
        SimpleNamespace(SkillLoader=_PassiveSkillLoader),
    )
    return companion_module


def _insert_actor(db, actor_id: str) -> None:
    with db.connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO actors (actor_id) VALUES (?)",
            (actor_id,),
        )


def test_companion_injects_one_repository_instance_into_service_worker_and_pipeline(
    monkeypatch,
    phase4_db,
):
    _feature_env(monkeypatch, queue=True)
    companion_module = _patch_companion(monkeypatch)

    companion = companion_module.Companion(
        {
            "qq": {"self_qq": 0, "friends_qq": [], "startup_wait_timeout": 0},
            "agent": {"task_planner_enabled": False},
        },
        database=phase4_db,
    )

    assert companion.chat_request_queue_requested is True
    assert companion.chat_request_queue_ready is True
    assert companion.chat_request_repository is companion.chat_request_service.repository
    assert companion.chat_request_repository is companion.chat_request_worker.repository
    assert companion.chat_request_service.worker is companion.chat_request_worker
    assert companion.chat_request_worker.pipeline is companion.pipeline
    assert companion.pipeline.conversation_repository is companion.conversation_repository


@pytest.mark.parametrize(
    ("migration", "conversation"),
    [(False, True), (True, False)],
)
def test_queue_flag_requires_migration_and_conversation_flags_fail_closed(
    monkeypatch,
    tmp_path,
    migration,
    conversation,
):
    from core.database import Database

    _feature_env(
        monkeypatch,
        queue=True,
        migration=migration,
        conversation=conversation,
    )
    companion_module = _patch_companion(monkeypatch)
    Database.reset_instance()
    try:
        database = Database(tmp_path / "queue-deps.db")
        companion = companion_module.Companion(
            {
                "qq": {"self_qq": 0, "friends_qq": []},
                "agent": {"task_planner_enabled": False},
            },
            database=database,
        )
    finally:
        Database.reset_instance()

    assert companion.chat_request_queue_requested is True
    assert companion.chat_request_queue_ready is False
    assert companion.chat_request_queue_error == "queue_dependencies_unavailable"
    assert companion.chat_request_worker is None
    assert companion.chat_request_service is None


@pytest.mark.asyncio
async def test_worker_starts_before_qq_wait_until_ready(
    monkeypatch,
    phase4_db,
):
    order: list[str] = []
    _feature_env(monkeypatch, queue=True)
    companion_module = _patch_companion(monkeypatch, order=order)

    class Worker:
        def __init__(self, **kwargs):
            self.repository = kwargs["repository"]
            self.pipeline = kwargs["pipeline"]

        async def start(self):
            order.append("worker_start")

        async def stop(self):
            order.append("worker_stop")

    monkeypatch.setattr(companion_module, "ChatRequestWorker", Worker)
    companion = companion_module.Companion(
        {
            "qq": {"self_qq": 0, "friends_qq": [], "startup_wait_timeout": 0},
            "agent": {"task_planner_enabled": False},
        },
        database=phase4_db,
    )

    await companion.start()
    await companion.stop()

    assert order.index("worker_start") < order.index("qq_wait")


def test_reply_to_requires_owned_message_in_same_actor_channel_conversation(
    phase4_db,
    frozen_utc_clock,
    ready_attachment,
):
    from core.chat_request_repository import ChatRequestRepository
    from core.chat_request_service import ChatRequestService
    from core.conversation_repository import ConversationRepository
    from core.identity.models import ChannelIdentity

    class IdentityRepository:
        def resolve(self, channel, channel_account_id):
            return ChannelIdentity("actor_reply", channel, channel_account_id)

    _insert_actor(phase4_db, "actor_reply")
    repository = ChatRequestRepository(
        phase4_db,
        clock=frozen_utc_clock.now,
    )
    service = ChatRequestService(
        repository=repository,
        identity_repository=IdentityRepository(),
        master_user_id_provider=lambda: 7001,
        id_factory=MagicMock(side_effect=["req_reply", "turn_reply"]),
    )
    conversation_repository = ConversationRepository(phase4_db, enabled=True)
    seed = service.submit(
        text="seed",
        attachments=[],
        reply_to_id=0,
        user_id=7001,
    )
    claimed = repository.claim_next(lease_owner="worker", lease_seconds=30)
    assert claimed is not None
    conversation_repository.persist_turn(
        request_id=seed.request_id,
        user_id=7001,
        actor_id="actor_reply",
        channel="desktop",
        channel_account_id="local",
        user_content="seed",
        user_attachments=[],
        assistant_segments=["reply"],
        conversation_id=seed.conversation_id,
        turn_id=seed.turn_id,
    )
    reply_to_id = phase4_db.query_one(
        """SELECT legacy_chat_log_id
           FROM messages
           WHERE turn_id = ? AND role = 'user'""",
        (seed.turn_id,),
    )["legacy_chat_log_id"]

    service.id_factory = MagicMock(side_effect=["req_reply_2", "turn_reply_2"])
    submitted = service.submit(
        text="follow up",
        attachments=[ready_attachment],
        reply_to_id=reply_to_id,
        user_id=7001,
    )

    assert submitted.status == "queued"


def test_reply_to_missing_or_foreign_is_indistinguishable(
    phase4_db,
    frozen_utc_clock,
):
    from core.chat_request_repository import ChatRequestRepository
    from core.chat_request_service import ChatRequestService, RequestNotFound
    from core.identity.models import ChannelIdentity

    class IdentityRepository:
        def __init__(self, actor_id):
            self.actor_id = actor_id

        def resolve(self, channel, channel_account_id):
            return ChannelIdentity(self.actor_id, channel, channel_account_id)

    _insert_actor(phase4_db, "actor_owner")
    _insert_actor(phase4_db, "actor_foreign")
    repository = ChatRequestRepository(
        phase4_db,
        clock=frozen_utc_clock.now,
    )
    service = ChatRequestService(
        repository=repository,
        identity_repository=IdentityRepository("actor_owner"),
        master_user_id_provider=lambda: 7001,
        id_factory=MagicMock(side_effect=["req_owner", "turn_owner"]),
    )
    service.submit(text="owner", attachments=[], reply_to_id=0, user_id=7001)
    with phase4_db.connection() as conn:
        conn.execute(
            """INSERT INTO conversations
               (conversation_id, actor_id, channel, channel_account_id)
               VALUES (?, ?, 'desktop', 'local')""",
            ("conv_foreign", "actor_foreign"),
        )
        conn.execute(
            """INSERT INTO turns (turn_id, conversation_id, status)
               VALUES (?, ?, 'completed')""",
            ("turn_foreign", "conv_foreign"),
        )
        conn.execute(
            """INSERT INTO messages
               (message_id, conversation_id, turn_id, role, content,
                sequence, channel, channel_account_id, actor_id,
                legacy_chat_log_id)
               VALUES (?, ?, ?, 'user', 'foreign', 0, 'desktop',
                       'local', 'actor_foreign', ?)""",
            (
                "msg_foreign",
                "conv_foreign",
                "turn_foreign",
                99001,
            ),
        )

    missing_error = foreign_error = None
    for reply_to_id in (123456, 99001):
        try:
            service.submit(
                text="follow",
                attachments=[],
                reply_to_id=reply_to_id,
                user_id=7001,
            )
        except RequestNotFound as exc:
            if reply_to_id == 123456:
                missing_error = exc.error_code
            else:
                foreign_error = exc.error_code

    assert missing_error == foreign_error == "request_not_found"


@pytest.mark.asyncio
async def test_flag_off_worker_does_not_consume_existing_queued_rows(
    monkeypatch,
    phase4_db,
    frozen_utc_clock,
):
    from core.chat_request_repository import ChatRequestRepository, RequestContext, RequestIdentity

    repository = ChatRequestRepository(
        phase4_db,
        clock=frozen_utc_clock.now,
    )
    _insert_actor(phase4_db, "actor_flag_off")
    context = RequestContext(
        request_id="req_flag_off_queued",
        conversation_id="conv_flag_off",
        turn_id="turn_flag_off",
        identity=RequestIdentity(
            actor_id="actor_flag_off",
            channel="desktop",
            channel_account_id="local",
            user_id=7001,
        ),
        input_content="queued",
        effective_content="queued",
    )
    repository.submit(context=context)
    _feature_env(monkeypatch, queue=False)
    companion_module = _patch_companion(monkeypatch)
    companion = companion_module.Companion(
        {
            "qq": {"self_qq": 0, "friends_qq": [], "startup_wait_timeout": 0},
            "agent": {"task_planner_enabled": False},
        },
        database=phase4_db,
    )

    await companion.start()
    await companion.stop()

    row = phase4_db.query_one(
        "SELECT status FROM requests WHERE request_id = ?",
        (context.request_id,),
    )
    assert companion.chat_request_worker is None
    assert row["status"] == "queued"


class _E2EIdFactory:
    def __init__(self, label: str = "e2e") -> None:
        self.label = label
        self._counts: dict[str, int] = {}

    def __call__(self, prefix: str) -> str:
        self._counts[prefix] = self._counts.get(prefix, 0) + 1
        return f"{prefix}_{self.label}_{self._counts[prefix]}"


class _E2EIdentityRepository:
    def __init__(self, actor_id: str) -> None:
        self.actor_id = actor_id

    def resolve(self, channel, channel_account_id):
        from core.identity.models import ChannelIdentity

        return ChannelIdentity(self.actor_id, channel, channel_account_id)


class _E2EEmotion:
    async def update_trajectory_async(self, *_args, **_kwargs):
        return None

    def update_trajectory(self, *_args, **_kwargs):
        return None

    def get_state(self, *_args, **_kwargs):
        return {
            "label": "neutral",
            "pad": {},
            "thresholds": {},
            "eruption": None,
        }

    def tune(self, text, **_kwargs):
        return text


class _E2EContextBuilder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def build(self, user_id, current_msg, route_mode, **kwargs):
        self.calls.append(
            {
                "user_id": user_id,
                "current_msg": current_msg,
                "route_mode": route_mode,
                **kwargs,
            }
        )
        return [
            {"role": "system", "content": "phase4 e2e system"},
            {"role": "user", "content": current_msg},
        ]


class _E2EBrain:
    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    async def chat(self, messages, **_kwargs):
        self.calls.append(messages)
        return SimpleNamespace(
            text="助手第一段\n助手第二段",
            model="phase4-e2e-model",
            usage={},
            react_trace=None,
            tool_results=[],
        )


class _E2ECognition:
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


class _E2EValidator:
    async def validate(self, *_args, **_kwargs):
        return SimpleNamespace(
            issues=[],
            passed=True,
            guard_passed=True,
            judge_score=1.0,
            rewrite_count=0,
        )


class _E2ESendQueue:
    def __init__(self) -> None:
        self.enqueued = []

    def enqueue(self, reply):
        self.enqueued.append(reply)


class _EnvelopeEmitter:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.events: list[tuple[str, dict]] = []

    def __call__(self, event_type, **payload):
        if self.fail:
            raise RuntimeError("event transport unavailable")
        from core.event_contracts import EventEnvelope

        envelope = EventEnvelope.create(event_type, **dict(payload)).to_dict()
        self.events.append((event_type, envelope))


class _PipelineRecorder:
    def __init__(self, delegate, *, gated: bool = False) -> None:
        self.delegate = delegate
        self.gated = gated
        self.started: list[str] = []
        self.active = 0
        self.max_active = 0
        self.active_by_conversation: dict[str, int] = {}
        self.max_same_conversation_active = 0
        self.releases: dict[str, asyncio.Event] = {}
        self.first_four_started = asyncio.Event()
        self.fifth_started = asyncio.Event()

    async def handle(self, *args, request_context, **kwargs):
        request_id = request_context.request_id
        conversation_id = request_context.conversation_id
        self.started.append(request_id)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.active_by_conversation[conversation_id] = (
            self.active_by_conversation.get(conversation_id, 0) + 1
        )
        self.max_same_conversation_active = max(
            self.max_same_conversation_active,
            self.active_by_conversation[conversation_id],
        )
        if len(self.started) == 4:
            self.first_four_started.set()
        if len(self.started) == 5:
            self.fifth_started.set()
        try:
            if self.gated:
                release = self.releases.setdefault(request_id, asyncio.Event())
                await release.wait()
            return await self.delegate.handle(
                *args,
                request_context=request_context,
                **kwargs,
            )
        finally:
            self.active -= 1
            self.active_by_conversation[conversation_id] -= 1

    def release(self, request_id: str) -> None:
        self.releases.setdefault(request_id, asyncio.Event()).set()

    def release_all(self) -> None:
        for release in self.releases.values():
            release.set()


def _make_e2e_harness(
    monkeypatch,
    phase4_db,
    frozen_utc_clock,
    *,
    label: str,
    max_concurrency: int = 4,
    gated_pipeline: bool = False,
    failing_events: bool = False,
):
    from core import api_server
    from core.chat_request_repository import ChatRequestRepository
    from core.chat_request_service import ChatRequestService
    from core.chat_request_worker import ChatRequestWorker
    from core.conversation_repository import ConversationRepository
    from core.pipeline import Pipeline

    actor_id = f"actor_{label}"
    _insert_actor(phase4_db, actor_id)
    repository = ChatRequestRepository(phase4_db, clock=frozen_utc_clock.now)
    identity_repository = _E2EIdentityRepository(actor_id)
    context_builder = _E2EContextBuilder()
    brain = _E2EBrain()
    send_queue = _E2ESendQueue()
    tool_registry = MagicMock()
    tool_registry.get_openai_schema.return_value = []
    real_pipeline = Pipeline(
        router=SimpleNamespace(route=MagicMock(return_value="FULL")),
        emotion_engine=_E2EEmotion(),
        context_builder=context_builder,
        brain=brain,
        send_queue=send_queue,
        tool_registry=tool_registry,
        db=phase4_db,
        cognition=_E2ECognition(),
        conversation_repository=ConversationRepository(phase4_db, enabled=True),
        settings={"agent": {"task_planner_enabled": False}},
    )
    real_pipeline.validator = _E2EValidator()
    real_pipeline._splitter.split = MagicMock(return_value=["助手第一段", "助手第二段"])
    pipeline = _PipelineRecorder(real_pipeline, gated=gated_pipeline)
    emitter = _EnvelopeEmitter(fail=failing_events)
    monkeypatch.setattr("core.pipeline.emit", emitter)
    worker = ChatRequestWorker(
        repository=repository,
        pipeline=pipeline,
        emit=emitter,
        clock=frozen_utc_clock.now,
        max_concurrency=max_concurrency,
        lease_seconds=30,
        heartbeat_seconds=0.01,
        worker_id=f"worker-{label}",
    )
    service = ChatRequestService(
        repository=repository,
        identity_repository=identity_repository,
        worker=worker,
        master_user_id_provider=lambda: 7001,
        id_factory=_E2EIdFactory(label),
    )
    companion = SimpleNamespace(
        feature_flags=SimpleNamespace(
            is_enabled=lambda name: name == "chat_request_queue_v1"
        ),
        chat_request_queue_requested=True,
        chat_request_queue_ready=True,
        chat_request_queue_error=None,
        chat_request_service=service,
        pipeline=pipeline,
    )
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api_server.app),
        base_url="http://testserver",
    )
    return SimpleNamespace(
        actor_id=actor_id,
        repository=repository,
        service=service,
        worker=worker,
        pipeline=pipeline,
        real_pipeline=real_pipeline,
        context_builder=context_builder,
        brain=brain,
        send_queue=send_queue,
        emitter=emitter,
        client=client,
    )


async def _close_harness(harness):
    await harness.worker.stop()
    await harness.client.aclose()


async def _wait_for_request_status(phase4_db, request_id: str, status: str):
    for _ in range(400):
        row = phase4_db.query_one(
            "SELECT status FROM requests WHERE request_id = ?",
            (request_id,),
        )
        if row and row["status"] == status:
            return row
        await asyncio.sleep(0.005)
    raise AssertionError(f"{request_id} did not reach {status}")


async def _wait_for_started(pipeline: _PipelineRecorder, count: int):
    for _ in range(400):
        if len(pipeline.started) >= count:
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"pipeline started {len(pipeline.started)} < {count}")


def _messages_for_turn(phase4_db, turn_id: str) -> list[dict]:
    return phase4_db.query(
        """SELECT role, content, sequence, legacy_chat_log_id
           FROM messages
           WHERE turn_id = ?
           ORDER BY sequence ASC""",
        (turn_id,),
    )


def _event_types_for_request(harness, request_id: str) -> list[str]:
    return [
        event_type
        for event_type, payload in harness.emitter.events
        if payload.get("request_id") == request_id
    ]


def _event_sequences_for_request(harness, request_id: str) -> list[int]:
    return [
        payload["sequence"]
        for _event_type, payload in harness.emitter.events
        if payload.get("request_id") == request_id
    ]


@pytest.mark.asyncio
async def test_submit_claim_pipeline_complete_status_and_events_end_to_end(
    monkeypatch,
    phase4_db,
    frozen_utc_clock,
):
    harness = _make_e2e_harness(
        monkeypatch,
        phase4_db,
        frozen_utc_clock,
        label="task11_e2e",
    )
    await harness.worker.start()
    try:
        response = await harness.client.post(
            "/api/chat/send",
            json={"text": "端到端请求", "user_id": 7001},
        )
        assert response.status_code == 202
        queued = response.json()
        assert queued["status"] == "queued"
        assert "reply" not in queued

        await _wait_for_request_status(
            phase4_db,
            queued["request_id"],
            "completed",
        )
        status = await harness.client.get(
            f"/api/chat/requests/{queued['request_id']}"
        )
        assert status.status_code == 200
        view = status.json()
        assert view["status"] == "completed"
        assert view["can_cancel"] is False
        assert view["can_retry"] is False
        assert isinstance(view["user_message_id"], int)
        assert len(view["assistant_message_ids"]) == 2

        assert len(harness.brain.calls) == 1
        messages = _messages_for_turn(phase4_db, queued["turn_id"])
        assert [message["role"] for message in messages] == [
            "user",
            "assistant",
            "assistant",
        ]
        assert len({message["legacy_chat_log_id"] for message in messages}) == 3

        event_types = _event_types_for_request(harness, queued["request_id"])
        assert event_types.count("chat_request_running") == 1
        assert event_types.count("chat_request_completed") == 1
        assert event_types.count("user") == 1
        assert event_types.count("assistant") == 2
        sequences = _event_sequences_for_request(harness, queued["request_id"])
        assert sequences == sorted(sequences)
        assert len(sequences) == len(set(sequences))
        assert harness.send_queue.enqueued == []
    finally:
        await _close_harness(harness)


@pytest.mark.asyncio
async def test_mobile_queue_shares_owner_desktop_history_and_isolates_guest(
    monkeypatch,
    phase4_db,
    frozen_utc_clock,
    tmp_path,
):
    from core import api_server
    from core.mobile_chat import MobileChatService
    from core.mobile_gateway import create_mobile_app
    from core.mobile_identity import MobileIdentityStore

    monkeypatch.setenv("AERIE_DISABLE_QQ", "true")
    harness = _make_e2e_harness(
        monkeypatch,
        phase4_db,
        frozen_utc_clock,
        label="mobile_shared_timeline",
    )
    monkeypatch.setattr(api_server, "_db", phase4_db)

    guest_actor_id = "actor_mobile_guest"
    _insert_actor(phase4_db, guest_actor_id)
    identity_store = MobileIdentityStore(
        tmp_path / "mobile-shared-timeline.db",
        pepper="test-only-pepper-with-at-least-32-bytes",
    )
    identity_store.create_account(
        username="owner",
        password="correct-horse-battery-staple",
        role="owner",
        actor_id=harness.actor_id,
        user_id=7001,
    )
    identity_store.create_account(
        username="guest-one",
        password="correct-horse-battery-staple",
        role="guest",
        actor_id=guest_actor_id,
        user_id=8001,
    )
    mobile_app = create_mobile_app(
        identity_store=identity_store,
        chat_service=MobileChatService(phase4_db, identity_store),
    )
    mobile_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mobile_app),
        base_url="http://mobile.test",
    )

    async def login(username: str) -> dict[str, str]:
        response = await mobile_client.post(
            "/api/mobile/v1/auth/login",
            json={
                "username": username,
                "password": "correct-horse-battery-staple",
                "deviceName": f"{username}-device",
                "pairingCode": identity_store.create_pairing_code(username),
            },
        )
        assert response.status_code == 200
        return {"Authorization": f"Bearer {response.json()['accessToken']}"}

    await harness.worker.start()
    try:
        owner_headers = await login("owner")
        owner_response = await mobile_client.post(
            "/api/mobile/v1/requests",
            headers=owner_headers,
            json={
                "clientRequestId": "00000000-0000-4000-8000-000000000701",
                "text": "owner mobile request",
                "fileIds": [],
            },
        )
        assert owner_response.status_code == 202
        owner_request = owner_response.json()
        await _wait_for_request_status(
            phase4_db,
            owner_request["requestId"],
            "completed",
        )

        owner_status = await mobile_client.get(
            f"/api/mobile/v1/requests/{owner_request['requestId']}",
            headers=owner_headers,
        )
        assert owner_status.status_code == 200
        assert owner_status.json()["status"] == "completed"

        owner_messages = await mobile_client.get(
            "/api/mobile/v1/messages?limit=100",
            headers=owner_headers,
        )
        assert owner_messages.status_code == 200
        assert [item["content"] for item in owner_messages.json()["items"]] == [
            "owner mobile request",
            "助手第一段",
            "助手第二段",
        ]

        desktop_history = await harness.client.get(
            "/api/chat/history?user_id=7001&limit=100",
        )
        assert desktop_history.status_code == 200
        assert [item["content"] for item in desktop_history.json()["history"]] == [
            "owner mobile request",
            "助手第一段",
            "助手第二段",
        ]

        guest_headers = await login("guest-one")
        guest_response = await mobile_client.post(
            "/api/mobile/v1/requests",
            headers=guest_headers,
            json={
                "clientRequestId": "00000000-0000-4000-8000-000000000801",
                "text": "guest isolated request",
                "fileIds": [],
            },
        )
        assert guest_response.status_code == 202
        guest_request = guest_response.json()
        await _wait_for_request_status(
            phase4_db,
            guest_request["requestId"],
            "completed",
        )

        owner_after_guest = await mobile_client.get(
            "/api/mobile/v1/messages?limit=100",
            headers=owner_headers,
        )
        guest_messages = await mobile_client.get(
            "/api/mobile/v1/messages?limit=100",
            headers=guest_headers,
        )
        owner_contents = [
            item["content"] for item in owner_after_guest.json()["items"]
        ]
        guest_contents = [item["content"] for item in guest_messages.json()["items"]]
        assert "guest isolated request" not in owner_contents
        assert "owner mobile request" not in guest_contents
        assert guest_contents == [
            "guest isolated request",
            "助手第一段",
            "助手第二段",
        ]

        owner_desktop_after_guest = await harness.client.get(
            "/api/chat/history?user_id=7001&limit=100",
        )
        assert "guest isolated request" not in {
            item["content"] for item in owner_desktop_after_guest.json()["history"]
        }
        assert len(harness.brain.calls) == 2
        assert harness.send_queue.enqueued == []
    finally:
        await mobile_client.aclose()
        await _close_harness(harness)


@pytest.mark.asyncio
async def test_three_same_conversation_requests_complete_in_order(
    monkeypatch,
    phase4_db,
    frozen_utc_clock,
):
    harness = _make_e2e_harness(
        monkeypatch,
        phase4_db,
        frozen_utc_clock,
        label="task11_serial",
        max_concurrency=4,
    )
    await harness.worker.start()
    try:
        responses = [
            await harness.client.post(
                "/api/chat/send",
                json={"text": f"同会话 {index}", "user_id": 7001},
            )
            for index in range(3)
        ]
        queued = [response.json() for response in responses]
        assert [response.status_code for response in responses] == [202, 202, 202]
        assert len({item["conversation_id"] for item in queued}) == 1

        for item in queued:
            await _wait_for_request_status(phase4_db, item["request_id"], "completed")

        assert harness.pipeline.started == [item["request_id"] for item in queued]
        assert harness.pipeline.max_same_conversation_active == 1
        assert len(harness.brain.calls) == 3
    finally:
        await _close_harness(harness)


@pytest.mark.asyncio
async def test_four_conversations_run_and_fifth_waits_end_to_end(
    monkeypatch,
    phase4_db,
    frozen_utc_clock,
):
    harness = _make_e2e_harness(
        monkeypatch,
        phase4_db,
        frozen_utc_clock,
        label="task11_parallel",
        max_concurrency=4,
        gated_pipeline=True,
    )
    await harness.worker.start()
    try:
        responses = [
            await harness.client.post(
                "/api/chat/send",
                json={"text": f"跨会话 {index}", "user_id": 7100 + index},
            )
            for index in range(5)
        ]
        queued = [response.json() for response in responses]
        assert [response.status_code for response in responses] == [202] * 5
        assert len({item["conversation_id"] for item in queued}) == 5

        await asyncio.wait_for(harness.pipeline.first_four_started.wait(), timeout=2)
        assert harness.pipeline.max_active == 4
        assert harness.pipeline.fifth_started.is_set() is False

        harness.pipeline.release(harness.pipeline.started[0])
        await asyncio.wait_for(harness.pipeline.fifth_started.wait(), timeout=2)
        harness.pipeline.release_all()
        for item in queued:
            await _wait_for_request_status(phase4_db, item["request_id"], "completed")

        assert harness.pipeline.max_active == 4
        assert len(harness.brain.calls) == 5
    finally:
        harness.pipeline.release_all()
        await _close_harness(harness)


@pytest.mark.asyncio
async def test_queued_and_running_cancel_have_no_duplicate_model_message_event_or_qq(
    monkeypatch,
    phase4_db,
    frozen_utc_clock,
):
    harness = _make_e2e_harness(
        monkeypatch,
        phase4_db,
        frozen_utc_clock,
        label="task11_cancel",
        max_concurrency=4,
        gated_pipeline=True,
    )
    await harness.worker.start()
    try:
        running_response = await harness.client.post(
            "/api/chat/send",
            json={"text": "运行中取消", "user_id": 7001},
        )
        queued_response = await harness.client.post(
            "/api/chat/send",
            json={"text": "排队中取消", "user_id": 7001},
        )
        running = running_response.json()
        queued = queued_response.json()
        await _wait_for_started(harness.pipeline, 1)
        assert harness.pipeline.started == [running["request_id"]]

        queued_cancel = await harness.client.post(
            f"/api/chat/requests/{queued['request_id']}/cancel"
        )
        running_cancel = await harness.client.post(
            f"/api/chat/requests/{running['request_id']}/cancel"
        )

        assert queued_cancel.status_code == 200
        assert running_cancel.status_code == 200
        await _wait_for_request_status(
            phase4_db,
            running["request_id"],
            "cancelled",
        )
        assert phase4_db.query_one(
            "SELECT status FROM requests WHERE request_id = ?",
            (queued["request_id"],),
        )["status"] == "cancelled"
        assert harness.brain.calls == []
        assert phase4_db.query("SELECT * FROM messages") == []
        assert phase4_db.query("SELECT * FROM chat_log") == []
        assert "chat_request_completed" not in (
            _event_types_for_request(harness, running["request_id"])
            + _event_types_for_request(harness, queued["request_id"])
        )
        assert harness.send_queue.enqueued == []
    finally:
        harness.pipeline.release_all()
        await _close_harness(harness)


@pytest.mark.asyncio
async def test_retry_creates_one_new_model_execution_and_preserves_original_terminal(
    monkeypatch,
    phase4_db,
    frozen_utc_clock,
):
    harness = _make_e2e_harness(
        monkeypatch,
        phase4_db,
        frozen_utc_clock,
        label="task11_retry",
        max_concurrency=1,
        gated_pipeline=True,
    )
    await harness.worker.start()
    try:
        original_response = await harness.client.post(
            "/api/chat/send",
            json={"text": "稍后重试", "user_id": 7001},
        )
        original = original_response.json()
        await _wait_for_started(harness.pipeline, 1)
        cancel = await harness.client.post(
            f"/api/chat/requests/{original['request_id']}/cancel"
        )
        assert cancel.status_code == 200
        await _wait_for_request_status(
            phase4_db,
            original["request_id"],
            "cancelled",
        )
        original_terminal = phase4_db.query_one(
            """SELECT status, cancelled_at, completed_at
               FROM requests WHERE request_id = ?""",
            (original["request_id"],),
        )

        retry = await harness.client.post(
            f"/api/chat/requests/{original['request_id']}/retry"
        )
        assert retry.status_code == 202
        retried = retry.json()
        assert retried["request_id"] != original["request_id"]
        assert retried["retry_of_request_id"] == original["request_id"]

        await _wait_for_started(harness.pipeline, 2)
        harness.pipeline.release(retried["request_id"])
        await _wait_for_request_status(
            phase4_db,
            retried["request_id"],
            "completed",
        )

        assert len(harness.brain.calls) == 1
        assert phase4_db.query_one(
            """SELECT status, cancelled_at, completed_at
               FROM requests WHERE request_id = ?""",
            (original["request_id"],),
        ) == original_terminal
        assert [row["role"] for row in _messages_for_turn(phase4_db, retried["turn_id"])] == [
            "user",
            "assistant",
            "assistant",
        ]
    finally:
        harness.pipeline.release_all()
        await _close_harness(harness)


@pytest.mark.asyncio
async def test_restart_recovery_marks_interrupted_failed_and_keeps_queued_claimable(
    monkeypatch,
    phase4_db,
    frozen_utc_clock,
):
    harness = _make_e2e_harness(
        monkeypatch,
        phase4_db,
        frozen_utc_clock,
        label="task11_recovery",
        max_concurrency=1,
    )
    actor_id = harness.actor_id
    from core.chat_request_repository import RequestContext, RequestIdentity

    identity = RequestIdentity(
        actor_id=actor_id,
        channel="desktop",
        channel_account_id="local",
        user_id=7001,
    )
    interrupted = RequestContext(
        request_id="req_task11_interrupted",
        conversation_id="conv_task11_recovery",
        turn_id="turn_task11_interrupted",
        identity=identity,
        input_content="interrupted",
        effective_content="interrupted",
    )
    queued = RequestContext(
        request_id="req_task11_after_recovery",
        conversation_id="conv_task11_recovery",
        turn_id="turn_task11_after_recovery",
        identity=identity,
        input_content="after recovery",
        effective_content="after recovery",
    )
    harness.repository.submit(context=interrupted)
    frozen_utc_clock.advance(1)
    harness.repository.submit(context=queued)
    assert harness.repository.claim_next(
        lease_owner="dead-worker",
        lease_seconds=30,
    )

    await harness.worker.start()
    try:
        await _wait_for_request_status(phase4_db, queued.request_id, "completed")
        assert phase4_db.query_one(
            "SELECT status, error_code FROM requests WHERE request_id = ?",
            (interrupted.request_id,),
        ) == {"status": "failed", "error_code": "process_interrupted"}
        assert harness.pipeline.started == [queued.request_id]
        assert len(harness.brain.calls) == 1
    finally:
        await _close_harness(harness)


@pytest.mark.asyncio
async def test_event_transport_failure_recovers_via_get_status(
    monkeypatch,
    phase4_db,
    frozen_utc_clock,
):
    harness = _make_e2e_harness(
        monkeypatch,
        phase4_db,
        frozen_utc_clock,
        label="task11_transport_failure",
        failing_events=True,
    )
    await harness.worker.start()
    try:
        response = await harness.client.post(
            "/api/chat/send",
            json={"text": "事件传输失败也要能查状态", "user_id": 7001},
        )
        queued = response.json()
        assert response.status_code == 202
        await _wait_for_request_status(
            phase4_db,
            queued["request_id"],
            "completed",
        )

        status = await harness.client.get(
            f"/api/chat/requests/{queued['request_id']}"
        )

        assert status.status_code == 200
        view = status.json()
        assert view["status"] == "completed"
        assert isinstance(view["user_message_id"], int)
        assert len(view["assistant_message_ids"]) == 2
        assert harness.emitter.events == []
    finally:
        await _close_harness(harness)


@pytest.mark.asyncio
async def test_flag_off_preserves_old_sync_contract_and_does_not_consume_queue(
    monkeypatch,
    phase4_db,
    frozen_utc_clock,
):
    from core import api_server
    from core.chat_request_repository import ChatRequestRepository, RequestContext, RequestIdentity

    actor_id = "actor_task11_flag_off"
    _insert_actor(phase4_db, actor_id)
    repository = ChatRequestRepository(phase4_db, clock=frozen_utc_clock.now)
    queued_context = RequestContext(
        request_id="req_task11_flag_off_existing",
        conversation_id="conv_task11_flag_off",
        turn_id="turn_task11_flag_off_existing",
        identity=RequestIdentity(
            actor_id=actor_id,
            channel="desktop",
            channel_account_id="local",
            user_id=7001,
        ),
        input_content="queued",
        effective_content="queued",
    )
    repository.submit(context=queued_context)
    companion = SimpleNamespace(
        feature_flags=SimpleNamespace(is_enabled=lambda _name: False),
        chat_request_queue_requested=False,
        chat_request_queue_ready=False,
        chat_request_service=None,
        pipeline=SimpleNamespace(
            handle=AsyncMock(
                return_value={
                    "reply": "同步回复",
                    "user_msg_id": 11,
                    "ai_msg_id": 12,
                    "persisted": True,
                }
            )
        ),
    )
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api_server.app),
        base_url="http://testserver",
    )
    try:
        response = await client.post(
            "/api/chat/send",
            json={"text": "同步旧合同", "user_id": 7001},
        )
        empty = await client.post("/api/chat/send", json={"text": "   "})

        assert response.status_code == 200
        assert response.json() == {
            "reply": "同步回复",
            "user_msg_id": 11,
            "ai_msg_id": 12,
            "reply_to_id": 0,
            "status": "ok",
            "persisted": True,
        }
        assert empty.status_code == 400
        companion.pipeline.handle.assert_awaited_once()
        assert phase4_db.query_one(
            "SELECT status FROM requests WHERE request_id = ?",
            (queued_context.request_id,),
        )["status"] == "queued"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_task12_flag_rollback_matrix_reenables_queue_without_data_loss(
    monkeypatch,
    phase4_db,
    frozen_utc_clock,
):
    from core import api_server
    from core.chat_request_repository import ChatRequestRepository, RequestContext, RequestIdentity

    queue_on = _make_e2e_harness(
        monkeypatch,
        phase4_db,
        frozen_utc_clock,
        label="task12_flag_on",
    )
    await queue_on.worker.start()
    try:
        first = await queue_on.client.post(
            "/api/chat/send",
            json={"text": "queue on completes", "user_id": 7001},
        )
        assert first.status_code == 202
        await _wait_for_request_status(
            phase4_db,
            first.json()["request_id"],
            "completed",
        )
    finally:
        await _close_harness(queue_on)

    actor_id = "actor_task12_flag_existing"
    _insert_actor(phase4_db, actor_id)
    existing_context = RequestContext(
        request_id="req_task12_survives_flag_off",
        conversation_id="conv_task12_survives_flag_off",
        turn_id="turn_task12_survives_flag_off",
        identity=RequestIdentity(
            actor_id=actor_id,
            channel="desktop",
            channel_account_id="local",
            user_id=7001,
        ),
        input_content="survives flag off",
        effective_content="survives flag off",
    )
    repository = ChatRequestRepository(phase4_db, clock=frozen_utc_clock.now)
    repository.submit(context=existing_context)

    flag_off_companion = SimpleNamespace(
        feature_flags=SimpleNamespace(is_enabled=lambda _name: False),
        chat_request_queue_requested=False,
        chat_request_queue_ready=False,
        chat_request_service=None,
        pipeline=SimpleNamespace(
            handle=AsyncMock(
                return_value={
                    "reply": "旧同步回复",
                    "user_msg_id": 21,
                    "ai_msg_id": 22,
                    "persisted": True,
                }
            )
        ),
    )
    monkeypatch.setattr(api_server, "get_companion", lambda: flag_off_companion)
    flag_off_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api_server.app),
        base_url="http://testserver",
    )
    try:
        legacy = await flag_off_client.post(
            "/api/chat/send",
            json={"text": "legacy while flag off", "user_id": 7001},
        )
        assert legacy.status_code == 200
        assert legacy.json()["status"] == "ok"
        assert phase4_db.query_one(
            "SELECT status FROM requests WHERE request_id = ?",
            (existing_context.request_id,),
        )["status"] == "queued"

        missing_dependency_companion = SimpleNamespace(
            feature_flags=SimpleNamespace(
                is_enabled=lambda name: name == "chat_request_queue_v1"
            ),
            chat_request_queue_requested=True,
            chat_request_queue_ready=False,
            chat_request_queue_error="queue_dependencies_unavailable",
            chat_request_service=None,
            pipeline=SimpleNamespace(handle=AsyncMock()),
        )
        monkeypatch.setattr(
            api_server,
            "get_companion",
            lambda: missing_dependency_companion,
        )
        unavailable = await flag_off_client.post(
            "/api/chat/send",
            json={"text": "must fail closed", "user_id": 7001},
        )
        assert unavailable.status_code == 503
        assert unavailable.json() == {"error": "queue_dependencies_unavailable"}
        assert missing_dependency_companion.pipeline.handle.await_count == 0
        assert phase4_db.query_one(
            "SELECT status FROM requests WHERE request_id = ?",
            (existing_context.request_id,),
        )["status"] == "queued"
    finally:
        await flag_off_client.aclose()

    reenabled = _make_e2e_harness(
        monkeypatch,
        phase4_db,
        frozen_utc_clock,
        label="task12_reenabled",
    )
    await reenabled.worker.start()
    try:
        await _wait_for_request_status(
            phase4_db,
            existing_context.request_id,
            "completed",
        )
        assert any(
            call[-1]["content"] == "survives flag off"
            for call in reenabled.brain.calls
        )
    finally:
        await _close_harness(reenabled)
