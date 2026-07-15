"""消息数据模型单元测试"""

import pytest
from datetime import datetime
from communication.message import (
    IncomingMessage,
    OutgoingReply,
    MessageType,
    Sender,
    Intent,
)


class TestSender:
    def test_from_dict_valid(self):
        data = {"user_id": 3489352115, "nickname": "伊泽", "sex": "male", "age": 25}
        sender = Sender.from_dict(data)
        assert sender.user_id == 3489352115
        assert sender.nickname == "伊泽"
        assert sender.sex == "male"
        assert sender.age == 25

    def test_from_dict_defaults(self):
        sender = Sender.from_dict({})
        assert sender.user_id == 0
        assert sender.nickname == ""
        assert sender.sex == "unknown"
        assert sender.age == 0


class TestIncomingMessage:
    def test_from_onebot_private_msg(self, sample_onebot_private_msg):
        msg = IncomingMessage.from_onebot_event(sample_onebot_private_msg)
        assert msg is not None
        assert msg.msg_id == 123456
        assert msg.user_id == 3489352115
        assert msg.user_nickname == "伊泽"
        assert msg.msg_type == MessageType.PRIVATE
        assert msg.content == "你好，伊塔"
        assert msg.is_private is True
        assert msg.is_group is False
        assert msg.self_id == 3998874040

    def test_from_onebot_group_msg(self, sample_onebot_group_msg):
        msg = IncomingMessage.from_onebot_event(sample_onebot_group_msg)
        assert msg is not None
        assert msg.msg_type == MessageType.GROUP
        assert msg.is_group is True
        assert msg.is_private is False
        assert msg.group_id == 987654321

    def test_from_onebot_non_message(self, sample_onebot_non_message):
        msg = IncomingMessage.from_onebot_event(sample_onebot_non_message)
        assert msg is None

    def test_from_onebot_empty(self):
        msg = IncomingMessage.from_onebot_event({})
        assert msg is None

    def test_summary_short(self, sample_incoming_message):
        summary = sample_incoming_message.summary()
        assert "3489352115" in summary
        assert "伊泽" in summary
        assert "你好，伊塔" in summary

    def test_summary_long(self, sample_incoming_message):
        sample_incoming_message.content = "这是一条很长的消息" * 20
        summary = sample_incoming_message.summary()
        assert len(summary) < len(sample_incoming_message.content)
        assert "..." in summary


class TestOutgoingReply:
    def test_to_onebot_private_action(self):
        reply = OutgoingReply(user_id=3489352115, content="你好呀～")
        action = reply.to_onebot_action()
        assert action["action"] == "send_private_msg"
        assert action["params"]["user_id"] == 3489352115
        assert action["params"]["message"] == "你好呀～"
        assert "echo" in action

    def test_to_onebot_group_action(self):
        reply = OutgoingReply(
            user_id=3489352115,
            content="群发消息",
            msg_type=MessageType.GROUP,
        )
        action = reply.to_onebot_action(group_id=987654321)
        assert action["action"] == "send_group_msg"
        assert action["params"]["group_id"] == 987654321

    def test_echo_is_unique(self):
        r1 = OutgoingReply(user_id=123, content="a")
        r2 = OutgoingReply(user_id=456, content="b")
        assert r1.echo != r2.echo
