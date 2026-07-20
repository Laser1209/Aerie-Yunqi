from dataclasses import asdict
import inspect
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def test_ready_attachment_fixture_contains_only_server_metadata(
    ready_attachment,
):
    assert ready_attachment["state"] == "ready"
    assert ready_attachment["url"].startswith(
        "/uploads/"
    )
    assert ready_attachment["name"]
    assert ready_attachment["size"] > 0
    assert ready_attachment["type"]
    assert "path" not in ready_attachment
    assert "content" not in ready_attachment


class _FixedIdFactory:
    def __init__(self):
        self.counts = {}

    def __call__(self, prefix):
        current = self.counts.get(prefix, 0) + 1
        self.counts[prefix] = current
        return f"{prefix}_service_{current}"


class _StaticIdentityRepository:
    def __init__(self, actor_id):
        self.actor_id = actor_id
        self.calls = []

    def resolve(self, channel, channel_account_id):
        from core.identity.models import ChannelIdentity

        self.calls.append((channel, channel_account_id))
        return ChannelIdentity(
            actor_id=self.actor_id,
            channel=channel,
            channel_account_id=channel_account_id,
        )


def _service_components(
    phase4_db,
    frozen_utc_clock,
    *,
    worker=None,
    identity_repository=None,
    master_user_id=7001,
):
    from core.chat_request_repository import ChatRequestRepository
    from core.chat_request_service import ChatRequestService
    from core.identity import IdentityRepository

    repository = ChatRequestRepository(
        phase4_db,
        clock=frozen_utc_clock.now,
    )
    identity_repository = identity_repository or IdentityRepository(phase4_db)
    service = ChatRequestService(
        repository=repository,
        identity_repository=identity_repository,
        worker=worker,
        master_user_id_provider=lambda: master_user_id,
        id_factory=_FixedIdFactory(),
    )
    return service, repository, identity_repository


def test_submit_ignores_renderer_actor_and_conversation_fields_by_signature():
    from core.chat_request_service import ChatRequestService

    parameters = inspect.signature(ChatRequestService.submit).parameters

    assert tuple(parameters) == (
        "self",
        "text",
        "attachments",
        "reply_to_id",
        "user_id",
    )
    assert "actor_id" not in parameters
    assert "conversation_id" not in parameters
    assert "turn_id" not in parameters


def test_submit_uses_trusted_desktop_local_identity_and_legacy_user_id(
    phase4_db,
    frozen_utc_clock,
):
    service, repository, identity_repository = _service_components(
        phase4_db,
        frozen_utc_clock,
    )

    submitted = service.submit(
        text="  trusted input  ",
        attachments=[],
        reply_to_id=0,
        user_id=7017,
    )
    row = repository.get_owned(
        request_id=submitted.request_id,
        actor_id=phase4_db.query_one(
            """SELECT actor_id FROM channel_accounts
               WHERE channel = 'desktop' AND channel_account_id = 'local'"""
        )["actor_id"],
    )

    assert identity_repository.resolve("desktop", "local").actor_id == row["actor_id"]
    assert row["channel"] == "desktop"
    assert row["channel_account_id"] == "local"
    assert row["user_id"] == 7017
    assert row["input_content"] == "trusted input"
    assert row["effective_content"] == "trusted input"
    assert row["reply_to_id"] == 0
    assert submitted.status == "queued"


def test_submit_textless_ready_attachment_preserves_empty_input_and_internal_effective_content(
    phase4_db,
    frozen_utc_clock,
    ready_attachment,
):
    service, repository, identity_repository = _service_components(
        phase4_db,
        frozen_utc_clock,
        master_user_id=7020,
    )

    submitted = service.submit(
        text="",
        attachments=[ready_attachment],
        reply_to_id=0,
        user_id=None,
    )
    identity = identity_repository.resolve("desktop", "local")
    row = repository.get_owned(
        request_id=submitted.request_id,
        actor_id=identity.actor_id,
    )

    assert row["input_content"] == ""
    assert row["effective_content"] == "请结合用户提供的附件内容进行回应。"
    assert json.loads(row["attachments"]) == [ready_attachment]
    assert row["user_id"] == 7020
    assert asdict(submitted)["status"] == "queued"


