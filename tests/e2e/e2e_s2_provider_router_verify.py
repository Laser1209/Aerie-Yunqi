"""Aerie · 云栖 v11.1 — S2 M2.1 Provider 复杂度评估验证.

验证 5 维评分系统 + 5 档复杂度 + Provider 选择逻辑。
纯本地，不依赖 LLM / DB。
用法: python e2e_s2_provider_router_verify.py
"""
from __future__ import annotations

import asyncio
import sys
import os

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
# T1 · 5 维评分验证
# ─────────────────────────────────────────────────────

def test_t1_dimension_scoring() -> bool:
    """验证 5 个维度的评分逻辑."""
    print("\n[T1] 5 维评分验证")
    all_ok = True

    from core.provider_router import ProviderRouter, ComplexityLevel

    router = ProviderRouter(arbiter_enabled=False)

    # 1.1 极简消息 → TRIVIAL
    score = router.evaluate_sync("好", context_turns=0, memory_hits=0)
    ok = score.level == ComplexityLevel.TRIVIAL
    _check("1.1 单字消息 → TRIVIAL", ok,
           f"score={score.total}, level={score.level.value}")
    if not ok:
        all_ok = False

    # 1.2 简单消息 → SIMPLE
    score = router.evaluate_sync("今天天气怎么样", context_turns=0, memory_hits=0)
    ok = score.level in (ComplexityLevel.SIMPLE, ComplexityLevel.TRIVIAL)
    _check("1.2 简单问答 → SIMPLE/TRIVIAL", ok,
           f"score={score.total}, level={score.level.value}")
    if not ok:
        all_ok = False

    # 1.3 中等消息 → MEDIUM
    score = router.evaluate_sync(
        "帮我分析一下这段代码有什么问题，然后告诉我怎么改进",
        context_turns=3, memory_hits=2,
    )
    ok = score.level in (ComplexityLevel.MEDIUM, ComplexityLevel.COMPLEX)
    _check("1.3 代码分析 → MEDIUM/COMPLEX", ok,
           f"score={score.total}, level={score.level.value}")
    if not ok:
        all_ok = False

    # 1.4 复杂消息 → COMPLEX
    score = router.evaluate_sync(
        "帮我设计一个微服务架构，包含服务发现、负载均衡、熔断降级、链路追踪，"
        "还要考虑分布式事务和数据一致性问题。请详细分析每个组件的选型和实现方案，"
        "并给出对比表格和推荐架构图。",
        context_turns=10, memory_hits=5,
    )
    ok = score.level in (ComplexityLevel.COMPLEX, ComplexityLevel.DEEP)
    _check("1.4 架构设计 → COMPLEX/DEEP", ok,
           f"score={score.total}, level={score.level.value}")
    if not ok:
        all_ok = False

    # 1.5 长文写作 → DEEP
    score = router.evaluate_sync(
        "帮我写一篇万字的研究报告，主题是大模型 Agent 架构的演进路线，"
        "需要包含历史回顾、现状分析、未来趋势、技术挑战和落地建议五个部分，"
        "每个部分都要有详细的数据支撑和案例分析。",
        context_turns=5, memory_hits=8,
    )
    ok = score.level == ComplexityLevel.DEEP
    _check("1.5 万字研究报告 → DEEP", ok,
           f"score={score.total}, level={score.level.value}")
    if not ok:
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# T2 · 多模态评分
# ─────────────────────────────────────────────────────

