from datetime import datetime, timedelta, timezone


def test_state_persists_cursor_and_encrypted_context_token(tmp_path):
    from core.ilink_state import ILinkStateStore

    path = tmp_path / "ilink_state.db"
    store = ILinkStateStore(path)
    store.set_cursor("bot-1", "opaque-cursor")
    store.set_context_token("bot-1", "secret-context-token")
    store.close()

    reopened = ILinkStateStore(path)
    assert reopened.get_cursor("bot-1") == "opaque-cursor"
    assert reopened.get_context_token("bot-1") == "secret-context-token"
    reopened.close()
    assert b"secret-context-token" not in path.read_bytes()


def test_pairing_binds_only_matching_sender_to_primary_actor(tmp_path, monkeypatch):
    import core.ilink_state as ilink_state

    now = datetime(2026, 8, 21, tzinfo=timezone.utc)
    monkeypatch.setattr(ilink_state.secrets, "randbelow", lambda upper: 12345678)
    store = ilink_state.ILinkStateStore(tmp_path / "ilink_state.db", now=lambda: now)

    code = store.create_pairing_code("bot-1")

    assert code == "12345678"
    assert store.verify_pairing("bot-1", "wx-owner", "12345678", 3998874040)
    assert store.get_binding("bot-1") == ilink_state.ILinkBinding(
        bot_id="bot-1",
        ilink_user_id="wx-owner",
        primary_user_id=3998874040,
    )
    assert not store.verify_pairing("bot-1", "wx-other", "12345678", 3998874040)
    store.close()


def test_pairing_stores_no_code_or_rejected_message(tmp_path, monkeypatch):
    import core.ilink_state as ilink_state

    monkeypatch.setattr(ilink_state.secrets, "randbelow", lambda upper: 87654321)
    path = tmp_path / "ilink_state.db"
    store = ilink_state.ILinkStateStore(path)

    store.create_pairing_code("bot-1")
    assert not store.verify_pairing("bot-1", "wx-stranger", "private-message", 7)
    store.close()

    content = path.read_bytes()
    assert b"87654321" not in content
    assert b"private-message" not in content


def test_pairing_expires_and_invalidates_after_five_failures(tmp_path, monkeypatch):
    import core.ilink_state as ilink_state

    current = datetime(2026, 8, 21, tzinfo=timezone.utc)
    monkeypatch.setattr(ilink_state.secrets, "randbelow", lambda upper: 11112222)
    store = ilink_state.ILinkStateStore(
        tmp_path / "ilink_state.db",
        now=lambda: current,
    )

    store.create_pairing_code("failed-bot")
    for attempt in range(5):
        assert not store.verify_pairing("failed-bot", f"sender-{attempt}", "wrong", 7)
    assert not store.verify_pairing("failed-bot", "owner", "11112222", 7)

    store.create_pairing_code("expired-bot")
    current += timedelta(minutes=11)
    assert not store.verify_pairing("expired-bot", "owner", "11112222", 7)
    store.close()


def test_clear_removes_cursor_context_and_binding(tmp_path, monkeypatch):
    import core.ilink_state as ilink_state

    monkeypatch.setattr(ilink_state.secrets, "randbelow", lambda upper: 22223333)
    store = ilink_state.ILinkStateStore(tmp_path / "ilink_state.db")
    store.set_cursor("bot-1", "cursor")
    store.set_context_token("bot-1", "context")
    store.create_pairing_code("bot-1")
    assert store.verify_pairing("bot-1", "owner", "22223333", 7)

    store.clear("bot-1")

    assert store.get_cursor("bot-1") == ""
    assert store.get_context_token("bot-1") is None
    assert store.get_binding("bot-1") is None
    store.close()


def test_message_deduplication_persists_across_store_reopen(tmp_path):
    from core.ilink_state import ILinkStateStore

    path = tmp_path / "ilink_state.db"
    store = ILinkStateStore(path)

    assert store.mark_message_processed("bot-1", "bot-1:42:client-42")
    assert not store.mark_message_processed("bot-1", "bot-1:42:client-42")
    store.close()

    reopened = ILinkStateStore(path)
    assert not reopened.mark_message_processed("bot-1", "bot-1:42:client-42")
    reopened.close()
