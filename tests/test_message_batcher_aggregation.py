"""Tests for MessageBatcher 首条聚合窗 (T_idle / T_cap) 语义.

覆盖:
  - 首条到达后不立即派发, T_idle 静默后派发;
  - T_idle 内新消息到达会重置计时;
  - 总时长到 T_cap 时强制派发;
  - 任务命中时跳过聚合窗立即派发;
  - enabled=false 时行为不变 (立即派发)。

时序控制: 直接给配置注入很小的 T_idle/T_cap + 短 asyncio.sleep,
避免真实长等待, 保持测试快速稳定。
"""

import asyncio

import pytest

from communication.message import IncomingMessage
from core.message_batcher import MessageBatcher
from core.task_loop import classify


def _batch_cfg(*, enabled=True, idle=0.2, cap=5.0, window=1.5, max_size=10):
    """构造 message_batching 配置 (含首条聚合窗键)."""
    return {
        "enabled": enabled,
        "window_seconds": window,
        "max_batch_size": max_size,
        "base_interval_seconds": 0.5,
        "chars_per_second": 4,
        "min_interval_seconds": 0.3,
        "max_interval_seconds": 5.0,
        "first_message_idle_seconds": idle,
        "first_message_cap_seconds": cap,
    }


def _patch_config(monkeypatch, cfg):
    monkeypatch.setattr(
        "core.message_batcher.get_message_batching_config", lambda: cfg
    )


def _make_message(content, user_id=12345):
    return IncomingMessage(
        user_id=user_id,
        content=content,
        msg_type="private",
        source="qq",
        channel="qq",
        channel_account_id=str(user_id),
    )


class TestFirstMessageAggregation:
    def setup_method(self):
        MessageBatcher.reset_instance()
        self.received: list[tuple[list[IncomingMessage], str]] = []

    def teardown_method(self):
        MessageBatcher.reset_instance()

    async def _collect(self, messages, batch_id):
        self.received.append((list(messages), batch_id))
        await asyncio.sleep(0)

    async def _make_batcher(self, monkeypatch, cfg):
        _patch_config(monkeypatch, cfg)
        batcher = await MessageBatcher.get_instance()
        batcher.register_callback(self._collect)
        return batcher

    @pytest.mark.asyncio
    async def test_first_message_waits_idle_then_dispatches(self, monkeypatch):
        """首条不再零等待: T_idle 静默期结束后才派发。"""
        batcher = await self._make_batcher(monkeypatch, _batch_cfg(idle=0.25))

        await batcher.submit_message(_make_message("msg1", user_id=101))
        await asyncio.sleep(0.05)
        assert len(self.received) == 0, "首条消息不应立即派发"

        await asyncio.sleep(0.35)
        assert len(self.received) == 1
        assert [m.content for m in self.received[0][0]] == ["msg1"]

    @pytest.mark.asyncio
    async def test_new_message_resets_idle_timer(self, monkeypatch):
        """T_idle 内到达的新消息会重置静默计时, 并并入同一批。"""
        batcher = await self._make_batcher(monkeypatch, _batch_cfg(idle=0.4))

        await batcher.submit_message(_make_message("m1", user_id=102))
        await asyncio.sleep(0.2)
        # 此时距首条 0.2s < 0.4s, 仍在静默期 -> 不派发。
        assert len(self.received) == 0

        await batcher.submit_message(_make_message("m2", user_id=102))
        await asyncio.sleep(0.2)
        # 距 m2 仅 0.2s < 0.4s, 计时已被重置 -> 仍不派发。
        assert len(self.received) == 0, "新消息应重置静默计时"

        await asyncio.sleep(0.4)
        assert len(self.received) == 1
        assert [m.content for m in self.received[0][0]] == ["m1", "m2"]

    @pytest.mark.asyncio
    async def test_cap_forces_dispatch(self, monkeypatch):
        """持续有新消息时, 聚合窗总时长到 T_cap 仍强制派发。

        设 idle=0.5 / cap=0.9, 每 0.2s 来一条 (间隔 < idle, 静默计时不断被重置)。
        若只看 idle, 派发会拖到「最后一条 + 0.5 = 1.3s」; 而 cap=0.9s 会先到。
        因此在 1.2s 处已收到批次, 即证明是 cap 而非 idle 触发。
        """
        batcher = await self._make_batcher(
            monkeypatch, _batch_cfg(idle=0.5, cap=0.9)
        )

        await batcher.submit_message(_make_message("m1", user_id=103))
        for i in range(2, 6):
            await asyncio.sleep(0.2)
            await batcher.submit_message(_make_message(f"m{i}", user_id=103))

        # 到此处 elapsed≈0.8s; 再等到 ≈1.2s: 早于 idle-only 的 1.3s。
        await asyncio.sleep(0.4)
        assert len(self.received) == 1, "到达 T_cap 必须强制派发 (早于 idle 静默)"
        contents = [m.content for m in self.received[0][0]]
        assert contents[0] == "m1"
        assert len(contents) >= 3, f"应合并多条聚合窗消息, got {contents}"

    @pytest.mark.asyncio
    async def test_task_message_skips_aggregation(self, monkeypatch):
        """任务判定命中的消息跳过聚合窗立即派发; 普通消息仍走聚合窗。"""
        batcher = await self._make_batcher(
            monkeypatch, _batch_cfg(idle=5.0, cap=10.0)
        )

        task_text = "帮我创建一个文件夹"
        assert classify(task_text) is not None, "测试前置: 该文本应被判为任务"

        await batcher.submit_message(_make_message(task_text, user_id=901))
        await asyncio.sleep(0.05)
        assert len(self.received) == 1, "任务消息应跳过聚合窗立即派发"
        assert [m.content for m in self.received[0][0]] == [task_text]

        # 对照: 普通消息在同样的长聚合窗下不会立即派发。
        await batcher.submit_message(_make_message("今天天气不错", user_id=902))
        await asyncio.sleep(0.05)
        assert len(self.received) == 1, "普通消息不应立即派发"

    @pytest.mark.asyncio
    async def test_disabled_batching_still_immediate(self, monkeypatch):
        """enabled=false 时保持全量立即派发的既有行为。"""
        batcher = await self._make_batcher(
            monkeypatch, _batch_cfg(enabled=False, idle=5.0, cap=10.0)
        )

        await batcher.submit_message(_make_message("hello", user_id=104))
        await asyncio.sleep(0.05)

        assert len(self.received) == 1


