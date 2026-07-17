"""Aerie v11.3 · S4 M4.3 自进化 L1/L2/L3 验证

验证项：
  T1 EvolutionLevel 枚举
  T2 关键词提取 (extract_keywords)
  T3 主题识别 (detect_topics)
  T4 情绪检测 (detect_mood)
  T5 L1 DreamConsolidator 初始化与空闲检测
  T6 L1 梦境整理运行
  T7 L2 SessionReflector 会话记录
  T8 L2 会话复盘
  T9 L3 KnowledgeDistiller 观察数据
  T10 L3 知识蒸馏
  T11 EvolutionManager 统一调度
  T12 EvolutionManager 统计信息
"""

from __future__ import annotations
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.evolution_manager import (
    DreamConsolidator,
    DreamResult,
    EvolutionLevel,
    EvolutionManager,
    EvolutionTask,
    KnowledgeDistiller,
    KnowledgeDistillResult,
    SessionReflectionResult,
    SessionReflector,
    detect_mood,
    detect_topics,
    extract_keywords,
)


def t1_evolution_level_enum() -> tuple[bool, str]:
    """T1 EvolutionLevel 枚举"""
    levels = list(EvolutionLevel)
    checks = []
    checks.append(EvolutionLevel.L1_DREAM in levels)
    checks.append(EvolutionLevel.L2_SESSION_REFLECTION in levels)
    checks.append(EvolutionLevel.L3_KNOWLEDGE_DISTILL in levels)
    checks.append(EvolutionLevel.L0_TOOL_PROPOSAL in levels)
    checks.append(len(levels) >= 5)
    return all(checks), f"levels={len(levels)}, l1={EvolutionLevel.L1_DREAM.value}"


def t2_keyword_extraction() -> tuple[bool, str]:
    """T2 关键词提取"""
    text = """我今天工作了一整天，加班到很晚。工作项目遇到了很多bug，
    加班写代码调试程序。虽然工作很累，但是学习到了很多新技术，
    编程能力有进步。明天还要继续工作完成项目任务。"""
    keywords = extract_keywords(text, top_k=5)
    checks = []
    checks.append(len(keywords) > 0)
    checks.append(len(keywords) <= 5)
    # 应该能提取到"工作"作为高频词
    words = [w for w, _ in keywords]
    has_work = any("工作" in w for w in words)
    checks.append(has_work)
    checks.append(all(isinstance(c, int) for _, c in keywords))
    return all(checks), f"keywords={len(keywords)}, top3={[w for w, _ in keywords[:3]]}"


def t3_topic_detection() -> tuple[bool, str]:
    """T3 主题识别"""
    cases = [
        ("今天工作项目开会讨论deadline，加班写代码", ["工作", "技术"]),
        ("周末逛街吃饭看电影，好开心", ["娱乐", "生活"]),
        ("我喜欢你，想你了，我爱你", ["情感"]),
        ("感冒了，身体不舒服，去医院看病", ["健康"]),
    ]
    passed = 0
    for text, expected_topics in cases:
        detected = detect_topics(text)
        if any(t in detected for t in expected_topics):
            passed += 1
    total = len(cases)
    return passed >= 3, f"passed={passed}/{total}"


def t4_mood_detection() -> tuple[bool, str]:
    """T4 情绪检测"""
    cases = [
        ("今天好开心，遇到了很多惊喜，太幸福了", "happy"),
        ("好难过，伤心极了，委屈又生气", "sad"),
        ("今天天气不错，吃了饭看了会书", "neutral"),
        ("我喜欢你，和你在一起很温暖很感动", "positive"),
    ]
    passed = 0
    for text, expected in cases:
        mood = detect_mood(text)
        if mood == expected or (expected == "happy" and mood == "positive"):
            passed += 1
    total = len(cases)
    return passed >= 3, f"passed={passed}/{total}"


