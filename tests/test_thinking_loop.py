"""C 部分：后台思考循环骨架测试（默认关闭 / 幂等 / 异常隔离 / 预算）。"""

from __future__ import annotations

import asyncio
import time

import pytest

from core.thinking_loop import (
    DEFAULT_MAX_TOKENS_PER_DAY,
    MIN_INTERVAL_SECONDS,
    ThinkingLoop,
    default_step,
)


@pytest.mark.asyncio
async def test_disabled_by_default():
    loop = ThinkingLoop()
    assert loop.status()["enabled"] is False
    assert await loop.start() is False
    assert loop.running is False
    assert loop.status()["steps_total"] == 0
    await loop.stop()  # 未启动时 stop 也必须安全


@pytest.mark.asyncio
async def test_start_stop_are_idempotent():
    loop = ThinkingLoop(enabled=True, interval_seconds=0.05)
    assert await loop.start() is True
    assert loop.running is True
    assert await loop.start() is False  # 重复 start 不叠加任务
    await loop.stop()
    assert loop.running is False
    await loop.stop()  # 重复 stop 安全
    assert loop.running is False


@pytest.mark.asyncio
async def test_loop_executes_step_and_tracks_tokens():
    calls: list[int] = []

    async def step() -> dict:
        calls.append(1)
        return {"status": "ok", "tokens": 3}

    loop = ThinkingLoop(step=step, enabled=True, interval_seconds=0.05)
    await loop.start()
    await asyncio.sleep(0.25)
    await loop.stop()

    status = loop.status()
    assert len(calls) >= 2  # 至少跑过两轮
    assert status["steps_total"] >= 2
    assert status["tokens_today"] == status["steps_total"] * 3


@pytest.mark.asyncio
async def test_default_step_is_zero_token():
    loop = ThinkingLoop(step=default_step, enabled=True)
    result = await loop.run_once()
    assert result["tokens"] == 0
    assert result["status"] == "idle"
    assert loop.status()["tokens_today"] == 0
    assert (await default_step())["status"] == "idle"


@pytest.mark.asyncio
async def test_t1_run_once_respects_enabled_flag():
    """T1: 未启用时 run_once 不得执行 step、不得计 token。"""
    calls: list[int] = []

    async def step() -> dict:
        calls.append(1)
        return {"status": "ok", "tokens": 7}

    loop = ThinkingLoop(step=step, enabled=False)
    assert await loop.run_once() is None
    assert calls == []
    status = loop.status()
    assert status["tokens_today"] == 0
    assert status["steps_total"] == 0
    assert status["errors_total"] == 0


@pytest.mark.asyncio
async def test_step_exception_is_isolated():
    async def step() -> dict:
        raise RuntimeError("boom inside thinking")

    loop = ThinkingLoop(step=step, enabled=True, interval_seconds=0.05)
    await loop.start()
    await asyncio.sleep(0.25)
    assert loop.running is True  # 异常没能把循环带崩
    status = loop.status()
    await loop.stop()
    assert status["errors_total"] >= 2
    assert status["steps_total"] == 0
    assert "RuntimeError: boom inside thinking" == status["last_error"]
    assert loop.running is False


@pytest.mark.asyncio
async def test_sync_step_exception_does_not_escape():
    def step() -> dict:
        raise ValueError("sync boom")

    loop = ThinkingLoop(step=step, enabled=True, interval_seconds=0.05)
    assert await loop.run_once() is None
    assert loop.status()["errors_total"] == 1
    assert "ValueError: sync boom" in loop.status()["last_error"]


@pytest.mark.asyncio
async def test_step_timeout_is_isolated():
    async def step() -> dict:
        await asyncio.sleep(1.0)
        return {"status": "ok"}

    loop = ThinkingLoop(
        step=step, enabled=True, interval_seconds=0.05, step_timeout_seconds=0.1
    )
    assert await loop.run_once() is None
    status = loop.status()
    assert status["errors_total"] == 1
    assert "timeout" in status["last_error"]
    assert status["steps_total"] == 0