def test_submit_accepts_safe_upload_url_without_leading_slash(
    phase4_db,
    frozen_utc_clock,
    ready_attachment,
):
    service, repository, identity_repository = _service_components(
        phase4_db,
        frozen_utc_clock,
    )
    compatible_attachment = dict(ready_attachment)
    compatible_attachment["url"] = compatible_attachment["url"].lstrip("/")

    submitted = service.submit(
        text="",
        attachments=[compatible_attachment],
        reply_to_id=0,
        user_id=7,
    )
    identity = identity_repository.resolve("desktop", "local")
    row = repository.get_owned(
        request_id=submitted.request_id,
        actor_id=identity.actor_id,
    )

    assert json.loads(row["attachments"]) == [compatible_attachment]


def test_submit_rejects_empty_text_and_no_attachments_with_400_contract(
    phase4_db,
    frozen_utc_clock,
):
    from core.chat_request_service import InvalidChatInput

    service, _, _ = _service_components(phase4_db, frozen_utc_clock)

    with pytest.raises(InvalidChatInput) as exc_info:
        service.submit(
            text="   ",
            attachments=[],
            reply_to_id=0,
            user_id=None,
        )

    assert exc_info.value.error_code == "empty_message"


@pytest.mark.parametrize(
    ("attachments", "expected_code"),
    [
        ([{"state": "converting", "url": "/uploads/pending.txt"}], "attachment_not_ready"),
        ([{"state": "ready", "url": "/uploads/../secret.txt"}], "invalid_attachment"),
        ([{"state": "ready", "url": "C:\\secret.txt"}], "invalid_attachment"),
        ([{"state": "ready", "url": "/uploads/nested/file.txt"}], "invalid_attachment"),
        (
            [
                {
                    "name": "encoded.txt",
                    "state": "ready",
                    "url": "/uploads/%2e%2e%2fsecret.txt",
                    "size": 1,
                    "type": "text/plain",
                }
            ],
            "invalid_attachment",
        ),
        (
            [
                {
                    "name": "client-data.txt",
                    "state": "ready",
                    "url": "/uploads/client-data.txt",
                    "size": 1,
                    "type": "text/plain",
                    "path": "client-supplied-path",
                    "content": "client-supplied-content",
                    "markdown": "client-supplied-markdown",
                }
            ],
            "invalid_attachment",
        ),
        (
            [
                {
                    "state": "ready",
                    "url": "/uploads/missing-metadata.txt",
                }
            ],
            "invalid_attachment",
        ),
        (["not-a-dict"], "invalid_attachment"),
        ({"state": "ready", "url": "/uploads/file.txt"}, "invalid_attachment"),
    ],
)
def test_submit_rejects_non_ready_or_malformed_attachment(
    phase4_db,
    frozen_utc_clock,
    attachments,
    expected_code,
):
    from core.chat_request_service import InvalidChatInput

    service, _, _ = _service_components(phase4_db, frozen_utc_clock)

    with pytest.raises(InvalidChatInput) as exc_info:
        service.submit(
            text="",
            attachments=attachments,
            reply_to_id=0,
            user_id=None,
        )

    assert exc_info.value.error_code == expected_code


def test_get_non_owner_and_missing_are_indistinguishable_404(
    phase4_db,
    frozen_utc_clock,
):
    from core.chat_request_service import ChatRequestService
    from core.chat_request_service import RequestNotFound

    owner_service, repository, owner_identity = _service_components(
        phase4_db,
        frozen_utc_clock,
    )
    submitted = owner_service.submit(
        text="owner request",
        attachments=[],
        reply_to_id=0,
        user_id=7,
    )
    intruder_service = ChatRequestService(
        repository=repository,
        identity_repository=_StaticIdentityRepository("actor_not_owner"),
        master_user_id_provider=lambda: 7,
        id_factory=_FixedIdFactory(),
    )

    errors = []
    for service, request_id in (
        (intruder_service, submitted.request_id),
        (owner_service, "req_missing"),
    ):
        with pytest.raises(RequestNotFound) as exc_info:
            service.get(request_id=request_id, user_id=7)
        errors.append((type(exc_info.value), str(exc_info.value), exc_info.value.error_code))

    assert errors[0] == errors[1]
    assert errors[0][2] == "request_not_found"
    assert owner_identity.resolve("desktop", "local").actor_id != "actor_not_owner"


