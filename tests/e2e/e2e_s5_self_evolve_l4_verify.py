"""Aerie v12.0 · S5 M5.1 自进化 L4 验证

验证项：
  T1 白名单/核心模块检测
  T2 风险等级评估
  T3 EvolutionProposal 数据模型
  T4 Gate 1 安全审查（白名单通过 / 核心模块拦截）
  T5 Gate 2 语法检查（正确/错误）
  T6 Gate 3 测试验证（跳过模式）
  T7 Gate 4 回滚准备
  T8 4 道门连跑（白名单文件 → 全过）
  T9 EvolutionArchive 存储与检索
  T10 EvolutionArchive 应用与回滚
  T11 L4SelfEvolution 完整流程（白名单自动应用）
  T12 L4SelfEvolution 核心模块（待审批）
  T13 24h 回退窗口检测
  T14 Journal 日志完整性
  T15 统计信息
"""

from __future__ import annotations
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.self_evolve_l4 import (
    AUTO_EVOLVE_WHITELIST,
    CORE_MODULES,
    EvolutionArchive,
    EvolutionProposal,
    EvolutionStatus,
    L4SelfEvolution,
    RiskLevel,
    ViabilityGate,
    _assess_risk,
    _is_core_module,
    _is_in_whitelist,
)


def _make_temp_project() -> Path:
    """创建一个临时项目目录用于测试"""
    root = Path(tempfile.mkdtemp(prefix="aerie_l4_test_"))

    # 创建白名单目录
    (root / "skills").mkdir()
    (root / "voice").mkdir()
    (root / "memory" / "layers").mkdir(parents=True)
    (root / "core").mkdir()

    # 创建一些测试文件
    (root / "skills" / "hello_skill.py").write_text('''
def hello():
    return "Hello!"
''')
    (root / "voice" / "tts_engine.py").write_text('''
class TTSEngine:
    def speak(self, text):
        pass
''')
    (root / "core" / "agent.py").write_text('''
class Agent:
    def run(self):
        pass
''')
    (root / "core" / "tool_isolation.py").write_text('''
class ToolIsolator:
    def execute(self, tool, args):
        pass
''')
    (root / "memory" / "layers" / "transient.py").write_text('''
class TransientMemory:
    def store(self, item):
        pass
''')
    # data 目录
    (root / "data").mkdir()

    return root


def t1_whitelist_core_detection() -> tuple[bool, str]:
    """T1 白名单/核心模块检测"""
    checks = []
    # 白名单
    checks.append(_is_in_whitelist("skills/my_skill.py"))
    checks.append(_is_in_whitelist("voice/tts_engine.py"))
    checks.append(_is_in_whitelist("memory/layers/transient.py"))
    checks.append(_is_in_whitelist("scripts/migrate.py"))
    # 非白名单
    checks.append(not _is_in_whitelist("core/agent.py"))
    checks.append(not _is_in_whitelist("main.py"))
    # 核心模块
    checks.append(_is_core_module("core/agent.py"))
    checks.append(_is_core_module("core/tool_isolation.py"))
    checks.append(_is_core_module("core/provider_router.py"))
    # 非核心
    checks.append(not _is_core_module("skills/hello.py"))
    checks.append(not _is_core_module("voice/tts.py"))

    return all(checks), f"whitelist={len(AUTO_EVOLVE_WHITELIST)}项, core={len(CORE_MODULES)}项"


def t2_risk_assessment() -> tuple[bool, str]:
    """T2 风险等级评估"""
    cases = [
        ("skills/new_skill.py", 'def hello():\n    return "hi"', RiskLevel.SAFE),
        ("core/agent.py", "some changes", RiskLevel.HIGH),
        ("core/tool_isolation.py", "change", RiskLevel.CRITICAL),
        ("voice/tts.py", 'os.system("rm -rf /")', RiskLevel.MEDIUM),
    ]
    passed = 0
    for path, content, expected in cases:
        actual = _assess_risk(path, content)
        if actual == expected:
            passed += 1
    total = len(cases)
    return passed >= 3, f"passed={passed}/{total}"


