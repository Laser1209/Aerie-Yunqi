"""消息数据模型（DTO）与类型定义"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class MessageType(str, Enum):
    """消息类型"""

    PRIVATE = "private"
    GROUP = "group"
    TEMP = "temp"


class Intent(str, Enum):
    """消息意图分类"""

    CHAT = "chat"
    COMMAND = "command"
    QUERY = "query"


@dataclass
class Sender:
    """发送者信息"""

    user_id: int
    nickname: str = ""
    sex: str = "unknown"
    age: int = 0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Sender":
        return cls(
            user_id=int(data.get("user_id", 0)),
            nickname=data.get("nickname", ""),
            sex=data.get("sex", "unknown"),
            age=int(data.get("age", 0)),
        )


@dataclass
class IncomingMessage:
    """收到的消息"""

    msg_id: int
    user_id: int
    user_nickname: str
    msg_type: MessageType
    content: str
    raw_message: str
    timestamp: datetime
    sender: Sender
    self_id: int = 0
    group_id: Optional[int] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_onebot_event(cls, data: Dict[str, Any]) -> Optional["IncomingMessage"]:
        """
        从 OneBot11 事件解析消息。

        Args:
            data: OneBot11 JSON 事件

        Returns:
            IncomingMessage 实例，如果不是消息事件则返回 None
        """
        if data.get("post_type") != "message":
            return None

        msg_type = data.get("message_type", "")
        try:
            msg_type_enum = MessageType(msg_type)
        except ValueError:
            return None

        sender_data = data.get("sender", {})
        sender = Sender.from_dict(sender_data)

        return cls(
            msg_id=int(data.get("message_id", 0)),
            user_id=int(data.get("user_id", 0)),
            user_nickname=sender.nickname,
            msg_type=msg_type_enum,
            content=str(data.get("message", "")),
            raw_message=str(data.get("raw_message", "")),
            timestamp=datetime.fromtimestamp(data.get("time", 0)),
            sender=sender,
            self_id=int(data.get("self_id", 0)),
            group_id=int(data.get("group_id")) if data.get("group_id") else None,
            raw_data=data,
        )

    @property
    def is_private(self) -> bool:
        return self.msg_type == MessageType.PRIVATE

    @property
    def is_group(self) -> bool:
        return self.msg_type == MessageType.GROUP

    def summary(self) -> str:
        """返回简短的消息摘要"""
        display = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"[{self.msg_type.value}] {self.user_nickname}({self.user_id}): {display}"


@dataclass
class OutgoingReply:
    """待发送的回复"""

    user_id: int
    content: str
    msg_type: MessageType = MessageType.PRIVATE
    echo: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_onebot_action(self, group_id: Optional[int] = None) -> Dict[str, Any]:
        """
        转换为 OneBot11 发送消息的 API 调用。

        Returns:
            OneBot11 send_msg / send_private_msg action
        """
        if self.msg_type == MessageType.GROUP and group_id:
            return {
                "action": "send_group_msg",
                "params": {
                    "group_id": group_id,
                    "message": self.content,
                },
                "echo": self.echo,
            }
        else:
            return {
                "action": "send_private_msg",
                "params": {
                    "user_id": self.user_id,
                    "message": self.content,
                },
                "echo": self.echo,
            }
