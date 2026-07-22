from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.mobile_identity import MobileAuthError, MobileIdentityStore


PEPPER = "test-only-pepper-with-at-least-32-bytes"


@pytest.fixture
def store(tmp_path):
    return MobileIdentityStore(tmp_path / "mobile.db", pepper=PEPPER)


def _account(store, username="owner", role="owner", actor_id="actor-primary"):
    return store.create_account(
        username=username,
        password="correct-horse-battery-staple",
        role=role,
        actor_id=actor_id,
        user_id=1001 if role == "owner" else 2001,
    )


def _login(store, username="owner"):
    code = store.create_pairing_code(username)
    return store.login(
        username=username,
        password="correct-horse-battery-staple",
        device_name="V2516A",
        pairing_code=code,
        ip_address="127.0.0.1",
    )


def test_account_rules_and_argon2id_hash(store):
    account = _account(store)
    row = store._fetch_account("owner")

    assert account.role == "owner"
    assert row["password_hash"].startswith("$argon2id$")
    with pytest.raises(ValueError, match="one enabled owner"):
        _account(store, username="other-owner")
    with pytest.raises(ValueError, match="username"):
        _account(store, username="x", role="guest")
    with pytest.raises(ValueError, match="12"):
        store.create_account(
            username="guest-one",
            password="too-short",
            role="guest",
            actor_id="actor-guest-one",
            user_id=2001,
        )


def test_pairing_is_single_use_and_login_error_is_uniform(store):
    _account(store)
    code = store.create_pairing_code("owner")
    tokens = store.login(
        username="OWNER",
        password="correct-horse-battery-staple",
        device_name="V2516A",
        pairing_code=code,
        ip_address="10.0.0.1",
    )

    assert store.authenticate_access(tokens.access_token).role == "owner"
    with pytest.raises(MobileAuthError) as reused:
        store.login(
            username="owner",
            password="correct-horse-battery-staple",
            device_name="second",
            pairing_code=code,
            ip_address="10.0.0.1",
        )
    assert reused.value.code == "invalid_credentials"


def test_refresh_rotates_and_reuse_revokes_family(store):
    _account(store)
    first = _login(store)
    second = store.refresh(first.refresh_token)

    assert second.refresh_token != first.refresh_token
    with pytest.raises(MobileAuthError) as reused:
        store.refresh(first.refresh_token)
    assert reused.value.code == "invalid_token"
    with pytest.raises(MobileAuthError):
        store.refresh(second.refresh_token)


def test_device_revoke_and_logout_immediately_invalidate_sessions(store):
    _account(store)
    tokens = _login(store)
    principal = store.authenticate_access(tokens.access_token)

    assert len(store.list_devices(principal)) == 1
    store.logout(principal)
    with pytest.raises(MobileAuthError):
        store.authenticate_access(tokens.access_token)

    replacement = _login(store)
    principal = store.authenticate_access(replacement.access_token)
    store.revoke_device(principal, principal.device_id)
    with pytest.raises(MobileAuthError):
        store.authenticate_access(replacement.access_token)


def test_owner_and_guests_have_distinct_identity_boundaries(store):
    owner = _account(store)
    guest = _account(
        store,
        username="guest-one",
        role="guest",
        actor_id="actor-guest-one",
    )

    assert owner.actor_id == "actor-primary"
    assert guest.actor_id == "actor-guest-one"
    assert owner.actor_id != guest.actor_id
    assert owner.user_id != guest.user_id


def test_login_rate_limit_applies_to_account_and_ip(store):
    _account(store)
    for index in range(5):
        with pytest.raises(MobileAuthError) as failed:
            store.login(
                username="owner",
                password="wrong-password-value",
                device_name="V2516A",
                pairing_code="00000000",
                ip_address="10.0.0.8",
            )
        assert failed.value.code == "invalid_credentials"

    with pytest.raises(MobileAuthError) as limited:
        store.login(
            username="owner",
            password="correct-horse-battery-staple",
            device_name="V2516A",
            pairing_code=store.create_pairing_code("owner"),
            ip_address="10.0.0.8",
        )
    assert limited.value.code == "rate_limited"


def test_pairing_code_expires_after_ten_minutes(tmp_path):
    now = datetime(2026, 7, 22, tzinfo=timezone.utc)
    store = MobileIdentityStore(
        tmp_path / "mobile.db",
        pepper=PEPPER,
        clock=lambda: now,
    )
    _account(store)
    code = store.create_pairing_code("owner")
    store.clock = lambda: now + timedelta(minutes=11)

    with pytest.raises(MobileAuthError) as expired:
        store.login(
            username="owner",
            password="correct-horse-battery-staple",
            device_name="V2516A",
            pairing_code=code,
            ip_address="127.0.0.1",
        )
    assert expired.value.code == "invalid_credentials"
