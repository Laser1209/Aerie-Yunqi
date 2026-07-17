"""Tests for Pipeline v9.0 — 10-stage message processing.

Uses mock dependencies to test pipeline stages in isolation.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from core.pipeline import Pipeline
from communication.message import IncomingMessage


class TestPipelineHandle:
    """Test handle() end-to-end with mock dependencies."""

    @pytest.fixture
    def router(self):
        r = MagicMock()
        r.route.return_value = "FULL"
        return r

    @pytest.fixture
    def emotion(self):
        e = MagicMock()
        e.update_trajectory = MagicMock()
        e.get_state = MagicMock(return_value={
            "label": "neutral",
            "pad": {"P": 0.0, "A": 0.0, "D": 0.0},
            "thresholds": {
                "patience": {"value": 0, "threshold": 100, "label": "忍耐值", "pct": 0},
            },
            "eruption": None,
            "panel": "",
        })
        e.tune = MagicMock(side_effect=lambda text: text)
        return e

    @pytest.fixture
    def ctx_builder(self):
        cb = MagicMock()
        cb.build.return_value = [
            {"role": "system", "content": "你是伊塔"},
            {"role": "user", "content": "你好"},
        ]
        return cb

    @pytest.fixture
    def brain(self):
        b = MagicMock()
        b.chat = AsyncMock(return_value=MagicMock(
            text="嗯。",
            provider="siliconflow",
            model="test",
            tokens_prompt=10,
            tokens_completion=5,
            duration_ms=200,
        ))
        return b

    @pytest.fixture
    def send_queue(self):
        sq = MagicMock()
        sq.enqueue = MagicMock()
        return sq

    @pytest.fixture
    def tool_registry(self):
        tr = MagicMock()
        tr.get_openai_schema.return_value = []
        return tr

    @pytest.fixture
    def db(self):
        d = MagicMock()
        d.query.return_value = []
        d.query_one.return_value = None
        d.insert = MagicMock(return_value=1)
        return d

    @pytest.fixture
    def pipeline(self, router, emotion, ctx_builder, brain, send_queue, tool_registry, db):
        return Pipeline(
            router=router,
            emotion_engine=emotion,
            context_builder=ctx_builder,
            brain=brain,
            send_queue=send_queue,
            tool_registry=tool_registry,
            db=db,
        )

    @pytest.mark.asyncio
    async def test_handle_local_message_returns_reply(self, pipeline):
        msg = IncomingMessage.from_local("你好", 3998874040)
        result = await pipeline.handle(msg, force_full=True)
        assert result is not None
        assert "reply" in result
        assert "route_mode" in result
        assert "emotion" in result

    @pytest.mark.asyncio
    async def test_handle_qq_message_enqueues(self, pipeline):
        msg = IncomingMessage(user_id=3998874040, content="你好", source="qq")
        await pipeline.handle(msg)
        pipeline.send_queue.enqueue.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_basic_skip_stranger(self, pipeline):
        pipeline.router.route.return_value = "BASIC"
        msg = IncomingMessage(user_id=99999, content="你好", source="qq")
        result = await pipeline.handle(msg)
        assert result is None
        # Brain should not have been called
        pipeline.brain.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_saves_to_db(self, pipeline):
        msg = IncomingMessage.from_local("测试", 3998874040)
        await pipeline.handle(msg, force_full=True)
        # Should have inserted user message and assistant reply
        assert pipeline.db.insert.call_count >= 2

    @pytest.mark.asyncio
    async def test_handle_includes_emotion_in_result(self, pipeline):
        pipeline.emotion.get_state.return_value = {
            "label": "joy",
            "pad": {"P": 0.6, "A": 0.5, "D": 0.3},
            "thresholds": {},
            "eruption": None,
            "panel": "",
        }
        msg = IncomingMessage.from_local("爱你", 3998874040)
        result = await pipeline.handle(msg, force_full=True)
        assert result["emotion"] == "joy"

    @pytest.mark.asyncio
    async def test_handle_calls_emotion_update(self, pipeline):
        msg = IncomingMessage.from_local("你好", 3998874040)
        await pipeline.handle(msg, force_full=True)
        pipeline.emotion.update_trajectory.assert_called_once_with(3998874040, "你好")

    @pytest.mark.asyncio
    async def test_handle_local_skip_send_queue(self, pipeline):
        msg = IncomingMessage.from_local("你好", 3998874040)
        await pipeline.handle(msg, force_full=True)
        pipeline.send_queue.enqueue.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_calls_emotion_tune(self, pipeline):
        msg = IncomingMessage.from_local("你好", 3998874040)
        await pipeline.handle(msg, force_full=True)
        pipeline.emotion.tune.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_db_error_graceful(self, pipeline):
        pipeline.db.insert = MagicMock(side_effect=Exception("DB error"))
        msg = IncomingMessage.from_local("你好", 3998874040)
        result = await pipeline.handle(msg, force_full=True)
        # Should not crash, still return result
        assert result is not None
        assert "reply" in result

    @pytest.mark.asyncio
    async def test_handle_emotion_error_graceful(self, pipeline):
        pipeline.emotion.update_trajectory = MagicMock(side_effect=Exception("Emo error"))
        msg = IncomingMessage.from_local("你好", 3998874040)
        result = await pipeline.handle(msg, force_full=True)
        assert result is not None


class TestPipelineRouteModes:
    """Test different route mode behaviors."""

    @pytest.mark.asyncio
    async def test_handle_auto_mode_still_returns_reply(self):
        """AUTO mode should still process and return, just with lighter context."""
        router = MagicMock()
        router.route.return_value = "AUTO"
        emotion = MagicMock()
        emotion.update_trajectory = MagicMock()
        emotion.get_state = MagicMock(return_value={
            "label": "neutral", "pad": {"P": 0, "A": 0, "D": 0},
            "thresholds": {}, "eruption": None, "panel": "",
        })
        emotion.tune = MagicMock(side_effect=lambda t: t)
        ctx = MagicMock()
        ctx.build.return_value = [{"role": "system", "content": "你是伊塔"}, {"role": "user", "content": "hi"}]
        brain = MagicMock()
        brain.chat = AsyncMock(return_value=MagicMock(
            text="你好。", provider="test", model="test",
            tokens_prompt=5, tokens_completion=3, duration_ms=100,
        ))
        sq = MagicMock()
        tr = MagicMock()
        tr.get_openai_schema.return_value = []
        db = MagicMock()
        db.query.return_value = []
        db.insert.return_value = 1

        pipeline = Pipeline(router, emotion, ctx, brain, sq, tr, db)
        msg = IncomingMessage.from_local("hi", 3489352115)
        result = await pipeline.handle(msg, force_full=True)
        assert result is not None