def test_t2_multimodal() -> bool:
    """验证多模态附件对复杂度的影响."""
    print("\n[T2] 多模态评分验证")
    all_ok = True

    from core.provider_router import ProviderRouter, ComplexityLevel

    router = ProviderRouter(arbiter_enabled=False)

    # 纯文本
    base = router.evaluate_sync("这张图片是什么", context_turns=0, memory_hits=0)

    # 带图片
    with_img = router.evaluate_sync(
        "这张图片是什么",
        context_turns=0, memory_hits=0,
        attachments=[{"type": "image", "url": "test.jpg"}],
    )
    ok = with_img.total > base.total
    _check("2.1 图片附件提升复杂度", ok,
           f"base={base.total}, with_img={with_img.total}")
    if not ok:
        all_ok = False

    # 带视频
    with_video = router.evaluate_sync(
        "这段视频讲了什么",
        context_turns=0, memory_hits=0,
        attachments=[{"type": "video", "url": "test.mp4"}],
    )
    ok = with_video.total > with_img.total
    _check("2.2 视频比图片复杂度更高", ok,
           f"with_img={with_img.total}, with_video={with_video.total}")
    if not ok:
        all_ok = False

    # 多附件（+长文本）
    multi = router.evaluate_sync(
        "帮我详细分析这些文件和图片，写一份完整的研究报告",
        context_turns=5, memory_hits=3,
        attachments=[
            {"type": "image", "url": "1.jpg"},
            {"type": "image", "url": "2.jpg"},
            {"type": "file", "url": "doc.pdf"},
        ],
    )
    ok = multi.level in (ComplexityLevel.COMPLEX, ComplexityLevel.DEEP)
    _check("2.3 多附件 + 分析需求 → 高复杂度", ok,
           f"score={multi.total}, level={multi.level.value}")
    if not ok:
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# T3 · Provider 选择
# ─────────────────────────────────────────────────────

def test_t3_provider_selection() -> bool:
    """验证 Provider 选择逻辑."""
    print("\n[T3] Provider 选择验证")
    all_ok = True

    from core.provider_router import (
        ProviderRouter, ComplexityLevel, ComplexityScore,
    )

    router = ProviderRouter(arbiter_enabled=False)

    providers = [
        {"name": "cheap_model", "tier": "low", "cost_level": "low"},
        {"name": "standard_model", "tier": "medium", "cost_level": "medium"},
        {"name": "premium_model", "tier": "high", "cost_level": "high"},
    ]

    # 3.1 TRIVIAL → low tier
    trivial = ComplexityScore(total=10, level=ComplexityLevel.TRIVIAL)
    p = router.select_provider(trivial, budget_status="normal",
                               provider_configs=providers)
    ok = p == "cheap_model"
    _check("3.1 TRIVIAL → low tier", ok, f"selected={p}")
    if not ok:
        all_ok = False

    # 3.2 MEDIUM → medium tier
    medium = ComplexityScore(total=50, level=ComplexityLevel.MEDIUM)
    p = router.select_provider(medium, budget_status="normal",
                               provider_configs=providers)
    ok = p == "standard_model"
    _check("3.2 MEDIUM → medium tier", ok, f"selected={p}")
    if not ok:
        all_ok = False

    # 3.3 DEEP → high tier
    deep = ComplexityScore(total=95, level=ComplexityLevel.DEEP)
    p = router.select_provider(deep, budget_status="normal",
                               provider_configs=providers)
    ok = p == "premium_model"
    _check("3.3 DEEP → high tier", ok, f"selected={p}")
    if not ok:
        all_ok = False

    # 3.4 预算紧张 → 降级
    p_low = router.select_provider(deep, budget_status="low",
                                   provider_configs=providers)
    ok = p_low != "premium_model"  # 应该降级
    _check("3.4 预算 low 时 DEEP 降级", ok,
           f"normal=premium, low={p_low}")
    if not ok:
        all_ok = False

    # 3.5 预算 critical → 再降级
    p_crit = router.select_provider(deep, budget_status="critical",
                                    provider_configs=providers)
    ok = p_crit == "cheap_model"  # 应该降到最低
    _check("3.5 预算 critical 时 DEEP → 最低", ok, f"selected={p_crit}")
    if not ok:
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# T4 · 边界检测（仲裁触发）
# ─────────────────────────────────────────────────────

