from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import subprocess
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from core.mobile_chat import MobileChatService
from core.mobile_files import MobileFileService, WindowsDefenderScanner
from core.mobile_gateway import create_mobile_app
from core.mobile_identity import MobileIdentityStore


PEPPER = "test-only-pepper-with-at-least-32-bytes"
PART_SIZE = 4 * 1024 * 1024


class RecordingScanner:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.paths = []

    def scan(self, path):
        self.paths.append(path)
        return self.allowed


@dataclass
class FileApi:
    client: TestClient
    store: MobileIdentityStore
    service: MobileFileService
    scanner: RecordingScanner
    owner_headers: dict[str, str]
    guest_headers: dict[str, str]
    owner_account_id: str
    guest_account_id: str
    owner_grant_id: str
    owner_directory: object
    storage_root: object


def _login(client, store, username):
    code = store.create_pairing_code(username)
    response = client.post(
        "/api/mobile/v1/auth/login",
        json={
            "username": username,
            "password": "correct-horse-battery-staple",
            "deviceName": f"{username}-device",
            "pairingCode": code,
        },
    )
    assert response.status_code == 200
    return {
        "Authorization": f"Bearer {response.json()['accessToken']}"
    }


@pytest.fixture
def file_api(tmp_path):
    store = MobileIdentityStore(
        tmp_path / "mobile.db",
        pepper=PEPPER,
    )
    owner = store.create_account(
        username="owner",
        password="correct-horse-battery-staple",
        role="owner",
        actor_id="actor-owner",
        user_id=1001,
    )
    guest = store.create_account(
        username="guest-one",
        password="correct-horse-battery-staple",
        role="guest",
        actor_id="actor-guest",
        user_id=2001,
    )
    scanner = RecordingScanner()
    storage_root = tmp_path / "mobile-files"
    service = MobileFileService(
        store.db_path,
        storage_root=storage_root,
        scanner=scanner,
    )
    owner_directory = tmp_path / "owner-authorized"
    owner_grant_id = service.register_directory_grant(
        account_id=owner.account_id,
        directory=owner_directory,
        allow_read=True,
        allow_upload=True,
        allow_download=True,
    )
    client = TestClient(
        create_mobile_app(identity_store=store, file_service=service)
    )
    return FileApi(
        client=client,
        store=store,
        service=service,
        scanner=scanner,
        owner_headers=_login(client, store, "owner"),
        guest_headers=_login(client, store, "guest-one"),
        owner_account_id=owner.account_id,
        guest_account_id=guest.account_id,
        owner_grant_id=owner_grant_id,
        owner_directory=owner_directory,
        storage_root=storage_root,
    )


def _upload_payload(
    content: bytes,
    *,
    name: str = "report.pdf",
    mime_type: str = "application/pdf",
    client_upload_id: str | None = None,
    directory_grant_id: str | None = None,
):
    payload = {
        "clientUploadId": client_upload_id or str(uuid.uuid4()),
        "fileName": name,
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "mimeType": mime_type,
    }
    if directory_grant_id is not None:
        payload["directoryGrantId"] = directory_grant_id
    return payload


def _create_upload(api, headers, payload):
    return api.client.post(
        "/api/mobile/v1/files/uploads",
        json=payload,
        headers=headers,
    )


def _put_part(api, headers, upload_id, number, content):
    return api.client.put(
        f"/api/mobile/v1/files/uploads/{upload_id}/parts/{number}",
        content=content,
        headers={
            **headers,
            "Content-Type": "application/octet-stream",
            "X-Part-SHA256": hashlib.sha256(content).hexdigest(),
        },
    )


def _complete(api, headers, upload_id):
    return api.client.post(
        f"/api/mobile/v1/files/uploads/{upload_id}/complete",
        headers=headers,
    )


