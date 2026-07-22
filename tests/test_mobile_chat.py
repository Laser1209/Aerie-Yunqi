from __future__ import annotations

from core.mobile_chat import MobileChatService
from core.mobile_identity import MobileIdentityStore


PEPPER = "test-only-pepper-with-at-least-32-bytes"


def _principal(tmp_path, *, username, role, actor_id, user_id):
    store = MobileIdentityStore(tmp_path / f"{username}.db", pepper=PEPPER)
    store.create_account(
        username=username,
        password="correct-horse-battery-staple",
        role=role,
        actor_id=actor_id,
        user_id=user_id,
    )
    code = store.create_pairing_code(username)
    tokens = store.login(
        username=username,
        password="correct-horse-battery-staple",
        device_name="V2516A",
        pairing_code=code,
        ip_address="127.0.0.1",
    )
    return store, tokens.principal


def _seed_desktop_message(db):
    with db.connection() as conn:
        conn.execute("INSERT INTO actors(actor_id) VALUES ('actor-primary')")
        conn.execute(
            """INSERT INTO conversations
               (conversation_id, actor_id, channel, channel_account_id, status)
               VALUES ('conv-desktop', 'actor-primary', 'qq', '1001', 'active')"""
        )
        conn.execute(
            """INSERT INTO turns(turn_id, conversation_id, status, completed_at)
               VALUES ('turn-desktop', 'conv-desktop', 'completed', datetime('now'))"""
        )
        conn.execute(
            """INSERT INTO messages
               (message_id, conversation_id, turn_id, role, content,
                sequence, channel, channel_account_id, actor_id)
               VALUES ('msg-desktop', 'conv-desktop', 'turn-desktop', 'user',
                       'desktop history', 0, 'qq', '1001', 'actor-primary')"""
        )


def test_mobile_event_migration_tracks_message_and_request_changes(phase4_db):
    _seed_desktop_message(phase4_db)
    with phase4_db.connection() as conn:
        conn.execute(
            """INSERT INTO turns(turn_id, conversation_id, status)
               VALUES ('turn-mobile', 'conv-desktop', 'pending')"""
        )
        conn.execute(
            """INSERT INTO requests
               (request_id, conversation_id, turn_id, status, actor_id)
               VALUES ('req-mobile', 'conv-desktop', 'turn-mobile', 'queued',
                       'actor-primary')"""
        )
        conn.execute(
            "UPDATE requests SET status = 'running' WHERE request_id = 'req-mobile'"
        )
        events = conn.execute(
            """SELECT event_type, entity_id FROM mobile_events
               WHERE actor_id = 'actor-primary' ORDER BY event_sequence"""
        ).fetchall()

    assert [(row["event_type"], row["entity_id"]) for row in events] == [
        ("message.created", "msg-desktop"),
        ("request.updated", "req-mobile"),
        ("request.updated", "req-mobile"),
    ]


def test_mobile_chat_shares_owner_history_and_isolates_guest(
    phase4_db,
    tmp_path,
):
    _seed_desktop_message(phase4_db)
    owner_store, owner = _principal(
        tmp_path,
        username="owner",
        role="owner",
        actor_id="actor-primary",
        user_id=1001,
    )
    guest_store, guest = _principal(
        tmp_path,
        username="guest-one",
        role="guest",
        actor_id="actor-guest-one",
        user_id=2001,
    )
    with phase4_db.connection() as conn:
        conn.execute("INSERT INTO actors(actor_id) VALUES ('actor-guest-one')")

    owner_service = MobileChatService(phase4_db, owner_store)
    guest_service = MobileChatService(phase4_db, guest_store)

    assert owner_service.list_messages(owner)["items"][0]["content"] == "desktop history"
    assert guest_service.list_messages(guest)["items"] == []


def test_mobile_request_submission_is_idempotent_and_owned(phase4_db, tmp_path):
    _seed_desktop_message(phase4_db)
    store, owner = _principal(
        tmp_path,
        username="owner",
        role="owner",
        actor_id="actor-primary",
        user_id=1001,
    )
    service = MobileChatService(phase4_db, store)
    client_id = "00000000-0000-4000-8000-000000000123"

    first = service.submit_request(
        owner,
        client_request_id=client_id,
        text="hello from mobile",
        file_ids=[],
    )
    second = service.submit_request(
        owner,
        client_request_id=client_id,
        text="hello from mobile",
        file_ids=[],
    )

    assert first["requestId"] == second["requestId"]
    assert first["status"] == "queued"
    assert service.get_request(owner, first["requestId"])["status"] == "queued"
    with phase4_db.connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM requests WHERE request_id = ?",
            (first["requestId"],),
        ).fetchone()[0]
    assert count == 1


def test_mobile_event_query_filters_actor_and_resumes_from_cursor(
    phase4_db,
    tmp_path,
):
    _seed_desktop_message(phase4_db)
    store, owner = _principal(
        tmp_path,
        username="owner",
        role="owner",
        actor_id="actor-primary",
        user_id=1001,
    )
    service = MobileChatService(phase4_db, store)

    first = service.list_events(owner, after_event_id=None)
    assert [event["type"] for event in first] == ["message.created"]
    assert service.list_events(owner, after_event_id=first[-1]["id"]) == []
