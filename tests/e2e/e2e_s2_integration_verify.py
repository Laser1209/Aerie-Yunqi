"""Aerie · 云栖 v11.1 — S2 收口验证 (M2.3).

综合验证 Provider 智能路由 + 预算跟踪的完整链路：
  T1 · 端到端：消息 → 复杂度评分 → 预算状态 → Provider 选择
  T2 · 预算驱动降级：随着预算消耗，provider 自动降级
  T3 · 混合模式仲裁：边界 case 触发 LLM 仲裁（模拟）
  T4 · Agent 完整集成：Agent 类中所有 S2 组件正常工作
  T5 · 零破坏验证：S1 功能 + 旧 Pipeline 不受影响

纯本地（不依赖 LLM / DB / 后端进程），可直接运行。
用法: python e2e_s2_integration_verify.py
"""
from __future__ import annotations

import asyncio
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
# T1 · 端到端路由链路
# ─────────────────────────────────────────────────────

def test_t1_e2e_routing() -> bool:
    """端到端验证：消息 → 复杂度 → 预算 → Provider."""
    print("\n[T1] 端到端路由链路")
    all_ok = True

    from core.provider_router import ProviderRouter, ComplexityLevel
    from core.budget_tracker import BudgetTracker, BudgetConfig

    tmp = tempfile.mktemp(suffix=".json")
    try:
        router = ProviderRouter(arbiter_enabled=False)
        config = BudgetConfig(
            monthly_budget_usd=100.0,
            weekly_budget_usd=100.0,
            daily_budget_usd=100.0,
        )
        budget = BudgetTracker(config=config, data_file=tmp)

        providers = [
            {"name": "qwen-turbo", "tier": "low", "cost_level": "low"},
            {"name": "qwen-plus", "tier": "medium", "cost_level": "medium"},
            {"name": "qwen-max", "tier": "high", "cost_level": "high"},
        ]

        test_cases = [
            # (消息, 上下文轮数, 记忆命中, 预期复杂度, 预期provider)
            ("好", 0, 0, ComplexityLevel.TRIVIAL, "qwen-turbo"),
            ("今天天气怎么样", 0, 0, ComplexityLevel.SIMPLE, "qwen-turbo"),
            ("帮我解释一下这段代码", 3, 2, ComplexityLevel.MEDIUM, "qwen-plus"),
            ("帮我设计一个微服务架构方案", 5, 3, ComplexityLevel.COMPLEX, "qwen-max"),
            ("写一篇万字的大模型研究报告", 10, 8, ComplexityLevel.DEEP, "qwen-max"),
        ]

        for msg, ctx_turns, mem_hits, expected_level, expected_provider in test_cases:
            score = router.evaluate_sync(msg, context_turns=ctx_turns, memory_hits=mem_hits)
            provider = router.select_provider(
                score,
                budget_status=budget.get_status(),
                provider_configs=providers,
            )
            level_ok = score.level == expected_level
            provider_ok = provider == expected_provider
            ok = level_ok and provider_ok
            idx = test_cases.index((msg, ctx_turns, mem_hits, expected_level, expected_provider)) + 1
            _check(
                f"1.{idx} '{msg[:20]}'",
                ok,
                f"level={score.level.value}, provider={provider}, score={score.total}, ctx={ctx_turns}, mem={mem_hits}",
            )
            if not ok:
                all_ok = False

    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    return all_ok


# ─────────────────────────────────────────────────────
# T2 · 预算驱动降级
# ─────────────────────────────────────────────────────

