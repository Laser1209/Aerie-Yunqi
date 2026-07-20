from __future__ import annotations

import asyncio

import pytest

from core.chat_request_repository import (
    ChatRequestRepository,
    RequestContext,
    RequestIdentity,
)


def test_frozen_utc_clock_advances_without_local_timezone(
    frozen_utc_clock,
):
    before = frozen_utc_clock.now()
    frozen_utc_clock.advance(30)
    after = frozen_utc_clock.now()

    assert before.tzinfo is not None
    assert after.tzinfo is not None
    assert (after - before).total_seconds() == 30
    assert after.utcoffset().total_seconds() == 0


def _repository(phase4_db, frozen_utc_clock):
    with phase4_db.connection() as connection:
        connection.execute(
            """INSERT OR IGNORE INTO actors (actor_id, created_at)
               VALUES (?, ?)""",
            ("actor_worker", frozen_utc_clock.now().isoformat()),
        )
    return ChatRequestRepository(
        phase4_db,
        clock=frozen_utc_clock.now,
    )


def _submit(
    repository,
    *,
    request_id,
    conversation_id,
):
    context = RequestContext(
        request_id=request_id,
        conversation_id=conversation_id,
        turn_id=f"turn_{request_id}",
        identity=RequestIdentity(
            actor_id="actor_worker",
            channel="desktop",
            channel_account_id="local",
            user_id=7,
        ),
        input_content="worker input",
        effective_content="worker input",
        attachments=[],
        reply_to_id=0,
    )
    repository.submit(context=context)
    return context


def _worker(
    *,
    repository,
    pipeline,
    frozen_utc_clock,
    emit=lambda *_args, **_kwargs: None,
    max_concurrency=1,
    lease_seconds=30,
    heartbeat_seconds=1,
    worker_id="worker-phase4",
):
    from core.chat_request_worker import ChatRequestWorker

    return ChatRequestWorker(
        repository=repository,
        pipeline=pipeline,
        emit=emit,
        clock=frozen_utc_clock.now,
        max_concurrency=max_concurrency,
        lease_seconds=lease_seconds,
        heartbeat_seconds=heartbeat_seconds,
        worker_id=worker_id,
    )


async def _wait_for_status(phase4_db, request_id, expected_status):
    for _ in range(2000):
        row = phase4_db.query_one(
            "SELECT status FROM requests WHERE request_id = ?",
            (request_id,),
        )
        if row and row["status"] == expected_status:
            return
        await asyncio.sleep(0)
    raise AssertionError(
        f"request {request_id} did not reach {expected_status}"
    )


class _RecordingEmitter:
    def __init__(self):
        self.events = []

    def __call__(self, event_type, **payload):
        self.events.append((event_type, payload))


def test_repository_mark_completed_requires_running_and_matching_lease(
    phase4_db,
    frozen_utc_clock,
):
    repository = _repository(phase4_db, frozen_utc_clock)
    context = _submit(
        repository,
        request_id="req_worker_complete",
        conversation_id="conv_worker_complete",
    )

    with pytest.raises(ValueError, match="claim-owned"):
        repository.mark_completed(
            request_id=context.request_id,
            lease_owner="worker-phase4",
            result={},
        )
    repository.claim_next(lease_owner="worker-phase4", lease_seconds=30)
    with pytest.raises(ValueError, match="claim-owned"):
        repository.mark_completed(
            request_id=context.request_id,
            lease_owner="worker-other",
            result={},
        )

    repository.mark_completed(
        request_id=context.request_id,
        lease_owner="worker-phase4",
        result={},
    )

    assert phase4_db.query_one(
        """SELECT r.status AS request_status, t.status AS turn_status,
                  r.lease_owner, r.lease_expires_at
           FROM requests r JOIN turns t ON t.turn_id = r.turn_id
           WHERE r.request_id = ?""",
        (context.request_id,),
    ) == {
        "request_status": "completed",
        "turn_status": "completed",
        "lease_owner": None,
        "lease_expires_at": None,
    }