@pytest.mark.asyncio
async def test_cancel_retry_non_owner_and_missing_share_404_contract(
    phase4_db,
    frozen_utc_clock,
):
    from core.chat_request_service import ChatRequestService
    from core.chat_request_service import RequestNotFound

    owner_service, repository, _ = _service_components(
        phase4_db,
        frozen_utc_clock,
    )
    submitted = owner_service.submit(
        text="owned request",
        attachments=[],
        reply_to_id=0,
        user_id=7,
    )
    intruder_service = ChatRequestService(
        repository=repository,
        identity_repository=_StaticIdentityRepository("actor_not_owner"),
        worker=SimpleNamespace(cancel_running=AsyncMock(return_value=True)),
        master_user_id_provider=lambda: 7,
        id_factory=_FixedIdFactory(),
    )

    cancel_errors = []
    retry_errors = []
    for service, request_id in (
        (intruder_service, submitted.request_id),
        (owner_service, "req_missing"),
    ):
        with pytest.raises(RequestNotFound) as cancel_error:
            await service.cancel(request_id=request_id, user_id=7)
        cancel_errors.append(
            (str(cancel_error.value), cancel_error.value.error_code)
        )
        with pytest.raises(RequestNotFound) as retry_error:
            service.retry(request_id=request_id, user_id=7)
        retry_errors.append(
            (str(retry_error.value), retry_error.value.error_code)
        )

    assert cancel_errors[0] == cancel_errors[1] == (
        "request_not_found",
        "request_not_found",
    )
    assert retry_errors[0] == retry_errors[1] == cancel_errors[0]


@pytest.mark.asyncio
async def test_cancel_terminal_is_idempotent_200_and_illegal_transition_is_409(
    phase4_db,
    frozen_utc_clock,
):
    from core.chat_request_service import RequestConflict

    worker = SimpleNamespace(cancel_running=AsyncMock(return_value=True))
    service, repository, identity_repository = _service_components(
        phase4_db,
        frozen_utc_clock,
        worker=worker,
    )
    terminal = service.submit(
        text="cancel once",
        attachments=[],
        reply_to_id=0,
        user_id=7,
    )

    first = await service.cancel(request_id=terminal.request_id, user_id=7)
    second = await service.cancel(request_id=terminal.request_id, user_id=7)

    assert first.status == "cancelled"
    assert second.status == "cancelled"

    failed = service.submit(
        text="failed terminal",
        attachments=[],
        reply_to_id=0,
        user_id=7,
    )
    claimed_failed = repository.claim_next(
        lease_owner="worker-failed-terminal",
        lease_seconds=30,
    )
    assert claimed_failed.context.request_id == failed.request_id
    repository.mark_failed(
        request_id=failed.request_id,
        lease_owner="worker-failed-terminal",
        error_code="pipeline_failed",
    )
    assert (
        await service.cancel(request_id=failed.request_id, user_id=7)
    ).status == "failed"

    completed = service.submit(
        text="completed terminal",
        attachments=[],
        reply_to_id=0,
        user_id=7,
    )
    claimed_completed = repository.claim_next(
        lease_owner="worker-completed-terminal",
        lease_seconds=30,
    )
    assert claimed_completed.context.request_id == completed.request_id
    from core.conversation_repository import ConversationRepository

    identity = identity_repository.resolve("desktop", "local")
    ConversationRepository(phase4_db, enabled=True).persist_turn(
        request_id=completed.request_id,
        user_id=7,
        actor_id=identity.actor_id,
        channel=identity.channel,
        channel_account_id=identity.channel_account_id,
        user_content="completed terminal",
        user_attachments=[],
        assistant_segments=["completed response"],
        conversation_id=completed.conversation_id,
        turn_id=completed.turn_id,
    )
    assert (
        await service.cancel(request_id=completed.request_id, user_id=7)
    ).status == "completed"

    queued = service.submit(
        text="not retryable",
        attachments=[],
        reply_to_id=0,
        user_id=7,
    )
    with pytest.raises(RequestConflict) as exc_info:
        service.retry(request_id=queued.request_id, user_id=7)
    assert exc_info.value.error_code == "request_state_conflict"
    assert exc_info.value.status == "queued"


