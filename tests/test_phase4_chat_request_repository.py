from __future__ import annotations

import json
import sqlite3
from datetime import timedelta

import pytest

from core.chat_request_repository import (
    ChatRequestRepository,
    RequestContext,
    RequestIdentity,
)


def _context(
    *,
    request_id: str,
    conversation_id: str = "conv_phase4_a",
    turn_id: str | None = None,
    input_content: str = "你好",
) -> RequestContext:
    return RequestContext(
        request_id=request_id,
        conversation_id=conversation_id,
        turn_id=turn_id or f"turn_{request_id}",
        identity=RequestIdentity(
            actor_id="actor_phase4",
            channel="desktop",
            channel_account_id="local",
            user_id=7,
        ),
        input_content=input_content,
        effective_content=input_content,
        attachments=[
            {
                "name": "phase4-attachment.txt",
                "url": "/uploads/phase4-attachment.txt",
                "state": "ready",
                "size": 128,
                "type": "text/plain",
            }
        ],
        reply_to_id=0,
    )


def _repository(phase4_db, frozen_utc_clock):
    phase4_db.insert(
        "actors",
        {
            "actor_id": "actor_phase4",
            "created_at": frozen_utc_clock.now().isoformat(),
        },
    )
    return ChatRequestRepository(
        phase4_db,
        clock=frozen_utc_clock.now,
    )


def test_phase4_db_fixture_has_006_and_foreign_keys(
    phase4_db,
):
    with phase4_db.connection() as conn:
        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(requests)"
            )
        }
        foreign_keys = conn.execute(
            "PRAGMA foreign_keys"
        ).fetchone()[0]

    assert "lease_owner" in columns
    assert foreign_keys == 1


def test_submit_atomically_ensures_conversation_pending_turn_and_queued_request(
    phase4_db,
    frozen_utc_clock,
):
    repository = _repository(phase4_db, frozen_utc_clock)
    context = _context(request_id="req_submit")

    submitted = repository.submit(context=context)

    conversation = phase4_db.query_one(
        "SELECT * FROM conversations WHERE conversation_id = ?",
        (context.conversation_id,),
    )
    turn = phase4_db.query_one(
        "SELECT * FROM turns WHERE turn_id = ?",
        (context.turn_id,),
    )
    request = phase4_db.query_one(
        "SELECT * FROM requests WHERE request_id = ?",
        (context.request_id,),
    )

    assert submitted.request_id == context.request_id
    assert submitted.conversation_id == context.conversation_id
    assert submitted.turn_id == context.turn_id
    assert submitted.status == "queued"
    assert conversation["actor_id"] == "actor_phase4"
    assert turn["status"] == "pending"
    assert request["status"] == "queued"
    assert request["actor_id"] == "actor_phase4"
    assert request["input_content"] == "你好"
    assert json.loads(request["attachments"])[0]["state"] == "ready"
    assert phase4_db.query_one(
        "SELECT COUNT(*) AS count FROM messages"
    )["count"] == 0


def test_submit_rolls_back_all_three_records_on_request_insert_failure(
    phase4_db,
    frozen_utc_clock,
):
    repository = _repository(phase4_db, frozen_utc_clock)
    with phase4_db.connection() as conn:
        conn.execute(
            """CREATE TRIGGER fail_phase4_request_insert
               BEFORE INSERT ON requests
               BEGIN
                   SELECT RAISE(ABORT, 'request insert failed');
               END"""
        )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="request insert failed",
    ):
        repository.submit(
            context=_context(request_id="req_rollback")
        )

    assert phase4_db.query_one(
        "SELECT COUNT(*) AS count FROM conversations"
    )["count"] == 0
    assert phase4_db.query_one(
        "SELECT COUNT(*) AS count FROM turns"
    )["count"] == 0
    assert phase4_db.query_one(
        "SELECT COUNT(*) AS count FROM requests"
    )["count"] == 0


