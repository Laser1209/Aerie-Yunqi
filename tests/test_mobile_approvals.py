"""Contracts for owner-only mobile approval routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.mobile_gateway import create_mobile_app
from core.mobile_identity import MobileIdentityStore

PEPPER = "test-pepper-at-least-32-bytes-long"


def _make_store(tmp_path) -> MobileIdentityStore:
    store = MobileIdentityStore(tmp_path / "mobile.db", pepper=PEPPER)
    store.create_account(
        username="owner",
        password="correct-horse-battery-staple",
        role="owner",
        actor_id="actor-owner",
        user_id=1001,
    )
    store.create_account(
        username="guest-one",
        password="correct-horse-battery-staple",
        role="guest",
        actor_id="actor-guest",
        user_id=2001,
    )
    return store


def _login(client: TestClient, store: MobileIdentityStore, username: str) -> str:
    code = store.create_pairing_code(username)
    response = client.post(
        "/api/mobile/v1/auth/login",
        json={
            "username": username,
            "password": "correct-horse-battery-staple",
            "deviceName": "test-device",
            "pairingCode": code,
        },
    )
    assert response.status_code == 200
    return f"Bearer {response.json()['accessToken']}"


@pytest.fixture
def approval_api(tmp_path):
    store = _make_store(tmp_path)
    client = TestClient(create_mobile_app(identity_store=store))
    return {
        "client": client,
        "store": store,
        "owner_headers": {"Authorization": _login(client, store, "owner")},
        "guest_headers": {"Authorization": _login(client, store, "guest-one")},
    }


def test_approvals_require_authentication(approval_api):
    response = approval_api["client"].get("/api/mobile/v1/approvals")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_guest_cannot_list_approvals(approval_api):
    response = approval_api["client"].get(
        "/api/mobile/v1/approvals",
        headers=approval_api["guest_headers"],
    )
    assert response.status_code == 403


def test_owner_lists_empty_approvals(approval_api):
    response = approval_api["client"].get(
        "/api/mobile/v1/approvals",
        headers=approval_api["owner_headers"],
    )
    assert response.status_code == 200
    assert response.json() == {"items": [], "count": 0}


def test_owner_missing_approval_is_404(approval_api):
    response = approval_api["client"].get(
        "/api/mobile/v1/approvals/does-not-exist",
        headers=approval_api["owner_headers"],
    )
    assert response.status_code == 404


def test_owner_guests_and_audit_endpoints(approval_api):
    guests = approval_api["client"].get(
        "/api/mobile/v1/owner/guests",
        headers=approval_api["owner_headers"],
    )
    assert guests.status_code == 200
    items = guests.json()["items"]
    assert len(items) == 1
    assert items[0]["username"] == "guest-one"
    assert items[0]["role"] == "guest"

    audit = approval_api["client"].get(
        "/api/mobile/v1/owner/audit",
        headers=approval_api["owner_headers"],
    )
    assert audit.status_code == 200
    assert isinstance(audit.json()["items"], list)


def test_guest_cannot_access_owner_audit(approval_api):
    response = approval_api["client"].get(
        "/api/mobile/v1/owner/audit",
        headers=approval_api["guest_headers"],
    )
    assert response.status_code == 403
