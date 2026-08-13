"""Aerie · 云栖 — Quote V2 integration tests.

Covers the unified quote chain: desktop direct resolve, QQ platform-id
mapping, get_msg fallback, outbound reply id resolution, and mobile
reply_to_id passthrough.
"""
import asyncio
import json

import pytest

from communication.message import IncomingMessage
from core.pipeline import Pipeline


class TestSegmentsToQuoteContent:
    def test_text_image_file(self):
        content, atts = Pipeline._segments_to_quote_content([
            {"type": "text", "data": {"text": "看看这个"}},
            {"type": "image", "data": {"url": "http://x/y.png"}},
            {"type": "file", "data": {"name": "计划.docx", "size": 100, "url": "http://x/d.docx"}},
        ])
        assert content == "看看这个 [图片] [文件:计划.docx]"
        assert len(atts) == 2
        assert atts[0]["category"] == "image"
        assert atts[1]["category"] == "file"
        assert atts[1]["name"] == "计划.docx"

    def test_empty(self):
        content, atts = Pipeline._segments_to_quote_content([])
        assert content == ""
        assert atts == []


@pytest.fixture
def quote_pipeline(phase4_db):
    pl = Pipeline.__new__(Pipeline)  # bypass __init__; only db + fetcher needed
    pl.db = phase4_db
    pl.qq_get_msg = None
    return pl


def test_resolve_desktop_direct_with_attachments(quote_pipeline):
    """Desktop: reply_to_id == chat_log.id resolves full quote (incl. atts)."""
    mid = quote_pipeline.db.insert("chat_log", {
        "user_id": 1,
        "role": "user",
        "content": "昨天说的那个方案",
        "attachments": json.dumps([
            {"name": "a.png", "category": "image", "url": "/uploads/a.png"}
        ]),
    })
    msg = IncomingMessage.from_local("继续说", 1, reply_to_id=mid)
    rt = asyncio.run(quote_pipeline._resolve_reply_to(msg))
    assert rt is not None
    assert rt.chat_log_id == mid
    assert rt.content == "昨天说的那个方案"
    assert rt.role == "user"
    assert rt.attachments[0]["name"] == "a.png"


def test_resolve_qq_via_platform_message_id(quote_pipeline):
    """QQ quote maps the platform message_id -> chat_log via qq_message_id."""
    quote_pipeline.db.insert("chat_log", {
        "user_id": 1,
        "role": "assistant",
        "content": "我在阳台呢",
        "qq_message_id": 10000000001,
    })
    msg = IncomingMessage.from_onebot_event({
        "sender": {"user_id": 1},
        "message_type": "private",
        "raw_message": "回复消息",
        "message": [
            {"type": "reply", "data": {"id": 10000000001}},
            {"type": "text", "data": {"text": "回复消息"}},
        ],
    })
    rt = asyncio.run(quote_pipeline._resolve_reply_to(msg))
    assert rt is not None
    assert rt.platform_message_id == 10000000001
    assert rt.content == "我在阳台呢"
    assert rt.role == "assistant"


def test_resolve_qq_get_msg_fallback(quote_pipeline):
    """Quote of a never-persisted message falls back to OneBot get_msg."""

    async def fake_get_msg(mid):
        return {
            "data": {
                "message": [
                    {"type": "text", "data": {"text": "引用我这句话"}},
                    {"type": "image", "data": {"url": "http://x/pic.png"}},
                ]
            }
        }

    quote_pipeline.qq_get_msg = fake_get_msg
    msg = IncomingMessage.from_onebot_event({
        "sender": {"user_id": 1},
        "message_type": "private",
        "raw_message": "回复消息",
        "message": [
            {"type": "reply", "data": {"id": 99999}},
            {"type": "text", "data": {"text": "回复消息"}},
        ],
    })
    rt = asyncio.run(quote_pipeline._resolve_reply_to(msg))
    assert rt is not None
    assert rt.platform_message_id == 99999
    assert rt.content == "引用我这句话 [图片]"
    assert rt.attachments[0]["category"] == "image"