def test_claim_next_is_atomic_and_skips_conversation_with_running_request(
    phase4_db,
    frozen_utc_clock,
):
    repository = _repository(phase4_db, frozen_utc_clock)
    repository.submit(context=_context(request_id="req_a1"))
    frozen_utc_clock.advance(1)
    repository.submit(context=_context(request_id="req_a2"))
    frozen_utc_clock.advance(1)
    repository.submit(
        context=_context(
            request_id="req_b1",
            conversation_id="conv_phase4_b",
        )
    )

    first = repository.claim_next(
        lease_owner="worker-a",
        lease_seconds=30,
    )
    second = repository.claim_next(
        lease_owner="worker-b",
        lease_seconds=30,
    )

    assert first.context.request_id == "req_a1"
    assert second.context.request_id == "req_b1"
    assert phase4_db.query_one(
        "SELECT status FROM requests WHERE request_id = ?",
        ("req_a2",),
    )["status"] == "queued"
    assert phase4_db.query_one(
        "SELECT status FROM turns WHERE turn_id = ?",
        ("turn_req_a1",),
    )["status"] == "running"


def test_claim_next_orders_by_created_at_then_request_id(
    phase4_db,
    frozen_utc_clock,
):
    repository = _repository(phase4_db, frozen_utc_clock)
    for request_id, conversation_id in (
        ("req_b", "conv_b"),
        ("req_a", "conv_a"),
    ):
        repository.submit(
            context=_context(
                request_id=request_id,
                conversation_id=conversation_id,
            )
        )

    first = repository.claim_next(
        lease_owner="worker-order",
        lease_seconds=30,
    )

    assert first.context.request_id == "req_a"


def test_heartbeat_requires_matching_lease_owner_and_extends_utc_lease(
    phase4_db,
    frozen_utc_clock,
):
    repository = _repository(phase4_db, frozen_utc_clock)
    repository.submit(context=_context(request_id="req_heartbeat"))
    claimed = repository.claim_next(
        lease_owner="worker-heartbeat",
        lease_seconds=30,
    )
    original_expiry = claimed.lease_expires_at
    frozen_utc_clock.advance(10)

    assert repository.heartbeat(
        request_id="req_heartbeat",
        lease_owner="wrong-worker",
        lease_seconds=30,
    ) is False
    assert repository.heartbeat(
        request_id="req_heartbeat",
        lease_owner="worker-heartbeat",
        lease_seconds=30,
    ) is True

    request = phase4_db.query_one(
        "SELECT lease_expires_at, last_heartbeat_at FROM requests "
        "WHERE request_id = ?",
        ("req_heartbeat",),
    )
    assert request["lease_expires_at"] > original_expiry
    assert request["lease_expires_at"].endswith("+00:00")
    assert request["last_heartbeat_at"].endswith("+00:00")


def test_recovery_fails_running_cancelling_and_expired_lease_but_keeps_queued(
    phase4_db,
    frozen_utc_clock,
):
    repository = _repository(phase4_db, frozen_utc_clock)
    repository.submit(
        context=_context(
            request_id="req_running",
            conversation_id="conv_running",
        )
    )
    repository.claim_next(
        lease_owner="worker-running",
        lease_seconds=30,
    )
    frozen_utc_clock.advance(1)
    repository.submit(
        context=_context(
            request_id="req_cancelling",
            conversation_id="conv_cancelling",
        )
    )
    repository.claim_next(
        lease_owner="worker-cancelling",
        lease_seconds=30,
    )
    repository.request_cancel(
        request_id="req_cancelling",
        actor_id="actor_phase4",
    )
    frozen_utc_clock.advance(1)
    repository.submit(
        context=_context(
            request_id="req_queued",
            conversation_id="conv_queued",
        )
    )
    frozen_utc_clock.advance(30)

    recovered = repository.recover_interrupted()

    assert recovered == 2
    rows = {
        row["request_id"]: row
        for row in phase4_db.query(
            "SELECT request_id, status, error_code, lease_owner "
            "FROM requests"
        )
    }
    assert rows["req_running"]["status"] == "failed"
    assert rows["req_running"]["error_code"] == "process_interrupted"
    assert rows["req_cancelling"]["status"] == "failed"
    assert rows["req_cancelling"]["error_code"] == "process_interrupted"
    assert rows["req_queued"]["status"] == "queued"
    assert rows["req_running"]["lease_owner"] is None