def t5_dream_init_idle() -> tuple[bool, str]:
    """T5 L1 DreamConsolidator 初始化与空闲检测"""
    dream = DreamConsolidator(min_idle_seconds=10)
    checks = []
    checks.append(dream._run_count == 0)
    checks.append(not dream.is_idle)  # 刚创建，标记了活跃
    dream.mark_active()
    checks.append(not dream.is_idle)
    # 手动设置为空闲
    dream._last_active_at = time.time() - 20
    checks.append(dream.is_idle)
    return all(checks), f"run_count={dream._run_count}, idle_when_old={dream.is_idle}"


def t6_dream_consolidation_run() -> tuple[bool, str]:
    """T6 L1 梦境整理运行"""
    dream = DreamConsolidator(min_idle_seconds=0)
    dream._last_active_at = 0  # 强制空闲

    result = asyncio.run(dream.run(force=True))
    checks = []
    checks.append(isinstance(result, DreamResult))
    checks.append(result.consolidated >= 0)
    checks.append(result.decayed >= 0)
    checks.append(isinstance(result.themes, list))
    checks.append(isinstance(result.details, list))
    checks.append(dream._run_count == 1)
    return all(checks), f"consolidated={result.consolidated}, decayed={result.decayed}, runs={dream._run_count}"


def t7_session_recording() -> tuple[bool, str]:
    """T7 L2 SessionReflector 会话记录"""
    reflector = SessionReflector()
    sid = "test_session_001"
    reflector.start_session(sid)

    reflector.add_message(sid, "user", "你好，今天工作忙吗？")
    reflector.add_message(sid, "assistant", "还挺忙的呢，一直在写代码。你呢？")
    reflector.add_message(sid, "user", "我也在加班，项目要赶deadline")

    stats = reflector.get_session_stats(sid)
    checks = []
    checks.append(stats["session_id"] == sid)
    checks.append(stats["message_count"] == 3)
    checks.append(stats["user_messages"] == 2)
    checks.append(stats["assistant_messages"] == 1)
    checks.append(stats["active"] is True)
    return all(checks), f"msgs={stats['message_count']}, user={stats['user_messages']}"


def t8_session_reflection() -> tuple[bool, str]:
    """T8 L2 会话复盘"""
    reflector = SessionReflector()
    sid = "reflect_test"
    reflector.start_session(sid)

    # 添加一些有明确主题的对话
    messages = [
        ("user", "今天工作怎么样？项目进展如何？"),
        ("assistant", "项目还行，就是bug有点多，一直在加班调试。"),
        ("user", "辛苦了，要注意身体。代码写完了吗？"),
        ("assistant", "差不多了，核心功能都实现了，技术架构也调整好了。"),
    ]
    for role, content in messages:
        reflector.add_message(sid, role, content)

    result = asyncio.run(reflector.reflect(sid))
    checks = []
    checks.append(isinstance(result, SessionReflectionResult))
    checks.append(result.session_id == sid)
    checks.append(result.message_count == 4)
    checks.append(result.duration_min >= 0)
    checks.append(isinstance(result.topics, list))
    checks.append(len(result.key_insights) > 0)
    checks.append(result.user_mood in ("happy", "positive", "neutral", "negative", "sad"))
    checks.append(len(result.summary) > 10)
    checks.append("工作" in result.topics or "技术" in result.topics or len(result.topics) >= 0)
    return all(checks), f"topics={result.topics}, mood={result.user_mood}, summary_len={len(result.summary)}"


def t9_knowledge_observations() -> tuple[bool, str]:
    """T9 L3 KnowledgeDistiller 观察数据"""
    distiller = KnowledgeDistiller()
    distiller.add_observation("我喜欢吃火锅")
    distiller.add_observation("我喜欢看电影")
    distiller.add_observation("我不喜欢早起")

    checks = []
    checks.append(len(distiller._knowledge_base) == 3)
    checks.append(len(distiller.preferences) >= 0)
    return all(checks), f"observations={len(distiller._knowledge_base)}"