@pytest.mark.asyncio
async def test_cancel_running_delegates_to_worker_and_returns_cancelling(
    phase4_db,
    frozen_utc_clock,
):
    worker = SimpleNamespace(cancel_running=AsyncMock(return_value=True))
    service, repository, _ = _service_components(
        phase4_db,
        frozen_utc_clock,
        worker=worker,
    )
    submitted = service.submit(
        text="running cancellation",
        attachments=[],
        reply_to_id=0,
        user_id=7,
    )
    claimed = repository.claim_next(
        lease_owner="worker-running-cancel",
        lease_seconds=30,
    )
    assert claimed.context.request_id == submitted.request_id

    view = await service.cancel(request_id=submitted.request_id, user_id=7)

    assert view.status == "cancelling"
    assert view.can_cancel is False
    worker.cancel_running.assert_awaited_once_with(submitted.request_id)


@pytest.mark.asyncio
async def test_cancel_running_without_worker_fails_closed_and_keeps_running(
    phase4_db,
    frozen_utc_clock,
):
    from core.chat_request_service import QueueUnavailable

    service, repository, identity_repository = _service_components(
        phase4_db,
        frozen_utc_clock,
    )
    submitted = service.submit(
        text="worker unavailable",
        attachments=[],
        reply_to_id=0,
        user_id=7,
    )
    repository.claim_next(
        lease_owner="worker-unavailable",
        lease_seconds=30,
    )

    with pytest.raises(QueueUnavailable) as exc_info:
        await service.cancel(request_id=submitted.request_id, user_id=7)

    identity = identity_repository.resolve("desktop", "local")
    row = repository.get_owned(
        request_id=submitted.request_id,
        actor_id=identity.actor_id,
    )
    assert exc_info.value.error_code == "queue_dependencies_unavailable"
    assert row["status"] == "running"


@pytest.mark.asyncio
async def test_cancel_uses_atomic_repository_status_when_queued_is_claimed(
    phase4_db,
    frozen_utc_clock,
):
    worker = SimpleNamespace(cancel_running=AsyncMock(return_value=True))
    service, repository, _ = _service_components(
        phase4_db,
        frozen_utc_clock,
        worker=worker,
    )
    submitted = service.submit(
        text="claim during cancel",
        attachments=[],
        reply_to_id=0,
        user_id=7,
    )
    original_request_cancel = repository.request_cancel

    def claim_then_cancel(**kwargs):
        claimed = repository.claim_next(
            lease_owner="worker-raced-claim",
            lease_seconds=30,
        )
        assert claimed.context.request_id == submitted.request_id
        return original_request_cancel(**kwargs)

    repository.request_cancel = claim_then_cancel

    view = await service.cancel(request_id=submitted.request_id, user_id=7)

    assert view.status == "cancelling"
    worker.cancel_running.assert_awaited_once_with(submitted.request_id)


@pytest.mark.asyncio
async def test_cancel_returns_terminal_race_without_calling_worker(
    phase4_db,
    frozen_utc_clock,
):
    worker = SimpleNamespace(
        cancel_running=AsyncMock(side_effect=AssertionError("must not cancel"))
    )
    service, repository, _ = _service_components(
        phase4_db,
        frozen_utc_clock,
        worker=worker,
    )
    submitted = service.submit(
        text="completion during cancel",
        attachments=[],
        reply_to_id=0,
        user_id=7,
    )
    claimed = repository.claim_next(
        lease_owner="worker-raced-completion",
        lease_seconds=30,
    )
    assert claimed.context.request_id == submitted.request_id
    original_request_cancel = repository.request_cancel

    def complete_then_cancel(**kwargs):
        with phase4_db.connection() as connection:
            connection.execute(
                """UPDATE requests
                   SET status = 'completed', completed_at = ?,
                       lease_owner = NULL, lease_expires_at = NULL
                   WHERE request_id = ?""",
                (frozen_utc_clock.now().isoformat(), submitted.request_id),
            )
            connection.execute(
                """UPDATE turns SET status = 'completed', completed_at = ?
                   WHERE turn_id = ?""",
                (frozen_utc_clock.now().isoformat(), submitted.turn_id),
            )
        return original_request_cancel(**kwargs)

    repository.request_cancel = complete_then_cancel

    view = await service.cancel(request_id=submitted.request_id, user_id=7)

    assert view.status == "completed"
    worker.cancel_running.assert_not_awaited()