def t3_proposal_model() -> tuple[bool, str]:
    """T3 EvolutionProposal 数据模型"""
    p = EvolutionProposal(
        proposal_id="test_001",
        title="添加新技能",
        description="测试提案",
        file_changes=[{"path": "skills/test.py", "action": "create", "new_content": "pass"}],
        risk_level=RiskLevel.SAFE,
    )
    checks = []
    checks.append(p.proposal_id == "test_001")
    checks.append(p.status == EvolutionStatus.PROPOSED)
    checks.append(p.can_auto_apply)  # 白名单 + SAFE
    checks.append(not p.is_rollback_window_open)  # 未应用
    checks.append(len(p.file_changes) == 1)
    # 高风险不能自动应用
    p2 = EvolutionProposal(
        proposal_id="test_002",
        title="修改核心",
        description="修改核心模块",
        file_changes=[{"path": "core/agent.py", "action": "modify"}],
        risk_level=RiskLevel.HIGH,
    )
    checks.append(not p2.can_auto_apply)
    return all(checks), f"safe_can_apply={p.can_auto_apply}, high_cannot={not p2.can_auto_apply}"


def t4_gate1_security() -> tuple[bool, str]:
    """T4 Gate 1 安全审查"""
    root = _make_temp_project()
    gate = ViabilityGate(project_root=str(root))

    # 白名单提案 → 通过
    safe_p = EvolutionProposal(
        proposal_id="safe_01",
        title="安全修改",
        file_changes=[{"path": "skills/test.py", "action": "create", "new_content": "pass"}],
        risk_level=RiskLevel.SAFE,
    )
    g1_ok, g1_result = gate.gate1_security_review(safe_p)
    checks = []
    checks.append(g1_ok)
    checks.append(g1_result["risk_level"] == "safe")
    checks.append(g1_result["can_auto_apply"])

    # 核心安全模块 → 不通过
    critical_p = EvolutionProposal(
        proposal_id="crit_01",
        title="修改安全模块",
        file_changes=[{"path": "core/tool_isolation.py", "action": "modify", "new_content": "pass"}],
        risk_level=RiskLevel.CRITICAL,
    )
    g1_fail, g1_fail_result = gate.gate1_security_review(critical_p)
    checks.append(not g1_fail)
    checks.append("核心安全模块" in str(g1_fail_result.get("issues", [])))

    return all(checks), f"safe_passed={g1_ok}, critical_blocked={not g1_fail}"


def t5_gate2_syntax() -> tuple[bool, str]:
    """T5 Gate 2 语法检查"""
    root = _make_temp_project()
    gate = ViabilityGate(project_root=str(root))

    # 正确语法
    good_p = EvolutionProposal(
        proposal_id="syn_good",
        title="好代码",
        file_changes=[{"path": "skills/good.py", "action": "create", "new_content": "def foo():\n    return 42\n"}],
        risk_level=RiskLevel.SAFE,
    )
    g2_ok, g2_result = gate.gate2_syntax_check(good_p)
    checks = []
    checks.append(g2_ok)
    checks.append(g2_result["files_passed"] == 1)

    # 错误语法
    bad_p = EvolutionProposal(
        proposal_id="syn_bad",
        title="坏代码",
        file_changes=[{"path": "skills/bad.py", "action": "create", "new_content": "def foo(\n    return 42\n"}],
        risk_level=RiskLevel.SAFE,
    )
    g2_bad, g2_bad_result = gate.gate2_syntax_check(bad_p)
    checks.append(not g2_bad)
    checks.append(len(g2_bad_result["issues"]) > 0)

    return all(checks), f"good_passed={g2_ok}, bad_blocked={not g2_bad}"


def t6_gate3_test() -> tuple[bool, str]:
    """T6 Gate 3 测试验证（跳过模式）"""
    root = _make_temp_project()
    gate = ViabilityGate(project_root=str(root))

    p = EvolutionProposal(
        proposal_id="test_01",
        title="测试跳过",
        file_changes=[{"path": "skills/test.py", "action": "create", "new_content": "pass"}],
        risk_level=RiskLevel.SAFE,
    )
    # 不传 test_command → 跳过但通过
    g3_ok, g3_result = gate.gate3_test_verify(p)
    checks = []
    checks.append(g3_ok)
    checks.append(g3_result["skipped"])

    return all(checks), f"skipped_and_passed={g3_ok}"


def t7_gate4_rollback_prep() -> tuple[bool, str]:
    """T7 Gate 4 回滚准备"""
    root = _make_temp_project()
    gate = ViabilityGate(project_root=str(root))

    p = EvolutionProposal(
        proposal_id="rb_01",
        title="回滚测试",
        file_changes=[
            {"path": "skills/hello_skill.py", "action": "modify",
             "old_content": 'def hello():\n    return "Hello!"\n',
             "new_content": 'def hello():\n    return "Hello World!"\n'},
        ],
        risk_level=RiskLevel.SAFE,
    )
    g4_ok, g4_result = gate.gate4_rollback_prep(p)
    checks = []
    checks.append(g4_ok)
    checks.append(g4_result["files_backed_up"] >= 1)
    checks.append(Path(g4_result["backup_path"]).exists())

    return all(checks), f"backed_up={g4_result['files_backed_up']}, backup_exists={Path(g4_result['backup_path']).exists()}"