def test_resolve_unknown_returns_none(quote_pipeline):
    """Unknown quote id with no platform id / fetcher resolves to None."""
    msg = IncomingMessage.from_local("hi", 1, reply_to_id=424242)
    rt = asyncio.run(quote_pipeline._resolve_reply_to(msg))
    assert rt is None


def test_outbound_reply_id_uses_resolved_platform_id(quote_pipeline):
    """AI reply referencing a quoted QQ message uses its platform id."""
    quote_pipeline.db.insert("chat_log", {
        "user_id": 1,
        "role": "user",
        "content": "嗯嗯",
        "qq_message_id": 55555555,
    })
    msg = IncomingMessage.from_onebot_event({
        "sender": {"user_id": 1},
        "message_type": "private",
        "raw_message": "回复消息",
        "message": [
            {"type": "reply", "data": {"id": 55555555}},
            {"type": "text", "data": {"text": "回复消息"}},
        ],
    })
    msg.reply_to = asyncio.run(quote_pipeline._resolve_reply_to(msg))
    assert msg.reply_to is not None
    assert quote_pipeline._resolve_outbound_qq_reply_id(msg) == 55555555


def test_outbound_reply_id_via_get_msg(quote_pipeline):
    """get_msg-resolved quote carries its platform id for outbound replies."""

    async def fake_get_msg(mid):
        return {"data": {"message": [{"type": "text", "data": {"text": "旧消息"}}]}}

    quote_pipeline.qq_get_msg = fake_get_msg
    msg = IncomingMessage.from_onebot_event({
        "sender": {"user_id": 1},
        "message_type": "private",
        "raw_message": "回复消息",
        "message": [
            {"type": "reply", "data": {"id": 777}},
            {"type": "text", "data": {"text": "回复消息"}},
        ],
    })
    msg.reply_to = asyncio.run(quote_pipeline._resolve_reply_to(msg))
    assert msg.reply_to is not None
    assert quote_pipeline._resolve_outbound_qq_reply_id(msg) == 777


def test_mobile_reply_to_id_reaches_request_context(phase4_db):
    """Mobile SubmitRequest replyToId is threaded into the RequestContext."""
    from core.mobile_chat import MobileChatService
    from core.mobile_identity import MobileIdentityStore

    store = MobileIdentityStore(
        phase4_db.db_path.parent / "identity.db",
        pepper="test-only-pepper-with-at-least-32-bytes",
    )
    store.create_account(
        username="owner",
        password="correct-horse-battery-staple",
        role="owner",
        actor_id="actor-owner",
        user_id=1,
    )
    principal = store.login(
        username="owner",
        password="correct-horse-battery-staple",
        device_name="V2516A",
        pairing_code=store.create_pairing_code("owner"),
        ip_address="127.0.0.1",
    ).principal
    service = MobileChatService(phase4_db, store)

    # Seed FK dependencies for the requests insert (turns is created by submit).
    with phase4_db.connection() as conn:
        conn.execute("INSERT OR IGNORE INTO actors(actor_id) VALUES ('actor-owner')")
        conn.execute(
            """INSERT OR IGNORE INTO conversations
               (conversation_id, actor_id, channel, channel_account_id, status)
               VALUES ('conv-q', 'actor-owner', 'mobile', 'acc-q', 'active')"""
        )

    req = service.requests.submit(
        context=__import__(
            "core.chat_request_repository", fromlist=["RequestContext"]
        ).RequestContext(
            request_id="req-quote-mobile",
            conversation_id="conv-q",
            turn_id="turn-q",
            identity=__import__(
                "core.chat_request_repository", fromlist=["RequestIdentity"]
            ).RequestIdentity(
                actor_id=principal.actor_id,
                channel="mobile",
                channel_account_id=principal.account_id,
                user_id=principal.user_id,
            ),
            input_content="引用你说的话",
            effective_content="引用你说的话",
            reply_to_id=12345,
            persona_id=None,
        ),
    )
    assert req is not None
    with phase4_db.connection() as conn:
        row = conn.execute(
            "SELECT reply_to_id FROM requests WHERE request_id = 'req-quote-mobile'"
        ).fetchone()
        assert row["reply_to_id"] == 12345
