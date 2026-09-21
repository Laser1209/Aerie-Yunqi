"""B / C 部分：把后台思考循环接进 companion 生命周期的接线测试。

覆盖：
  - 默认关闭：未 enabled 时不运行、不消耗 token
  - 启用：能 start / stop，status 如实反映预算
  - step：最小打点实现，零 token（不调模型）
  - 关闭幂等
  - companion.start()/stop() 生命周期里真的走了接线点
  - 只读状态端点 /api/background/status 暴露 running / 预算用量 / 最近错误
"""

from __future__ import annotations

import asyncio

import pytest

from tests.test_mcp_wiring import _companion_shell


# ── 默认关闭 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_thinking_loop_disabled_by_default():
    comp = _companion_shell()

    await comp._start_thinking_loop()
    try:
        loop = comp.thinking_loop
        assert loop is not None
        assert loop.running is False
        assert loop.status()["enabled"] is False
        assert loop.status()["steps_total"] == 0
    finally:
        await comp._stop_thinking_loop()
        await comp._stop_thinking_loop()  # 幂等：重复停止安全


# ── 启用：启停 + 预算 ─────────────────────────────────

@pytest.mark.asyncio
async def test_thinking_loop_enabled_starts_and_reports_budget():
    comp = _companion_shell()
    comp.settings = {
        "thinking_loop": {
            "enabled": True,
            "interval_seconds": 0.05,
            "max_steps_per_hour": 2,
            "max_steps_per_day": 10,
            "max_tokens_per_day": 500,
        }
    }

    await comp._start_thinking_loop()
    try:
        loop = comp.thinking_loop
        assert loop.running is True
        status = loop.status()
        assert status["enabled"] is True
        assert status["budget"]["max_steps_per_hour"] == 2
        assert status["budget"]["max_steps_per_day"] == 10
        assert status["budget"]["max_tokens_per_day"] == 500
    finally:
        await comp._stop_thinking_loop()

    assert comp.thinking_loop.running is False


# ── step：零 token 打点 ───────────────────────────────

@pytest.mark.asyncio
async def test_minimal_step_is_zero_token_heartbeat():
    comp = _companion_shell()
    comp.settings = {"thinking_loop": {"enabled": True}}

    await comp._start_thinking_loop()
    try:
        loop = comp.thinking_loop
        result = await loop.run_once()
        assert result == {"status": "idle", "reason": "heartbeat", "tokens": 0}
        assert loop.status()["tokens_today"] == 0
        assert loop.status()["steps_total"] == 1
    finally:
        await comp._stop_thinking_loop()


@pytest.mark.asyncio
async def test_enabled_loop_ticks_without_calling_model():
    comp = _companion_shell()
    comp.settings = {"thinking_loop": {"enabled": True, "interval_seconds": 0.05}}

    await comp._start_thinking_loop()
    try:
        await asyncio.sleep(0.25)
        status = comp.thinking_loop.status()
        assert status["steps_total"] >= 1
        assert status["tokens_today"] == 0
        assert status["errors_total"] == 0
    finally:
        await comp._stop_thinking_loop()


# ── companion 生命周期接线 ────────────────────────────

@pytest.mark.asyncio
async def test_companion_lifecycle_thinking_loop_disabled_by_default(
    monkeypatch, phase4_db
):
    from tests.test_phase4_integration import _feature_env, _patch_companion

    _feature_env(monkeypatch, queue=False)
    companion_module = _patch_companion(monkeypatch)
    companion = companion_module.Companion(
        {"qq": {"self_qq": 0, "friends_qq": [], "startup_wait_timeout": 0}},
        database=phase4_db,
    )

    await companion.start()
    try:
        assert companion.thinking_loop is not None
        assert companion.thinking_loop.running is False
        assert companion.thinking_loop.status()["enabled"] is False
    finally:
        await companion.stop()


@pytest.mark.asyncio
async def test_companion_lifecycle_starts_and_stops_thinking_loop(
    monkeypatch, phase4_db
):
    from tests.test_phase4_integration import _feature_env, _patch_companion

    _feature_env(monkeypatch, queue=False)
    companion_module = _patch_companion(monkeypatch)
    companion = companion_module.Companion(
        {
            "qq": {"self_qq": 0, "friends_qq": [], "startup_wait_timeout": 0},
            "thinking_loop": {"enabled": True, "interval_seconds": 0.05},
        },
        database=phase4_db,
    )

    await companion.start()
    try:
        assert companion.thinking_loop.running is True
    finally:
        await companion.stop()

    assert companion.thinking_loop.running is False


# ── 只读状态端点 ──────────────────────────────────────

@pytest.mark.asyncio
async def test_background_status_reports_thinking_loop_budget(monkeypatch):
    import httpx

    from core import api_server

    comp = _companion_shell()
    comp.settings = {
        "thinking_loop": {
            "enabled": True,
            "interval_seconds": 0.05,
            "max_steps_per_day": 7,
            "max_tokens_per_day": 300,
        }
    }
    await comp._start_thinking_loop()
    comp.thinking_loop.record_tokens(42)
    monkeypatch.setattr(api_server, "get_companion", lambda: comp)

    transport = httpx.ASGITransport(app=api_server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/background/status")

    assert response.status_code == 200
    thinking = response.json()["thinking_loop"]
    assert thinking["enabled"] is True
    assert thinking["running"] is True
    assert thinking["budget"]["max_steps_per_day"] == 7
    assert thinking["budget"]["max_tokens_per_day"] == 300
    assert thinking["tokens_today"] == 42
    assert "last_error" in thinking
    await comp._stop_thinking_loop()