def test_repository_mark_cancelled_requires_cancelling_and_sets_timestamp(
    phase4_db,
    frozen_utc_clock,
):
    repository = _repository(phase4_db, frozen_utc_clock)
    context = _submit(
        repository,
        request_id="req_worker_cancel_contract",
        conversation_id="conv_worker_cancel_contract",
    )
    repository.claim_next(lease_owner="worker-phase4", lease_seconds=30)

    with pytest.raises(ValueError, match="claim-owned"):
        repository.mark_cancelled(
            request_id=context.request_id,
            lease_owner="worker-phase4",
        )
    assert repository.request_cancel(
        request_id=context.request_id,
        actor_id="actor_worker",
    ) == "cancelling"

    repository.mark_cancelled(
        request_id=context.request_id,
        lease_owner="worker-phase4",
    )

    row = phase4_db.query_one(
        """SELECT r.status AS request_status, t.status AS turn_status,
                  r.cancelled_at, r.completed_at
           FROM requests r JOIN turns t ON t.turn_id = r.turn_id
           WHERE r.request_id = ?""",
        (context.request_id,),
    )
    assert row["request_status"] == "cancelled"
    assert row["turn_status"] == "cancelled"
    assert row["cancelled_at"] == frozen_utc_clock.now().isoformat()
    assert row["completed_at"] == frozen_utc_clock.now().isoformat()


@pytest.mark.asyncio
async def test_worker_recovers_before_first_claim(
    phase4_db,
    frozen_utc_clock,
):
    base_repository = _repository(phase4_db, frozen_utc_clock)
    interrupted = _submit(
        base_repository,
        request_id="req_worker_interrupted",
        conversation_id="conv_worker_interrupted",
    )
    base_repository.claim_next(
        lease_owner="dead-worker",
        lease_seconds=30,
    )
    runnable = _submit(
        base_repository,
        request_id="req_worker_after_recovery",
        conversation_id="conv_worker_after_recovery",
    )
    calls = []

    class RecordingRepository:
        def recover_interrupted(self):
            calls.append("recover")
            return base_repository.recover_interrupted()

        def claim_next(self, **kwargs):
            calls.append("claim")
            return base_repository.claim_next(**kwargs)

        def __getattr__(self, name):
            return getattr(base_repository, name)

    pipeline_called = asyncio.Event()

    class Pipeline:
        async def handle(self, *_args, **_kwargs):
            calls.append("pipeline")
            pipeline_called.set()
            return {}

    worker = _worker(
        repository=RecordingRepository(),
        pipeline=Pipeline(),
        frozen_utc_clock=frozen_utc_clock,
    )

    await worker.start()
    await asyncio.wait_for(pipeline_called.wait(), timeout=1)
    await _wait_for_status(phase4_db, runnable.request_id, "completed")
    await worker.stop()

    assert calls.index("recover") < calls.index("claim") < calls.index("pipeline")
    assert phase4_db.query_one(
        "SELECT status, error_code FROM requests WHERE request_id = ?",
        (interrupted.request_id,),
    ) == {"status": "failed", "error_code": "process_interrupted"}


