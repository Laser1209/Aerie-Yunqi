"""Aerie · 云栖 — Gate 2: LLM 主动撤回指令 (<recall>) 测试.

覆盖:
  1. 单元: extract_recall_instruction / strip_recall_instruction / execute
  2. 集成: Pipeline 收到含 <recall> 的 LLM 输出 → try_recall 被调 + 标签被剔除
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from core.recall_instruction import (
    extract_recall_instruction,
    strip_recall_instruction,
    execute_recall_instruction,
)
from core.pipeline import Pipeline
from communication.message import IncomingMessage
from communication.recall_manager import RecallManager, RecallConfig


class TestRecallInstructionUnit:
    def test_extract_present(self):
        inst = extract_recall_instruction(
            "刚刚那句我想收回 <recall reason=\"说错话了\">这句我撤回</recall> 忽略吧"
        )
        assert inst is not None
        assert inst.reason == "说错话了"
        assert "<recall" in inst.raw_tag

    def test_extract_absent(self):
        assert extract_recall_instruction("今天天气不错") is None

    def test_extract_empty(self):
        assert extract_recall_instruction("") is None

    def test_extract_case_insensitive(self):
        inst = extract_recall_instruction("<RECALL reason=\"x\">a</RECALL>")
        assert inst is not None
        assert inst.reason == "x"

    def test_strip_removes_tag(self):
        stripped = strip_recall_instruction(
            "正文 <recall reason=\"r\">这句我撤回</recall> 尾巴"
        )
        assert "<recall" not in stripped
        assert "正文" in stripped and "尾巴" in stripped

    def test_strip_none(self):
        assert strip_recall_instruction("你好") == "你好"

    def test_execute_no_manager(self):
        result = asyncio.run(execute_recall_instruction(
            None, channel="qq", channel_account_id="1", user_id=1, reason="x",
        ))
        assert result["status"] == "skipped"

    def test_execute_calls_try_recall(self):
        rm = RecallManager(config=RecallConfig(
            enabled=True, window_seconds=120,
            min_recall_gap_seconds=0, max_recalls_per_session=5,
        ))
        rm.record_sent(1, "hi", msg_id=7, channel="qq")
        result = asyncio.run(execute_recall_instruction(
            rm, channel="qq", channel_account_id=None, user_id=1, reason="regret",
        ))
        assert result["status"] == "ok"
        assert result["msg_id"] == 7
        assert result["reason"] == "regret"


class TestPipelineRecallInstructionIntegration:
    @pytest.fixture
    def recall_manager(self):
        rm = RecallManager(config=RecallConfig(
            enabled=True, window_seconds=120,
            min_recall_gap_seconds=0, max_recalls_per_session=5,
            triggers=["send_after_thinking", "regret_correction"],
        ))
        # 预置一条已发送的 AI 消息供撤回 (与 pipeline 消息同一 user)
        rm.record_sent(3998874040, "之前发的内容", msg_id=100, qq_message_id=9001, channel="qq")
        return rm

    @pytest.fixture
    def pipeline(self, recall_manager):
        router = MagicMock()
        router.route.return_value = "FULL"
        emotion = MagicMock()
        emotion.update_trajectory = MagicMock()
        emotion.update_trajectory_async = AsyncMock()
        emotion.get_state = MagicMock(return_value={
            "label": "neutral", "pad": {}, "thresholds": {}, "eruption": None,
        })
        emotion.tune = MagicMock(side_effect=lambda text, **kw: text)
        ctx_builder = MagicMock()
        ctx_builder.build.return_value = [
            {"role": "system", "content": "你是伊塔"},
            {"role": "user", "content": "hi"},
        ]
        brain = MagicMock()
        brain.chat = AsyncMock(return_value=MagicMock(
            text="这句我发错了 <recall reason=\"regret_correction\">撤回</recall> 忽略吧",
            provider="siliconflow", model="test",
            tokens_prompt=10, tokens_completion=5, duration_ms=200,
            react_trace=None, tool_results=None, usage={},
        ))
        send_queue = MagicMock()
        tool_registry = MagicMock()
        tool_registry.get_openai_schema.return_value = []
        db = MagicMock()
        db.query.return_value = []
        db.query_one.return_value = None
        db.insert = MagicMock(return_value=1)
        identity_resolver = MagicMock()
        identity_resolver.resolve_message = MagicMock(side_effect=lambda m: m)
        conversation_repository = MagicMock()
        conversation_repository.enabled = False

        return Pipeline(
            router=router, emotion_engine=emotion, context_builder=ctx_builder,
            brain=brain, send_queue=send_queue, tool_registry=tool_registry,
            db=db, recall_manager=recall_manager,
            identity_resolver=identity_resolver,
            conversation_repository=conversation_repository,
        )

    @pytest.mark.asyncio
    async def test_recall_instruction_executes_and_strips(self, pipeline, recall_manager):
        msg = IncomingMessage.from_onebot_event(
            {"sender": {"user_id": 3998874040}, "message_type": "private",
             "raw_message": "hi", "message": []}
        )
        result = await pipeline.handle(msg, force_full=True)

        # 撤回被触发: 该 channel 最近记录已 no_recent_message (被撤回/清空语义)
        # 由于 try_recall 只改预算不清记录, 校验预算计数 +1 且回复正文无标签。
        assert recall_manager._session_recall_count[("qq", "3998874040")] == 1

        # 正文不应包含 <recall> 标签
        assert "<recall" not in (result or {}).get("reply_text", "")
        assert "撤回" not in (result or {}).get("reply_text", "")
