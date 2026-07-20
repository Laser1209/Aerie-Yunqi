from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from core import api_server
from core.api_server import app
from core.chat_request_service import (
    InvalidChatInput,
    QueueUnavailable,
    RequestConflict,
    RequestNotFound,
    RequestStatusView,
)


client = TestClient(app)


def _view(
    request_id: str = "req_api_1",
    *,
    status: str = "queued",
    can_cancel: bool = True,
    can_retry: bool = False,
) -> RequestStatusView:
    return RequestStatusView(
        request_id=request_id,
        conversation_id="conv_api_1",
        turn_id="turn_api_1",
        status=status,
        error_code=None,
        created_at="2026-07-20T00:00:00+00:00",
        started_at=None,
        completed_at=None,
        cancelled_at=None,
        can_cancel=can_cancel,
        can_retry=can_retry,
        user_message_id=None,
        assistant_message_ids=(),
    )


def _service() -> SimpleNamespace:
    return SimpleNamespace(
        submit=MagicMock(return_value=_view()),
        get=MagicMock(return_value=_view(status="completed", can_cancel=False)),
        cancel=AsyncMock(return_value=_view(status="cancelled", can_cancel=False)),
        retry=MagicMock(return_value=_view("req_api_retry")),
    )


def _feature_flags(queue_enabled: bool) -> SimpleNamespace:
    def is_enabled(name: str) -> bool:
        if name == "chat_request_queue_v1":
            return queue_enabled
        return True

    return SimpleNamespace(is_enabled=is_enabled)


def _companion(
    *,
    queue_requested: bool,
    queue_ready: bool = True,
    service=None,
) -> SimpleNamespace:
    pipeline = SimpleNamespace(
        handle=AsyncMock(
            return_value={
                "reply": "嗯。",
                "user_msg_id": 1,
                "ai_msg_id": 2,
                "persisted": True,
            }
        )
    )
    return SimpleNamespace(
        feature_flags=_feature_flags(queue_requested),
        chat_request_queue_requested=queue_requested,
        chat_request_queue_ready=queue_ready,
        chat_request_queue_error=(
            None if queue_ready else "queue_dependencies_unavailable"
        ),
        chat_request_service=service,
        pipeline=pipeline,
    )


def _json(response):
    return response.status_code, response.json()


def test_api_queue_flag_on_returns_202_queued_without_waiting_pipeline(
    monkeypatch,
):
    service = _service()
    companion = _companion(
        queue_requested=True,
        queue_ready=True,
        service=service,
    )
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)

    response = client.post(
        "/api/chat/send",
        json={"text": "排队", "user_id": 3998874040},
    )

    assert response.status_code == 202
    data = response.json()
    assert data["request_id"] == "req_api_1"
    assert data["status"] == "queued"
    assert "reply" not in data
    companion.pipeline.handle.assert_not_called()
    service.submit.assert_called_once_with(
        text="排队",
        attachments=[],
        reply_to_id=0,
        user_id=3998874040,
    )


def test_api_queue_flag_off_preserves_legacy_200_shape_and_empty_400(
    monkeypatch,
):
    companion = _companion(queue_requested=False)
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)

    ok = client.post(
        "/api/chat/send",
        json={"text": "同步", "user_id": 3998874040},
    )
    empty = client.post("/api/chat/send", json={"text": "   "})

    assert ok.status_code == 200
    assert ok.json() == {
        "reply": "嗯。",
        "user_msg_id": 1,
        "ai_msg_id": 2,
        "reply_to_id": 0,
        "status": "ok",
        "persisted": True,
    }
    assert empty.status_code == 400
    companion.pipeline.handle.assert_awaited_once()


def test_api_pure_attachment_202_and_empty_no_attachment_400(
    monkeypatch,
    ready_attachment,
):
    service = _service()

    def submit(*, text, attachments, reply_to_id, user_id):
        if not text.strip() and not attachments:
            raise InvalidChatInput("empty_message")
        return _view()

    service.submit.side_effect = submit
    companion = _companion(
        queue_requested=True,
        queue_ready=True,
        service=service,
    )
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)

    pure_attachment = client.post(
        "/api/chat/send",
        json={"text": "", "attachments": [ready_attachment]},
    )
    empty = client.post("/api/chat/send", json={"text": ""})

    assert pure_attachment.status_code == 202
    assert pure_attachment.json()["status"] == "queued"
    assert _json(empty) == (400, {"error": "empty_message"})


def test_api_unready_queue_returns_503_not_legacy_fallback(monkeypatch):
    service = _service()
    companion = _companion(
        queue_requested=True,
        queue_ready=False,
        service=service,
    )
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)

    response = client.post("/api/chat/send", json={"text": "排队"})

    assert _json(response) == (
        503,
        {"error": "queue_dependencies_unavailable"},
    )
    service.submit.assert_not_called()
    companion.pipeline.handle.assert_not_called()


def test_api_get_cancel_retry_404_409_200_202_contracts(monkeypatch):
    service = _service()
    service.get.side_effect = [
        RequestNotFound(),
        _view(status="completed", can_cancel=False),
    ]
    service.cancel.side_effect = [
        RequestConflict(status="cancelling"),
        _view(status="cancelled", can_cancel=False),
    ]
    service.retry.return_value = _view("req_api_retry")
    companion = _companion(
        queue_requested=True,
        queue_ready=True,
        service=service,
    )
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)

    missing = client.get("/api/chat/requests/req_missing")
    found = client.get("/api/chat/requests/req_found")
    conflict = client.post("/api/chat/requests/req_conflict/cancel")
    cancelled = client.post("/api/chat/requests/req_cancel/cancel")
    retried = client.post("/api/chat/requests/req_failed/retry")

    assert _json(missing) == (404, {"error": "request_not_found"})
    assert found.status_code == 200
    assert found.json()["status"] == "completed"
    assert _json(conflict) == (
        409,
        {"error": "request_state_conflict", "status": "cancelling"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert retried.status_code == 202
    assert retried.json()["request_id"] == "req_api_retry"


def test_api_non_owner_never_leaks_request_existence(monkeypatch):
    service = _service()
    service.get.side_effect = RequestNotFound()
    companion = _companion(
        queue_requested=True,
        queue_ready=True,
        service=service,
    )
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)

    missing = client.get("/api/chat/requests/req_missing")
    foreign = client.get("/api/chat/requests/req_foreign")

    assert _json(missing) == _json(foreign)
    assert missing.status_code == 404


def test_api_server_never_constructs_chat_request_repository(monkeypatch):
    from core import chat_request_repository

    service = _service()
    companion = _companion(
        queue_requested=True,
        queue_ready=True,
        service=service,
    )
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)
    monkeypatch.setattr(
        chat_request_repository,
        "ChatRequestRepository",
        MagicMock(side_effect=AssertionError("api constructed repository")),
    )

    response = client.post("/api/chat/send", json={"text": "排队"})

    assert response.status_code == 202
    chat_request_repository.ChatRequestRepository.assert_not_called()


def test_status_response_redacts_internal_fields(monkeypatch):
    service = _service()
    companion = _companion(
        queue_requested=True,
        queue_ready=True,
        service=service,
    )
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)

    response = client.get("/api/chat/requests/req_api_1")

    assert response.status_code == 200
    data = response.json()
    assert set(data) == set(asdict(_view()).keys())
    assert "actor_id" not in data
    assert "input_content" not in data
    assert "effective_content" not in data
    assert "lease_owner" not in data
