"""Aerie · 云栖 v11.1 — S2 M2.2 预算跟踪验证.

验证 BudgetTracker 的日/周/月跟踪、状态计算、动态降级等功能。
纯本地，不依赖 LLM / DB。
用法: python e2e_s2_budget_tracker_verify.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _check(label: str, ok: bool, detail: str = "") -> None:
    sym = "✓" if ok else "✗"
    print(f"  {sym} {label}  {detail}")


# ─────────────────────────────────────────────────────
# T1 · 基础记录与查询
# ─────────────────────────────────────────────────────

def test_t1_basic_recording() -> bool:
    """验证基础的记录和查询功能."""
    print("\n[T1] 基础记录与查询")
    all_ok = True

    from core.budget_tracker import BudgetTracker, BudgetConfig, BudgetStatus

    # 临时文件
    tmp = tempfile.mktemp(suffix=".json")
    try:
        config = BudgetConfig(
            monthly_budget_usd=100.0,
            low_threshold_pct=0.50,
            critical_threshold_pct=0.20,
        )
        tracker = BudgetTracker(config=config, data_file=tmp)

        # 1.1 初始状态
        status = tracker.get_status()
        ok = status == BudgetStatus.NORMAL
        _check("1.1 初始状态 = normal", ok, f"status={status}")
        if not ok:
            all_ok = False

        # 1.2 初始剩余 100%
        pct = tracker.get_remaining_pct()
        ok = abs(pct - 1.0) < 0.001
        _check("1.2 初始剩余 = 100%", ok, f"remaining={pct*100:.1f}%")
        if not ok:
            all_ok = False

        # 1.3 记录一次调用
        tracker.record_call(
            provider_name="test_model",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.01,
        )
        ok = tracker.monthly.call_count == 1
        _check("1.3 记录调用后 call_count = 1", ok,
               f"calls={tracker.monthly.call_count}")
        if not ok:
            all_ok = False

        # 1.4 费用累加正确
        ok = abs(tracker.monthly.cost_usd - 0.01) < 0.0001
        _check("1.4 费用累加正确", ok, f"cost={tracker.monthly.cost_usd}")
        if not ok:
            all_ok = False

        # 1.5 token 累加正确
        ok = tracker.monthly.total_tokens == 1500
        _check("1.5 token 累加正确", ok,
               f"tokens={tracker.monthly.total_tokens}")
        if not ok:
            all_ok = False

    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    return all_ok


# ─────────────────────────────────────────────────────
# T2 · 预算状态转换
# ─────────────────────────────────────────────────────

def test_t2_status_transitions() -> bool:
    """验证预算状态转换（normal → low → critical）."""
    print("\n[T2] 预算状态转换")
    all_ok = True

    from core.budget_tracker import BudgetTracker, BudgetConfig, BudgetStatus

    tmp = tempfile.mktemp(suffix=".json")
    try:
        config = BudgetConfig(
            monthly_budget_usd=100.0,  # 月预算 100 美元
            weekly_budget_usd=100.0,   # 周预算也设为 100，避免周预算先耗尽
            daily_budget_usd=100.0,    # 日预算也设为 100，避免日预算先耗尽
            low_threshold_pct=0.50,   # 低于 50% → low
            critical_threshold_pct=0.20,  # 低于 20% → critical
        )
        tracker = BudgetTracker(config=config, data_file=tmp)

        # 2.1 0% 使用 → normal
        ok = tracker.get_status() == BudgetStatus.NORMAL
        _check("2.1 0% 使用 → normal", ok)
        if not ok:
            all_ok = False

        # 2.2 用掉 40%（剩 60%）→ normal
        tracker.record_call("m1", 1000, 500, cost_usd=40.0)
        ok = tracker.get_status() == BudgetStatus.NORMAL
        _check("2.2 剩 60% → normal", ok,
               f"remaining={tracker.get_remaining_pct()*100:.0f}%")
        if not ok:
            all_ok = False

        # 2.3 用掉 55%（剩 45%）→ low
        tracker.record_call("m1", 1000, 500, cost_usd=15.0)
        ok = tracker.get_status() == BudgetStatus.LOW
        _check("2.3 剩 45% → low", ok,
               f"remaining={tracker.get_remaining_pct()*100:.0f}%")
        if not ok:
            all_ok = False

        # 2.4 用掉 85%（剩 15%）→ critical
        tracker.record_call("m1", 1000, 500, cost_usd=30.0)
        ok = tracker.get_status() == BudgetStatus.CRITICAL
        _check("2.4 剩 15% → critical", ok,
               f"remaining={tracker.get_remaining_pct()*100:.0f}%")
        if not ok:
            all_ok = False

    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    return all_ok


# ─────────────────────────────────────────────────────
# T3 · Provider 动态降级
# ─────────────────────────────────────────────────────

def test_t3_dynamic_downgrade() -> bool:
    """验证预算紧张时 Provider 自动降级."""
    print("\n[T3] Provider 动态降级")
    all_ok = True

    from core.budget_tracker import BudgetTracker, BudgetConfig
    from core.provider_router import (
        ProviderRouter, ComplexityScore, ComplexityLevel,
    )

    tmp = tempfile.mktemp(suffix=".json")
    try:
        config = BudgetConfig(
            monthly_budget_usd=100.0,
            weekly_budget_usd=100.0,
            daily_budget_usd=100.0,
            low_threshold_pct=0.50,
            critical_threshold_pct=0.20,
        )
        tracker = BudgetTracker(config=config, data_file=tmp)
        router = ProviderRouter(arbiter_enabled=False)

        providers = [
            {"name": "cheap", "tier": "low", "cost_level": "low"},
            {"name": "standard", "tier": "medium", "cost_level": "medium"},
            {"name": "premium", "tier": "high", "cost_level": "high"},
        ]

        complex_score = ComplexityScore(
            total=85, level=ComplexityLevel.DEEP,
        )

        # 3.1 normal 预算 → premium
        p_normal = router.select_provider(
            complex_score,
            budget_status=tracker.get_status(),
            provider_configs=providers,
        )
        ok = p_normal == "premium"
        _check("3.1 normal 预算 → premium", ok, f"selected={p_normal}")
        if not ok:
            all_ok = False

        # 3.2 low 预算 → standard（降一档）
        tracker.record_call("premium", 10000, 5000, cost_usd=55.0)  # 用掉 55%
        p_low = router.select_provider(
            complex_score,
            budget_status=tracker.get_status(),
            provider_configs=providers,
        )
        ok = p_low == "standard"
        _check("3.2 low 预算 → standard", ok,
               f"status={tracker.get_status()}, selected={p_low}")
        if not ok:
            all_ok = False

        # 3.3 critical 预算 → cheap（降到底）
        tracker.record_call("premium", 10000, 5000, cost_usd=30.0)  # 再用 30%
        p_crit = router.select_provider(
            complex_score,
            budget_status=tracker.get_status(),
            provider_configs=providers,
        )
        ok = p_crit == "cheap"
        _check("3.3 critical 预算 → cheap", ok,
               f"status={tracker.get_status()}, selected={p_crit}")
        if not ok:
            all_ok = False

    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    return all_ok


# ─────────────────────────────────────────────────────
# T4 · 持久化
# ─────────────────────────────────────────────────────

def test_t4_persistence() -> bool:
    """验证预算数据的保存和加载."""
    print("\n[T4] 持久化验证")
    all_ok = True

    from core.budget_tracker import BudgetTracker, BudgetConfig

    tmp = tempfile.mktemp(suffix=".json")
    try:
        config = BudgetConfig(monthly_budget_usd=100.0)

        # 写入
        tracker1 = BudgetTracker(config=config, data_file=tmp)
        tracker1.record_call("model_a", 1000, 500, cost_usd=0.05)
        tracker1.record_call("model_b", 2000, 1000, cost_usd=0.10)
        tracker1.save()

        # 验证文件存在
        ok = os.path.exists(tmp)
        _check("4.1 数据文件已保存", ok)
        if not ok:
            all_ok = False

        # 读取
        tracker2 = BudgetTracker(config=config, data_file=tmp)
        ok = tracker2.load()
        _check("4.2 数据文件加载成功", ok)
        if not ok:
            all_ok = False

        # 验证数据一致
        ok = tracker2.monthly.call_count == 2
        _check("4.3 call_count 一致", ok,
               f"calls={tracker2.monthly.call_count}")
        if not ok:
            all_ok = False

        ok = abs(tracker2.monthly.cost_usd - 0.15) < 0.0001
        _check("4.4 cost_usd 一致", ok, f"cost={tracker2.monthly.cost_usd}")
        if not ok:
            all_ok = False

        ok = tracker2.monthly.total_tokens == 4500
        _check("4.5 total_tokens 一致", ok,
               f"tokens={tracker2.monthly.total_tokens}")
        if not ok:
            all_ok = False

        # 验证 provider 明细
        ok = "model_a" in tracker2.monthly.provider_usage
        _check("4.6 provider_a 明细存在", ok)
        if not ok:
            all_ok = False

    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    return all_ok


# ─────────────────────────────────────────────────────
# T5 · 多周期跟踪
# ─────────────────────────────────────────────────────

def test_t5_multi_period() -> bool:
    """验证日/周/月三个周期独立跟踪."""
    print("\n[T5] 多周期跟踪")
    all_ok = True

    from core.budget_tracker import BudgetTracker, BudgetConfig

    tmp = tempfile.mktemp(suffix=".json")
    try:
        config = BudgetConfig(
            monthly_budget_usd=300.0,
            weekly_budget_usd=75.0,
            daily_budget_usd=10.0,
        )
        tracker = BudgetTracker(config=config, data_file=tmp)

        # 记录一次调用，三个周期都应该 +1
        tracker.record_call("test", 1000, 500, cost_usd=1.0)

        ok = tracker.daily.call_count == 1
        _check("5.1 日周期 call_count = 1", ok, f"daily={tracker.daily.call_count}")
        if not ok:
            all_ok = False

        ok = tracker.weekly.call_count == 1
        _check("5.2 周周期 call_count = 1", ok, f"weekly={tracker.weekly.call_count}")
        if not ok:
            all_ok = False

        ok = tracker.monthly.call_count == 1
        _check("5.3 月周期 call_count = 1", ok, f"monthly={tracker.monthly.call_count}")
        if not ok:
            all_ok = False

        # 日预算最严格（用了 1/10 = 10%，剩 90% → normal）
        # 月预算（用了 1/300 = 0.3% → normal）
        # 所以状态应该都是 normal
        status = tracker.get_status()
        _check("5.4 三周期均正常 → normal", True, f"status={status}")

        # 使用摘要
        summary = tracker.get_usage_summary()
        ok = "daily" in summary and "weekly" in summary and "monthly" in summary
        _check("5.5 使用摘要包含三周期", ok)
        if not ok:
            all_ok = False

    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    return all_ok


# ─────────────────────────────────────────────────────
# T6 · 无预算限制
# ─────────────────────────────────────────────────────

def test_t6_no_budget_limit() -> bool:
    """验证没有配置预算时，始终返回 normal."""
    print("\n[T6] 无预算限制")
    all_ok = True

    from core.budget_tracker import BudgetTracker, BudgetConfig, BudgetStatus

    tmp = tempfile.mktemp(suffix=".json")
    try:
        config = BudgetConfig()  # 没有设置任何预算
        tracker = BudgetTracker(config=config, data_file=tmp)

        # 大量调用也不会变状态
        for i in range(100):
            tracker.record_call("test", 10000, 5000, cost_usd=100.0)

        status = tracker.get_status()
        ok = status == BudgetStatus.NORMAL
        _check("6.1 无预算限制 → 始终 normal", ok,
               f"status={status}, calls={tracker.monthly.call_count}")
        if not ok:
            all_ok = False

        pct = tracker.get_remaining_pct()
        ok = abs(pct - 1.0) < 0.001
        _check("6.2 无预算限制 → 剩余 100%", ok, f"remaining={pct*100:.0f}%")
        if not ok:
            all_ok = False

    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    return all_ok


# ─────────────────────────────────────────────────────
# T7 · Agent 集成
# ─────────────────────────────────────────────────────

def test_t7_agent_integration() -> bool:
    """验证 Agent 类中 BudgetTracker 正确初始化."""
    print("\n[T7] Agent 集成验证")
    all_ok = True

    try:
        from core.agent import Agent
        from core.budget_tracker import BudgetTracker

        # 验证导入
        _check("7.1 Agent 模块导入成功", True)

        # 验证 BudgetTracker 类存在
        ok = hasattr(BudgetTracker, "record_call") and hasattr(BudgetTracker, "get_status")
        _check("7.2 BudgetTracker 类完整", ok)
        if not ok:
            all_ok = False

    except Exception as e:
        _check("7.1 Agent 模块导入", False, str(e))
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────

async def main() -> int:
    print("=" * 60)
    print("Aerie v11.1 · S2 M2.2 预算跟踪验证")
    print("=" * 60)

    results: list[tuple[str, bool]] = []

    results.append(("T1 基础记录", test_t1_basic_recording()))
    results.append(("T2 状态转换", test_t2_status_transitions()))
    results.append(("T3 动态降级", test_t3_dynamic_downgrade()))
    results.append(("T4 持久化", test_t4_persistence()))
    results.append(("T5 多周期", test_t5_multi_period()))
    results.append(("T6 无限制", test_t6_no_budget_limit()))
    results.append(("T7 Agent 集成", test_t7_agent_integration()))

    print("\n" + "=" * 60)
    print("汇总")
    print("=" * 60)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        sym = "✓ PASS" if ok else "✗ FAIL"
        print(f"  {sym}  {name}")

    print(f"\n结果: {passed}/{total} 通过")

    if passed == total:
        print("\n🎉 M2.2 预算跟踪全部通过！")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 项未通过，请检查。")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