@pytest.mark.asyncio
async def test_t2_sync_step_honors_timeout_and_does_not_block_loop():
    """T2: 同步 step 的 step_timeout_seconds 必须真正生效，且不阻塞事件循环。"""

    def step() -> dict:
        time.sleep(1.2)  # 同步阻塞，若在事件循环内直接调用会卡满 1.2s
        return {"status": "ok", "tokens": 5}

    loop = ThinkingLoop(
        step=step, enabled=True, interval_seconds=0.05, step_timeout_seconds=0.1
    )
    started = time.monotonic()
    # 事件循环没有被同步 step 卡住：并发心跳应能在 step 阻塞期间照常推进
    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    hb = asyncio.create_task(heartbeat())
    try:
        assert await loop.run_once() is None
    finally:
        hb.cancel()
        try:
            await hb
        except asyncio.CancelledError:
            pass

    elapsed = time.monotonic() - started
    assert elapsed < 0.6  # 明确超时返回，而不是等满 1.2s
    status = loop.status()
    assert status["errors_total"] == 1
    assert "timeout" in status["last_error"]
    assert status["steps_total"] == 0
    assert ticks >= 2  # step 阻塞期间心跳仍在跑 → 事件循环未被阻塞


@pytest.mark.asyncio
async def test_t3_zero_token_budget_disables_thinking():
    """T3: max_tokens_per_day=0 表示禁用，step 返回超大 tokens 也不会被执行。"""
    calls: list[int] = []

    async def step() -> dict:
        calls.append(1)
        return {"status": "ok", "tokens": 10_000_000}

    loop = ThinkingLoop(
        step=step,
        enabled=True,
        max_steps_per_hour=0,
        max_steps_per_day=0,
        max_tokens_per_day=0,
    )
    assert await loop.run_once() is None
    assert calls == []
    status = loop.status()
    assert status["tokens_today"] == 0
    assert status["steps_total"] == 0
    assert status["last_skip_reason"] == "daily_token_limit"


@pytest.mark.asyncio
async def test_t3_negative_token_budget_means_unlimited():
    loop = ThinkingLoop(
        step=lambda: {"status": "ok", "tokens": 10_000_000},
        enabled=True,
        max_steps_per_hour=0,
        max_steps_per_day=0,
        max_tokens_per_day=-1,
    )
    assert await loop.run_once() is not None
    assert loop.status()["tokens_today"] == 10_000_000
    assert await loop.run_once() is not None  # 负数 = 显式不限，不拦


@pytest.mark.asyncio
async def test_t3_missing_token_budget_uses_safe_default_cap():
    """出厂配置 0 不再是"不限"；未配置时落到安全默认上限，超限即拦截。"""
    loop = ThinkingLoop(
        step=lambda: {"status": "ok", "tokens": DEFAULT_MAX_TOKENS_PER_DAY},
        enabled=True,
        max_steps_per_hour=0,
        max_steps_per_day=0,
    )
    assert loop.budget.max_tokens_per_day == DEFAULT_MAX_TOKENS_PER_DAY
    assert await loop.run_once() is not None
    assert await loop.run_once() is None  # 已达默认上限
    assert loop.status()["last_skip_reason"] == "daily_token_limit"


@pytest.mark.asyncio
async def test_hourly_step_budget_blocks_further_steps():
    loop = ThinkingLoop(
        step=lambda: {"status": "ok", "tokens": 0},
        enabled=True,
        interval_seconds=0.05,
        max_steps_per_hour=2,
        max_steps_per_day=100,
    )
    assert await loop.run_once() is not None
    assert await loop.run_once() is not None
    assert await loop.run_once() is None  # 超出小时上限
    status = loop.status()
    assert status["steps_this_hour"] == 2
    assert status["skips_total"] == 1
    assert status["last_skip_reason"] == "hourly_step_limit"


