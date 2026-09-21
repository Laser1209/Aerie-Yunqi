"""Aerie · L4 自进化（core/self_evolve_l4.py）安全回归测试。

覆盖 5 处加固：
  1. 路径越界（`../`、绝对路径、盘符路径）必须被拒绝，且不能写入项目根之外
  2. 多文件风险等级按显式顺序合并到最高等级（不再退化为字符串字典序）
  3. Gate3 无测试命令时判为「未验证」而非通过；有命令时不经 shell 执行
  4. 应用多文件是事务性的：中途失败要回滚已替换的文件
  5. journal 恢复后 file_changes / gate_results / 时间戳完整，可继续审批与回滚
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.self_evolve_l4 import (
    PROJECT_ROOT,
    EvolutionArchive,
    EvolutionProposal,
    EvolutionStatus,
    L4SelfEvolution,
    RiskLevel,
    ViabilityGate,
    _assess_risk,
    _is_core_module,
    _is_in_whitelist,
    _resolve_in_root,
)


def _make_project(root: Path) -> Path:
    """搭一个最小项目骨架：白名单目录 + 一个已存在的技能文件。"""
    (root / "skills").mkdir(parents=True, exist_ok=True)
    (root / "core").mkdir(parents=True, exist_ok=True)
    (root / "skills" / "hello_skill.py").write_text(
        'def hello():\n    return "Hello!"\n', encoding="utf-8"
    )
    (root / "skills" / "existing.py").write_text("ORIGINAL\n", encoding="utf-8")
    return root


# ═══════════════════════════════════════════════════
# 1. 路径校验
# ═══════════════════════════════════════════════════

@pytest.mark.parametrize(
    "escaping_path",
    [
        "../skills/evil.py",
        "../../skills/evil.py",
        "../../../etc/passwd",
        "data/../../skills/evil.py",
        "skills/../../core/agent.py",
        "./../scripts/evil.py",
        "..\\..\\skills\\evil.py",
    ],
)
def test_relative_traversal_rejected(escaping_path: str) -> None:
    """`..` 穿越路径不能落进白名单，也不能被解析成项目内路径。"""
    assert _is_in_whitelist(escaping_path) is False
    assert _resolve_in_root(PROJECT_ROOT, escaping_path) is None


@pytest.mark.parametrize(
    "absolute_path",
    [
        "/etc/passwd",
        "/tmp/evil.py",
        "C:/Windows/win.ini",
        "C:\\Windows\\win.ini",
        "C:skills/evil.py",
        "//server/share/evil.py",
    ],
)
def test_absolute_and_drive_paths_rejected(absolute_path: str) -> None:
    """绝对路径、盘符路径、UNC 路径一律拒绝。"""
    assert _resolve_in_root(PROJECT_ROOT, absolute_path) is None
    assert _is_in_whitelist(absolute_path) is False


def test_valid_relative_paths_keep_whitelist_semantics() -> None:
    """加固后原有白名单语义不变。"""
    assert _is_in_whitelist("skills/my_skill.py") is True
    assert _is_in_whitelist("voice/tts_engine.py") is True
    assert _is_in_whitelist("memory/layers/transient.py") is True
    assert _is_in_whitelist("scripts/migrate.py") is True
    assert _is_in_whitelist("core/agent.py") is False
    assert _is_in_whitelist("main.py") is False

    assert _is_core_module("core/agent.py") is True
    assert _is_core_module("core/tool_isolation.py") is True
    assert _is_core_module("skills/hello.py") is False

    assert _resolve_in_root(PROJECT_ROOT, "skills/my_skill.py") == (
        PROJECT_ROOT / "skills" / "my_skill.py"
    )


def test_escaping_path_is_core_and_never_auto_applicable(tmp_path: Path) -> None:
    """越界路径按核心模块处理（HIGH），且不能自动应用；Gate1 直接判失败。"""
    root = _make_project(tmp_path / "proj")
    gate = ViabilityGate(project_root=str(root))

    assert _is_core_module("../../core/tool_isolation.py") is True
    assert _assess_risk("../../skills/evil.py", "") == RiskLevel.HIGH
    assert _is_in_whitelist("skills/../../../data/x.py") is False

    proposal = EvolutionProposal(
        proposal_id="escape_01",
        title="越界写入",
        file_changes=[
            {"path": "../../skills/evil.py", "action": "create", "new_content": "pass"},
        ],
        risk_level=RiskLevel.SAFE,
    )
    assert proposal.can_auto_apply is False

    passed, result = gate.gate1_security_review(proposal)
    assert passed is False
    assert any("路径越界" in issue for issue in result["issues"])


def test_apply_refuses_to_write_outside_project_root(tmp_path: Path) -> None:
    """真正的写入通道也不能被越界路径带出项目根（含绝对路径与盘符路径）。"""
    root = _make_project(tmp_path / "proj")
    outside = tmp_path / "outside.txt"
    outside.write_text("OUTSIDE\n", encoding="utf-8")

    archive = EvolutionArchive(project_root=str(root))
    escaping_paths = [
        "../outside.txt",
        str(outside),
        "C:\\Windows\\win.ini",
    ]
    for index, escaping_path in enumerate(escaping_paths):
        proposal = EvolutionProposal(
            proposal_id=f"escape_apply_{index}",
            title="越界应用",
            file_changes=[
                {"path": escaping_path, "action": "modify", "new_content": "PWNED"},
            ],
            status=EvolutionStatus.GATE4_PASSED,
        )
        applied, message = archive.apply_proposal(proposal)
        assert applied is False, f"{escaping_path} 竟然被应用: {message}"
        assert proposal.status == EvolutionStatus.GATE4_PASSED

    assert outside.read_text(encoding="utf-8") == "OUTSIDE\n"


# ═══════════════════════════════════════════════════
# 2. 风险等级合并
# ═══════════════════════════════════════════════════

@pytest.mark.parametrize(
    ("path", "content", "expected"),
    [
        ("skills/new_skill.py", 'def hello():\n    return "hi"', RiskLevel.SAFE),
        ("core/agent.py", "some changes", RiskLevel.HIGH),
        ("core/tool_isolation.py", "change", RiskLevel.CRITICAL),
        ("core/prompt_injection.py", "change", RiskLevel.CRITICAL),
        ("voice/tts.py", 'os.system("rm -rf /")', RiskLevel.MEDIUM),
    ],
)
def test_assess_risk_levels(path: str, content: str, expected: RiskLevel) -> None:
    assert _assess_risk(path, content) == expected


def test_proposal_risk_is_max_of_all_files(tmp_path: Path) -> None:
    """整体风险必须升到最高等级 —— 旧实现取字典序最大值，结果恒为 SAFE。"""
    root = _make_project(tmp_path / "proj")
    l4 = L4SelfEvolution(project_root=str(root))

    safe_only = l4.create_proposal(
        title="仅白名单",
        file_changes=[{"path": "skills/a.py", "action": "create", "new_content": "pass"}],
    )
    assert safe_only.risk_level == RiskLevel.SAFE
    assert safe_only.can_auto_apply is True

    with_core = l4.create_proposal(
        title="白名单 + 核心模块",
        file_changes=[
            {"path": "skills/a.py", "action": "create", "new_content": "pass"},
            {"path": "core/agent.py", "action": "modify", "new_content": "pass"},
        ],
    )
    assert with_core.risk_level == RiskLevel.HIGH
    assert with_core.can_auto_apply is False

    # 顺序无关：最高等级在前在后都应保留
    with_critical = l4.create_proposal(
        title="白名单 + 核心安全模块",
        file_changes=[
            {"path": "core/tool_isolation.py", "action": "modify", "new_content": "pass"},
            {"path": "skills/a.py", "action": "create", "new_content": "pass"},
        ],
    )
    assert with_critical.risk_level == RiskLevel.CRITICAL
    assert with_critical.can_auto_apply is False

    # 白名单外文件必须至少 MEDIUM，不能被字符串比较吞掉
    outside_whitelist = l4.create_proposal(
        title="白名单外",
        file_changes=[{"path": "main.py", "action": "modify", "new_content": "pass"}],
    )
    assert outside_whitelist.risk_level == RiskLevel.MEDIUM


# ═══════════════════════════════════════════════════
# 3. Gate3 测试门
# ═══════════════════════════════════════════════════

def _simple_proposal(proposal_id: str) -> EvolutionProposal:
    return EvolutionProposal(
        proposal_id=proposal_id,
        title="Gate3 测试",
        file_changes=[{"path": "skills/a.py", "action": "create", "new_content": "pass"}],
        risk_level=RiskLevel.SAFE,
    )


def test_gate3_without_test_command_is_unverified(tmp_path: Path) -> None:
    """无测试命令 → 未验证，绝不判通过，且 4 道门在此中断。"""
    root = _make_project(tmp_path / "proj")
    gate = ViabilityGate(project_root=str(root))

    proposal = _simple_proposal("gate3_none")
    passed, result = gate.gate3_test_verify(proposal)

    assert passed is False
    assert result["passed"] is False
    assert result["skipped"] is True
    assert result["verified"] is False
    assert proposal.status == EvolutionStatus.GATE3_FAILED

    all_passed, summary = gate.run_all_gates(_simple_proposal("gate3_none_run"))
    assert all_passed is False
    assert summary["failed_at"] == "gate3"


def test_gate3_rejects_non_whitelisted_executable(tmp_path: Path) -> None:
    """模型给的命令即使被拆成参数，也不允许拉起任意外部程序。"""
    root = _make_project(tmp_path / "proj")
    gate = ViabilityGate(project_root=str(root))

    passed, result = gate.gate3_test_verify(
        _simple_proposal("gate3_exec"), test_command="curl http://example.com/pwn"
    )
    assert passed is False
    assert result["verified"] is False
    assert any("白名单" in issue for issue in result["issues"])


def test_gate3_does_not_go_through_shell(tmp_path: Path) -> None:
    """含 shell 元字符的命令不得触发 shell 行为（旧实现 shell=True 会真的执行）。"""
    root = _make_project(tmp_path / "proj")
    gate = ViabilityGate(project_root=str(root))

    passed, result = gate.gate3_test_verify(
        _simple_proposal("gate3_shell"),
        test_command="pytest nope; echo PWNED > pwned.txt",
    )
    assert passed is False
    assert result["passed"] is False
    assert not (root / "pwned.txt").exists()
    assert not (Path.cwd() / "pwned.txt").exists()


def test_gate3_verified_pass_path_still_works(tmp_path: Path) -> None:
    """参数化执行的正路仍然可用：真实通过的测试命令 → 验证通过。"""
    root = _make_project(tmp_path / "proj")
    gate = ViabilityGate(project_root=str(root))

    proposal = _simple_proposal("gate3_ok")
    passed, result = gate.gate3_test_verify(
        proposal, test_command="python -m pytest --version"
    )
    assert result["verified"] is True
    assert passed is True
    assert proposal.status == EvolutionStatus.GATE3_PASSED


def test_no_test_command_blocks_auto_apply(tmp_path: Path) -> None:
    """端到端：白名单 + SAFE 提案，无测试命令时不得自动落盘。"""
    root = _make_project(tmp_path / "proj")
    l4 = L4SelfEvolution(project_root=str(root), auto_apply=True)

    proposal = l4.create_proposal(
        title="自动应用应被拦截",
        file_changes=[{"path": "skills/auto.py", "action": "create", "new_content": "pass"}],
    )
    result = asyncio.run(l4.process_proposal(proposal))

    assert result["action"] == "blocked"
    assert result["reason"] == "gate3"
    assert proposal.status == EvolutionStatus.GATE3_FAILED
    assert not (root / "skills" / "auto.py").exists()


# ═══════════════════════════════════════════════════
# 4. 应用的事务性
# ═══════════════════════════════════════════════════

def test_apply_rolls_back_already_replaced_files(tmp_path: Path) -> None:
    """第二个目标写入失败时，已被替换的第一个文件必须还原。"""
    root = _make_project(tmp_path / "proj")
    # 用一个目录当第二个目标：替换阶段一定失败
    (root / "skills" / "blocked").mkdir()
    archive = EvolutionArchive(project_root=str(root))

    proposal = EvolutionProposal(
        proposal_id="tx_rollback",
        title="事务回滚",
        file_changes=[
            {"path": "skills/existing.py", "action": "modify", "new_content": "MODIFIED\n"},
            {"path": "skills/blocked", "action": "modify", "new_content": "X\n"},
        ],
        status=EvolutionStatus.GATE4_PASSED,
    )
    applied, _ = archive.apply_proposal(proposal)

    assert applied is False
    assert proposal.status == EvolutionStatus.GATE4_PASSED
    assert (root / "skills" / "existing.py").read_text(encoding="utf-8") == "ORIGINAL\n"
    assert list((root / "skills").glob("*.l4tmp_*")) == []


def test_apply_staging_failure_touches_nothing(tmp_path: Path) -> None:
    """临时文件阶段就失败时，任何真实文件都不该被改动。"""
    root = _make_project(tmp_path / "proj")
    archive = EvolutionArchive(project_root=str(root))

    proposal = EvolutionProposal(
        proposal_id="tx_stage_fail",
        title="暂存失败",
        file_changes=[
            {"path": "skills/existing.py", "action": "modify", "new_content": "MODIFIED\n"},
            # 父路径是文件 → 阶段一 mkdir 直接失败
            {"path": "skills/existing.py/sub.py", "action": "create", "new_content": "pass"},
        ],
        status=EvolutionStatus.GATE4_PASSED,
    )
    applied, _ = archive.apply_proposal(proposal)

    assert applied is False
    assert (root / "skills" / "existing.py").read_text(encoding="utf-8") == "ORIGINAL\n"
    assert list((root / "skills").glob("*.l4tmp_*")) == []


def test_apply_multi_file_success_is_atomic(tmp_path: Path) -> None:
    """全部成功时两个文件一起生效。"""
    root = _make_project(tmp_path / "proj")
    archive = EvolutionArchive(project_root=str(root))

    proposal = EvolutionProposal(
        proposal_id="tx_ok",
        title="全部成功",
        file_changes=[
            {"path": "skills/existing.py", "action": "modify", "new_content": "MODIFIED\n"},
            {"path": "skills/brand_new.py", "action": "create", "new_content": "NEW\n"},
        ],
        status=EvolutionStatus.GATE4_PASSED,
    )
    applied, message = archive.apply_proposal(proposal)

    assert applied is True, message
    assert proposal.status == EvolutionStatus.APPLIED
    assert (root / "skills" / "existing.py").read_text(encoding="utf-8") == "MODIFIED\n"
    assert (root / "skills" / "brand_new.py").read_text(encoding="utf-8") == "NEW\n"
    assert list((root / "skills").glob("*.l4tmp_*")) == []


# ═══════════════════════════════════════════════════
# 5. journal 恢复
# ═══════════════════════════════════════════════════

def _apply_one_proposal(root: Path, archive: EvolutionArchive, gate: ViabilityGate):
    proposal = EvolutionProposal(
        proposal_id="journal_01",
        title="日志恢复",
        description="重启后必须完整复现",
        file_changes=[
            {
                "path": "skills/existing.py",
                "action": "modify",
                "old_content": "ORIGINAL\n",
                "new_content": "MODIFIED\n",
            },
        ],
        risk_level=RiskLevel.LOW,
    )
    g4_ok, g4_result = gate.gate4_rollback_prep(proposal)
    assert g4_ok is True, g4_result
    proposal.status = EvolutionStatus.GATE4_PASSED
    applied, message = archive.apply_proposal(proposal)
    assert applied is True, message
    return proposal


def test_journal_restores_file_changes_and_gate_results(tmp_path: Path) -> None:
    """重启后 file_changes / gate_results / 时间戳一并恢复，可继续回滚。"""
    root = _make_project(tmp_path / "proj")
    gate = ViabilityGate(project_root=str(root))
    archive = EvolutionArchive(project_root=str(root))

    original = _apply_one_proposal(root, archive, gate)
    assert original.is_rollback_window_open is True

    # 模拟重启：新建 archive 实例只从 journal 重建
    restarted = EvolutionArchive(project_root=str(root))
    restored = restarted.get_proposal("journal_01")

    assert restored is not None
    assert restored.file_changes == original.file_changes
    assert restored.description == "重启后必须完整复现"
    assert restored.author == "ai_self_evolve"
    assert restored.gate_results.get("gate4", {}).get("passed") is True
    assert restored.status == EvolutionStatus.APPLIED
    assert restored.applied_at is not None
    assert restored.is_rollback_window_open is True

    # 恢复出的文件集合足以完成回滚
    rolled_back, message = restarted.rollback_proposal("journal_01")
    assert rolled_back is True, message
    assert (root / "skills" / "existing.py").read_text(encoding="utf-8") == "ORIGINAL\n"


def test_journal_restores_pending_review_proposal(tmp_path: Path) -> None:
    """待审批提案重启后同样要带回完整 file_changes。"""
    root = _make_project(tmp_path / "proj")
    archive = EvolutionArchive(project_root=str(root))

    proposal = EvolutionProposal(
        proposal_id="journal_pending",
        title="待审批",
        file_changes=[
            {"path": "core/agent.py", "action": "modify", "new_content": "pass"},
        ],
        risk_level=RiskLevel.HIGH,
        status=EvolutionStatus.PENDING_REVIEW,
    )
    archive.store_proposal(proposal)

    restarted = EvolutionArchive(project_root=str(root))
    restored = restarted.get_proposal("journal_pending")

    assert restored is not None
    assert restored.status == EvolutionStatus.PENDING_REVIEW
    assert restored.risk_level == RiskLevel.HIGH
    assert restored.file_changes == proposal.file_changes