def test_owner_upload_is_idempotent_resumable_and_range_downloadable(file_api):
    content = b"%PDF-1.7\nAerie mobile file contract\n%%EOF\n"
    client_id = str(uuid.uuid4())
    payload = _upload_payload(
        content,
        client_upload_id=client_id,
        directory_grant_id=file_api.owner_grant_id,
    )

    created = _create_upload(file_api, file_api.owner_headers, payload)
    repeated = _create_upload(file_api, file_api.owner_headers, payload)

    assert created.status_code == 201
    assert repeated.status_code == 200
    assert repeated.json()["uploadId"] == created.json()["uploadId"]
    assert created.json()["partSize"] == PART_SIZE
    assert created.json()["partCount"] == 1
    assert created.json()["uploadedParts"] == []
    upload_id = created.json()["uploadId"]

    first_part = _put_part(
        file_api,
        file_api.owner_headers,
        upload_id,
        1,
        content,
    )
    repeated_part = _put_part(
        file_api,
        file_api.owner_headers,
        upload_id,
        1,
        content,
    )
    resumed = file_api.client.get(
        f"/api/mobile/v1/files/uploads/{upload_id}",
        headers=file_api.owner_headers,
    )

    assert first_part.status_code == 204
    assert repeated_part.status_code == 204
    assert resumed.status_code == 200
    assert resumed.json()["uploadedParts"] == [1]

    stored_part = (
        file_api.storage_root
        / ".quarantine"
        / upload_id
        / "part-00000001"
    )
    stored_part.unlink()
    recovered_part = _put_part(
        file_api,
        file_api.owner_headers,
        upload_id,
        1,
        content,
    )
    assert recovered_part.status_code == 204
    assert stored_part.read_bytes() == content

    completed = _complete(file_api, file_api.owner_headers, upload_id)
    completed_again = _complete(file_api, file_api.owner_headers, upload_id)

    assert completed.status_code == 200
    assert completed.json()["status"] == "ready"
    assert completed_again.status_code == 200
    assert completed_again.json()["fileId"] == completed.json()["fileId"]
    assert len(file_api.scanner.paths) == 1
    file_id = completed.json()["fileId"]

    metadata = file_api.client.get(
        f"/api/mobile/v1/files/{file_id}",
        headers=file_api.owner_headers,
    )
    listing = file_api.client.get(
        "/api/mobile/v1/files",
        headers=file_api.owner_headers,
    )
    full = file_api.client.get(
        f"/api/mobile/v1/files/{file_id}/content",
        headers=file_api.owner_headers,
    )
    partial = file_api.client.get(
        f"/api/mobile/v1/files/{file_id}/content",
        headers={**file_api.owner_headers, "Range": "bytes=2-8"},
    )
    suffix = file_api.client.get(
        f"/api/mobile/v1/files/{file_id}/content",
        headers={**file_api.owner_headers, "Range": "bytes=-5"},
    )

    assert metadata.status_code == 200
    assert "path" not in metadata.json()
    assert "storedPath" not in metadata.json()
    assert listing.json()["items"] == [metadata.json()]
    assert full.status_code == 200
    assert full.content == content
    assert full.headers["accept-ranges"] == "bytes"
    assert full.headers["etag"] == f'"{hashlib.sha256(content).hexdigest()}"'
    assert "report.pdf" in full.headers["content-disposition"]
    assert str(file_api.owner_directory) not in full.headers["content-disposition"]
    assert partial.status_code == 206
    assert partial.content == content[2:9]
    assert partial.headers["content-range"] == f"bytes 2-8/{len(content)}"
    assert suffix.status_code == 206
    assert suffix.content == content[-5:]

    invalid_ranges = ("bytes=999-", "bytes=0-1,4-5", "items=0-1")
    for value in invalid_ranges:
        denied = file_api.client.get(
            f"/api/mobile/v1/files/{file_id}/content",
            headers={**file_api.owner_headers, "Range": value},
        )
        assert denied.status_code == 416
        assert denied.headers["content-range"] == f"bytes */{len(content)}"

    with sqlite3.connect(file_api.store.db_path) as conn:
        audit_events = {
            row[0]
            for row in conn.execute(
                """SELECT event_type FROM mobile_audit
                   WHERE account_id = ? AND event_type LIKE 'file.%'""",
                (file_api.owner_account_id,),
            )
        }
    assert {
        "file.upload.created",
        "file.upload.completed",
        "file.downloaded",
    }.issubset(audit_events)