@pytest.mark.asyncio
async def test_worker_runs_four_distinct_conversations_and_fifth_waits(
    phase4_db,
    frozen_utc_clock,
):
    repository = _repository(phase4_db, frozen_utc_clock)
    contexts = [
        _submit(
            repository,
            request_id=f"req_worker_parallel_{index}",
            conversation_id=f"conv_worker_parallel_{index}",
        )
        for index in range(5)
    ]

    class Pipeline:
        def __init__(self):
            self.active = 0
            self.max_active = 0
            self.started = []
            self.releases = {
                context.request_id: asyncio.Event() for context in contexts
            }
            self.first_four_started = asyncio.Event()
            self.fifth_started = asyncio.Event()

        async def handle(self, *_args, request_context, **_kwargs):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.started.append(request_context.request_id)
            if len(self.started) == 4:
                self.first_four_started.set()
            if len(self.started) == 5:
                self.fifth_started.set()
            try:
                await self.releases[request_context.request_id].wait()
            finally:
                self.active -= 1
            return {}

    pipeline = Pipeline()
    worker = _worker(
        repository=repository,
        pipeline=pipeline,
        frozen_utc_clock=frozen_utc_clock,
        max_concurrency=4,
    )

    await worker.start()
    await asyncio.wait_for(pipeline.first_four_started.wait(), timeout=1)

    assert pipeline.max_active == 4
    assert len(worker._running_tasks) == 4
    assert pipeline.fifth_started.is_set() is False
    pipeline.releases[pipeline.started[0]].set()
    await asyncio.wait_for(pipeline.fifth_started.wait(), timeout=1)
    for release in pipeline.releases.values():
        release.set()
    for context in contexts:
        await _wait_for_status(phase4_db, context.request_id, "completed")
    await worker.stop()

    assert pipeline.max_active == 4


@pytest.mark.asyncio
async def test_worker_serializes_requests_in_same_conversation(
    phase4_db,
    frozen_utc_clock,
):
    repository = _repository(phase4_db, frozen_utc_clock)
    first = _submit(
        repository,
        request_id="req_worker_serial_1",
        conversation_id="conv_worker_serial",
    )
    second = _submit(
        repository,
        request_id="req_worker_serial_2",
        conversation_id="conv_worker_serial",
    )

    class Pipeline:
        def __init__(self):
            self.active = 0
            self.max_active = 0
            self.started = []
            self.releases = {
                first.request_id: asyncio.Event(),
                second.request_id: asyncio.Event(),
            }
            self.first_started = asyncio.Event()
            self.second_started = asyncio.Event()

        async def handle(self, *_args, request_context, **_kwargs):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.started.append(request_context.request_id)
            if request_context.request_id == first.request_id:
                self.first_started.set()
            else:
                self.second_started.set()
            try:
                await self.releases[request_context.request_id].wait()
            finally:
                self.active -= 1
            return {}

    pipeline = Pipeline()
    worker = _worker(
        repository=repository,
        pipeline=pipeline,
        frozen_utc_clock=frozen_utc_clock,
        max_concurrency=4,
    )

    await worker.start()
    await asyncio.wait_for(pipeline.first_started.wait(), timeout=1)

    assert phase4_db.query_one(
        "SELECT status FROM requests WHERE request_id = ?",
        (second.request_id,),
    )["status"] == "queued"
    assert pipeline.second_started.is_set() is False
    pipeline.releases[first.request_id].set()
    await asyncio.wait_for(pipeline.second_started.wait(), timeout=1)
    pipeline.releases[second.request_id].set()
    await _wait_for_status(phase4_db, second.request_id, "completed")
    await worker.stop()

    assert pipeline.started == [first.request_id, second.request_id]
    assert pipeline.max_active == 1


@pytest.mark.asyncio
async def test_worker_keeps_real_asyncio_task_by_request_id(
    phase4_db,
    frozen_utc_clock,
    phase4_pipeline_double,
):
    repository = _repository(phase4_db, frozen_utc_clock)
    context = _submit(
        repository,
        request_id="req_worker_real_task",
        conversation_id="conv_worker_real_task",
    )
    worker = _worker(
        repository=repository,
        pipeline=phase4_pipeline_double,
        frozen_utc_clock=frozen_utc_clock,
    )

    await worker.start()
    await asyncio.wait_for(phase4_pipeline_double.started.wait(), timeout=1)

    running_task = worker._running_tasks[context.request_id]
    assert isinstance(running_task, asyncio.Task)
    assert running_task.done() is False
    phase4_pipeline_double.release.set()
    await _wait_for_status(phase4_db, context.request_id, "completed")
    await worker.stop()


