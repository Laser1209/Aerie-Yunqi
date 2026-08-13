"""Aerie · 云栖 — Quote V2 unified quote context tests (QQ/desktop/mobile)."""
from communication.message import IncomingMessage, OutgoingReply, QuoteContext


class TestQuoteContext:
    def test_is_valid_by_chat_log_id(self):
        assert QuoteContext(chat_log_id=7).is_valid is True

    def test_is_valid_by_content(self):
        assert QuoteContext(content="hello").is_valid is True

    def test_invalid_when_empty(self):
        assert QuoteContext().is_valid is False

    def test_to_prompt_dict(self):
        rt = QuoteContext(
            chat_log_id=7,
            platform_message_id=888,
            role="assistant",
            content="在忙呢",
            attachments=[{"category": "image", "name": "图片"}],
        )
        d = rt.to_prompt_dict()
        assert d["id"] == 7
        assert d["role"] == "assistant"
        assert d["content"] == "在忙呢"
        assert d["attachments"][0]["category"] == "image"


class TestIncomingMessageQuote:
    def test_from_local_with_reply_to(self):
        msg = IncomingMessage.from_local("hi", 1, reply_to_id=42)
        assert msg.reply_to_id == 42
        assert msg.user_id == 1
        assert msg.platform_message_id == 0

    def test_from_local_no_reply_to_default(self):
        msg = IncomingMessage.from_local("hi", 1)
        assert msg.reply_to_id == 0

    def test_from_onebot_extracts_reply_segment(self):
        event = {
            "sender": {"user_id": 12345},
            "message_type": "private",
            "raw_message": "回复消息",
            "message": [
                {"type": "reply", "data": {"id": 67890}},
                {"type": "text", "data": {"text": "回复消息"}},
            ],
        }
        msg = IncomingMessage.from_onebot_event(event)
        assert msg.reply_to_id == 67890
        # Quote V2: the OneBot reply segment id is the QQ platform message_id
        assert msg.platform_message_id == 67890
        assert msg.user_id == 12345

    def test_from_onebot_no_reply_segment(self):
        event = {
            "sender": {"user_id": 1},
            "message_type": "private",
            "raw_message": "plain",
            "message": [{"type": "text", "data": {"text": "plain"}}],
        }
        msg = IncomingMessage.from_onebot_event(event)
        assert msg.reply_to_id == 0
        assert msg.platform_message_id == 0

    def test_from_local_with_attachments(self):
        atts = [{"name": "x.png", "type": "image", "size": 1024, "url": "/uploads/x.png"}]
        msg = IncomingMessage.from_local("look", 1, attachments=atts)
        assert len(msg.attachments) == 1
        assert msg.attachments[0]["name"] == "x.png"


class TestOutgoingReplyQuote:
    def test_reply_to_qq_message_id(self):
        r = OutgoingReply(user_id=1, content="hi", reply_to_qq_message_id=12345)
        assert r.reply_to_qq_message_id == 12345

    def test_default_reply_to_zero(self):
        r = OutgoingReply(user_id=1, content="hi")
        assert r.reply_to_qq_message_id == 0

    def test_attachments_field(self):
        atts = [{"name": "a.zip"}]
        r = OutgoingReply(user_id=1, content="x", attachments=atts)
        assert r.attachments == atts
