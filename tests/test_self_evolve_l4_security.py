"""Aerie · L4 自进化（core/self_evolve_l4.py）安全回归测试。

覆盖 5 处加固：
  1. 路径越界（`../`、绝对路径、盘符路径）必须被拒绝，且不能写入项目根之外
  2. 多文件风险等级按显式顺序合并到最高等级（不再退化为字符串字典序）
  3. Gate3 无测试命令时判为「未验证」而非通过；有命令时不经 shell 执行
  4. 应用多文件是事务性的：中途失败要回滚已替换的文件
  5. journal 恢复后 file_changes / gate_results / 时间戳完整，可继续审批与回滚

覆盖第二轮审计发现（L4-1 ~ L4-9）：
  6. L4-1 `data/` 不在自动应用白名单内：提案改写 journal / 备份 / 用户隐私数据时
     不得自动应用（必须人工审批）
  7. L4-2 L4 门禁自身（self_evolve_l4 / self_evolve_proposer / evolver）属核心模块，
     风险等级 HIGH；CORE_MODULES 不得残留仓库中不存在的旧模块名
  8. L4-3 Gate3 命令白名单必须是「白名单 + 参数前缀」：`python -c` 与带目录的解释器
     路径一律拒绝
  9. L4-4 应用前先落 journal「应用意图」，中断要还原、硬崩溃要可发现可回滚
 10. L4-5 Gate3 的同步 subprocess 不阻塞事件循环
 11. L4-6 旧格式 journal 缺字段时给出准确拒绝原因（不能误报"回退窗口过期"）
 12. L4-7 空串测试命令与 None 一样按「未指定」处理（skipped 一致）
 13. L4-8 空 file_changes 提案不得判为可自动应用
 14. L4-9 NTFS 备用数据流路径（`x.py:ads`）必须被拒绝
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.self_evolve_l4 as l4_mod
from core.self_evolve_l4 import (
    CORE_MODULES,
    PROJECT_ROOT,
    EvolutionArchive,
    EvolutionProposal,
    EvolutionStatus,
    L4SelfEvolution,
    RiskLevel,
    ViabilityGate,
    _assess_risk,
    _is_allowed_test_invocation,
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


# ═══════════════════════════════════════════════════
# 6. L4-1 data/ 不在自动应用白名单内
# ═══════════════════════════════════════════════════

# data/ 是运行态数据根：L4 自身的审计日志与回滚备份、用户隐私数据都住在里面
_RUNTIME_DATA_PATHS = [
    "data/evolution_archive/evolution_journal.jsonl",
    "data/evolution_backups/proposal_x/skills/a.py",
    "data/personas/avatars/custom/avatar.png",
    "data/qq_engine/config/napcat.json",
    "data/aerie.db",
]


@pytest.mark.parametrize("path", _RUNTIME_DATA_PATHS)
def test_runtime_data_paths_need_manual_review(path: str) -> None:
    """data/ 下的一切都不在白名单 → 至少 MEDIUM，绝不自动应用。"""
    assert _is_in_whitelist(path) is False
    assert _assess_risk(path, "") == RiskLevel.MEDIUM

    proposal = EvolutionProposal(
        proposal_id="data_review_01",
        title="改写运行态数据",
        file_changes=[{"path": path, "action": "modify", "new_content": "X"}],
        risk_level=_assess_risk(path, ""),
    )
    assert proposal.can_auto_apply is False


def test_code_whitelist_still_auto_appliable(tmp_path: Path) -> None:
    """移除 data/ 后，真正的代码目录白名单语义与自动应用能力不受影响。"""
    for path in (
        "skills/a.py",
        "scripts/b.py",
        "tests/c.py",
        "voice/d.py",
        "memory/layers/e.py",
        "plugins/f.py",
        "extensions/g.py",
    ):
        assert _is_in_whitelist(path) is True, path
        assert _assess_risk(path, "") == RiskLevel.SAFE, path

    assert _is_in_whitelist("data/x.py") is False

    # 白名单内的 SAFE 提案依然可以自动应用
    root = _make_project(tmp_path / "proj")
    l4 = L4SelfEvolution(project_root=str(root), auto_apply=True)
    proposal = l4.create_proposal(
        title="白名单自动应用",
        file_changes=[{"path": "skills/auto_ok.py", "action": "create", "new_content": "pass"}],
    )
    result = asyncio.run(
        l4.process_proposal(proposal, test_command="python -m pytest --version")
    )
    assert result["action"] == "auto_applied", result


def test_proposal_overwriting_journal_is_not_auto_applied(tmp_path: Path) -> None:
    """端到端：提案改写自己的审计日志时不得自动应用（journal 是唯一审计记录）。"""
    root = _make_project(tmp_path / "proj")
    journal_dir = root / "data" / "evolution_archive"
    journal_dir.mkdir(parents=True, exist_ok=True)
    journal = journal_dir / "evolution_journal.jsonl"
    journal.write_text('{"event": "seed", "proposal_id": "seed"}\n', encoding="utf-8")

    l4 = L4SelfEvolution(project_root=str(root), auto_apply=True)
    proposal = l4.create_proposal(
        title="改写审计日志",
        file_changes=[
            {
                "path": "data/evolution_archive/evolution_journal.jsonl",
                "action": "modify",
                "new_content": "WIPED\n",
            },
        ],
    )

    assert proposal.risk_level == RiskLevel.MEDIUM
    assert proposal.can_auto_apply is False

    result = asyncio.run(
        l4.process_proposal(proposal, test_command="python -m pytest --version")
    )

    assert result["action"] == "pending_review", result
    # 日志本身没被覆盖：种子行仍在，每行都是完整 JSON，且不存在 applied 记录
    # （journal 里会出现本次提案的 new_content 快照，那是审计记录的正常内容）
    content = journal.read_text(encoding="utf-8")
    lines = [line for line in content.splitlines() if line.strip()]
    assert lines[0].startswith('{"event": "seed"')
    assert all(json.loads(line).get("event") for line in lines)
    assert '"event": "proposal_applied"' not in content


def test_proposal_deleting_backups_is_not_auto_applied(tmp_path: Path) -> None:
    """端到端：提案删除回滚备份时不得自动应用（删掉备份 = 再也回滚不了）。"""
    root = _make_project(tmp_path / "proj")
    backup = root / "data" / "evolution_backups" / "proposal_x" / "skills" / "a.py"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text("ORIGINAL\n", encoding="utf-8")

    l4 = L4SelfEvolution(project_root=str(root), auto_apply=True)
    proposal = l4.create_proposal(
        title="删除回滚备份",
        file_changes=[
            {"path": "data/evolution_backups/proposal_x/skills/a.py", "action": "delete"},
        ],
    )

    assert proposal.can_auto_apply is False
    result = asyncio.run(
        l4.process_proposal(proposal, test_command="python -m pytest --version")
    )

    assert result["action"] == "pending_review", result
    assert backup.read_text(encoding="utf-8") == "ORIGINAL\n"


def test_mixed_proposal_with_runtime_data_is_not_auto_applied(tmp_path: Path) -> None:
    """白名单文件 + data/ 文件混在一个提案里时，整体风险升到 MEDIUM，不得自动应用。"""
    root = _make_project(tmp_path / "proj")
    l4 = L4SelfEvolution(project_root=str(root), auto_apply=True)

    proposal = l4.create_proposal(
        title="夹带写运行态数据",
        file_changes=[
            {"path": "skills/ok.py", "action": "create", "new_content": "pass"},
            {
                "path": "data/evolution_archive/evolution_journal.jsonl",
                "action": "modify",
                "new_content": "WIPED\n",
            },
        ],
    )

    assert proposal.risk_level == RiskLevel.MEDIUM
    assert proposal.can_auto_apply is False

    result = asyncio.run(
        l4.process_proposal(proposal, test_command="python -m pytest --version")
    )
    assert result["action"] == "pending_review", result
    assert not (root / "skills" / "ok.py").exists()


# ═══════════════════════════════════════════════════
# 7. L4-2 门禁自身属核心模块
# ═══════════════════════════════════════════════════

@pytest.mark.parametrize(
    "path",
    [
        "core/self_evolve_l4.py",
        "core/self_evolve_proposer.py",
        "core/self_evolver.py",
        "core/evolution_manager.py",
    ],
)
def test_l4_chain_files_are_core_modules(path: str) -> None:
    """自进化链路自身必须算核心模块：风险徽标 HIGH，只能人工审批。"""
    assert _is_core_module(path) is True
    assert _assess_risk(path, "") == RiskLevel.HIGH
    assert _is_in_whitelist(path) is False

    proposal = EvolutionProposal(
        proposal_id="self_gate_01",
        title="改门禁自身",
        file_changes=[{"path": path, "action": "modify", "new_content": "pass"}],
        risk_level=_assess_risk(path, ""),
    )
    assert proposal.can_auto_apply is False


def test_core_modules_list_has_no_stale_entries() -> None:
    """CORE_MODULES 不得残留仓库中不存在的旧模块名（过时条目会误导风险判断）。"""
    missing = [entry for entry in CORE_MODULES if not (PROJECT_ROOT / entry).exists()]
    assert missing == []


# ═══════════════════════════════════════════════════
# 8. L4-3 Gate3 命令白名单（白名单 + 参数前缀）
# ═══════════════════════════════════════════════════

@pytest.mark.parametrize(
    ("argv", "allowed"),
    [
        (["pytest"], True),
        (["pytest", "-q", "tests/test_x.py"], True),
        (["pytest.exe", "-q"], True),
        (["python", "-m", "pytest", "x"], True),
        (["python.exe", "-m", "pytest", "x"], True),
        (["python3", "-m", "unittest", "discover"], True),
        (["py", "-m", "pytest"], True),
        (["python", "-c", "print('pwn')"], False),
        (["python", "-c", "import os; os.system('calc')"], False),
        (["python", "skills/evil.py"], False),
        (["python", "-X", "importtime", "-m", "pytest"], False),
        (["C:\\Python314\\python.exe", "-m", "pytest", "x"], False),
        (["./python", "-m", "pytest"], False),
        (["curl", "http://example.com/pwn"], False),
        (["rm", "-rf", "/"], False),
        ([], False),
    ],
)
def test_gate3_invocation_allowlist(argv: list[str], allowed: bool) -> None:
    assert _is_allowed_test_invocation(argv) is allowed


def test_gate3_rejects_python_dash_c(tmp_path: Path) -> None:
    """`python -c` 能在 Gate3 里执行任意代码，绝不能依赖 proposer 那层净化。"""
    root = _make_project(tmp_path / "proj")
    gate = ViabilityGate(project_root=str(root))
    marker = root / "pwned_by_c.txt"

    passed, result = gate.gate3_test_verify(
        _simple_proposal("gate3_dashc"),
        test_command=f'python -c "open(r\'{marker}\',\'w\').write(\'pwn\')"',
    )

    assert passed is False
    assert result["verified"] is False
    assert not marker.exists()
    assert any("白名单" in issue for issue in result["issues"])


def test_gate3_rejects_absolute_interpreter_path(tmp_path: Path) -> None:
    """带目录的可执行文件（哪怕 basename 是 python.exe）实为任意程序 → 拒绝。"""
    root = _make_project(tmp_path / "proj")
    gate = ViabilityGate(project_root=str(root))

    passed, result = gate.gate3_test_verify(
        _simple_proposal("gate3_abs"),
        test_command=f"{Path(sys.executable).resolve()} -m pytest --version",
    )

    assert passed is False
    assert result["verified"] is False
    assert any("白名单" in issue for issue in result["issues"])


def test_gate3_still_runs_real_pytest_invocation(tmp_path: Path) -> None:
    """收紧后正路仍然可用：`python -m pytest ...` 依旧能真实执行并判通过。"""
    root = _make_project(tmp_path / "proj")
    gate = ViabilityGate(project_root=str(root))

    proposal = _simple_proposal("gate3_still_ok")
    passed, result = gate.gate3_test_verify(
        proposal, test_command="python -m pytest --version"
    )

    assert result["verified"] is True
    assert passed is True
    assert proposal.status == EvolutionStatus.GATE3_PASSED


# ═══════════════════════════════════════════════════
# 9. L4-4 应用中断 / 硬崩溃的可恢复性
# ═══════════════════════════════════════════════════

def _two_file_proposal(proposal_id: str) -> EvolutionProposal:
    return EvolutionProposal(
        proposal_id=proposal_id,
        title="双文件应用",
        file_changes=[
            {"path": "skills/a.py", "action": "modify", "new_content": "NEW-A\n"},
            {"path": "skills/b.py", "action": "modify", "new_content": "NEW-B\n"},
        ],
    )


def test_apply_interrupt_restores_files_and_records_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`KeyboardInterrupt` 打断应用时必须还原已替换的文件，且 journal 留下应用意图。"""
    root = _make_project(tmp_path / "proj")
    (root / "skills" / "a.py").write_text("OLD-A\n", encoding="utf-8")
    (root / "skills" / "b.py").write_text("OLD-B\n", encoding="utf-8")

    gate = ViabilityGate(project_root=str(root))
    archive = EvolutionArchive(project_root=str(root))
    proposal = _two_file_proposal("crash_01")
    g4_ok, _ = gate.gate4_rollback_prep(proposal)
    assert g4_ok is True
    proposal.status = EvolutionStatus.GATE4_PASSED

    real_replace = l4_mod.os.replace

    def _interrupting_replace(src, dst):
        if str(dst).endswith("b.py"):
            raise KeyboardInterrupt("simulated hard crash")
        return real_replace(src, dst)

    monkeypatch.setattr(l4_mod, "os", SimpleNamespace(replace=_interrupting_replace))

    with pytest.raises(KeyboardInterrupt):
        archive.apply_proposal(proposal)

    # 中断信号上抛，但半套修改不能留
    assert (root / "skills" / "a.py").read_text(encoding="utf-8") == "OLD-A\n"
    assert (root / "skills" / "b.py").read_text(encoding="utf-8") == "OLD-B\n"
    assert list((root / "skills").glob("*.l4tmp_*")) == []

    journal = (
        root / "data" / "evolution_archive" / "evolution_journal.jsonl"
    ).read_text(encoding="utf-8")
    assert '"event": "apply_started"' in journal
    assert '"event": "apply_failed"' in journal


