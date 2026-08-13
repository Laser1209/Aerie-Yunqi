"""Aerie · 云栖 — Quote V2 fool-proof & multi-persona tests.

Fool-proof coverage: malformed ids, cross-user / cross-persona boundary
guards, QQ platform-id collision safety, corrupt attachment data.
Multi-persona coverage: speaker attribution (no mis-attribution across
personas) and memory-pollution isolation (quoted content never enters the
user message ``content`` that memory extraction reads).
"""
import asyncio
import json

import pytest

from communication.message import IncomingMessage
from core.pipeline import Pipeline


@pytest.fixture
def quote_pipeline(phase4_db, monkeypatch):
    """Pipeline double pinned to the active persona yita_default."""
    monkeypatch.setattr(
        "core.pipeline.active_persona_id", lambda: "yita_default"
    )
    pl = Pipeline.__new__(Pipeline)  # bypass __init__; only db + fetcher needed
    pl.db = phase4_db
    pl.qq_get_msg = None
    return pl


# ── 防呆：非法输入 / 边界守卫 ─────────────────────

class TestFoolProof:
    def test_malformed_reply_to_id_coerced(self, quote_pipeline):
        """Non-numeric reply_to_id must not raise; coerced to a miss."""
        msg = IncomingMessage.from_local("hi", 1, reply_to_id="not-an-int")
        assert asyncio.run(quote_pipeline._resolve_reply_to(msg)) is None

    def test_negative_reply_to_id(self, quote_pipeline):
        msg = IncomingMessage.from_local("hi", 1, reply_to_id=-5)
        assert asyncio.run(quote_pipeline._resolve_reply_to(msg)) is None

    def test_cross_user_reply_blocked(self, quote_pipeline):
        """A user can never resolve another user's message."""
        mid = quote_pipeline.db.insert("chat_log", {
            "user_id": 999,
            "role": "user",
            "content": "另一个用户的消息",
        })
        msg = IncomingMessage.from_local("hi", 1, reply_to_id=mid)
        assert asyncio.run(quote_pipeline._resolve_reply_to(msg)) is None

    def test_same_user_reply_resolved(self, quote_pipeline):
        mid = quote_pipeline.db.insert("chat_log", {
            "user_id": 1,
            "role": "user",
            "content": "自己的消息",
        })
        msg = IncomingMessage.from_local("hi", 1, reply_to_id=mid)
        rt = asyncio.run(quote_pipeline._resolve_reply_to(msg))
        assert rt is not None
        assert rt.chat_log_id == mid
        assert rt.content == "自己的消息"

    def test_cross_persona_reply_blocked(self, quote_pipeline):
        """Quotes never surface messages owned by another persona."""
        mid = quote_pipeline.db.insert("chat_log", {
            "user_id": 1,
            "role": "assistant",
            "content": "另一角色的发言",
            "persona_id": "sena",
        })
        msg = IncomingMessage.from_local("hi", 1, reply_to_id=mid)
        assert asyncio.run(quote_pipeline._resolve_reply_to(msg)) is None

    def test_legacy_row_without_persona_still_resolvable(self, quote_pipeline):
        """Legacy shared rows (persona_id NULL) stay quotable."""
        mid = quote_pipeline.db.insert("chat_log", {
            "user_id": 1,
            "role": "assistant",
            "content": "存量无角色消息",
        })
        msg = IncomingMessage.from_local("hi", 1, reply_to_id=mid)
        rt = asyncio.run(quote_pipeline._resolve_reply_to(msg))
        assert rt is not None
        assert rt.content == "存量无角色消息"

    def test_qq_platform_id_no_collision_with_local_id(self, quote_pipeline):
        """QQ platform id must map through qq_message_id, never chat_log.id."""
        mid = quote_pipeline.db.insert("chat_log", {
            "user_id": 1,
            "role": "assistant",
            "content": "本地消息不该被命中",
        })
        assert mid == 1  # local row occupies chat_log.id == 1
        msg = IncomingMessage.from_onebot_event({
            "sender": {"user_id": 1},
            "message_type": "private",
            "raw_message": "回复",
            "message": [{"type": "reply", "data": {"id": 1}}],
        })
        assert asyncio.run(quote_pipeline._resolve_reply_to(msg)) is None

    def test_qq_platform_id_mapping_ok(self, quote_pipeline):
        mid = quote_pipeline.db.insert("chat_log", {
            "user_id": 1,
            "role": "assistant",
            "content": "QQ 消息",
            "qq_message_id": 777000777,
        })
        msg = IncomingMessage.from_onebot_event({
            "sender": {"user_id": 1},
            "message_type": "private",
            "raw_message": "回复",
            "message": [{"type": "reply", "data": {"id": 777000777}}],
        })
        rt = asyncio.run(quote_pipeline._resolve_reply_to(msg))
        assert rt is not None
        assert rt.chat_log_id == mid

    def test_corrupt_attachments_json(self, quote_pipeline):
        mid = quote_pipeline.db.insert("chat_log", {
            "user_id": 1,
            "role": "user",
            "content": "坏附件",
            "attachments": "{not-json",
        })
        msg = IncomingMessage.from_local("hi", 1, reply_to_id=mid)
        rt = asyncio.run(quote_pipeline._resolve_reply_to(msg))
        assert rt is not None
        assert rt.attachments == []

    def test_persona_id_carried_into_quote(self, quote_pipeline):
        mid = quote_pipeline.db.insert("chat_log", {
            "user_id": 1,
            "role": "assistant",
            "content": "伊塔说的",
            "persona_id": "yita_default",
        })
        msg = IncomingMessage.from_local("hi", 1, reply_to_id=mid)
        rt = asyncio.run(quote_pipeline._resolve_reply_to(msg))
        assert rt is not None
        assert rt.persona_id == "yita_default"
        assert rt.to_prompt_dict()["persona_id"] == "yita_default"