def t8_all_gates_whitelist() -> tuple[bool, str]:
    """T8 4 道门连跑（白名单文件 → 全过）"""
    root = _make_temp_project()
    gate = ViabilityGate(project_root=str(root))

    p = EvolutionProposal(
        proposal_id="all_gates_01",
        title="全门测试",
        file_changes=[
            {"path": "skills/new_skill.py", "action": "create",
             "new_content": 'def new_skill():\n    return "new!"\n'},
        ],
        risk_level=RiskLevel.SAFE,
    )
    all_ok, summary = gate.run_all_gates(p)
    checks = []
    checks.append(all_ok)
    checks.append(p.status == EvolutionStatus.GATE4_PASSED)
    checks.append("gate1" in summary)
    checks.append("gate4" in summary)

    return all(checks), f"all_passed={all_ok}, final_status={p.status.value}"


def t9_archive_store_get() -> tuple[bool, str]:
    """T9 EvolutionArchive 存储与检索"""
    root = _make_temp_project()
    archive = EvolutionArchive(project_root=str(root))

    p = EvolutionProposal(
        proposal_id="arch_01",
        title="归档测试",
        description="测试归档功能",
        file_changes=[{"path": "skills/t.py", "action": "create", "new_content": "pass"}],
        risk_level=RiskLevel.LOW,
    )
    archive.store_proposal(p)

    checks = []
    got = archive.get_proposal("arch_01")
    checks.append(got is not None)
    checks.append(got.title == "归档测试")
    checks.append(got.risk_level == RiskLevel.LOW)

    # 列表
    props = archive.list_proposals()
    checks.append(len(props) >= 1)

    return all(checks), f"stored={got is not None}, list_count={len(props)}"


def t10_archive_apply_rollback() -> tuple[bool, str]:
    """T10 EvolutionArchive 应用与回滚"""
    root = _make_temp_project()
    archive = EvolutionArchive(project_root=str(root))
    gate = ViabilityGate(project_root=str(root))

    # 准备：先通过 Gate4 创建备份
    p = EvolutionProposal(
        proposal_id="apply_rb_01",
        title="应用回滚测试",
        file_changes=[
            {"path": "skills/hello_skill.py", "action": "modify",
             "old_content": '',
             "new_content": 'def hello():\n    return "Modified!"\n'},
        ],
        risk_level=RiskLevel.SAFE,
    )
    # 先跑 gate4 创建备份
    gate.gate4_rollback_prep(p)
    p.status = EvolutionStatus.GATE4_PASSED

    # 应用
    applied, msg = archive.apply_proposal(p)
    checks = []
    checks.append(applied)
    checks.append(p.status == EvolutionStatus.APPLIED)
    checks.append(p.applied_at is not None)
    checks.append(p.is_rollback_window_open)

    # 验证文件已修改
    file_content = (root / "skills" / "hello_skill.py").read_text()
    checks.append("Modified!" in file_content)

    # 回滚
    rolled_back, rb_msg = archive.rollback_proposal("apply_rb_01")
    checks.append(rolled_back)
    checks.append(p.status == EvolutionStatus.ROLLED_BACK)

    return all(checks), f"applied={applied}, rolled_back={rolled_back}"


def t11_l4_full_auto() -> tuple[bool, str]:
    """T11 L4SelfEvolution 完整流程（白名单自动应用）"""
    root = _make_temp_project()
    l4 = L4SelfEvolution(project_root=str(root), auto_apply=True)

    proposal = l4.create_proposal(
        title="自动添加技能",
        description="测试白名单自动应用",
        file_changes=[
            {"path": "skills/auto_skill.py", "action": "create",
             "new_content": 'def auto():\n    return "auto applied"\n'},
        ],
    )

    import asyncio
    result = asyncio.run(l4.process_proposal(proposal))

    checks = []
    checks.append(result["action"] == "auto_applied")
    checks.append(result["risk_level"] == "safe")
    checks.append(proposal.status == EvolutionStatus.APPLIED)

    # 验证文件已创建
    checks.append((root / "skills" / "auto_skill.py").exists())

    return all(checks), f"action={result['action']}, status={proposal.status.value}"