@pytest.mark.asyncio
async def test_daily_step_budget_blocks_further_steps():
    loop = ThinkingLoop(
        step=lambda: {"status": "ok"},
        enabled=True,
        max_steps_per_hour=0,  # 不限小时
        max_steps_per_day=1,
    )
    assert await loop.run_once() is not None
    assert await loop.run_once() is None
    assert loop.status()["last_skip_reason"] == "daily_step_limit"


@pytest.mark.asyncio
async def test_daily_token_budget_blocks_further_steps():
    loop = ThinkingLoop(
        step=lambda: {"status": "ok", "tokens": 5},
        enabled=True,
        max_steps_per_hour=0,
        max_steps_per_day=0,
        max_tokens_per_day=10,
    )
    assert await loop.run_once() is not None
    assert loop.status()["tokens_today"] == 5
    assert await loop.run_once() is not None
    assert loop.status()["tokens_today"] == 10
    assert await loop.run_once() is None  # token 预算用尽
    assert loop.status()["last_skip_reason"] == "daily_token_limit"
    assert loop.status()["steps_total"] == 2


@pytest.mark.asyncio
async def test_record_tokens_feeds_the_budget():
    loop = ThinkingLoop(
        step=lambda: {"status": "ok"},
        enabled=True,
        max_steps_per_hour=0,
        max_steps_per_day=0,
        max_tokens_per_day=10,
    )
    loop.record_tokens(10)
    assert loop.status()["tokens_today"] == 10
    assert await loop.run_once() is None
    assert loop.status()["last_skip_reason"] == "daily_token_limit"


@pytest.mark.asyncio
async def test_day_rollover_resets_counters():
    loop = ThinkingLoop(step=lambda: {"status": "ok", "tokens": 4}, enabled=True)
    await loop.run_once()
    assert loop.status()["steps_today"] == 1

    # 白盒：把日期桶拨回过去，模拟跨天
    loop._day_key = "2000-01-01"
    loop._steps_day = 7
    loop._tokens_day = 70
    await loop.run_once()
    status = loop.status()
    assert status["steps_today"] == 1
    assert status["tokens_today"] == 4


def test_from_config_defaults_to_disabled():
    loop = ThinkingLoop.from_config({})
    assert loop.status()["enabled"] is False
    assert loop.budget.interval_seconds == 900.0
    assert loop.budget.max_steps_per_hour == 4
    assert loop.budget.max_steps_per_day == 24
    assert loop.budget.max_tokens_per_day == DEFAULT_MAX_TOKENS_PER_DAY


def test_from_config_applies_overrides():
    loop = ThinkingLoop.from_config({
        "enabled": True,
        "interval_seconds": 30,
        "max_steps_per_hour": 1,
        "max_steps_per_day": 5,
        "max_tokens_per_day": 1000,
        "step_timeout_seconds": 15,
    })
    assert loop.status()["enabled"] is True
    assert loop.budget.interval_seconds == 30
    assert loop.budget.max_steps_per_hour == 1
    assert loop.budget.max_steps_per_day == 5
    assert loop.budget.max_tokens_per_day == 1000
    assert loop.budget.step_timeout_seconds == 15


def test_interval_is_clamped_to_avoid_hot_loop():
    loop = ThinkingLoop(interval_seconds=0)
    assert loop.budget.interval_seconds == MIN_INTERVAL_SECONDS


@pytest.mark.asyncio
async def test_on_event_reports_each_tick():
    events: list[dict] = []
    loop = ThinkingLoop(
        step=lambda: {"status": "ok", "tokens": 1},
        enabled=True,
        interval_seconds=0.05,
        max_steps_per_hour=1,
        on_event=events.append,
    )
    await loop.run_once()
    await loop.run_once()  # 第二轮被预算拦下
    assert [e["type"] for e in events] == ["step", "skip"]
    assert events[0]["tokens"] == 1
    assert events[1]["reason"] == "hourly_step_limit"
    assert len(loop.status()["history"]) == 2