@pytest.mark.asyncio
async def test_worker_heartbeats_while_pipeline_is_running(
    phase4_db,
    frozen_utc_clock,
    phase4_pipeline_double,
):
    base_repository = _repository(phase4_db, frozen_utc_clock)
    context = _submit(
        base_repository,
        request_id="req_worker_heartbeat",
        conversation_id="conv_worker_heartbeat",
    )
    heartbeat_seen = asyncio.Event()
    heartbeat_count = 0

    class HeartbeatRepository:
        def heartbeat(self, **kwargs):
            nonlocal heartbeat_count
            heartbeat_count += 1
            heartbeat_seen.set()
            return base_repository.heartbeat(**kwargs)

        def __getattr__(self, name):
            return getattr(base_repository, name)

    worker = _worker(
        repository=HeartbeatRepository(),
        pipeline=phase4_pipeline_double,
        frozen_utc_clock=frozen_utc_clock,
    )

    await worker.start()
    await asyncio.wait_for(phase4_pipeline_double.started.wait(), timeout=1)
    await asyncio.wait_for(heartbeat_seen.wait(), timeout=1)

    assert heartbeat_count >= 1
    assert phase4_db.query_one(
        "SELECT last_heartbeat_at FROM requests WHERE request_id = ?",
        (context.request_id,),
    )["last_heartbeat_at"] == frozen_utc_clock.now().isoformat()
    phase4_pipeline_double.release.set()
    await _wait_for_status(phase4_db, context.request_id, "completed")
    await worker.stop()


@pytest.mark.asyncio
async def test_cancel_queued_never_calls_pipeline(
    phase4_db,
    frozen_utc_clock,
    phase4_pipeline_double,
):
    repository = _repository(phase4_db, frozen_utc_clock)
    context = _submit(
        repository,
        request_id="req_worker_cancel_queued",
        conversation_id="conv_worker_cancel_queued",
    )
    assert repository.request_cancel(
        request_id=context.request_id,
        actor_id="actor_worker",
    ) == "cancelled"
    worker = _worker(
        repository=repository,
        pipeline=phase4_pipeline_double,
        frozen_utc_clock=frozen_utc_clock,
    )

    await worker.start()
    await asyncio.wait_for(worker._idle_event.wait(), timeout=1)
    await worker.stop()

    assert phase4_pipeline_double.started.is_set() is False
    assert phase4_db.query_one(
        "SELECT status FROM requests WHERE request_id = ?",
        (context.request_id,),
    )["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_running_cancels_task_and_marks_cancelled(
    phase4_db,
    frozen_utc_clock,
    phase4_pipeline_double,
):
    repository = _repository(phase4_db, frozen_utc_clock)
    context = _submit(
        repository,
        request_id="req_worker_cancel_running",
        conversation_id="conv_worker_cancel_running",
    )
    emitter = _RecordingEmitter()
    worker = _worker(
        repository=repository,
        pipeline=phase4_pipeline_double,
        frozen_utc_clock=frozen_utc_clock,
        emit=emitter,
    )

    await worker.start()
    await asyncio.wait_for(phase4_pipeline_double.started.wait(), timeout=1)
    assert repository.request_cancel(
        request_id=context.request_id,
        actor_id="actor_worker",
    ) == "cancelling"

    assert await worker.cancel_running(context.request_id) is True
    await asyncio.wait_for(phase4_pipeline_double.cancel_seen.wait(), timeout=1)
    await worker.stop()

    row = phase4_db.query_one(
        "SELECT status, cancelled_at FROM requests WHERE request_id = ?",
        (context.request_id,),
    )
    assert row["status"] == "cancelled"
    assert row["cancelled_at"] == frozen_utc_clock.now().isoformat()
    assert "chat_request_cancelled" in [event[0] for event in emitter.events]
    assert "chat_request_completed" not in [event[0] for event in emitter.events]