def test_guest_inbox_and_owner_grant_are_strictly_isolated(file_api):
    content = b"hello from guest\n"
    guest_payload = _upload_payload(
        content,
        name="note.txt",
        mime_type="text/plain",
    )
    guest_created = _create_upload(
        file_api,
        file_api.guest_headers,
        guest_payload,
    )
    assert guest_created.status_code == 201
    upload_id = guest_created.json()["uploadId"]
    assert _put_part(
        file_api,
        file_api.guest_headers,
        upload_id,
        1,
        content,
    ).status_code == 204
    ready = _complete(file_api, file_api.guest_headers, upload_id)
    assert ready.status_code == 200
    file_id = ready.json()["fileId"]

    with sqlite3.connect(file_api.store.db_path) as conn:
        stored_path = conn.execute(
            "SELECT stored_path FROM mobile_files WHERE file_id = ?",
            (file_id,),
        ).fetchone()[0]
    expected_parent = (
        file_api.storage_root / file_api.guest_account_id / "inbox"
    ).resolve()
    assert expected_parent in type(expected_parent)(stored_path).resolve().parents
    assert type(expected_parent)(stored_path).name.startswith("file_")

    owner_denied = file_api.client.get(
        f"/api/mobile/v1/files/{file_id}",
        headers=file_api.owner_headers,
    )
    assert owner_denied.status_code == 404
    assert owner_denied.json()["error"]["code"] == "file_not_found"

    owner_without_grant = _create_upload(
        file_api,
        file_api.owner_headers,
        _upload_payload(content, name="note.txt", mime_type="text/plain"),
    )
    assert owner_without_grant.status_code == 404
    assert owner_without_grant.json()["error"]["code"] == "file_not_found"

    guest_with_grant = _create_upload(
        file_api,
        file_api.guest_headers,
        _upload_payload(
            content,
            name="note.txt",
            mime_type="text/plain",
            directory_grant_id=file_api.owner_grant_id,
        ),
    )
    assert guest_with_grant.status_code == 422
    assert guest_with_grant.json()["error"]["code"] == "invalid_file"


def test_multi_part_upload_resumes_out_of_order_and_streams_across_boundary(
    file_api,
):
    content = b"a" * PART_SIZE + b"second-part-tail"
    created = _create_upload(
        file_api,
        file_api.owner_headers,
        _upload_payload(
            content,
            name="large.txt",
            mime_type="text/plain",
            directory_grant_id=file_api.owner_grant_id,
        ),
    )
    assert created.status_code == 201
    assert created.json()["partCount"] == 2
    upload_id = created.json()["uploadId"]

    assert _put_part(
        file_api,
        file_api.owner_headers,
        upload_id,
        2,
        content[PART_SIZE:],
    ).status_code == 204
    resumed = file_api.client.get(
        f"/api/mobile/v1/files/uploads/{upload_id}",
        headers=file_api.owner_headers,
    )
    assert resumed.json()["uploadedParts"] == [2]
    assert _put_part(
        file_api,
        file_api.owner_headers,
        upload_id,
        1,
        content[:PART_SIZE],
    ).status_code == 204

    completed = _complete(file_api, file_api.owner_headers, upload_id)
    assert completed.status_code == 200
    file_id = completed.json()["fileId"]
    boundary = file_api.client.get(
        f"/api/mobile/v1/files/{file_id}/content",
        headers={
            **file_api.owner_headers,
            "Range": f"bytes={PART_SIZE - 2}-",
        },
    )
    assert boundary.status_code == 206
    assert boundary.content == content[PART_SIZE - 2 :]
    assert boundary.headers["content-range"] == (
        f"bytes {PART_SIZE - 2}-{len(content) - 1}/{len(content)}"
    )


