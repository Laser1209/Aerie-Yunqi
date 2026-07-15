"""聊天日志存储单元测试"""

import pytest
import pytest_asyncio
import os
import tempfile
from datetime import datetime
from communication.message import IncomingMessage, OutgoingReply, MessageType, Sender


@pytest.fixture
def temp_db():
    """创建临时 SQLite 数据库文件"""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="test_chat_")
    os.close(fd)
    yield path
    # 清理 WAL/SHM 文件后再删除主文件
    for suffix in ("", "-wal", "-shm"):
        p = path + suffix
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass


@pytest_asyncio.fixture
async def chat_logger(temp_db):
    """创建已初始化的 ChatLogger 实例"""
    from memory.chat_log import ChatLogger

    logger = ChatLogger(temp_db)
    await logger.initialize()
    yield logger
    await logger.close()


def sample_incoming(content="你好"):
    """创建示例 IncomingMessage"""
    return IncomingMessage(
        msg_id=123456,
        user_id=3489352115,
        user_nickname="伊泽",
        msg_type=MessageType.PRIVATE,
        content=content,
        raw_message=content,
        timestamp=datetime.now(),
        sender=Sender(user_id=3489352115, nickname="伊泽"),
        self_id=3998874040,
    )


def sample_outgoing(content="主人你好～"):
    """创建示例 OutgoingReply"""
    return OutgoingReply(
        user_id=3489352115,
        content=content,
        msg_type=MessageType.PRIVATE,
    )


class TestChatLogger:
    @pytest.mark.asyncio
    async def test_initialize_creates_db(self, temp_db):
        """测试初始化创建数据库文件"""
        from memory.chat_log import ChatLogger

        logger = ChatLogger(temp_db)
        await logger.initialize()
        assert os.path.exists(temp_db)

        # 清理
        await logger.close()

    @pytest.mark.asyncio
    async def test_log_incoming(self, chat_logger):
        """测试记录收到的消息"""
        msg = sample_incoming("你好主人")
        row_id = await chat_logger.log_incoming(msg, intent="chat")
        assert row_id is not None
        assert row_id > 0

    @pytest.mark.asyncio
    async def test_log_outgoing(self, chat_logger):
        """测试记录发出的回复"""
        reply = sample_outgoing("主人你好～")
        row_id = await chat_logger.log_outgoing(reply)
        assert row_id is not None
        assert row_id > 0

    @pytest.mark.asyncio
    async def test_get_recent_returns_correct_count(self, chat_logger):
        """测试 get_recent 返回正确数量的记录"""
        for i in range(5):
            msg = sample_incoming(f"测试消息 {i}")
            await chat_logger.log_incoming(msg)

        records = await chat_logger.get_recent(3489352115, limit=3)
        assert len(records) == 3

    @pytest.mark.asyncio
    async def test_get_recent_only_user_role(self, chat_logger):
        """测试按角色过滤"""
        msg = sample_incoming("用户消息")
        await chat_logger.log_incoming(msg)
        reply = sample_outgoing("AI 回复")
        await chat_logger.log_outgoing(reply)

        user_records = await chat_logger.get_recent(3489352115, limit=10, role="user")
        assert len(user_records) >= 1
        assert all(r["role"] == "user" for r in user_records)

    @pytest.mark.asyncio
    async def test_get_recent_reverse_chronological(self, chat_logger):
        """测试最近记录按时间逆序（最早在前）"""
        msg_a = sample_incoming("第一条消息")
        msg_b = sample_incoming("第二条消息")
        await chat_logger.log_incoming(msg_a)
        await chat_logger.log_incoming(msg_b)

        records = await chat_logger.get_recent(3489352115, limit=10)
        assert records[0]["content"] == "第一条消息"
        assert records[1]["content"] == "第二条消息"

    @pytest.mark.asyncio
    async def test_get_stats_empty(self, chat_logger):
        """测试空数据库统计"""
        stats = await chat_logger.get_stats(user_id=999999999)
        # 空统计
        assert stats.get("user_msgs") == 0 or stats.get("user_msgs") is None

    @pytest.mark.asyncio
    async def test_get_stats_with_data(self, chat_logger):
        """测试有数据时的统计"""
        msg = sample_incoming("统计测试")
        await chat_logger.log_incoming(msg)
        reply = sample_outgoing("AI 回复")
        await chat_logger.log_outgoing(reply)

        stats = await chat_logger.get_stats()
        assert stats["user_msgs"] >= 1
        assert stats["assistant_msgs"] >= 1

    @pytest.mark.asyncio
    async def test_close(self, chat_logger):
        """测试关闭数据库连接"""
        await chat_logger.close()
        # 不抛异常即为通过

    @pytest.mark.asyncio
    async def test_idempotent_initialize(self, chat_logger):
        """测试重复初始化（幂等）"""
        await chat_logger.initialize()
        await chat_logger.initialize()
        # 不抛异常即为通过

    @pytest.mark.asyncio
    async def test_log_with_intent(self, chat_logger):
        """测试带意图标签的记录"""
        msg = sample_incoming("打开文件")
        await chat_logger.log_incoming(msg, intent="command")
        records = await chat_logger.get_recent(3489352115, limit=1)
        assert len(records) == 1
        assert records[0]["intent"] == "command"