@pytest.mark.asyncio
async def test_cancelled_error_never_becomes_completed(
    phase4_db,
    frozen_utc_clock,
):
    repository = _repository(phase4_db, frozen_utc_clock)
    context = _submit(
        repository,
        request_id="req_worker_unexpected_cancel",
        conversation_id="conv_worker_unexpected_cancel",
    )

    class Pipeline:
        async def handle(self, *_args, **_kwargs):
            raise asyncio.CancelledError

    emitter = _RecordingEmitter()
    worker = _worker(
        repository=repository,
        pipeline=Pipeline(),
        frozen_utc_clock=frozen_utc_clock,
        emit=emitter,
    )

    await worker.start()
    await _wait_for_status(phase4_db, context.request_id, "failed")
    await worker.stop()

    row = phase4_db.query_one(
        "SELECT status, error_code FROM requests WHERE request_id = ?",
        (context.request_id,),
    )
    assert row == {"status": "failed", "error_code": "pipeline_cancelled"}
    assert "chat_request_completed" not in [event[0] for event in emitter.events]


@pytest.mark.asyncio
async def test_event_emit_failure_does_not_reverse_database_terminal_state(
    phase4_db,
    frozen_utc_clock,
):
    repository = _repository(phase4_db, frozen_utc_clock)
    context = _submit(
        repository,
        request_id="req_worker_emit_failure",
        conversation_id="conv_worker_emit_failure",
    )

    class Pipeline:
        async def handle(self, *_args, **_kwargs):
            return {}

    def failing_emit(*_args, **_kwargs):
        raise RuntimeError("event transport unavailable")

    worker = _worker(
        repository=repository,
        pipeline=Pipeline(),
        frozen_utc_clock=frozen_utc_clock,
        emit=failing_emit,
    )

    await worker.start()
    await _wait_for_status(phase4_db, context.request_id, "completed")
    await worker.stop()

    assert phase4_db.query_one(
        "SELECT status FROM requests WHERE request_id = ?",
        (context.request_id,),
    )["status"] == "completed"


@pytest.mark.asyncio
async def test_stop_does_not_masquerade_as_user_cancel(
    phase4_db,
    frozen_utc_clock,
    phase4_pipeline_double,
):
    repository = _repository(phase4_db, frozen_utc_clock)
    running = _submit(
        repository,
        request_id="req_worker_stop_running",
        conversation_id="conv_worker_stop",
    )
    queued = _submit(
        repository,
        request_id="req_worker_stop_queued",
        conversation_id="conv_worker_stop",
    )
    worker = _worker(
        repository=repository,
        pipeline=phase4_pipeline_double,
        frozen_utc_clock=frozen_utc_clock,
    )

    await worker.start()
    await asyncio.wait_for(phase4_pipeline_double.started.wait(), timeout=1)
    await worker.stop()

    rows = {
        row["request_id"]: (row["status"], row["error_code"])
        for row in phase4_db.query(
            "SELECT request_id, status, error_code FROM requests"
        )
    }
    assert rows[running.request_id] == ("failed", "worker_stopped")
    assert rows[queued.request_id] == ("queued", None)


@pytest.mark.asyncio
async def test_cancel_running_missing_task_fails_request_instead_of_hanging(
    phase4_db,
    frozen_utc_clock,
):
    repository = _repository(phase4_db, frozen_utc_clock)
    context = _submit(
        repository,
        request_id="req_worker_missing_task",
        conversation_id="conv_worker_missing_task",
    )
    repository.claim_next(lease_owner="worker-phase4", lease_seconds=30)
    assert repository.request_cancel(
        request_id=context.request_id,
        actor_id="actor_worker",
    ) == "cancelling"
    worker = _worker(
        repository=repository,
        pipeline=object(),
        frozen_utc_clock=frozen_utc_clock,
    )

    assert await worker.cancel_running(context.request_id) is False

    assert phase4_db.query_one(
        "SELECT status, error_code FROM requests WHERE request_id = ?",
        (context.request_id,),
    ) == {"status": "failed", "error_code": "cancel_task_missing"}
