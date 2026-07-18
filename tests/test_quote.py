"""Aerie · 云栖 v0.1.0-beta.1 — Phase 4 Quote tests."""
from communication.message import IncomingMessage, OutgoingReply


class TestIncomingMessageQuote:
    def test_from_local_with_reply_to(self):
        msg = IncomingMessage.from_local("hi", 1, reply_to_id=42)
        assert msg.reply_to_id == 42
        assert msg.user_id == 1

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
