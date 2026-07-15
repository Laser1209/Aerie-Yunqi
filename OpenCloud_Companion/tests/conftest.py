"""pytest 配置与共享 fixtures"""

import pytest
from datetime import datetime

from communication.message import (
    IncomingMessage,
    OutgoingReply,
    MessageType,
    Sender,
    Intent,
)


@pytest.fixture
def sample_onebot_private_msg() -> dict:
    """模拟 OneBot11 私聊消息事件"""
    return {
        "post_type": "message",
        "message_type": "private",
        "sub_type": "friend",
        "message_id": 123456,
        "user_id": 3489352115,
        "message": "你好，伊塔",
        "raw_message": "你好，伊塔",
        "font": 14,
        "sender": {
            "user_id": 3489352115,
            "nickname": "伊泽",
            "sex": "male",
            "age": 25,
        },
        "time": 1752560000,
        "self_id": 3998874040,
    }


@pytest.fixture
def sample_onebot_group_msg() -> dict:
    """模拟 OneBot11 群聊消息事件"""
    return {
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "message_id": 654321,
        "user_id": 123456789,
        "group_id": 987654321,
        "message": "大家好",
        "raw_message": "大家好",
        "sender": {
            "user_id": 123456789,
            "nickname": "路人甲",
            "sex": "unknown",
            "age": 0,
        },
        "time": 1752560000,
        "self_id": 3998874040,
    }


@pytest.fixture
def sample_onebot_non_message() -> dict:
    """模拟 OneBot11 非消息事件（如心跳）"""
    return {
        "post_type": "meta_event",
        "meta_event_type": "heartbeat",
        "time": 1752560000,
        "self_id": 3998874040,
    }


@pytest.fixture
def sample_incoming_message() -> IncomingMessage:
    """标准私聊消息 DTO"""
    return IncomingMessage(
        msg_id=123456,
        user_id=3489352115,
        user_nickname="伊泽",
        msg_type=MessageType.PRIVATE,
        content="你好，伊塔",
        raw_message="你好，伊塔",
        timestamp=datetime.fromtimestamp(1752560000),
        sender=Sender(user_id=3489352115, nickname="伊泽", sex="male", age=25),
        self_id=3998874040,
    )