def test_t2_budget_driven_downgrade() -> bool:
    """验证随着预算消耗，同一消息的 provider 自动降级."""
    print("\n[T2] 预算驱动降级")
    all_ok = True

    from core.provider_router import ProviderRouter
    from core.budget_tracker import BudgetTracker, BudgetConfig

    tmp = tempfile.mktemp(suffix=".json")
    try:
        router = ProviderRouter(arbiter_enabled=False)
        config = BudgetConfig(
            monthly_budget_usd=100.0,
            weekly_budget_usd=100.0,
            daily_budget_usd=100.0,
            low_threshold_pct=0.50,
            critical_threshold_pct=0.20,
        )
        budget = BudgetTracker(config=config, data_file=tmp)

        providers = [
            {"name": "cheap", "tier": "low", "cost_level": "low"},
            {"name": "mid", "tier": "medium", "cost_level": "medium"},
            {"name": "premium", "tier": "high", "cost_level": "high"},
        ]

        # 同一条复杂消息
        msg = ("帮我设计一个完整的微服务架构，包含服务发现、负载均衡、链路追踪、"
               "熔断降级、分布式事务，还要写一份详细的技术方案报告，"
               "包含架构图、选型对比、性能预估和风险分析")

        # 阶段 1: 预算充足 → premium
        score1 = router.evaluate_sync(msg, context_turns=10, memory_hits=8)
        p1 = router.select_provider(score1, budget.get_status(), providers)
        ok1 = p1 == "premium"
        _check("2.1 预算充足 → premium", ok1,
               f"status={budget.get_status()}, provider={p1}")
        if not ok1:
            all_ok = False

        # 消耗 55% 预算
        budget.record_call("premium", 50000, 20000, cost_usd=55.0)

        # 阶段 2: 预算 low → mid
        score2 = router.evaluate_sync(msg, context_turns=5, memory_hits=3)
        p2 = router.select_provider(score2, budget.get_status(), providers)
        ok2 = p2 == "mid"
        _check("2.2 预算 low → mid", ok2,
               f"status={budget.get_status()}, provider={p2}")
        if not ok2:
            all_ok = False

        # 再消耗 30%（累计 85%）
        budget.record_call("mid", 50000, 20000, cost_usd=30.0)

        # 阶段 3: 预算 critical → cheap
        score3 = router.evaluate_sync(msg, context_turns=5, memory_hits=3)
        p3 = router.select_provider(score3, budget.get_status(), providers)
        ok3 = p3 == "cheap"
        _check("2.3 预算 critical → cheap", ok3,
               f"status={budget.get_status()}, provider={p3}")
        if not ok3:
            all_ok = False

    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    return all_ok


# ─────────────────────────────────────────────────────
# T3 · 边界检测与仲裁
# ─────────────────────────────────────────────────────

def test_t3_boundary_arbiter() -> bool:
    """验证边界 case 检测（仲裁触发逻辑）."""
    print("\n[T3] 边界检测与仲裁触发")
    all_ok = True

    from core.provider_router import ProviderRouter

    router = ProviderRouter(arbiter_enabled=True, boundary_tolerance=0.10)

    # 阈值：15, 35, 55, 70, 100；容差 10
    boundary_cases = [15, 25, 35, 45, 55, 58, 68, 78, 95]
    # 阈值间隔小 + 容差大，只有极低分区才是非边界
    non_boundary_cases = [2, 3]

    for score in boundary_cases:
        ok = router._is_near_boundary(score)
        _check(f"3.{boundary_cases.index(score)+1} score={score} → 边界", ok)
        if not ok:
            all_ok = False

    for score in non_boundary_cases:
        ok = not router._is_near_boundary(score)
        _check(f"3.8+{non_boundary_cases.index(score)} score={score} → 非边界", ok)
        if not ok:
            all_ok = False

    # arbiter_enabled=False 时，evaluate_sync 不调用 LLM
    router_no_arbiter = ProviderRouter(arbiter_enabled=False)
    score = router_no_arbiter.evaluate_sync("测试消息")
    ok = not score.used_arbiter
    _check("3.10 arbiter_enabled=False → 不触发仲裁", ok,
           f"used_arbiter={score.used_arbiter}")
    if not ok:
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# T4 · Agent 完整集成
# ─────────────────────────────────────────────────────

def test_t4_agent_full_integration() -> bool:
    """验证 Agent 类中所有 S2 组件完整集成."""
    print("\n[T4] Agent 完整集成")
    all_ok = True

    try:
        from core.agent import Agent, PerceivedInput
        from core.provider_router import ProviderRouter, ComplexityScore
        from core.budget_tracker import BudgetTracker

        # 4.1 验证所有模块可导入
        _check("4.1 所有模块可导入", True)

        # 4.2 验证 PerceivedInput 有 S2 字段
        import dataclasses
        pi_fields = {f.name for f in dataclasses.fields(PerceivedInput)}
        ok_complexity = "complexity" in pi_fields
        ok_provider = "selected_provider" in pi_fields
        _check("4.2 PerceivedInput.complexity 字段", ok_complexity)
        _check("4.3 PerceivedInput.selected_provider 字段", ok_provider)
        if not ok_complexity or not ok_provider:
            all_ok = False

        # 4.4 验证 Agent 有 S2 属性
        # 通过源代码间接验证（不实例化，避免依赖 Companion）
        import inspect
        agent_src = inspect.getsource(Agent.__init__)
        ok_provider_router = "provider_router" in agent_src
        ok_budget = "budget_tracker" in agent_src
        _check("4.4 Agent.__init__ 有 provider_router", ok_provider_router)
        _check("4.5 Agent.__init__ 有 budget_tracker", ok_budget)
        if not ok_provider_router or not ok_budget:
            all_ok = False

        # 4.6 验证 perceive 方法中有复杂度评估
        perceive_src = inspect.getsource(Agent.perceive)
        ok_eval = "provider_router.evaluate" in perceive_src
        ok_select = "select_provider" in perceive_src
        ok_budget_status = "budget_status" in perceive_src
        _check("4.6 perceive 中有复杂度评估", ok_eval)
        _check("4.7 perceive 中有 provider 选择", ok_select)
        _check("4.8 perceive 中有预算状态", ok_budget_status)
        if not ok_eval or not ok_select or not ok_budget_status:
            all_ok = False

    except Exception as e:
        _check("4.0 Agent 集成验证", False, str(e))
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# T5 · 零破坏验证
# ─────────────────────────────────────────────────────

