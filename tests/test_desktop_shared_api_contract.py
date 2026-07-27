"""Cross-module HTTP contracts for the desktop-complete repair batch.

The fixtures in this module never use the repository's runtime database,
attachment directory, credentials, or model providers.  They deliberately
exercise the public FastAPI surface while injecting disposable services.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from core import api_server
from core.database import Database


client = TestClient(api_server.app)


@pytest.fixture
def isolated_database(monkeypatch, tmp_path):
    """Replace the import-time singleton with a disposable SQLite database."""

    previous = Database._instance
    Database._instance = None
    database = Database(tmp_path / "desktop-api.db")
    monkeypatch.setattr(api_server, "_db", database)
    try:
        yield database
    finally:
        Database._instance = previous


def _public_payload(response_json):
    if isinstance(response_json, dict) and isinstance(
        response_json.get("attachment"), dict
    ):
        return response_json["attachment"]
    return response_json


def _walk_keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key)
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_keys(nested)


def _assert_no_private_paths(payload, private_root: Path):
    forbidden_keys = {
        "path",
        "storage_path",
        "storage_relpath",
        "stored_name",
        "quarantine_path",
        "ready_path",
        "allowed_root",
        "allowedroot",
        "local_path",
        "localpath",
        "absolute_path",
        "absolutepath",
    }
    assert not ({key.lower() for key in _walk_keys(payload)} & forbidden_keys)
    serialized = json.dumps(payload, ensure_ascii=False).replace("\\\\", "/")
    assert str(private_root.resolve()).replace("\\", "/") not in serialized


class _RuntimeCompanion:
    def __init__(self, service):
        self.runtime_config_service = service

    def get_primary_user_selection(self):
        from core.primary_identity import PrimaryIdentitySelection

        value = self.runtime_config_service.get_effective("primary_user_id")
        if value in (None, ""):
            return None
        return PrimaryIdentitySelection(
            int(value),
            f"runtime_config:{self.runtime_config_service.source_for('primary_user_id')}",
        )


@pytest.fixture
def runtime_api(monkeypatch, tmp_path):
    from core.runtime_config import (
        DEFAULT_RUNTIME_CONFIG_SPECS,
        RuntimeConfigService,
        RuntimeConfigSpec,
    )

    secret = "sk-synthetic-runtime-secret-must-not-leak"
    service = RuntimeConfigService(
        state_path=tmp_path / "runtime" / "config.json",
        env={"AERIE_TEST_PRIVATE_KEY": secret},
        specs=(
            *DEFAULT_RUNTIME_CONFIG_SPECS,
            RuntimeConfigSpec(
                key="private_api_key",
                env_name="AERIE_TEST_PRIVATE_KEY",
                secret=True,
            ),
        ),
    )
    companion = _RuntimeCompanion(service)
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)
    return service, secret


def test_runtime_snapshot_patch_revision_and_secret_redaction(runtime_api):
    service, secret = runtime_api

    initial = client.get("/api/runtime/snapshot")
    assert initial.status_code == 200
    initial_payload = initial.json()
    assert initial_payload["revision"] == 0
    assert initial_payload["primaryUserId"] is None
    assert initial_payload["values"]["private_api_key"]["configured"] is True
    assert "effectiveValue" not in initial_payload["values"]["private_api_key"]
    assert secret not in json.dumps(initial_payload, ensure_ascii=False)

    accepted = client.patch(
        "/api/runtime/config",
        json={"expectedRevision": 0, "changes": {"primary_user_id": 77112233}},
    )
    assert accepted.status_code == 200
    accepted_payload = accepted.json()
    assert accepted_payload["accepted"] is True
    assert accepted_payload["revision"] == 1
    assert accepted_payload["primaryUserId"] == 77112233
    assert accepted_payload["primaryIdentity"] == {
        "primaryUserId": 77112233,
        "source": "runtime_config:local",
    }
    assert secret not in json.dumps(accepted_payload, ensure_ascii=False)
    assert service.state_path.is_file()

    conflict = client.patch(
        "/api/runtime/config",
        json={"expected_revision": 0, "changes": {"primary_user_id": 77112234}},
    )
    assert conflict.status_code == 409
    assert conflict.json() == {
        "accepted": False,
        "error": "revision_conflict",
        "errorCode": "revision_conflict",
        "expectedRevision": 0,
        "currentRevision": 1,
    }


@pytest.mark.parametrize("invalid_identity", [0, -1, True, False, "0", "-9", ""])
def test_runtime_patch_rejects_non_positive_identity(runtime_api, invalid_identity):
    response = client.patch(
        "/api/runtime/config",
        json={
            "expectedRevision": 0,
            "changes": {"primary_user_id": invalid_identity},
        },
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["accepted"] is False
    assert payload["errorCode"] == "validation_failed"
    assert payload["validationErrors"] == [
        {"key": "primary_user_id", "code": "invalid_positive_identity"}
    ]


class _IdentityResolver:
    def __init__(self, actor_id="actor_desktop_primary"):
        self.actor_id = actor_id

    def resolve(self, channel, channel_account_id):
        return SimpleNamespace(
            actor_id=self.actor_id,
            channel=channel,
            channel_account_id=channel_account_id,
        )


def _history_companion(repository, user_id=24680):
    selection = (
        None
        if user_id is None
        else SimpleNamespace(user_id=user_id, source="test")
    )
    return SimpleNamespace(
        conversation_repository=repository,
        identity_resolver=_IdentityResolver(),
        get_primary_user_selection=lambda: selection,
    )


def test_chat_history_page_uses_primary_identity_and_opaque_cursors(
    monkeypatch,
    isolated_database,
):
    from core.conversation_repository import ConversationRepository

    user_id = 24680
    for index in range(7):
        isolated_database.insert(
            "chat_log",
            {
                "user_id": user_id,
                "role": "user" if index % 2 == 0 else "assistant",
                "content": f"history-{index}",
            },
        )
    isolated_database.insert(
        "chat_log",
        {"user_id": 0, "role": "user", "content": "must-not-be-returned"},
    )
    repository = ConversationRepository(isolated_database, enabled=False)
    monkeypatch.setattr(
        api_server,
        "get_companion",
        lambda: _history_companion(repository, user_id),
    )

    latest = client.get("/api/chat/history/page?limit=3")
    assert latest.status_code == 200
    payload = latest.json()
    assert payload["primaryUserId"] == user_id
    assert [item["content"] for item in payload["items"]] == [
        "history-4",
        "history-5",
        "history-6",
    ]
    assert payload["hasMore"] is True
    assert isinstance(payload["nextCursor"], str) and payload["nextCursor"]
    assert all(item["cursor"] for item in payload["items"])

    older = client.get(
        "/api/chat/history/page",
        params={"limit": 3, "cursor": payload["nextCursor"], "direction": "older"},
    )
    assert older.status_code == 200
    assert [item["content"] for item in older.json()["items"]] == [
        "history-1",
        "history-2",
        "history-3",
    ]
    assert older.json()["primaryUserId"] == user_id

    malformed = client.get("/api/chat/history/page?cursor=not-an-opaque-cursor")
    assert malformed.status_code == 400
    assert malformed.json()["error"] == "invalid_cursor"


def test_chat_history_page_never_falls_back_to_zero_identity(monkeypatch):
    repository = SimpleNamespace(
        history_page=lambda **_kwargs: pytest.fail(
            "history repository must not be called without a primary identity"
        )
    )
    monkeypatch.setattr(
        api_server,
        "get_companion",
        lambda: _history_companion(repository, None),
    )

    missing = client.get("/api/chat/history/page")
    zero = client.get("/api/chat/history/page?user_id=0")

    assert missing.status_code == 409
    assert missing.json()["error"] == "primary_identity_unconfigured"
    assert zero.status_code == 400
    assert zero.json()["error"] == "invalid_user_id"


def test_chat_history_page_treats_dynamic_mock_identity_as_unconfigured(monkeypatch):
    companion = SimpleNamespace(
        get_primary_user_selection=MagicMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)

    response = client.get("/api/chat/history/page")

    assert response.status_code == 409
    assert response.json()["error"] == "primary_identity_unconfigured"


class _CleanScanner:
    def scan(self, path):
        return Path(path).is_file()


class _FailOnceWorker:
    def __init__(self):
        self.calls = 0

    def process(self, request):
        from core.desktop_attachments import AttachmentWorkerError

        self.calls += 1
        if self.calls == 1:
            raise AttachmentWorkerError("synthetic_parse_failure", "synthetic failure")
        content = "DESKTOP_ATTACHMENT_SENTINEL"
        return {
            "version": 1,
            "attachmentId": request["attachmentId"],
            "status": "ready",
            "chunks": [
                {
                    "content": content,
                    "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                }
            ],
            "metadata": {
                "synthetic": True,
                "contentExtracted": True,
                "contentKind": "extracted_text",
                "semanticStatus": "available",
            },
            "pythonVersion": "3.12-test",
            "truncated": False,
        }


def test_attachment_service_reuses_companion_owned_instance(monkeypatch, tmp_path):
    owned_service = object()
    companion = SimpleNamespace(
        db=object(),
        desktop_attachment_service=owned_service,
    )
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)
    monkeypatch.setenv(
        "AERIE_DESKTOP_ATTACHMENT_DIR",
        str(tmp_path / "compat-root"),
    )
    monkeypatch.setattr(api_server, "_desktop_attachment_service_instance", None)
    monkeypatch.setattr(api_server, "_desktop_attachment_service_key", None)

    assert api_server._desktop_attachment_service() is owned_service


def test_attachment_root_prefers_new_name_and_supports_compat_alias(
    monkeypatch,
    isolated_database,
    tmp_path,
):
    companion = SimpleNamespace(db=isolated_database)
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)
    preferred = tmp_path / "preferred-root"
    compatibility = tmp_path / "compatibility-root"
    monkeypatch.setenv("AERIE_DESKTOP_ATTACHMENT_ROOT", str(preferred))
    monkeypatch.setenv("AERIE_DESKTOP_ATTACHMENT_DIR", str(compatibility))
    monkeypatch.setattr(api_server, "_desktop_attachment_service_instance", None)
    monkeypatch.setattr(api_server, "_desktop_attachment_service_key", None)

    service = api_server._desktop_attachment_service()

    assert service.storage_root == preferred.resolve()

    monkeypatch.delenv("AERIE_DESKTOP_ATTACHMENT_ROOT")
    monkeypatch.setattr(api_server, "_desktop_attachment_service_instance", None)
    monkeypatch.setattr(api_server, "_desktop_attachment_service_key", None)

    compatibility_service = api_server._desktop_attachment_service()

    assert compatibility_service.storage_root == compatibility.resolve()


@pytest.fixture
def desktop_attachment_api(monkeypatch, isolated_database, tmp_path):
    from core.desktop_attachments import DesktopAttachmentService

    storage_root = tmp_path / "desktop-attachment-private"
    worker = _FailOnceWorker()
    service = DesktopAttachmentService(
        isolated_database,
        storage_root=storage_root,
        scanner=_CleanScanner(),
        worker=worker,
    )
    companion = SimpleNamespace(desktop_attachment_service=service)
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)
    # Keep this compatible with either a module-owned or Companion-owned
    # integration without coupling the contract to one implementation detail.
    monkeypatch.setattr(api_server, "_desktop_attachment_service", lambda: service)
    monkeypatch.setattr(
        api_server,
        "_schedule_attachment_processing",
        lambda selected_service, attachment_id: selected_service.process(attachment_id),
    )
    monkeypatch.setattr(api_server, "_attachment_service", service, raising=False)
    monkeypatch.setattr(
        api_server,
        "_get_desktop_attachment_service",
        lambda: service,
        raising=False,
    )
    monkeypatch.setattr(
        api_server,
        "_get_attachment_service",
        lambda: service,
        raising=False,
    )
    return service, storage_root, worker


def test_desktop_attachment_http_lifecycle_has_no_public_paths(
    desktop_attachment_api,
):
    service, storage_root, worker = desktop_attachment_api

    capabilities = client.get("/api/attachments/capabilities")
    assert capabilities.status_code == 200
    capability_payload = capabilities.json()
    assert capability_payload["version"] == 1
    assert capability_payload["states"] == [
        "queued",
        "processing",
        "ready",
        "failed",
        "quarantined",
        "unsupported",
    ]
    assert capability_payload["uploadEndpoint"] == "/api/attachments"
    by_extension = {
        extension: item
        for item in capability_payload["capabilities"]
        for extension in item["extensions"]
    }
    assert by_extension["png"]["semanticStatus"] == "unavailable"
    assert by_extension["png"]["readyRequiresContentExtracted"] is True
    _assert_no_private_paths(capability_payload, storage_root)

    upload = client.post(
        "/api/attachments",
        files={"file": ("sentinel.txt", b"synthetic upload", "text/plain")},
    )
    assert upload.status_code in {200, 201, 202}
    uploaded = _public_payload(upload.json())
    _assert_no_private_paths(upload.json(), storage_root)
    attachment_id = uploaded.get("attachmentId") or uploaded.get("id")
    assert attachment_id
    assert uploaded["name"] == "sentinel.txt"
    assert uploaded["state"] in {
        "queued",
        "processing",
        "failed",
        "ready",
    }

    internal = service.repository.get(attachment_id)
    assert internal is not None
    if internal["state"] == "queued":
        service.process(attachment_id)
    failed = service.repository.get(attachment_id)
    assert failed["state"] == "failed"

    status = client.get(f"/api/attachments/{attachment_id}")
    assert status.status_code == 200
    assert _public_payload(status.json())["state"] == "failed"
    assert _public_payload(status.json())["contentExtracted"] is False
    assert _public_payload(status.json())["semanticStatus"] == "unavailable"
    _assert_no_private_paths(status.json(), storage_root)

    retry = client.post(f"/api/attachments/{attachment_id}/retry")
    assert retry.status_code in {200, 202}
    assert _public_payload(retry.json())["state"] in {"queued", "processing", "ready"}
    assert worker.calls == 2
    _assert_no_private_paths(retry.json(), storage_root)

    ready_status = client.get(f"/api/attachments/{attachment_id}")
    assert ready_status.status_code == 200
    assert _public_payload(ready_status.json())["downloadUrl"] == (
        f"/api/attachments/{attachment_id}/download"
    )
    assert _public_payload(ready_status.json())["contentExtracted"] is True
    assert _public_payload(ready_status.json())["semanticStatus"] == "available"
    _assert_no_private_paths(ready_status.json(), storage_root)

    download = client.get(f"/api/attachments/{attachment_id}/download")
    assert download.status_code == 200
    assert download.content == b"synthetic upload"
    assert "sentinel.txt" in download.headers.get("content-disposition", "")

    deleted = client.delete(f"/api/attachments/{attachment_id}")
    assert deleted.status_code in {200, 204}
    assert service.repository.get(attachment_id) is None
    assert client.get(f"/api/attachments/{attachment_id}").status_code == 404


def test_chat_send_desktop_attachment_uses_only_attachment_id_boundary(
    monkeypatch,
    isolated_database,
    tmp_path,
):
    from core.desktop_attachments import DesktopAttachmentService

    storage_root = tmp_path / "desktop-attachment-private"
    service = DesktopAttachmentService(
        isolated_database,
        storage_root=storage_root,
        scanner=_CleanScanner(),
        worker=_FailOnceWorker(),
    )
    source = tmp_path / "source.txt"
    source.write_text("synthetic upload", encoding="utf-8")
    queued = service.ingest(source, original_name="sentinel.txt", mime_type="text/plain")
    service.process(queued["attachment_id"])
    service.retry(queued["attachment_id"])

    calls = []

    def legacy_extract(path, **_kwargs):
        calls.append(str(path))
        return "LEGACY_UPLOAD_MARKDOWN"

    captured = {}

    async def process_local_message_sync(message):
        captured["message"] = message
        return {"reply": "ok", "user_msg_id": 1, "ai_msg_id": 2}

    companion = SimpleNamespace(
        desktop_attachment_service=service,
        pipeline=object(),
        process_local_message_sync=AsyncMock(side_effect=process_local_message_sync),
    )
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "sentinel.txt").write_text("legacy", encoding="utf-8")
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)
    monkeypatch.setattr(api_server, "UPLOAD_DIR", str(uploads))
    monkeypatch.setattr("core.attachment_handler.extract_markdown", legacy_extract)

    response = client.post(
        "/api/chat/send",
        json={
            "text": "读取附件",
            "user_id": 3998874040,
            "attachments": [
                {
                    "attachmentId": queued["attachment_id"],
                    "id": queued["attachment_id"],
                    "url": "/uploads/sentinel.txt",
                    "markdown": "CLIENT_MARKDOWN",
                    "content": "CLIENT_CONTENT",
                    "path": "C:/secret.txt",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert calls == []
    [attachment] = captured["message"].attachments
    assert attachment == {
        "attachmentId": queued["attachment_id"],
        "id": queued["attachment_id"],
    }


def _emotion_companion(database, user_id, actor_id, sampled_at):
    from core.emotion_state_store import EmotionStateStore

    state_store = EmotionStateStore(database)
    emotion = SimpleNamespace(
        get_state=lambda requested_user_id, *, actor_id: {
            "label": "joy",
            "pad": {"P": 0.4, "A": 0.2, "D": 0.1},
        }
    )
    identity_resolver = _IdentityResolver(actor_id)
    return SimpleNamespace(
        emotion=emotion,
        state_store=state_store,
        identity_resolver=identity_resolver,
        _emotion_last_sampled_at=sampled_at,
        get_primary_identity=lambda: (
            user_id,
            identity_resolver.resolve("qq", str(user_id)),
        ),
    )


def test_explicit_emotion_state_exposes_freshness_fields(
    monkeypatch,
    isolated_database,
):
    user_id = 13579
    actor_id = "actor_emotion_primary"
    now_ms = int(time.time() * 1000)
    isolated_database.insert(
        "emotion_state_snapshot",
        {
            "ts": now_ms - 500,
            "user_id": user_id,
            "actor_id": actor_id,
            "pleasure": 0.4,
            "arousal": 0.2,
            "dominance": 0.1,
            "label": "joy",
        },
    )
    companion = _emotion_companion(
        isolated_database,
        user_id,
        actor_id,
        now_ms - 100,
    )
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)

    response = client.get(f"/api/emotion/state?user_id={user_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["primaryUserId"] == user_id
    assert payload["sampledAt"] == now_ms - 100
    assert payload["latestPersistedAt"] == now_ms - 500
    assert payload["serverNow"] >= payload["sampledAt"]
    assert payload["stale"] is False
    assert payload["label"] == "joy"


def test_explicit_emotion_history_returns_latest_5000_in_time_order(
    monkeypatch,
    isolated_database,
):
    user_id = 13579
    actor_id = "actor_emotion_primary"
    now_ms = int(time.time() * 1000)
    first_ts = now_ms - 10_000
    rows = [
        (
            first_ts + index,
            user_id,
            actor_id,
            index / 10_000,
            0.2,
            0.1,
            "joy",
        )
        for index in range(5005)
    ]
    isolated_database.executemany(
        """INSERT INTO emotion_state_snapshot
           (ts, user_id, actor_id, pleasure, arousal, dominance, label)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    sampled_at = rows[-1][0]
    companion = _emotion_companion(
        isolated_database,
        user_id,
        actor_id,
        sampled_at,
    )
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)

    response = client.get(
        "/api/emotion/history",
        params={"user_id": user_id, "window": "1h", "downsample": "false"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["primaryUserId"] == user_id
    assert payload["count"] == payload["raw_count"] == 5000
    timestamps = [item["ts"] for item in payload["items"]]
    assert timestamps == sorted(timestamps)
    assert timestamps[0] == rows[5][0]
    assert timestamps[-1] == rows[-1][0]
    assert payload["sampledAt"] == sampled_at
    assert payload["latestPersistedAt"] == rows[-1][0]
    assert payload["serverNow"] >= sampled_at
    assert payload["stale"] is False