def test_upload_rejects_limits_part_conflicts_hash_spoofing_and_scan_failure(
    file_api,
):
    too_large = _create_upload(
        file_api,
        file_api.owner_headers,
        {
            **_upload_payload(
                b"x",
                name="large.txt",
                mime_type="text/plain",
                directory_grant_id=file_api.owner_grant_id,
            ),
            "size": 50 * 1024 * 1024 + 1,
        },
    )
    assert too_large.status_code == 413
    assert too_large.json()["error"]["code"] == "file_too_large"

    content = b"%PDF-1.7\nvalid\n"
    created = _create_upload(
        file_api,
        file_api.owner_headers,
        _upload_payload(
            content,
            directory_grant_id=file_api.owner_grant_id,
        ),
    )
    upload_id = created.json()["uploadId"]
    assert _put_part(
        file_api,
        file_api.owner_headers,
        upload_id,
        1,
        content,
    ).status_code == 204
    conflicting = _put_part(
        file_api,
        file_api.owner_headers,
        upload_id,
        1,
        content + b"different",
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["error"]["code"] == "file_conflict"
    assert file_api.client.delete(
        f"/api/mobile/v1/files/uploads/{upload_id}",
        headers=file_api.owner_headers,
    ).status_code == 204

    missing_content = b"a" * PART_SIZE + b"end"
    missing = _create_upload(
        file_api,
        file_api.owner_headers,
        _upload_payload(
            missing_content,
            name="large.txt",
            mime_type="text/plain",
            directory_grant_id=file_api.owner_grant_id,
        ),
    )
    missing_id = missing.json()["uploadId"]
    assert _put_part(
        file_api,
        file_api.owner_headers,
        missing_id,
        1,
        missing_content[:PART_SIZE],
    ).status_code == 204
    incomplete = _complete(file_api, file_api.owner_headers, missing_id)
    assert incomplete.status_code == 409
    assert incomplete.json()["error"]["code"] == "file_conflict"
    assert file_api.client.delete(
        f"/api/mobile/v1/files/uploads/{missing_id}",
        headers=file_api.owner_headers,
    ).status_code == 204

    declared = b"%PDF-1.7\ndeclared\n"
    altered = declared[:-2] + b"X\n"
    wrong_hash = _create_upload(
        file_api,
        file_api.owner_headers,
        _upload_payload(
            declared,
            directory_grant_id=file_api.owner_grant_id,
        ),
    )
    wrong_hash_id = wrong_hash.json()["uploadId"]
    assert _put_part(
        file_api,
        file_api.owner_headers,
        wrong_hash_id,
        1,
        altered,
    ).status_code == 204
    hash_conflict = _complete(
        file_api,
        file_api.owner_headers,
        wrong_hash_id,
    )
    assert hash_conflict.status_code == 409
    assert hash_conflict.json()["error"]["code"] == "file_conflict"
    assert file_api.client.delete(
        f"/api/mobile/v1/files/uploads/{wrong_hash_id}",
        headers=file_api.owner_headers,
    ).status_code == 204

    spoofed = b"plain text pretending to be a PDF"
    spoof = _create_upload(
        file_api,
        file_api.owner_headers,
        _upload_payload(
            spoofed,
            directory_grant_id=file_api.owner_grant_id,
        ),
    )
    spoof_id = spoof.json()["uploadId"]
    assert _put_part(
        file_api,
        file_api.owner_headers,
        spoof_id,
        1,
        spoofed,
    ).status_code == 204
    denied_type = _complete(file_api, file_api.owner_headers, spoof_id)
    assert denied_type.status_code == 415
    assert denied_type.json()["error"]["code"] == "file_type_denied"
    assert file_api.client.delete(
        f"/api/mobile/v1/files/uploads/{spoof_id}",
        headers=file_api.owner_headers,
    ).status_code == 204

    scan_content = b"scan me\n"
    scan = _create_upload(
        file_api,
        file_api.owner_headers,
        _upload_payload(
            scan_content,
            name="scan.txt",
            mime_type="text/plain",
            directory_grant_id=file_api.owner_grant_id,
        ),
    )
    scan_id = scan.json()["uploadId"]
    assert _put_part(
        file_api,
        file_api.owner_headers,
        scan_id,
        1,
        scan_content,
    ).status_code == 204
    file_api.scanner.allowed = False
    rejected_scan = _complete(file_api, file_api.owner_headers, scan_id)
    assert rejected_scan.status_code == 422
    assert rejected_scan.json()["error"]["code"] == "file_scan_failed"
    with sqlite3.connect(file_api.store.db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM mobile_files WHERE upload_id = ?",
            (scan_id,),
        ).fetchone()[0] == 0


def test_upload_limit_cancel_expiry_and_filename_validation(tmp_path):
    now = datetime(2026, 7, 23, tzinfo=timezone.utc)
    store = MobileIdentityStore(tmp_path / "mobile.db", pepper=PEPPER)
    guest = store.create_account(
        username="guest-one",
        password="correct-horse-battery-staple",
        role="guest",
        actor_id="actor-guest",
        user_id=2001,
    )
    scanner = RecordingScanner()
    service = MobileFileService(
        store.db_path,
        storage_root=tmp_path / "files",
        scanner=scanner,
        clock=lambda: now,
    )
    client = TestClient(
        create_mobile_app(identity_store=store, file_service=service)
    )
    headers = _login(client, store, "guest-one")

    for index in range(2):
        response = _create_upload(
            FileApi(
                client,
                store,
                service,
                scanner,
                {},
                headers,
                "",
                guest.account_id,
                "",
                tmp_path,
                tmp_path / "files",
            ),
            headers,
            _upload_payload(
                f"file-{index}".encode(),
                name=f"file-{index}.txt",
                mime_type="text/plain",
            ),
        )
        assert response.status_code == 201

    third = client.post(
        "/api/mobile/v1/files/uploads",
        json=_upload_payload(
            b"third",
            name="third.txt",
            mime_type="text/plain",
        ),
        headers=headers,
    )
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "rate_limited"

    first_upload = client.get(
        "/api/mobile/v1/files/uploads/does-not-exist",
        headers=headers,
    )
    assert first_upload.status_code == 404

    with sqlite3.connect(store.db_path) as conn:
        upload_ids = [
            row[0]
            for row in conn.execute(
                "SELECT upload_id FROM mobile_uploads ORDER BY rowid"
            )
        ]
    upload_id, expiring_upload_id = upload_ids
    cancelled = client.delete(
        f"/api/mobile/v1/files/uploads/{upload_id}",
        headers=headers,
    )
    assert cancelled.status_code == 204
    assert not (tmp_path / "files" / ".quarantine" / upload_id).exists()

    now += timedelta(hours=25)
    expired = client.get(
        f"/api/mobile/v1/files/uploads/{expiring_upload_id}",
        headers=headers,
    )
    assert expired.status_code == 404
    assert not (
        tmp_path / "files" / ".quarantine" / expiring_upload_id
    ).exists()

    for name in ("../escape.txt", "folder/file.txt", "folder\\file.txt"):
        invalid = client.post(
            "/api/mobile/v1/files/uploads",
            json=_upload_payload(
                b"safe",
                name=name,
                mime_type="text/plain",
            ),
            headers=headers,
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "invalid_file"


def test_ooxml_signature_must_match_extension_and_mime(file_api):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<document />")
    content = buffer.getvalue()
    payload = _upload_payload(
        content,
        name="document.docx",
        mime_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        directory_grant_id=file_api.owner_grant_id,
    )
    created = _create_upload(file_api, file_api.owner_headers, payload)
    upload_id = created.json()["uploadId"]
    assert _put_part(
        file_api,
        file_api.owner_headers,
        upload_id,
        1,
        content,
    ).status_code == 204
    assert _complete(
        file_api,
        file_api.owner_headers,
        upload_id,
    ).status_code == 200


def test_ready_file_ids_enter_chat_and_remain_account_scoped(
    file_api,
    phase4_db,
):
    content = b"attachment-only request\n"
    created = _create_upload(
        file_api,
        file_api.guest_headers,
        _upload_payload(content, name="brief.txt", mime_type="text/plain"),
    )
    upload_id = created.json()["uploadId"]
    assert _put_part(
        file_api,
        file_api.guest_headers,
        upload_id,
        1,
        content,
    ).status_code == 204
    ready = _complete(file_api, file_api.guest_headers, upload_id)
    assert ready.status_code == 200
    file_id = ready.json()["fileId"]

    with phase4_db.connection() as conn:
        conn.execute("INSERT INTO actors(actor_id) VALUES ('actor-owner')")
        conn.execute("INSERT INTO actors(actor_id) VALUES ('actor-guest')")
    chat = MobileChatService(
        phase4_db,
        file_api.store,
        file_service=file_api.service,
    )
    client = TestClient(
        create_mobile_app(
            identity_store=file_api.store,
            chat_service=chat,
            file_service=file_api.service,
        )
    )

    submitted = client.post(
        "/api/mobile/v1/requests",
        json={
            "clientRequestId": "00000000-0000-4000-8000-000000000501",
            "text": "",
            "fileIds": [file_id],
        },
        headers=file_api.guest_headers,
    )
    assert submitted.status_code == 202
    request_id = submitted.json()["requestId"]
    with phase4_db.connection() as conn:
        row = conn.execute(
            """SELECT actor_id, input_content, effective_content, attachments
               FROM requests WHERE request_id = ?""",
            (request_id,),
        ).fetchone()
    assert row["actor_id"] == "actor-guest"
    assert row["input_content"] == ""
    assert row["effective_content"]
    attachments = json.loads(row["attachments"])
    assert len(attachments) == 1
    assert attachments[0]["name"] == "brief.txt"
    assert attachments[0]["state"] == "ready"
    assert attachments[0]["sha256"] == hashlib.sha256(content).hexdigest()
    assert "path" not in attachments[0]
    assert "storedPath" not in attachments[0]

    denied = client.post(
        "/api/mobile/v1/requests",
        json={
            "clientRequestId": "00000000-0000-4000-8000-000000000502",
            "text": "try another account file",
            "fileIds": [file_id],
        },
        headers=file_api.owner_headers,
    )
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "file_not_found"


def test_computer_outputs_are_registered_into_owner_and_guest_boundaries(file_api):
    owner_source = file_api.storage_root / "generated-source.pdf"
    owner_source.parent.mkdir(parents=True, exist_ok=True)
    owner_source.write_bytes(b"%PDF-1.7\ncomputer output\n%%EOF\n")
    owner_file = file_api.service.register_computer_output(
        account_id=file_api.owner_account_id,
        source_path=owner_source,
        file_name="generated.pdf",
        mime_type="application/pdf",
        directory_grant_id=file_api.owner_grant_id,
    )

    guest_source = file_api.storage_root / "guest-source.txt"
    guest_source.write_text("guest output\n", encoding="utf-8")
    guest_file = file_api.service.register_computer_output(
        account_id=file_api.guest_account_id,
        source_path=guest_source,
        file_name="answer.txt",
        mime_type="text/plain",
    )

    with sqlite3.connect(file_api.store.db_path) as conn:
        owner_path = conn.execute(
            "SELECT stored_path FROM mobile_files WHERE file_id = ?",
            (owner_file["fileId"],),
        ).fetchone()[0]
        guest_path = conn.execute(
            "SELECT stored_path FROM mobile_files WHERE file_id = ?",
            (guest_file["fileId"],),
        ).fetchone()[0]

    owner_path = type(file_api.owner_directory)(owner_path).resolve()
    guest_path = type(file_api.storage_root)(guest_path).resolve()
    assert file_api.owner_directory.resolve() in owner_path.parents
    assert owner_path.name.startswith("file_")
    assert (
        file_api.storage_root
        / file_api.guest_account_id
        / "outbox"
    ).resolve() in guest_path.parents
    assert guest_path.name.startswith("file_")
    assert owner_source.exists()
    assert guest_source.exists()
    assert len(file_api.scanner.paths) == 2
    assert all(
        (file_api.storage_root / ".quarantine").resolve()
        in path.resolve().parents
        for path in file_api.scanner.paths
    )
    assert owner_source not in file_api.scanner.paths
    assert guest_source not in file_api.scanner.paths

    with sqlite3.connect(file_api.store.db_path) as conn:
        assert conn.execute(
            """SELECT COUNT(*) FROM mobile_audit
               WHERE event_type = 'file.output.registered'
                 AND outcome = 'success'"""
        ).fetchone()[0] == 2

    owner_cannot_read_guest = file_api.client.get(
        f"/api/mobile/v1/files/{guest_file['fileId']}",
        headers=file_api.owner_headers,
    )
    assert owner_cannot_read_guest.status_code == 404


def test_revoked_owner_directory_grant_removes_file_visibility(file_api):
    content = b"%PDF-1.7\nrevoked grant\n%%EOF\n"
    created = _create_upload(
        file_api,
        file_api.owner_headers,
        _upload_payload(
            content,
            directory_grant_id=file_api.owner_grant_id,
        ),
    )
    upload_id = created.json()["uploadId"]
    assert _put_part(
        file_api,
        file_api.owner_headers,
        upload_id,
        1,
        content,
    ).status_code == 204
    ready = _complete(file_api, file_api.owner_headers, upload_id)
    file_id = ready.json()["fileId"]

    with sqlite3.connect(file_api.store.db_path) as conn:
        conn.execute(
            "UPDATE mobile_directory_grants SET enabled = 0 WHERE grant_id = ?",
            (file_api.owner_grant_id,),
        )

    metadata = file_api.client.get(
        f"/api/mobile/v1/files/{file_id}",
        headers=file_api.owner_headers,
    )
    listing = file_api.client.get(
        "/api/mobile/v1/files",
        headers=file_api.owner_headers,
    )
    download = file_api.client.get(
        f"/api/mobile/v1/files/{file_id}/content",
        headers=file_api.owner_headers,
    )
    assert metadata.status_code == 404
    assert listing.status_code == 200
    assert listing.json()["items"] == []
    assert download.status_code == 404


def test_windows_defender_scanner_fails_closed_when_unavailable_or_timed_out(
    tmp_path,
):
    sample = tmp_path / "sample.txt"
    sample.write_text("scan me", encoding="utf-8")

    unavailable = WindowsDefenderScanner(
        executable=tmp_path / "missing-MpCmdRun.exe",
    )
    assert unavailable.scan(sample) is False

    executable = tmp_path / "MpCmdRun.exe"
    executable.write_bytes(b"test double")
    calls = []

    def timeout_runner(command, **kwargs):
        calls.append((command, kwargs))
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    timed_out = WindowsDefenderScanner(
        executable=executable,
        timeout_seconds=1,
        runner=timeout_runner,
    )
    assert timed_out.scan(sample) is False
    assert calls[0][0][0] == str(executable)
    assert calls[0][0][calls[0][0].index("-File") + 1] == str(sample.resolve())
    assert calls[0][1]["shell"] is False