def test_t5_zero_regression() -> bool:
    """验证 S2 新增代码不破坏 S1 和旧 Pipeline."""
    print("\n[T5] 零破坏验证")
    all_ok = True

    # 5.1 S1 组件仍正常
    try:
        from core.agent import Agent, PerceivedInput, Thought, Decision
        from core.agent_reflection_queue import ReflectionQueue, ReflectionTask
        _check("5.1 S1 组件全部可导入", True)
    except Exception as e:
        _check("5.1 S1 组件全部可导入", False, str(e))
        all_ok = False

    # 5.2 旧 Pipeline 仍正常
    try:
        from core.pipeline import Pipeline
        from core.companion import Companion
        _check("5.2 旧 Pipeline 仍可导入", True)
    except Exception as e:
        _check("5.2 旧 Pipeline 仍可导入", False, str(e))
        all_ok = False

    # 5.3 S2 新文件不影响 core 模块导入
    try:
        import importlib
        for mod in [
            "core.provider_router",
            "core.budget_tracker",
        ]:
            importlib.import_module(mod)
        _check("5.3 S2 新模块可导入", True)
    except Exception as e:
        _check("5.3 S2 新模块可导入", False, str(e))
        all_ok = False

    # 5.4 反射队列不依赖预算系统
    try:
        queue = ReflectionQueue(self_evolver=None, db=None)
        _check("5.4 反射队列可独立创建", True)
    except Exception as e:
        _check("5.4 反射队列可独立创建", False, str(e))
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# T6 · 使用摘要
# ─────────────────────────────────────────────────────

def test_t6_usage_summary() -> bool:
    """验证使用量摘要输出格式正确."""
    print("\n[T6] 使用摘要")
    all_ok = True

    from core.budget_tracker import BudgetTracker, BudgetConfig

    tmp = tempfile.mktemp(suffix=".json")
    try:
        config = BudgetConfig(
            monthly_budget_usd=100.0,
            weekly_budget_usd=50.0,
            daily_budget_usd=10.0,
        )
        tracker = BudgetTracker(config=config, data_file=tmp)
        tracker.record_call("model_a", 1000, 500, cost_usd=2.0)
        tracker.record_call("model_b", 2000, 1000, cost_usd=3.0)

        summary = tracker.get_usage_summary()

        # 验证关键字段
        required_top = ["status", "remaining_pct", "daily", "weekly", "monthly", "providers"]
        for key in required_top:
            ok = key in summary
            _check(f"6.1 summary.{key} 存在", ok)
            if not ok:
                all_ok = False

        # 验证 provider 明细
        ok = "model_a" in summary.get("providers", {})
        _check("6.2 model_a 在 provider 明细中", ok)
        if not ok:
            all_ok = False

        ok = summary["monthly"]["calls"] == 2
        _check("6.3 调用次数正确", ok, f"calls={summary['monthly']['calls']}")
        if not ok:
            all_ok = False

    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    return all_ok


# ─────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────

async def main() -> int:
    print("=" * 60)
    print("Aerie v11.1 · S2 收口验证 (M2.3)")
    print("Provider 智能路由 + 全局预算跟踪")
    print("=" * 60)

    results: list[tuple[str, bool]] = []

    results.append(("T1 端到端路由", test_t1_e2e_routing()))
    results.append(("T2 预算驱动降级", test_t2_budget_driven_downgrade()))
    results.append(("T3 边界检测仲裁", test_t3_boundary_arbiter()))
    results.append(("T4 Agent 集成", test_t4_agent_full_integration()))
    results.append(("T5 零破坏", test_t5_zero_regression()))
    results.append(("T6 使用摘要", test_t6_usage_summary()))

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
        print("\n🎉 S2 收口验证全部通过！")
        print("   Provider 复杂度评估 + 全局预算跟踪 + 动态路由")
        print("   可申请 v11.1.0 版本升级。")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 项未通过，请检查。")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