def test_cancel_and_failure_keep_request_turn_status_invariant(
    phase4_db,
    frozen_utc_clock,
):
    repository = _repository(phase4_db, frozen_utc_clock)
    repository.submit(context=_context(request_id="req_cancel_queued"))
    repository.submit(
        context=_context(
            request_id="req_cancel_running",
            conversation_id="conv_cancel_running",
        )
    )
    repository.submit(
        context=_context(
            request_id="req_failure",
            conversation_id="conv_failure",
        )
    )

    assert repository.request_cancel(
        request_id="req_cancel_queued",
        actor_id="actor_phase4",
    ) == "cancelled"
    repository.claim_next(
        lease_owner="worker-cancel",
        lease_seconds=30,
    )
    repository.claim_next(
        lease_owner="worker-failure",
        lease_seconds=30,
    )
    assert repository.request_cancel(
        request_id="req_cancel_running",
        actor_id="actor_phase4",
    ) == "cancelling"
    repository.mark_cancelled(
        request_id="req_cancel_running",
        lease_owner="worker-cancel",
    )
    repository.mark_failed(
        request_id="req_failure",
        lease_owner="worker-failure",
        error_code="pipeline_failed",
    )

    pairs = phase4_db.query(
        """SELECT r.request_id, r.status AS request_status,
                  t.status AS turn_status
           FROM requests r
           JOIN turns t ON t.turn_id = r.turn_id
           ORDER BY r.request_id"""
    )
    assert {
        row["request_id"]: (
            row["request_status"],
            row["turn_status"],
        )
        for row in pairs
    } == {
        "req_cancel_queued": ("cancelled", "cancelled"),
        "req_cancel_running": ("cancelled", "cancelled"),
        "req_failure": ("failed", "failed"),
    }


def test_retry_creates_new_request_and_turn_with_original_unchanged(
    phase4_db,
    frozen_utc_clock,
):
    repository = _repository(phase4_db, frozen_utc_clock)
    repository.submit(context=_context(request_id="req_original"))
    repository.claim_next(
        lease_owner="worker-original",
        lease_seconds=30,
    )
    repository.mark_failed(
        request_id="req_original",
        lease_owner="worker-original",
        error_code="pipeline_failed",
    )

    retried = repository.create_retry(
        source_request_id="req_original",
        actor_id="actor_phase4",
        request_id="req_retry",
        turn_id="turn_retry",
    )

    original = phase4_db.query_one(
        "SELECT status, error_code FROM requests WHERE request_id = ?",
        ("req_original",),
    )
    retry = phase4_db.query_one(
        "SELECT status, retry_of_request_id, turn_id FROM requests "
        "WHERE request_id = ?",
        ("req_retry",),
    )
    retry_turn = phase4_db.query_one(
        "SELECT status FROM turns WHERE turn_id = ?",
        ("turn_retry",),
    )

    assert retried["request_id"] == "req_retry"
    assert original == {
        "status": "failed",
        "error_code": "pipeline_failed",
    }
    assert retry == {
        "status": "queued",
        "retry_of_request_id": "req_original",
        "turn_id": "turn_retry",
    }
    assert retry_turn["status"] == "pending"


def test_repository_operations_do_not_hold_connection_during_pipeline_call(
    phase4_db,
    frozen_utc_clock,
):
    class TrackingDatabase:
        def __init__(self, database):
            self.database = database
            self.active_connections = 0

        def connection(self):
            tracker = self
            base_context = self.database.connection()

            class ConnectionContext:
                def __enter__(self):
                    tracker.active_connections += 1
                    return base_context.__enter__()

                def __exit__(self, exc_type, exc, traceback):
                    try:
                        return base_context.__exit__(
                            exc_type,
                            exc,
                            traceback,
                        )
                    finally:
                        tracker.active_connections -= 1

            return ConnectionContext()

    phase4_db.insert(
        "actors",
        {
            "actor_id": "actor_phase4",
            "created_at": frozen_utc_clock.now().isoformat(),
        },
    )
    tracking_db = TrackingDatabase(phase4_db)
    repository = ChatRequestRepository(
        tracking_db,
        clock=frozen_utc_clock.now,
    )
    repository.submit(context=_context(request_id="req_connection"))

    claimed = repository.claim_next(
        lease_owner="worker-connection",
        lease_seconds=30,
    )

    assert claimed.context.request_id == "req_connection"
    assert tracking_db.active_connections == 0

    pipeline_observation = {
        "active_connections": tracking_db.active_connections,
        "deadline": frozen_utc_clock.now() + timedelta(seconds=1),
    }
    assert pipeline_observation["active_connections"] == 0


def test_resolve_conversation_id_is_public_and_deterministic():
    from core.conversation_repository import resolve_conversation_id

    first = resolve_conversation_id(
        actor_id="actor_phase4",
        channel="desktop",
        channel_account_id="local",
        user_id=7,
    )
    second = resolve_conversation_id(
        actor_id="actor_phase4",
        channel="desktop",
        channel_account_id="local",
        user_id=7,
    )

    assert first == second
    assert first.startswith("conv_")