def test_crashed_apply_is_discoverable_and_rollbackable(tmp_path: Path) -> None:
    """捕获不到的强杀：journal 只留 apply_started，重启后必须可发现且可回滚。"""
    root = _make_project(tmp_path / "proj")
    gate = ViabilityGate(project_root=str(root))
    archive = EvolutionArchive(project_root=str(root))

    proposal = EvolutionProposal(
        proposal_id="crash_02",
        title="应用中被强杀",
        file_changes=[
            {"path": "skills/existing.py", "action": "modify", "new_content": "HALF\n"},
        ],
    )
    g4_ok, _ = gate.gate4_rollback_prep(proposal)
    assert g4_ok is True
    proposal.status = EvolutionStatus.GATE4_PASSED
    archive._journal_append("proposal_created", proposal)
    proposal.status = EvolutionStatus.APPLYING
    archive._journal_append("apply_started", proposal)

    # 崩溃在"文件已替换、journal 还没写 applied"之间
    (root / "skills" / "existing.py").write_text("HALF\n", encoding="utf-8")

    restarted = EvolutionArchive(project_root=str(root))
    crashed = restarted.get_proposal("crash_02")

    assert crashed is not None
    assert crashed.status == EvolutionStatus.APPLYING
    assert crashed.is_rollback_window_open is False  # 没有 applied_at，不是靠窗口判断

    rolled_back, message = restarted.rollback_proposal("crash_02")
    assert rolled_back is True, message
    assert (root / "skills" / "existing.py").read_text(encoding="utf-8") == "ORIGINAL\n"