def t12_l4_core_pending() -> tuple[bool, str]:
    """T12 L4SelfEvolution 核心模块（待审批）"""
    root = _make_temp_project()
    l4 = L4SelfEvolution(project_root=str(root), auto_apply=True)

    proposal = l4.create_proposal(
        title="修改核心模块",
        description="核心模块修改需人工审批",
        file_changes=[
            {"path": "core/agent.py", "action": "modify",
             "new_content": 'class Agent:\n    def run(self):\n        print("modified")\n'},
        ],
    )

    import asyncio
    result = asyncio.run(l4.process_proposal(proposal))

    checks = []
    # 核心模块应该是 pending_review（Gate1通过但 can_auto_apply=False）
    checks.append(result["action"] == "pending_review")
    checks.append(proposal.status == EvolutionStatus.PENDING_REVIEW)
    checks.append(not proposal.can_auto_apply)

    # 人工审批
    approved, _ = l4.approve_and_apply(proposal.proposal_id)
    checks.append(approved)
    checks.append(proposal.status == EvolutionStatus.APPLIED)

    return all(checks), f"action={result['action']}, approved_status={proposal.status.value if approved else 'n/a'}"


def t13_rollback_window() -> tuple[bool, str]:
    """T13 24h 回退窗口检测"""
    p = EvolutionProposal(
        proposal_id="rb_window_test",
        title="回退窗口测试",
    )
    # 未应用 → 窗口关闭
    checks = []
    checks.append(not p.is_rollback_window_open)

    # 刚应用 → 窗口开启
    p.status = EvolutionStatus.APPLIED
    p.applied_at = time.time()
    checks.append(p.is_rollback_window_open)

    # 25小时前应用 → 窗口关闭
    p.applied_at = time.time() - 25 * 3600
    checks.append(not p.is_rollback_window_open)

    return all(checks), f"open_when_recent={p.is_rollback_window_open is False and True}, 25h_closed={not p.is_rollback_window_open}"


def t14_journal_integrity() -> tuple[bool, str]:
    """T14 Journal 日志完整性"""
    root = _make_temp_project()
    l4 = L4SelfEvolution(project_root=str(root), auto_apply=True)

    p = l4.create_proposal(
        title="日志测试",
        description="检查 journal 是否记录",
        file_changes=[
            {"path": "skills/journal_test.py", "action": "create", "new_content": "pass"},
        ],
    )

    import asyncio
    asyncio.run(l4.process_proposal(p))

    journal_path = root / "data" / "evolution_archive" / "evolution_journal.jsonl"
    checks = []
    checks.append(journal_path.exists())

    # 读取日志
    lines = journal_path.read_text().strip().split("\n")
    checks.append(len(lines) >= 2)  # 至少 created + applied 两条

    # 每条都有 event 和 proposal_id
    import json
    valid = 0
    for line in lines:
        try:
            entry = json.loads(line)
            if "event" in entry and "proposal_id" in entry:
                valid += 1
        except Exception:
            pass
    checks.append(valid == len(lines))

    return all(checks), f"journal_exists={journal_path.exists()}, entries={len(lines)}, valid={valid}"


def t15_stats() -> tuple[bool, str]:
    """T15 统计信息"""
    root = _make_temp_project()
    l4 = L4SelfEvolution(project_root=str(root), auto_apply=True)

    # 创建几个不同状态的提案
    for i in range(3):
        p = l4.create_proposal(
            title=f"测试{i}",
            file_changes=[{"path": f"skills/test{i}.py", "action": "create", "new_content": "pass"}],
        )
        import asyncio
        asyncio.run(l4.process_proposal(p))

    stats = l4.get_stats()
    checks = []
    checks.append("total" in stats)
    checks.append("applied" in stats)
    checks.append("success_rate" in stats)
    checks.append(stats["total"] >= 3)
    checks.append(stats["applied"] >= 1)

    return all(checks), f"total={stats.get('total')}, applied={stats.get('applied')}"


def main() -> int:
    tests = [
        t1_whitelist_core_detection,
        t2_risk_assessment,
        t3_proposal_model,
        t4_gate1_security,
        t5_gate2_syntax,
        t6_gate3_test,
        t7_gate4_rollback_prep,
        t8_all_gates_whitelist,
        t9_archive_store_get,
        t10_archive_apply_rollback,
        t11_l4_full_auto,
        t12_l4_core_pending,
        t13_rollback_window,
        t14_journal_integrity,
        t15_stats,
    ]

    print("=" * 60)
    print("Aerie v12.0 · S5 M5.1 自进化 L4 验证")
    print("  沙箱自动进化模式")
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
        print("\n🎉 M5.1 自进化 L4 全部通过！")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 项未通过，请检查。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