def test_ensure_conversation_reuses_same_identity_key(
    phase4_db,
):
    from core.conversation_repository import ConversationRepository
    from core.conversation_repository import resolve_conversation_id

    repository = ConversationRepository(phase4_db, enabled=True)
    conversation_id = resolve_conversation_id(
        actor_id="actor_phase4",
        channel="desktop",
        channel_account_id="local",
        user_id=7,
    )

    with phase4_db.connection() as conn:
        repository.ensure_conversation(
            conn,
            conversation_id=conversation_id,
            actor_id="actor_phase4",
            channel="desktop",
            channel_account_id="local",
        )
        repository.ensure_conversation(
            conn,
            conversation_id=conversation_id,
            actor_id="actor_phase4",
            channel="desktop",
            channel_account_id="local",
        )

    assert phase4_db.query_one(
        "SELECT COUNT(*) AS count FROM conversations"
    )["count"] == 1


def test_persist_turn_completes_existing_request_and_turn_without_duplicate_pk(
    phase4_db,
    frozen_utc_clock,
):
    from core.conversation_repository import ConversationRepository

    request_repository = _repository(phase4_db, frozen_utc_clock)
    context = _context(request_id="req_complete_existing")
    request_repository.submit(context=context)
    conversation_repository = ConversationRepository(
        phase4_db,
        enabled=True,
    )

    result = conversation_repository.persist_turn(
        request_id=context.request_id,
        user_id=context.identity.user_id,
        actor_id=context.identity.actor_id,
        channel=context.identity.channel,
        channel_account_id=context.identity.channel_account_id,
        user_content=context.input_content,
        user_attachments=context.attachments,
        assistant_segments=["完成回复"],
        conversation_id=context.conversation_id,
        turn_id=context.turn_id,
    )

    assert result["request_id"] == context.request_id
    assert result["turn_id"] == context.turn_id
    assert phase4_db.query_one(
        "SELECT status FROM requests WHERE request_id = ?",
        (context.request_id,),
    )["status"] == "completed"
    assert phase4_db.query_one(
        "SELECT status FROM turns WHERE turn_id = ?",
        (context.turn_id,),
    )["status"] == "completed"
    assert phase4_db.query_one(
        "SELECT COUNT(*) AS count FROM messages WHERE turn_id = ?",
        (context.turn_id,),
    )["count"] == 2


def test_existing_request_completion_rolls_back_messages_and_status_on_failure(
    phase4_db,
    frozen_utc_clock,
):
    from core.conversation_repository import ConversationRepository

    request_repository = _repository(phase4_db, frozen_utc_clock)
    context = _context(request_id="req_complete_rollback")
    request_repository.submit(context=context)
    with phase4_db.connection() as conn:
        conn.execute(
            """CREATE TRIGGER fail_phase4_assistant_message
               BEFORE INSERT ON messages
               WHEN NEW.role = 'assistant'
               BEGIN
                   SELECT RAISE(ABORT, 'completion message failed');
               END"""
        )
    conversation_repository = ConversationRepository(
        phase4_db,
        enabled=True,
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="completion message failed",
    ):
        conversation_repository.persist_turn(
            request_id=context.request_id,
            user_id=context.identity.user_id,
            actor_id=context.identity.actor_id,
            channel=context.identity.channel,
            channel_account_id=context.identity.channel_account_id,
            user_content=context.input_content,
            user_attachments=context.attachments,
            assistant_segments=["失败回复"],
            conversation_id=context.conversation_id,
            turn_id=context.turn_id,
        )

    assert phase4_db.query_one(
        "SELECT status FROM requests WHERE request_id = ?",
        (context.request_id,),
    )["status"] == "queued"
    assert phase4_db.query_one(
        "SELECT status FROM turns WHERE turn_id = ?",
        (context.turn_id,),
    )["status"] == "pending"
    assert phase4_db.query_one(
        "SELECT COUNT(*) AS count FROM messages WHERE turn_id = ?",
        (context.turn_id,),
    )["count"] == 0