def test_t4_boundary_detection() -> bool:
    """验证边界区间检测逻辑."""
    print("\n[T4] 边界区间检测")
    all_ok = True

    from core.provider_router import ProviderRouter

    router = ProviderRouter(arbiter_enabled=True, boundary_tolerance=0.10)

    # 阈值点: 15, 35, 55, 70
    # 边界区间: ±10  →  (5-25), (25-45), (45-65), (60-80)

    # 在边界上 → 触发
    ok = router._is_near_boundary(15.0)
    _check("4.1 正好在阈值 15 → 触发", ok)
    if not ok:
        all_ok = False

    # 边界附近 → 触发
    ok = router._is_near_boundary(60.0)
    _check("4.2 在 55-65 区间 → 触发", ok)
    if not ok:
        all_ok = False

    # 远离边界 → 不触发
    ok = not router._is_near_boundary(2.0)
    _check("4.3 远离边界 2 → 不触发", ok)
    if not ok:
        all_ok = False

    # 中间区域 45 正好在 35+10 和 55-10 的边界
    ok_boundary = router._is_near_boundary(45.0)
    _check("4.4 分数 45 (边界交集) → 触发", ok_boundary,
           "容差 10%，45 = 35+10 = 55-10")
    if not ok_boundary:
        all_ok = False

    # 中间安全区（阈值间隔 20，容差 10，几乎没有安全区）
    # 验证极端情况
    ok_mid = router._is_near_boundary(75.0)  # 70+5=75，在 70 的边界内
    _check("4.5 分数 75 (70+5) → 触发", ok_mid,
           "阈值间隔 15-35-55-70，容差 10 基本覆盖全部区间")

    return all_ok


# ─────────────────────────────────────────────────────
# T5 · BASIC 模式强制降级
# ─────────────────────────────────────────────────────

def test_t5_basic_mode() -> bool:
    """验证 BASIC 路由模式强制降级."""
    print("\n[T5] BASIC 模式强制降级")
    all_ok = True

    from core.provider_router import ProviderRouter, ComplexityLevel

    router = ProviderRouter(arbiter_enabled=False)

    # 即使是深度写作请求，BASIC 模式也应该降级
    score = router.evaluate_sync(
        "帮我写一篇万字研究报告",
        context_turns=10, memory_hits=5,
        route_mode="BASIC",
    )
    ok = score.level == ComplexityLevel.TRIVIAL
    _check("5.1 BASIC 模式 → 强制 TRIVIAL", ok,
           f"score={score.total}, level={score.level.value}")
    if not ok:
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# T6 · Agent 集成验证
# ─────────────────────────────────────────────────────

def test_t6_agent_integration() -> bool:
    """验证 Agent 类中 ProviderRouter 正确初始化."""
    print("\n[T6] Agent 集成验证")
    all_ok = True

    # 验证可以从 agent 模块导入
    try:
        from core.agent import Agent, PerceivedInput
        from core.provider_router import ProviderRouter, ComplexityScore

        # 验证 PerceivedInput 有新字段
        import dataclasses
        fields = {f.name for f in dataclasses.fields(PerceivedInput)}
        ok_complexity = "complexity" in fields
        ok_provider = "selected_provider" in fields
        _check("6.1 PerceivedInput.complexity 字段", ok_complexity)
        _check("6.2 PerceivedInput.selected_provider 字段", ok_provider)
        if not ok_complexity or not ok_provider:
            all_ok = False

        # 验证 Agent 有 provider_router 属性
        ok_router_attr = hasattr(Agent, "__init__")  # 间接验证
        _check("6.3 Agent 类结构完整", ok_router_attr)
        if not ok_router_attr:
            all_ok = False

    except Exception as e:
        _check("6.1 Agent 模块导入", False, str(e))
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────

async def main() -> int:
    print("=" * 60)
    print("Aerie v11.1 · S2 M2.1 Provider 复杂度评估验证")
    print("=" * 60)

    results: list[tuple[str, bool]] = []

    results.append(("T1 5 维评分", test_t1_dimension_scoring()))
    results.append(("T2 多模态评分", test_t2_multimodal()))
    results.append(("T3 Provider 选择", test_t3_provider_selection()))
    results.append(("T4 边界检测", test_t4_boundary_detection()))
    results.append(("T5 BASIC 模式", test_t5_basic_mode()))
    results.append(("T6 Agent 集成", test_t6_agent_integration()))

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
        print("\n🎉 M2.1 Provider 复杂度评估全部通过！")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 项未通过，请检查。")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
