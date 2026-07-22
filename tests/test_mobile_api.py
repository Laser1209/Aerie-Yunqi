from __future__ import annotations

from fastapi.testclient import TestClient

from core.mobile_chat import MobileChatService
from core.mobile_gateway import create_mobile_app
from core.mobile_identity import MobileIdentityStore


def _client(tmp_path):
    store = MobileIdentityStore(
        tmp_path / "mobile.db",
        pepper="test-only-pepper-with-at-least-32-bytes",
    )
    store.create_account(
        username="owner",
        password="correct-horse-battery-staple",
        role="owner",
        actor_id="actor-primary",
        user_id=1001,
    )
    app = create_mobile_app(identity_store=store)
    return TestClient(app), store


def _login(client, store):
    code = store.create_pairing_code("owner")
    response = client.post(
        "/api/mobile/v1/auth/login",
        json={
            "username": "owner",
            "password": "correct-horse-battery-staple",
            "deviceName": "V2516A",
            "pairingCode": code,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_mobile_auth_me_devices_refresh_and_logout(tmp_path):
    client, store = _client(tmp_path)
    tokens = _login(client, store)
    headers = {"Authorization": f"Bearer {tokens['accessToken']}"}

    me = client.get("/api/mobile/v1/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["role"] == "owner"
    assert me.json()["actorId"] == "actor-primary"

    devices = client.get("/api/mobile/v1/devices", headers=headers)
    assert devices.status_code == 200
    assert devices.json()["items"][0]["deviceName"] == "V2516A"

    refreshed = client.post(
        "/api/mobile/v1/auth/refresh",
        json={"refreshToken": tokens["refreshToken"]},
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["refreshToken"] != tokens["refreshToken"]

    logout = client.post("/api/mobile/v1/auth/logout", headers=headers)
    assert logout.status_code == 204
    denied = client.get("/api/mobile/v1/me", headers=headers)
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "invalid_token"
    assert denied.json()["error"]["requestId"].startswith("req_")


def test_invalid_login_and_validation_use_stable_error_shape(tmp_path):
    client, store = _client(tmp_path)

    invalid = client.post(
        "/api/mobile/v1/auth/login",
        json={
            "username": "owner",
            "password": "wrong-password-value",
            "deviceName": "V2516A",
            "pairingCode": store.create_pairing_code("owner"),
        },
    )
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "invalid_credentials"

    malformed = client.post("/api/mobile/v1/auth/login", json={})
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "invalid_request"


def test_gateway_route_allowlist_excludes_desktop_management_api(tmp_path):
    client, _ = _client(tmp_path)
    paths = {route.path for route in client.app.routes}

    assert paths == {
        "/api/mobile/v1/health",
        "/api/mobile/v1/auth/login",
        "/api/mobile/v1/auth/refresh",
        "/api/mobile/v1/auth/logout",
        "/api/mobile/v1/me",
        "/api/mobile/v1/devices",
        "/api/mobile/v1/devices/{device_id}",
        "/api/mobile/v1/messages",
        "/api/mobile/v1/requests",
        "/api/mobile/v1/requests/{request_id}",
        "/api/mobile/v1/requests/{request_id}/cancel",
        "/api/mobile/v1/requests/{request_id}/retry",
        "/api/mobile/v1/events",
    }
    for path in ("/api/system/restart", "/api/brain/shell", "/docs"):
        assert client.get(path).status_code == 404


def test_mobile_persistent_chat_api_is_idempotent(phase4_db, tmp_path):
    client, store = _client(tmp_path)
    with phase4_db.connection() as conn:
        conn.execute("INSERT INTO actors(actor_id) VALUES ('actor-primary')")
    client.app.state.chat_service = MobileChatService(phase4_db, store)
    tokens = _login(client, store)
    headers = {"Authorization": f"Bearer {tokens['accessToken']}"}
    payload = {
        "clientRequestId": "00000000-0000-4000-8000-000000000123",
        "text": "hello from Android",
        "fileIds": [],
    }

    first = client.post("/api/mobile/v1/requests", json=payload, headers=headers)
    second = client.post("/api/mobile/v1/requests", json=payload, headers=headers)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["requestId"] == second.json()["requestId"]
    status = client.get(
        f"/api/mobile/v1/requests/{first.json()['requestId']}",
        headers=headers,
    )
    assert status.status_code == 200
    assert status.json()["status"] == "queued"

    invalid_cursor = client.get(
        "/api/mobile/v1/events",
        headers={**headers, "Last-Event-ID": "not-an-event"},
    )
    assert invalid_cursor.status_code == 400
    assert invalid_cursor.json()["error"]["code"] == "invalid_cursor"