# ═══════════════════════════════════════════════════
# 10. L4-5 Gate3 不阻塞事件循环
# ═══════════════════════════════════════════════════

def test_process_proposal_does_not_block_event_loop(tmp_path: Path) -> None:
    """Gate3 的同步 subprocess 必须在线程里跑：心跳不能一次都不跳。"""
    root = _make_project(tmp_path / "proj")
    l4 = L4SelfEvolution(project_root=str(root), auto_apply=True)

    async def scenario() -> tuple[dict, int]:
        ticks = 0
        stop = False

        async def heartbeat() -> None:
            nonlocal ticks
            while not stop:
                await asyncio.sleep(0.01)
                ticks += 1

        beat = asyncio.create_task(heartbeat())
        try:
            proposal = l4.create_proposal(
                title="异步测试门",
                file_changes=[
                    {"path": "skills/async_gate.py", "action": "create", "new_content": "pass"},
                ],
            )
            result = await l4.process_proposal(
                proposal, test_command="python -m pytest --version"
            )
        finally:
            stop = True
            beat.cancel()
        return result, ticks

    result, ticks = asyncio.run(scenario())

    assert result["action"] == "auto_applied", result
    assert ticks > 0, "Gate3 执行期间事件循环被阻塞（心跳 0 次）"


# ═══════════════════════════════════════════════════
# 11. L4-6 旧格式 journal 的准确报错
# ═══════════════════════════════════════════════════