class TestLocalTypingSignal:
    """本地通道「输入框有内容」信号：推后静默截止，但绝不越过 T_cap。"""

    def setup_method(self):
        MessageBatcher.reset_instance()
        self.received: list[tuple[list[IncomingMessage], str]] = []

    def teardown_method(self):
        MessageBatcher.reset_instance()

    async def _collect(self, messages, batch_id):
        self.received.append((list(messages), batch_id))
        await asyncio.sleep(0)

    async def _make_batcher(self, monkeypatch, cfg):
        _patch_config(monkeypatch, cfg)
        batcher = await MessageBatcher.get_instance()
        batcher.register_callback(self._collect)
        return batcher

    @pytest.mark.asyncio
    async def test_typing_postpones_idle_within_cap(self, monkeypatch):
        """用户在输入框继续打字 → 静默期被推后，本轮不提前派发。"""
        batcher = await self._make_batcher(
            monkeypatch, _batch_cfg(idle=0.3, cap=1.2)
        )
        conv = "qq:105"

        await batcher.submit_message(_make_message("第一句", user_id=105))
        await asyncio.sleep(0.2)
        batcher.notify_typing(conv)  # 推后 idle 到 0.5s
        await asyncio.sleep(0.15)    # elapsed≈0.35s < 0.5s

        assert len(self.received) == 0, "仍在输入时不应按原 idle 提前派发"

        await asyncio.sleep(0.4)     # elapsed≈0.75s，静默期已过
        assert len(self.received) == 1
        assert [m.content for m in self.received[0][0]] == ["第一句"]

    @pytest.mark.asyncio
    async def test_typing_never_exceeds_cap(self, monkeypatch):
        """一直输入也不会饿死批次：T_cap 到点必须派发。"""
        batcher = await self._make_batcher(
            monkeypatch, _batch_cfg(idle=0.3, cap=0.5)
        )
        conv = "qq:106"

        await batcher.submit_message(_make_message("m1", user_id=106))
        for _ in range(8):               # 持续输入 ≈0.8s，远超 cap
            await asyncio.sleep(0.1)
            batcher.notify_typing(conv)

        assert len(self.received) == 1, "T_cap 到点必须强制派发"

    @pytest.mark.asyncio
    async def test_typing_noop_when_idle_or_disabled(self, monkeypatch):
        """无聚合窗（空闲态 / 关闭批处理）时是 no-op，不抛错、不派发。"""
        batcher = await self._make_batcher(
            monkeypatch, _batch_cfg(idle=5.0, cap=10.0)
        )
        batcher.notify_typing("qq:107")          # 空闲态
        await asyncio.sleep(0.05)
        assert self.received == []

        MessageBatcher.reset_instance()
        disabled = await self._make_batcher(
            monkeypatch, _batch_cfg(enabled=False, idle=5.0, cap=10.0)
        )
        disabled.notify_typing("qq:107")         # 关闭批处理
        await asyncio.sleep(0.05)
        assert self.received == []