# ── 多角色：说话人归属（不误判）───────────────────

class TestMultiPersonaAttribution:
    def test_speaker_label_user_quote(self):
        from core.context_builder import ContextBuilder

        cb = ContextBuilder()
        assert cb._quote_speaker_label({"role": "user"}, "伊塔") == "你"

    def test_speaker_label_current_persona(self):
        from core.context_builder import ContextBuilder

        cb = ContextBuilder()
        active = cb._persona_mgr.get_active_id()
        # assistant message from the active persona -> active persona name
        assert (
            cb._quote_speaker_label(
                {"role": "assistant", "persona_id": active}, "伊塔"
            )
            == "伊塔"
        )

    def test_speaker_label_legacy_without_persona(self):
        from core.context_builder import ContextBuilder

        cb = ContextBuilder()
        assert cb._quote_speaker_label({"role": "assistant"}, "伊塔") == "伊塔"

    def test_speaker_label_other_persona_not_misattributed(self):
        from core.context_builder import ContextBuilder

        cb = ContextBuilder()
        active = cb._persona_mgr.get_active_id()
        label = cb._quote_speaker_label(
            {"role": "assistant", "persona_id": "sena"}, "伊塔"
        )
        # never attributed to the active persona; either the real name or id
        assert label != "伊塔"
        assert label == "塞纳" or label == "sena"

    def test_build_injects_quote_with_attachments(self):
        from core.context_builder import ContextBuilder

        cb = ContextBuilder()
        msgs = cb.build(
            user_id=1,
            current_msg="继续说",
            route_mode="FULL",
            reply_to={
                "id": 1,
                "role": "user",
                "content": "昨天说的那个方案",
                "persona_id": "yita_default",
                "attachments": [
                    {"name": "a.png", "category": "image", "url": "http://x/a.png"}
                ],
            },
        )
        sys_prompt = msgs[0]["content"]
        assert "引用上下文" in sys_prompt
        assert "你引用了" in sys_prompt
        assert "（来自你）" in sys_prompt
        assert "a.png" in sys_prompt
        assert "http://x/a.png" in sys_prompt


# ── 记忆污染：引用内容不进 user content ────────────

class TestNoMemoryPollution:
    def test_quoted_content_stays_out_of_user_message_content(self, phase4_db):
        """persist_turn stores the quote in reply_to_* columns only, so
        memory extraction / summaries / retrieval reading ``content`` never
        treat quoted text as the user's own words."""
        from core.conversation_repository import ConversationRepository
        from core.persona_hub.persona_manager import get_persona_manager

        repo = ConversationRepository(phase4_db, enabled=True)
        with phase4_db.connection() as conn:
            conn.execute("INSERT OR IGNORE INTO actors(actor_id) VALUES ('actor-owner')")
        result = repo.persist_turn(
            request_id="req-quote-pollute",
            user_id=1,
            conversation_id="conv-quote-pollute",
            turn_id="turn-quote-pollute",
            actor_id="actor-owner",
            channel="desktop",
            channel_account_id="acc-owner",
            user_content="我今天说这句话",
            user_attachments=None,
            assistant_segments=["回复你"],
            user_legacy_chat_log_id=100,
            assistant_legacy_chat_log_ids=[101],
            persona_id=get_persona_manager().get_active_id(),
            user_reply_to={
                "id": 42,
                "role": "user",
                "content": "被引用的旧消息内容",
                "attachments": [
                    {"name": "old.png", "category": "image", "url": "/uploads/old.png"}
                ],
                "persona_id": "",
            },
        )
        assert result is not None
        with phase4_db.connection() as conn:
            row = conn.execute(
                "SELECT content, reply_to_id, reply_to_content, "
                "reply_to_role, reply_to_attachments "
                "FROM messages "
                "WHERE turn_id = 'turn-quote-pollute' AND role = 'user'"
            ).fetchone()
        assert row["content"] == "我今天说这句话"  # pure user words
        assert "被引用的旧消息内容" not in (row["content"] or "")
        assert row["reply_to_id"] == 42
        assert row["reply_to_content"] == "被引用的旧消息内容"
        assert row["reply_to_role"] == "user"
        assert json.loads(row["reply_to_attachments"])[0]["name"] == "old.png"