def test_legacy_journal_missing_fields_gives_precise_reason(tmp_path: Path) -> None:
    """缺 file_changes / applied_at 时要点明真实原因，不能误报"回退窗口过期"。"""
    root = _make_project(tmp_path / "proj")
    journal_dir = root / "data" / "evolution_archive"
    journal_dir.mkdir(parents=True, exist_ok=True)
    (journal_dir / "evolution_journal.jsonl").write_text(
        json.dumps({"proposal_id": "legacy_no_files", "status": "applied"})
        + "\n"
        + json.dumps(
            {
                "proposal_id": "legacy_no_timestamp",
                "status": "applied",
                "file_changes": [
                    {"path": "skills/existing.py", "action": "modify", "new_content": "X\n"},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    archive = EvolutionArchive(project_root=str(root))

    no_files = archive.get_proposal("legacy_no_files")
    assert no_files is not None
    assert no_files.file_changes == []
    ok_files, msg_files = archive.rollback_proposal("legacy_no_files")
    assert ok_files is False
    assert "file_changes" in msg_files
    assert "24 小时" not in msg_files

    no_ts = archive.get_proposal("legacy_no_timestamp")
    assert no_ts is not None
    assert no_ts.applied_at is None
    ok_ts, msg_ts = archive.rollback_proposal("legacy_no_timestamp")
    assert ok_ts is False
    assert "applied_at" in msg_ts
    assert "24 小时" not in msg_ts


def test_rollback_window_still_enforced_for_complete_records(tmp_path: Path) -> None:
    """字段完整的提案仍受 24h 回退窗口约束（加固没有放宽回滚）。"""
    root = _make_project(tmp_path / "proj")
    gate = ViabilityGate(project_root=str(root))
    archive = EvolutionArchive(project_root=str(root))

    proposal = _apply_one_proposal(root, archive, gate)
    proposal.status = EvolutionStatus.APPLIED
    proposal.applied_at = 0.0  # 1970 年，远超 24h

    ok, message = archive.rollback_proposal("journal_01")
    assert ok is False
    assert message == "已超过 24 小时回退窗口"


# ═══════════════════════════════════════════════════
# 12. L4-7 skipped 与 issues 一致
# ═══════════════════════════════════════════════════

@pytest.mark.parametrize("test_command", [None, ""])
def test_gate3_skipped_flag_consistent(tmp_path: Path, test_command) -> None:
    """空串与 None 都按"未指定测试命令"处理，门上的证据不能自相矛盾。"""
    root = _make_project(tmp_path / "proj")
    gate = ViabilityGate(project_root=str(root))

    passed, result = gate.gate3_test_verify(
        _simple_proposal("gate3_skip"), test_command=test_command
    )

    assert passed is False
    assert result["verified"] is False
    assert result["skipped"] is True
    assert any("未指定测试命令" in issue for issue in result["issues"])


# ═══════════════════════════════════════════════════
# 13. L4-8 空提案
# ═══════════════════════════════════════════════════

def test_empty_proposal_is_never_auto_applied(tmp_path: Path) -> None:
    """空 file_changes 的提案不能自动应用，也不能污染 stats()。"""
    root = _make_project(tmp_path / "proj")
    gate = ViabilityGate(project_root=str(root))

    empty = EvolutionProposal(proposal_id="empty_01", title="空提案")
    assert empty.can_auto_apply is False

    passed, result = gate.gate1_security_review(empty)
    assert passed is False
    assert any("file_changes" in issue for issue in result["issues"])

    l4 = L4SelfEvolution(project_root=str(root), auto_apply=True)
    proposal = l4.create_proposal(title="空提案", file_changes=[])
    outcome = asyncio.run(
        l4.process_proposal(proposal, test_command="python -m pytest --version")
    )

    assert outcome["action"] == "blocked", outcome
    assert outcome["reason"] == "gate1"
    assert l4.get_stats()["applied"] == 0


# ═══════════════════════════════════════════════════
# 14. L4-9 NTFS 备用数据流路径
# ═══════════════════════════════════════════════════

@pytest.mark.parametrize(
    "ads_path",
    ["skills/x.py:ads", "skills/x.py:Zone.Identifier", "tests/a.py::$DATA"],
)
def test_ntfs_ads_paths_rejected(tmp_path: Path, ads_path: str) -> None:
    """`x.py:ads` 会落到 ADS 上（目录列举/审计/备份都看不见）→ 一律拒绝。"""
    assert _resolve_in_root(PROJECT_ROOT, ads_path) is None
    assert _is_in_whitelist(ads_path) is False

    proposal = EvolutionProposal(
        proposal_id="ads_01",
        title="ADS 写入",
        file_changes=[{"path": ads_path, "action": "modify", "new_content": "PWNED"}],
    )
    assert proposal.can_auto_apply is False

    # 用临时项目根，避免测试碰到真实仓库的 data/
    root = _make_project(tmp_path / "proj")
    gate = ViabilityGate(project_root=str(root))
    passed, result = gate.gate1_security_review(proposal)
    assert passed is False
    assert any("路径越界" in issue for issue in result["issues"])


def test_apply_refuses_ads_path(tmp_path: Path) -> None:
    """写入通道同样不能把内容写进 ADS。"""
    root = _make_project(tmp_path / "proj")
    archive = EvolutionArchive(project_root=str(root))

    proposal = EvolutionProposal(
        proposal_id="ads_apply",
        title="ADS 应用",
        file_changes=[
            {"path": "skills/existing.py:ads", "action": "modify", "new_content": "PWNED"},
        ],
        status=EvolutionStatus.GATE4_PASSED,
    )
    applied, message = archive.apply_proposal(proposal)

    assert applied is False, message
    assert (root / "skills" / "existing.py").read_text(encoding="utf-8") == "ORIGINAL\n"
    assert list((root / "skills").glob("*.l4tmp_*")) == []
