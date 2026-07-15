"""Tests for message processing pipeline."""

import pytest
from unittest.mock import MagicMock

from core.pipeline import Pipeline
from communication.message import OutgoingReply


class TestPipeline:
    """Test 5-stage pipeline helpers (color_reply only — full pipeline needs deps)."""

    @pytest.fixture
    def pipeline(self):
        # Create a minimal pipeline with mocks for all deps
        return Pipeline(
            router=MagicMock(),
            emotion_engine=MagicMock(),
            context_builder=MagicMock(),
            brain=MagicMock(),
            send_queue=MagicMock(),
            tool_registry=MagicMock(),
            recall_manager=MagicMock(),
        )

    def test_color_reply_defaults(self, pipeline):
        reply = pipeline._color_reply(123, "测试回复", "joy")
        assert isinstance(reply, OutgoingReply)
        assert reply.content == "测试回复"
        assert reply.mood == "joy"
        assert reply.render_mode == "text"

    def test_color_reply_system_keyword_markdown(self, pipeline):
        reply = pipeline._color_reply(123, "查询系统状态", "neutral")
        assert reply.render_mode == "markdown"

    def test_color_reply_cpu_markdown(self, pipeline):
        reply = pipeline._color_reply(123, "CPU 使用率 45%", "neutral")
        assert reply.render_mode == "markdown"

    def test_color_reply_memory_markdown(self, pipeline):
        reply = pipeline._color_reply(123, "内存占用", "neutral")
        assert reply.render_mode == "markdown"

    def test_color_reply_normal_no_markdown(self, pipeline):
        reply = pipeline._color_reply(123, "今天天气真好", "joy")
        assert reply.render_mode == "text"

    def test_color_reply_scene_emotional(self, pipeline):
        for mood in ("sad", "anger", "fear"):
            reply = pipeline._color_reply(123, "test", mood)
            assert reply.scene == "emotional"

    def test_color_reply_scene_daily(self, pipeline):
        for mood in ("joy", "neutral"):
            reply = pipeline._color_reply(123, "test", mood)
            assert reply.scene == "daily"