@pytest.mark.parametrize("terminal_status", ["failed", "cancelled"])
def test_retry_only_failed_cancelled_and_returns_new_ids(
    phase4_db,
    frozen_utc_clock,
    terminal_status,
):
    service, repository, identity_repository = _service_components(
        phase4_db,
        frozen_utc_clock,
    )
    original = service.submit(
        text="retry source",
        attachments=[],
        reply_to_id=0,
        user_id=7,
    )
    identity = identity_repository.resolve("desktop", "local")
    if terminal_status == "failed":
        claimed = repository.claim_next(
            lease_owner="worker-retry",
            lease_seconds=30,
        )
        assert claimed.context.request_id == original.request_id
        repository.mark_failed(
            request_id=original.request_id,
            lease_owner="worker-retry",
            error_code="pipeline_failed",
        )
    else:
        assert repository.request_cancel(
            request_id=original.request_id,
            actor_id=identity.actor_id,
        ) == "cancelled"

    retried = service.retry(request_id=original.request_id, user_id=7)
    original_row = repository.get_owned(
        request_id=original.request_id,
        actor_id=identity.actor_id,
    )
    retry_row = repository.get_owned(
        request_id=retried.request_id,
        actor_id=identity.actor_id,
    )

    assert retried.request_id != original.request_id
    assert retried.turn_id != original.turn_id
    assert retried.conversation_id == original.conversation_id
    assert retried.status == "queued"
    assert original_row["status"] == terminal_status
    assert retry_row["retry_of_request_id"] == original.request_id


def test_status_view_redacts_input_effective_attachments_lease_owner_and_error_stack(
    phase4_db,
    frozen_utc_clock,
):
    service, repository, identity_repository = _service_components(
        phase4_db,
        frozen_utc_clock,
    )
    submitted = service.submit(
        text="sensitive input",
        attachments=[],
        reply_to_id=0,
        user_id=7,
    )
    claimed = repository.claim_next(
        lease_owner="internal-worker-name",
        lease_seconds=30,
    )
    assert claimed.context.request_id == submitted.request_id
    with phase4_db.connection() as connection:
        connection.execute(
            "UPDATE requests SET error = ? WHERE request_id = ?",
            ("internal stack details", submitted.request_id),
        )
    identity = identity_repository.resolve("desktop", "local")

    view = service.get(request_id=submitted.request_id, user_id=7)
    payload = asdict(view)
    internal = repository.get_owned(
        request_id=submitted.request_id,
        actor_id=identity.actor_id,
    )

    assert set(payload) == {
        "request_id",
        "conversation_id",
        "turn_id",
        "status",
        "error_code",
        "created_at",
        "started_at",
        "completed_at",
        "cancelled_at",
        "can_cancel",
        "can_retry",
        "user_message_id",
        "assistant_message_ids",
        "retry_of_request_id",
    }
    assert all(
        field not in payload
        for field in (
            "input_content",
            "effective_content",
            "attachments",
            "lease_owner",
            "lease_expires_at",
            "error",
        )
    )
    assert internal["lease_owner"] == "internal-worker-name"
    assert internal["error"] == "internal stack details"
    serialized = json.dumps(payload, ensure_ascii=False, default=list)
    assert "sensitive input" not in serialized
    assert "internal-worker-name" not in serialized
    assert "internal stack details" not in serialized
