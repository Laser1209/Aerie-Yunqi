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
        e.update_trajectory_async = AsyncMock()
        e.get_state = MagicMock(return_value={
            "label": "neutral",
            "pad": {"P": 0.0, "A": 0.0, "D": 0.0},
            "thresholds": {
                "patience": {"value": 0, "threshold": 100, "label": "忍耐值", "pct": 0},
            },
            "eruption": None,
            "panel": "",
        })
        e.tune = MagicMock(side_effect=lambda text, **kwargs: text)
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
    def identity_resolver(self):
        resolver = MagicMock()

        def resolve_message(msg):
            msg.actor_id = "actor_primary"
            return msg

        resolver.resolve_message.side_effect = resolve_message
        return resolver

    @pytest.fixture
    def conversation_repository(self):
        repository = MagicMock()
        repository.enabled = False
        return repository

    @pytest.fixture
    def pipeline(
        self,
        router,
        emotion,
        ctx_builder,
        brain,
        send_queue,
        tool_registry,
        db,
        identity_resolver,
        conversation_repository,
    ):
        return Pipeline(
            router=router,
            emotion_engine=emotion,
            context_builder=ctx_builder,
            brain=brain,
            send_queue=send_queue,
            tool_registry=tool_registry,
            db=db,
            identity_resolver=identity_resolver,
            conversation_repository=conversation_repository,
        )

    @pytest.mark.asyncio
    async def test_handle_reads_complete_turn_history_from_repository(
        self,
        pipeline,
        conversation_repository,
    ):
        conversation_repository.enabled = True
        conversation_repository.recent_turn_history.return_value = [
            {"role": "user", "content": "上一问", "sequence": 0},
            {"role": "assistant", "content": "上一段", "sequence": 1},
            {"role": "assistant", "content": "下一段", "sequence": 2},
        ]
        msg = IncomingMessage.from_local("继续", 3998874040)

        await pipeline.handle(msg, force_full=True)

        conversation_repository.recent_turn_history.assert_called_once_with(
            actor_id="actor_primary",
            channel="desktop",
            channel_account_id="local",
            user_id=3998874040,
            limit=20,
        )
        assert pipeline.ctx_builder.build.call_args.kwargs["history_msgs"] == [
            {"role": "user", "content": "上一问", "sequence": 0},
            {"role": "assistant", "content": "上一段", "sequence": 1},
            {"role": "assistant", "content": "下一段", "sequence": 2},
        ]
        assert not any(
            "FROM chat_log" in call.args[0]
            for call in pipeline.db.query.call_args_list
        )

    @pytest.mark.asyncio
    async def test_basic_path_reads_complete_turn_history_from_repository(
        self,
        pipeline,
        conversation_repository,
    ):
        pipeline.router.route.return_value = "BASIC"
        conversation_repository.enabled = True
        conversation_repository.recent_turn_history.return_value = [
            {"role": "user", "content": "轻量上一问", "sequence": 0},
            {"role": "assistant", "content": "轻量上一答", "sequence": 1},
        ]
        msg = IncomingMessage.from_local("继续轻量", 3998874040)

        await pipeline.handle(msg)

        conversation_repository.recent_turn_history.assert_called_once_with(
            actor_id="actor_primary",
            channel="desktop",
            channel_account_id="local",
            user_id=3998874040,
            limit=10,
        )
        assert pipeline.ctx_builder.build.call_args.kwargs["history_msgs"] == [
            {"role": "user", "content": "轻量上一问", "sequence": 0},
            {"role": "assistant", "content": "轻量上一答", "sequence": 1},
        ]

    @pytest.mark.asyncio
    async def test_canonical_history_failure_falls_back_to_legacy_history(
        self,
        pipeline,
        conversation_repository,
    ):
        conversation_repository.enabled = True
        conversation_repository.recent_turn_history.side_effect = RuntimeError(
            "canonical read down"
        )
        pipeline.db.query.return_value = [
            {"role": "assistant", "content": "旧回复"},
            {"role": "user", "content": "旧问题"},
        ]
        msg = IncomingMessage.from_local("继续", 3998874040)

        await pipeline.handle(msg, force_full=True)

        history_sql, history_params = pipeline.db.query.call_args_list[0].args
        assert "FROM chat_log" in history_sql
        assert "LIMIT 20" in history_sql
        assert history_params == ("actor_primary", "desktop")
        assert pipeline.ctx_builder.build.call_args.kwargs["history_msgs"] == [
            {"role": "user", "content": "旧问题"},
            {"role": "assistant", "content": "旧回复"},
        ]

    @pytest.mark.asyncio
    async def test_disabled_conversation_repository_uses_only_legacy_path(
        self,
        pipeline,
        conversation_repository,
    ):
        msg = IncomingMessage.from_local("保持旧路径", 3998874040)

        await pipeline.handle(msg, force_full=True)

        conversation_repository.recent_turn_history.assert_not_called()
        conversation_repository.persist_turn.assert_not_called()
        history_sql, history_params = pipeline.db.query.call_args_list[0].args
        assert "FROM chat_log" in history_sql
        assert "LIMIT 20" in history_sql
        assert history_params == ("actor_primary", "desktop")

    @pytest.mark.asyncio
    async def test_handle_scopes_history_and_persistence_to_channel_identity(
        self,
        pipeline,
        identity_resolver,
    ):
        msg = IncomingMessage.from_local("隔离历史", 3998874040)

        await pipeline.handle(msg, force_full=True)

        identity_resolver.resolve_message.assert_called_once_with(msg)
        history_sql, history_params = pipeline.db.query.call_args_list[0].args
        assert "actor_id = ?" in history_sql
        assert "channel = ?" in history_sql
        assert history_params == ("actor_primary", "desktop")
        chat_rows = [
            call.args[1]
            for call in pipeline.db.insert.call_args_list
            if call.args[0] == "chat_log"
        ]
        assert len(chat_rows) >= 2
        assert all(row["actor_id"] == "actor_primary" for row in chat_rows)
        assert all(row["channel"] == "desktop" for row in chat_rows)
        assert all(row["channel_account_id"] == "local" for row in chat_rows)

    @pytest.mark.asyncio
    async def test_handle_local_message_returns_reply(self, pipeline):
        msg = IncomingMessage.from_local("你好", 3998874040)
        result = await pipeline.handle(msg, force_full=True)
        assert result is not None
        assert "reply" in result
        assert "route_mode" in result
        assert "emotion" in result

    @pytest.mark.asyncio
    async def test_handle_mirrors_full_turn_to_conversation_repository(
        self,
        pipeline,
        conversation_repository,
    ):
        conversation_repository.enabled = True
        pipeline._splitter.split = MagicMock(return_value=["第一段", "第二段"])
        msg = IncomingMessage.from_local("完整轮次", 3998874040)
        msg.attachments = [{"path": "a.png"}]

        await pipeline.handle(msg, force_full=True)

        conversation_repository.persist_turn.assert_called_once()
        persisted = conversation_repository.persist_turn.call_args.kwargs
        assert persisted["request_id"].startswith("req_")
        assert persisted["user_id"] == 3998874040
        assert persisted["actor_id"] == "actor_primary"
        assert persisted["channel"] == "desktop"
        assert persisted["channel_account_id"] == "local"
        assert persisted["user_content"] == "完整轮次"
        assert persisted["user_attachments"] == [{"path": "a.png"}]
        assert persisted["assistant_segments"] == ["第一段", "第二段"]

    @pytest.mark.asyncio
    async def test_canonical_mirror_waits_for_legacy_persistence_success(
        self,
        pipeline,
        conversation_repository,
    ):
        conversation_repository.enabled = True
        pipeline.db.insert.side_effect = RuntimeError("legacy down")
        msg = IncomingMessage.from_local("旧存储失败", 3998874040)

        await pipeline.handle(msg, force_full=True)

        conversation_repository.persist_turn.assert_not_called()

    @pytest.mark.asyncio
    async def test_canonical_mirror_failure_does_not_break_legacy_reply(
        self,
        pipeline,
        conversation_repository,
    ):
        conversation_repository.enabled = True
        conversation_repository.persist_turn.side_effect = RuntimeError("mirror down")
        msg = IncomingMessage.from_local("兼容旧路径", 3998874040)

        result = await pipeline.handle(msg, force_full=True)

        assert result is not None
        assert result["reply"] == "嗯。"
        assert pipeline.db.insert.call_count >= 2

    @pytest.mark.asyncio
    async def test_handle_qq_message_enqueues(self, pipeline):
        msg = IncomingMessage(user_id=3998874040, content="你好", source="qq")
        await pipeline.handle(msg)
        pipeline.send_queue.enqueue.assert_called_once()

    @pytest.mark.asyncio
    async def test_basic_path_scopes_history_and_persistence_to_channel_identity(
        self,
        pipeline,
    ):
        pipeline.router.route.return_value = "BASIC"
        msg = IncomingMessage.from_local("轻量隔离", 3998874040)

        await pipeline.handle(msg)

        history_sql, history_params = pipeline.db.query.call_args_list[0].args
        assert "actor_id = ?" in history_sql
        assert "channel = ?" in history_sql
        assert history_params == ("actor_primary", "desktop")
        chat_rows = [
            call.args[1]
            for call in pipeline.db.insert.call_args_list
            if call.args[0] == "chat_log"
        ]
        assert len(chat_rows) >= 2
        assert all(row["actor_id"] == "actor_primary" for row in chat_rows)
        assert all(row["channel"] == "desktop" for row in chat_rows)

    @pytest.mark.asyncio
    async def test_basic_path_mirrors_turn_to_conversation_repository(
        self,
        pipeline,
        conversation_repository,
    ):
        pipeline.router.route.return_value = "BASIC"
        conversation_repository.enabled = True
        pipeline._splitter.split = MagicMock(return_value=["轻量一", "轻量二"])
        msg = IncomingMessage.from_local("轻量轮次", 3998874040)

        await pipeline.handle(msg)

        conversation_repository.persist_turn.assert_called_once()
        persisted = conversation_repository.persist_turn.call_args.kwargs
        assert persisted["assistant_segments"] == ["轻量一", "轻量二"]
        assert persisted["actor_id"] == "actor_primary"
        assert persisted["channel"] == "desktop"

    @pytest.mark.asyncio
    async def test_basic_path_uses_actor_emotion_contract(
        self,
        pipeline,
    ):
        pipeline.router.route.return_value = "BASIC"
        msg = IncomingMessage.from_local("你好", 3998874040)

        await pipeline.handle(msg)

        pipeline.emotion.update_trajectory.assert_called_once_with(
            3998874040,
            "你好",
            actor_id="actor_primary",
        )
        pipeline.emotion.get_state.assert_called_once_with(
            3998874040,
            actor_id="actor_primary",
        )
        pipeline.emotion.tune.assert_called_once_with(
            "嗯。",
            actor_id="actor_primary",
        )

    @pytest.mark.asyncio
    async def test_handle_basic_uses_lightweight_reply(self, pipeline):
        pipeline.router.route.return_value = "BASIC"
        msg = IncomingMessage(user_id=99999, content="你好", source="qq")

        result = await pipeline.handle(msg)

        assert result is not None
        assert result["route_mode"] == "BASIC"
        assert result["lightweight"] is True
        pipeline.brain.chat.assert_awaited_once()
        assert pipeline.brain.chat.await_args.kwargs["tools"] is None
        pipeline.send_queue.enqueue.assert_called_once()

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
        pipeline.emotion.update_trajectory_async.assert_awaited_once_with(
            3998874040,
            "你好",
            actor_id="actor_primary",
        )

    @pytest.mark.asyncio
    async def test_handle_local_skip_send_queue(self, pipeline):
        msg = IncomingMessage.from_local("你好", 3998874040)
        await pipeline.handle(msg, force_full=True)
        pipeline.send_queue.enqueue.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_calls_emotion_tune(self, pipeline):
        msg = IncomingMessage.from_local("你好", 3998874040)
        await pipeline.handle(msg, force_full=True)
        pipeline.emotion.tune.assert_called_once_with(
            "嗯。",
            actor_id="actor_primary",
        )

    @pytest.mark.asyncio
    async def test_handle_db_error_graceful(self, pipeline):
        pipeline.db.insert = MagicMock(side_effect=Exception("DB error"))
        msg = IncomingMessage.from_local("你好", 3998874040)
        result = await pipeline.handle(msg, force_full=True)
        # Should not crash, still return result
        assert result is not None
        assert "reply" in result
        assert result["persisted"] is False
        assert "DB error" in result["persist_error"]

    @pytest.mark.asyncio
    async def test_handle_reports_successful_persistence(self, pipeline):
        msg = IncomingMessage.from_local("你好", 3998874040)
        result = await pipeline.handle(msg, force_full=True)
        assert result["persisted"] is True
        assert "persist_error" not in result

    @pytest.mark.asyncio
    async def test_handle_emotion_error_graceful(self, pipeline):
        pipeline.emotion.update_trajectory_async = AsyncMock(
            side_effect=Exception("Emo error")
        )
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
        emotion.update_trajectory_async = AsyncMock()
        emotion.get_state = MagicMock(return_value={
            "label": "neutral", "pad": {"P": 0, "A": 0, "D": 0},
            "thresholds": {}, "eruption": None, "panel": "",
        })
        emotion.tune = MagicMock(side_effect=lambda t, **kwargs: t)
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