def test_recent_turn_history_reads_completed_turns_only(
    phase4_db,
    frozen_utc_clock,
):
    from core.conversation_repository import ConversationRepository
    from core.conversation_repository import resolve_conversation_id

    request_repository = _repository(phase4_db, frozen_utc_clock)
    conversation_repository = ConversationRepository(
        phase4_db,
        enabled=True,
    )
    conversation_id = resolve_conversation_id(
        actor_id="actor_phase4",
        channel="desktop",
        channel_account_id="local",
        user_id=7,
    )
    context = _context(
        request_id="req_history_completed",
        conversation_id=conversation_id,
    )
    request_repository.submit(context=context)
    conversation_repository.persist_turn(
        request_id=context.request_id,
        user_id=context.identity.user_id,
        actor_id=context.identity.actor_id,
        channel=context.identity.channel,
        channel_account_id=context.identity.channel_account_id,
        user_content="已完成问题",
        user_attachments=None,
        assistant_segments=["已完成回复"],
        conversation_id=context.conversation_id,
        turn_id=context.turn_id,
    )
    with phase4_db.connection() as conn:
        for status, turn_id, request_id, content in (
            ("pending", "turn_pending_history", "req_pending_history", "待处理"),
            ("failed", "turn_failed_history", "req_failed_history", "失败"),
            ("cancelled", "turn_cancelled_history", "req_cancelled_history", "取消"),
        ):
            conn.execute(
                "INSERT INTO turns (turn_id, conversation_id, status) "
                "VALUES (?, ?, ?)",
                (turn_id, context.conversation_id, status),
            )
            conn.execute(
                "INSERT INTO requests (request_id, conversation_id, turn_id, status) "
                "VALUES (?, ?, ?, ?)",
                (request_id, context.conversation_id, turn_id, status),
            )
            conn.execute(
                """INSERT INTO messages
                   (message_id, conversation_id, turn_id, role, content, sequence)
                   VALUES (?, ?, ?, 'user', ?, 0)""",
                (
                    f"msg_{turn_id}",
                    context.conversation_id,
                    turn_id,
                    content,
                ),
            )

    history = conversation_repository.recent_turn_history(
        actor_id=context.identity.actor_id,
        channel=context.identity.channel,
        channel_account_id=context.identity.channel_account_id,
        user_id=context.identity.user_id,
        limit=20,
    )

    assert [row["content"] for row in history] == [
        "已完成问题",
        "已完成回复",
    ]


def test_completion_is_idempotent_and_conflict_does_not_overwrite_completed_data(
    phase4_db,
    frozen_utc_clock,
):
    from core.conversation_repository import ConversationRepository

    request_repository = _repository(phase4_db, frozen_utc_clock)
    context = _context(request_id="req_idempotent_completion")
    request_repository.submit(context=context)
    conversation_repository = ConversationRepository(
        phase4_db,
        enabled=True,
    )
    first = conversation_repository.persist_turn(
        request_id=context.request_id,
        user_id=context.identity.user_id,
        actor_id=context.identity.actor_id,
        channel=context.identity.channel,
        channel_account_id=context.identity.channel_account_id,
        user_content=context.input_content,
        user_attachments=None,
        assistant_segments=["固定回复"],
        conversation_id=context.conversation_id,
        turn_id=context.turn_id,
    )
    second = conversation_repository.persist_turn(
        request_id=context.request_id,
        user_id=context.identity.user_id,
        actor_id=context.identity.actor_id,
        channel=context.identity.channel,
        channel_account_id=context.identity.channel_account_id,
        user_content=context.input_content,
        user_attachments=None,
        assistant_segments=["固定回复"],
        conversation_id=context.conversation_id,
        turn_id=context.turn_id,
    )

    assert second == first
    assert phase4_db.query_one(
        "SELECT COUNT(*) AS count FROM messages WHERE turn_id = ?",
        (context.turn_id,),
    )["count"] == 2

    with pytest.raises(Exception, match="conflict"):
        conversation_repository.persist_turn(
            request_id=context.request_id,
            user_id=context.identity.user_id,
            actor_id=context.identity.actor_id,
            channel=context.identity.channel,
            channel_account_id=context.identity.channel_account_id,
            user_content=context.input_content,
            user_attachments=None,
            assistant_segments=["不同回复"],
            conversation_id=context.conversation_id,
            turn_id=context.turn_id,
        )

    assert phase4_db.query_one(
        "SELECT content FROM messages WHERE turn_id = ? "
        "AND role = 'assistant'",
        (context.turn_id,),
    )["content"] == "固定回复"