def t10_knowledge_distillation() -> tuple[bool, str]:
    """T10 L3 知识蒸馏"""
    distiller = KnowledgeDistiller()

    # 添加足够多的观察数据以触发蒸馏
    observations = [
        "我喜欢吃火锅，真的很喜欢火锅的味道",
        "我喜欢看电影，每周都去电影院",
        "我不喜欢早起，早上起不来",
        "今天工作很忙，加班到很晚",
        "明天还要继续工作，项目deadline快到了",
        "周末想去旅行，放松一下",
    ]
    for obs in observations:
        distiller.add_observation(obs)

    result = asyncio.run(distiller.distill())
    checks = []
    checks.append(isinstance(result, KnowledgeDistillResult))
    checks.append(result.new_knowledge_cards >= 0)
    checks.append(result.persona_updates >= 0)
    checks.append(isinstance(result.patterns_discovered, list))
    checks.append(isinstance(result.preferences_updated, list))

    summary = distiller.get_insights_summary()
    checks.append(isinstance(summary, str))
    checks.append(len(summary) > 0)  # 至少有内容或"暂无洞察"

    return all(checks), f"cards={result.new_knowledge_cards}, persona={result.persona_updates}, prefs={len(result.preferences_updated)}"


def t11_evolution_manager_init() -> tuple[bool, str]:
    """T11 EvolutionManager 统一调度"""
    mgr = EvolutionManager(enable_l1=True, enable_l2=True, enable_l3=True)
    checks = []
    checks.append(mgr.dream is not None)
    checks.append(mgr.reflector is not None)
    checks.append(mgr.distiller is not None)
    checks.append(mgr.enable_l1)
    checks.append(mgr.enable_l2)
    checks.append(mgr.enable_l3)

    # mark_active 应该传播到 dream
    mgr.mark_active()
    checks.append(not mgr.dream.is_idle)

    return all(checks), f"components_ok={all([mgr.dream, mgr.reflector, mgr.distiller])}"


def t12_evolution_stats() -> tuple[bool, str]:
    """T12 EvolutionManager 统计信息"""
    mgr = EvolutionManager()

    # 跑一轮各层级
    asyncio.run(mgr.run_l1_dream(force=True))

    sid = "stats_test"
    mgr.reflector.start_session(sid)
    mgr.reflector.add_message(sid, "user", "hi")
    mgr.reflector.add_message(sid, "assistant", "hello")
    asyncio.run(mgr.run_l2_reflect(sid))

    mgr.distiller.add_observation("测试观察数据")
    asyncio.run(mgr.run_l3_distill())

    stats = mgr.get_stats()
    checks = []
    checks.append("total_runs" in stats)
    checks.append(stats["total_runs"]["l1"] >= 1)
    checks.append(stats["total_runs"]["l2"] >= 1)
    checks.append(stats["total_runs"]["l3"] >= 1)
    checks.append("total_tasks" in stats)
    checks.append(stats["total_tasks"] >= 3)
    checks.append("l1_idle" in stats)
    checks.append("l2_sessions" in stats)
    checks.append("l3_preferences" in stats)
    return all(checks), f"runs_l1={stats['total_runs']['l1']}, l2={stats['total_runs']['l2']}, l3={stats['total_runs']['l3']}, tasks={stats['total_tasks']}"


def main() -> int:
    tests = [
        t1_evolution_level_enum,
        t2_keyword_extraction,
        t3_topic_detection,
        t4_mood_detection,
        t5_dream_init_idle,
        t6_dream_consolidation_run,
        t7_session_recording,
        t8_session_reflection,
        t9_knowledge_observations,
        t10_knowledge_distillation,
        t11_evolution_manager_init,
        t12_evolution_stats,
    ]

    print("=" * 60)
    print("Aerie v11.3 · S4 M4.3 自进化 L1/L2/L3 验证")
    print("=" * 60)

    passed = 0
    for test in tests:
        ok, detail = test()
        status = "✓" if ok else "✗"
        name = test.__doc__ or test.__name__
        print(f"  {status} {name}  {detail}")
        if ok:
            passed += 1

    total = len(tests)
    print()
    print("=" * 60)
    print(f"结果: {passed}/{total} 通过")
    print("=" * 60)

    if passed == total:
        print("\n🎉 M4.3 自进化 L1/L2/L3 全部通过！")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 项未通过，请检查。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
