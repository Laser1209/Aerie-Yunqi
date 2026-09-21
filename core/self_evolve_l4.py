"""Aerie · 云栖 v0.1.0-beta.1 — Self-Evolution L4: Code Self-Modification.

  ╔══════════════════════════════════════════════════════════╗
  ║  L4 自进化：代码自修改（沙箱自动进化模式）              ║
  ╠══════════════════════════════════════════════════════════╣
  ║                                                          ║
  ║  4 道门（Viability Gate）：                              ║
  ║  ─────────────────────────────────────────────────       ║
  ║  Gate 1 · 安全审查                                       ║
  ║    └─ 修改范围是否在白名单内？                            ║
  ║    └─ 是否触碰敏感文件/函数？                             ║
  ║    └─ 风险等级评估                                       ║
  ║                                                          ║
  ║  Gate 2 · 语法检查                                       ║
  ║    └─ 修改后 Python 语法是否正确？                        ║
  ║    └─ 导入是否完整？                                     ║
  ║                                                          ║
  ║  Gate 3 · 测试验证                                       ║
  ║    └─ 相关单元测试是否通过？                              ║
  ║    └─ 冒烟测试是否通过？                                 ║
  ║                                                          ║
  ║  Gate 4 · 回滚准备                                       ║
  ║    └─ 回滚点已创建？                                     ║
  ║    └─ 备份文件完整？                                     ║
  ║                                                          ║
  ║  自动执行条件：                                          ║
  ║    白名单文件 + 4 道门全通过 → 自动应用                  ║
  ║    核心文件 + 4 道门通过 → 生成提案，等待人工审批        ║
  ║                                                          ║
  ║  24h 回退窗口：                                          ║
  ║    所有自动应用的修改，24小时内可一键回退                 ║
  ║                                                          ║
  ╚══════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 项目根目录：提案里的相对路径必须最终落在它之内，越界一律拒绝。
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent


class EvolutionStatus(str, Enum):
    PROPOSED = "proposed"
    GATE1_PASSED = "gate1_passed"
    GATE1_FAILED = "gate1_failed"
    GATE2_PASSED = "gate2_passed"
    GATE2_FAILED = "gate2_failed"
    GATE3_PASSED = "gate3_passed"
    GATE3_FAILED = "gate3_failed"
    GATE4_PASSED = "gate4_passed"
    GATE4_FAILED = "gate4_failed"
    APPROVED = "approved"
    APPLIED = "applied"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"
    PENDING_REVIEW = "pending_review"


class RiskLevel(str, Enum):
    SAFE = "safe"           # 白名单内，纯功能添加
    LOW = "low"             # 白名单内，修改现有逻辑
    MEDIUM = "medium"       # 白名单边缘，或修改共享模块
    HIGH = "high"           # 核心模块，或涉及安全/权限
    CRITICAL = "critical"   # 核心安全模块，绝对禁止自动修改


# 风险等级的显式大小顺序。
# RiskLevel 继承 str，直接用 value 比大小会退化成字典序
# （"critical" < "high" < "low" < "medium" < "safe"，与语义完全相反），
# 因此合并风险时必须走这张表而不是字符串比较。
_RISK_ORDER: dict[RiskLevel, int] = {
    RiskLevel.SAFE: 0,
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.CRITICAL: 4,
}


# ═══════════════════════════════════════════════════
# 白名单与黑名单配置
# ═══════════════════════════════════════════════════

# 自动进化白名单（可自动应用修改）
AUTO_EVOLVE_WHITELIST: list[str] = [
    "skills/",              # 技能模块
    "memory/layers/",       # 记忆层（非核心调度）
    "voice/",               # 语音模块
    "data/",                # 数据目录
    "scripts/",             # 脚本
    "tests/",               # 测试
    "plugins/",             # 插件
    "extensions/",          # 扩展
]

# 核心模块（仅提案，不自动应用，需人工审批）
CORE_MODULES: list[str] = [
    "core/agent.py",
    "core/provider_router.py",
    "core/tool_isolation.py",
    "core/prompt_injection.py",
    "core/llm_caller.py",
    "core/companion.py",
    "core/decision.py",
    "core/pipeline.py",
    "core/sandbox_runner.py",
    "core/self_evolver.py",
    "core/evolution_manager.py",      # 自身也要保护
    "core/self_evolve_archive.py",    # 自身也要保护
    "core/viability_gate.py",         # 自身也要保护
    "core/security/",
]

# 敏感模式（修改内容中出现即提升风险等级）
SENSITIVE_PATTERNS: list[str] = [
    "os.system",
    "subprocess",
    "eval(",
    "exec(",
    "__import__",
    "remove(",
    "rmtree",
    "shutil.rmtree",
    "sudo",
    "chmod 777",
    "api_key",
    "password",
    "secret",
    "token",
    "private_key",
]

# Gate3 允许的执行器：模型给的测试命令只能落在这些解释器/测试运行器上，
# 即使命令串被拆成参数列表，也不允许拉起任意外部程序。
_ALLOWED_TEST_EXECUTABLES: set[str] = {
    "pytest", "pytest.exe",
    "python", "python.exe",
    "python3", "python3.exe",
    "py", "py.exe",
}


def _resolve_in_root(root: Path, file_path: str) -> Optional[Path]:
    """把提案中的相对路径解析为 root 内的绝对路径；不合法返回 None。

    模型给出的路径不可信：绝对路径、Windows 盘符路径、`..` 穿越都能在纯字符串
    层面拼出白名单前缀（如 `../../skills/x.py`），因此必须 resolve 之后确认目标
    仍落在 root 之内，而不是只做前缀匹配。
    """
    if not isinstance(file_path, str) or not file_path.strip():
        return None
    raw = file_path.strip().replace("\\", "/")
    # 绝对路径、盘符路径（C:/...）、UNC 路径（//server/...）没有"项目内相对路径"语义
    if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        return None
    try:
        target = (root / raw).resolve()
        target.relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    return target


def _safe_relative_path(file_path: str) -> Optional[str]:
    """把路径归一化为项目根内的 POSIX 相对路径；越界/绝对/盘符路径返回 None。"""
    target = _resolve_in_root(PROJECT_ROOT, file_path)
    if target is None:
        return None
    return target.relative_to(PROJECT_ROOT).as_posix()


def _silent_unlink(path: Path) -> None:
    """清理临时/半成品文件；不存在或删不掉都不该打断主流程。"""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("L4 清理临时文件失败: %s", path)


def _is_in_whitelist(file_path: str) -> bool:
    """检查文件是否在自动进化白名单内（越界路径视为不在白名单）"""
    normalized = _safe_relative_path(file_path)
    if normalized is None:
        return False
    for prefix in AUTO_EVOLVE_WHITELIST:
        if normalized.startswith(prefix):
            return True
    return False


def _is_core_module(file_path: str) -> bool:
    """检查文件是否为核心模块

    越界路径无法确认真实落点，按最保守处理（视为核心模块），
    避免用 `../` 之类绕过"核心模块必须人工审批"。
    """
    normalized = _safe_relative_path(file_path)
    if normalized is None:
        return True
    for core_path in CORE_MODULES:
        if normalized == core_path or normalized.startswith(core_path.rstrip("/") + "/"):
            return True
    return False


def _assess_risk(file_path: str, diff_content: str) -> RiskLevel:
    """评估修改风险等级"""
    normalized = _safe_relative_path(file_path) or ""

    # 核心安全模块 → CRITICAL
    for sensitive_file in ["tool_isolation", "prompt_injection", "sandbox_runner"]:
        if sensitive_file in normalized:
            return RiskLevel.CRITICAL

    # 核心模块 → HIGH
    if _is_core_module(file_path):
        return RiskLevel.HIGH

    # 检查内容中的敏感模式
    risk = RiskLevel.SAFE
    for pattern in SENSITIVE_PATTERNS:
        if pattern in diff_content:
            risk = RiskLevel.MEDIUM
            break

    # 白名单内 + 无敏感内容 → SAFE/LOW
    if _is_in_whitelist(file_path):
        # 修改量大会提升风险
        lines_changed = diff_content.count("\n+") + diff_content.count("\n-")
        if lines_changed > 100:
            risk = RiskLevel.LOW if risk == RiskLevel.SAFE else risk
    else:
        # 不在白名单 → 至少 MEDIUM
        if _RISK_ORDER[risk] < _RISK_ORDER[RiskLevel.MEDIUM]:
            risk = RiskLevel.MEDIUM

    return risk


# ═══════════════════════════════════════════════════
# 进化提案数据模型
# ═══════════════════════════════════════════════════

@dataclass
class EvolutionProposal:
    """自进化提案"""
    proposal_id: str
    title: str
    description: str = ""
    file_changes: list[dict] = field(default_factory=list)
    # file_changes: [{"path": "...", "action": "modify/create/delete",
    #                 "old_content": "...", "new_content": "...", "diff": "..."}]
    risk_level: RiskLevel = RiskLevel.SAFE
    status: EvolutionStatus = EvolutionStatus.PROPOSED
    created_at: float = field(default_factory=time.time)
    applied_at: Optional[float] = None
    rolled_back_at: Optional[float] = None
    gate_results: dict[str, dict] = field(default_factory=dict)
    author: str = "ai_self_evolve"
    metadata: dict = field(default_factory=dict)

    @property
    def can_auto_apply(self) -> bool:
        """是否可以自动应用（白名单 + 低风险）"""
        if self.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            return False
        all_whitelist = all(
            _is_in_whitelist(fc.get("path", ""))
            for fc in self.file_changes
        )
        return all_whitelist and self.risk_level in (RiskLevel.SAFE, RiskLevel.LOW)

    @property
    def is_rollback_window_open(self) -> bool:
        """24小时回退窗口是否开启"""
        if not self.applied_at:
            return False
        return (time.time() - self.applied_at) < 24 * 3600


# ═══════════════════════════════════════════════════
# Viability Gate（4道门）
# ═══════════════════════════════════════════════════

class ViabilityGate:
    """可行性闸门（4 道门）

    每道门都返回 (passed: bool, details: dict)
    """

    def __init__(
        self,
        project_root: Optional[str] = None,
        backup_dir: Optional[str] = None,
    ) -> None:
        self.project_root = Path(project_root) if project_root else Path(__file__).resolve().parent.parent
        self.backup_dir = Path(backup_dir) if backup_dir else self.project_root / "data" / "evolution_backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    # ── Gate 1: 安全审查 ───────────────────────────

    def gate1_security_review(self, proposal: EvolutionProposal) -> tuple[bool, dict]:
        """Gate 1: 安全审查

        检查：
        - 修改文件范围
        - 风险等级
        - 敏感内容检测
        """
        issues: list[str] = []
        warnings: list[str] = []

        for fc in proposal.file_changes:
            path = fc.get("path", "")
            diff = fc.get("diff", "") or fc.get("new_content", "") or ""

            # 越界路径（绝对/盘符/`../` 穿越）直接判失败：
            # 只做白名单字符串前缀匹配时这类路径能被误判为"安全"，必须前置拦截
            if _resolve_in_root(self.project_root, path) is None:
                issues.append(f"路径越界，拒绝: {path}")
                continue

            # 检查是否为核心安全模块
            if _is_core_module(path):
                if "tool_isolation" in path or "prompt_injection" in path or "sandbox" in path:
                    issues.append(f"触碰核心安全模块: {path}")
                else:
                    warnings.append(f"触碰核心模块（需人工审批）: {path}")

            # 敏感模式检测
            found_patterns = []
            for pattern in SENSITIVE_PATTERNS:
                if pattern in diff:
                    found_patterns.append(pattern)
            if found_patterns:
                warnings.append(f"检测到敏感模式: {found_patterns}")

        # 安全审查通过条件：没有任何 issue（核心安全模块 / 越界路径）
        passed = not issues

        result = {
            "passed": passed,
            "issues": issues,
            "warnings": warnings,
            "risk_level": proposal.risk_level.value,
            "can_auto_apply": proposal.can_auto_apply,
            "files_modified": len(proposal.file_changes),
        }

        proposal.gate_results["gate1"] = result
        if passed:
            proposal.status = EvolutionStatus.GATE1_PASSED
        else:
            proposal.status = EvolutionStatus.GATE1_FAILED

        return passed, result

    # ── Gate 2: 语法检查 ───────────────────────────

    def gate2_syntax_check(self, proposal: EvolutionProposal) -> tuple[bool, dict]:
        """Gate 2: 语法检查

        对每个修改的 Python 文件做语法验证。
        """
        issues: list[str] = []
        files_checked = 0
        files_passed = 0

        for fc in proposal.file_changes:
            path = fc.get("path", "")
            if not path.endswith(".py"):
                continue

            files_checked += 1
            new_content = fc.get("new_content", "")
            if not new_content:
                # 如果是删除文件，跳过语法检查
                if fc.get("action") == "delete":
                    files_passed += 1
                    continue
                issues.append(f"{path}: 新内容为空")
                continue

            try:
                compile(new_content, path, "exec")
                files_passed += 1
            except SyntaxError as e:
                issues.append(f"{path}: 语法错误 - {e}")
            except Exception as e:
                issues.append(f"{path}: 编译异常 - {e}")

        passed = files_checked == 0 or files_passed == files_checked

        result = {
            "passed": passed,
            "files_checked": files_checked,
            "files_passed": files_passed,
            "issues": issues,
        }

        proposal.gate_results["gate2"] = result
        if passed:
            proposal.status = EvolutionStatus.GATE2_PASSED
        else:
            proposal.status = EvolutionStatus.GATE2_FAILED

        return passed, result

    # ── Gate 3: 测试验证 ───────────────────────────

    def gate3_test_verify(
        self,
        proposal: EvolutionProposal,
        test_command: Optional[str] = None,
    ) -> tuple[bool, dict]:
        """Gate 3: 测试验证

        没有测试命令时必须判为「未验证」而非通过：模型给的命令串本身不可信，
        而"没命令就放行"等于把 Gate3 变成摆设，自动应用通道必须至少跑过一次真实验证。
        有命令时也只按参数列表执行（不再经过 shell），杜绝命令注入。
        """
        issues: list[str] = []
        verified = False
        test_passed = False
        test_output = ""

        if test_command:
            try:
                import subprocess
                # 不用 shell=True：模型给的字符串只能拆成参数列表执行
                argv = test_command.split()
                executable = Path(argv[0]).name.lower() if argv else ""
                if executable not in _ALLOWED_TEST_EXECUTABLES:
                    issues.append(f"测试命令不在允许的执行器白名单内: {argv[0] if argv else ''}")
                else:
                    result = subprocess.run(
                        argv,
                        shell=False,
                        capture_output=True,
                        text=True,
                        timeout=120,
                        cwd=str(self.project_root),
                    )
                    verified = True
                    test_passed = result.returncode == 0
                    test_output = result.stdout[-500:] if result.stdout else result.stderr[-500:]
                    if not test_passed:
                        issues.append(f"测试失败: {test_output[:200]}")
            except subprocess.TimeoutExpired:
                issues.append("测试超时（>120s）")
            except Exception as e:
                issues.append(f"测试运行失败: {e}")
        else:
            # 无测试命令 → 明确的未验证状态，不满足自动应用条件
            issues.append("未指定测试命令：未验证，不满足自动应用条件")

        passed = verified and test_passed

        result = {
            "passed": passed,
            "verified": verified,
            "skipped": test_command is None,
            "issues": issues,
            "output_preview": test_output[:300] if test_output else "",
        }

        proposal.gate_results["gate3"] = result
        if passed:
            proposal.status = EvolutionStatus.GATE3_PASSED
        else:
            proposal.status = EvolutionStatus.GATE3_FAILED

        return passed, result

    # ── Gate 4: 回滚准备 ───────────────────────────

    def gate4_rollback_prep(self, proposal: EvolutionProposal) -> tuple[bool, dict]:
        """Gate 4: 回滚准备

        创建备份文件，确保可以回滚。
        """
        issues: list[str] = []
        backup_path = self.backup_dir / f"proposal_{proposal.proposal_id}"
        backup_path.mkdir(parents=True, exist_ok=True)

        files_backed_up = 0
        root = self.project_root.resolve()

        for fc in proposal.file_changes:
            path = fc.get("path", "")
            action = fc.get("action", "modify")
            # 越界路径不能备份也不能应用，直接判失败（否则备份/写入会落到项目外）
            full_path = _resolve_in_root(self.project_root, path)
            if full_path is None:
                issues.append(f"路径越界，拒绝: {path}")
                continue
            rel_path = full_path.relative_to(root)

            try:
                if action in ("modify", "delete") and full_path.exists():
                    # 备份原文件
                    backup_file = backup_path / rel_path
                    backup_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(full_path), str(backup_file))
                    files_backed_up += 1
                elif action == "create":
                    # 新建文件：记录标记，回滚时删除
                    marker = backup_path / (str(rel_path) + ".newfile_marker")
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    marker.write_text(f"created by proposal {proposal.proposal_id}")
                    files_backed_up += 1
            except Exception as e:
                issues.append(f"备份失败 {path}: {e}")

        passed = len(issues) == 0 and files_backed_up >= len(proposal.file_changes)

        result = {
            "passed": passed,
            "backup_path": str(backup_path),
            "files_backed_up": files_backed_up,
            "total_files": len(proposal.file_changes),
            "issues": issues,
        }

        proposal.gate_results["gate4"] = result
        if passed:
            proposal.status = EvolutionStatus.GATE4_PASSED
        else:
            proposal.status = EvolutionStatus.GATE4_FAILED

        return passed, result

    # ── 4 道门连跑 ─────────────────────────────────

    def run_all_gates(
        self,
        proposal: EvolutionProposal,
        test_command: Optional[str] = None,
    ) -> tuple[bool, dict]:
        """依次运行 4 道门。

        Returns:
            (all_passed, summary_dict)
        """
        g1_ok, g1_result = self.gate1_security_review(proposal)
        if not g1_ok:
            return False, {"failed_at": "gate1", **g1_result}

        g2_ok, g2_result = self.gate2_syntax_check(proposal)
        if not g2_ok:
            return False, {"failed_at": "gate2", **g2_result}

        g3_ok, g3_result = self.gate3_test_verify(proposal, test_command)
        if not g3_ok:
            return False, {"failed_at": "gate3", **g3_result}

        g4_ok, g4_result = self.gate4_rollback_prep(proposal)
        if not g4_ok:
            return False, {"failed_at": "gate4", **g4_result}

        return True, {
            "all_passed": True,
            "gate1": g1_result,
            "gate2": g2_result,
            "gate3": g3_result,
            "gate4": g4_result,
        }


# ═══════════════════════════════════════════════════
# Archive（归档与执行）
# ═══════════════════════════════════════════════════

class EvolutionArchive:
    """自进化归档管理器

    负责：
    - 提案存储与检索
    - 应用修改
    - 回滚操作
    - 24h 回退窗口管理
    - Journal 日志
    """

    def __init__(
        self,
        project_root: Optional[str] = None,
        archive_dir: Optional[str] = None,
    ) -> None:
        self.project_root = Path(project_root) if project_root else Path(__file__).resolve().parent.parent
        self.archive_dir = Path(archive_dir) if archive_dir else self.project_root / "data" / "evolution_archive"
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.journal_path = self.archive_dir / "evolution_journal.jsonl"
        self._proposals: dict[str, EvolutionProposal] = {}
        self._load_journal()

    def _load_journal(self) -> None:
        """加载历史日志"""
        if not self.journal_path.exists():
            return
        try:
            with open(self.journal_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        pid = entry.get("proposal_id")
                        if pid:
                            # 重建完整提案：file_changes/gate_results 必须一起恢复，
                            # 否则重启后既复现不了原始文件集合（pending 审批失效），
                            # 也回滚不了已应用的提案；时间戳缺失还会误判 24h 回退窗口。
                            p = EvolutionProposal(
                                proposal_id=pid,
                                title=entry.get("title", ""),
                                description=entry.get("description", ""),
                                file_changes=entry.get("file_changes") or [],
                                status=EvolutionStatus(entry.get("status", "proposed")),
                                created_at=entry.get("created_at", 0),
                                applied_at=entry.get("applied_at"),
                                rolled_back_at=entry.get("rolled_back_at"),
                                risk_level=RiskLevel(entry.get("risk_level", "safe")),
                                gate_results=entry.get("gate_results") or {},
                                author=entry.get("author", "ai_self_evolve"),
                            )
                            self._proposals[pid] = p
                    except Exception:
                        continue
        except Exception:
            logger.exception("Failed to load evolution journal")

    def _journal_append(self, event: str, proposal: EvolutionProposal, **extra) -> None:
        """追加日志

        写入的是完整提案快照（含 file_changes / gate_results / 各时间戳），
        重启后 _load_journal 才能原样复现，而不是只剩一个空壳状态。
        """
        entry = {
            "event": event,
            "proposal_id": proposal.proposal_id,
            "title": proposal.title,
            "description": proposal.description,
            "status": proposal.status.value,
            "risk_level": proposal.risk_level.value,
            "file_changes": proposal.file_changes,
            "gate_results": proposal.gate_results,
            "created_at": proposal.created_at,
            "applied_at": proposal.applied_at,
            "rolled_back_at": proposal.rolled_back_at,
            "author": proposal.author,
            "timestamp": time.time(),
            **extra,
        }
        try:
            with open(self.journal_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            logger.exception("Failed to write evolution journal")

    def store_proposal(self, proposal: EvolutionProposal) -> None:
        """存储提案"""
        self._proposals[proposal.proposal_id] = proposal
        self._journal_append("proposal_created", proposal)

    def get_proposal(self, proposal_id: str) -> Optional[EvolutionProposal]:
        """获取提案"""
        return self._proposals.get(proposal_id)

    def list_proposals(
        self,
        status: Optional[EvolutionStatus] = None,
        limit: int = 50,
    ) -> list[EvolutionProposal]:
        """列出提案"""
        props = list(self._proposals.values())
        if status:
            props = [p for p in props if p.status == status]
        props.sort(key=lambda p: p.created_at, reverse=True)
        return props[:limit]

    def apply_proposal(self, proposal: EvolutionProposal) -> tuple[bool, str]:
        """应用提案（修改文件）

        多文件必须原子化：先把全部新内容写到目标同目录的临时文件，全部就绪后才
        os.replace 到位；任何一步失败都把已替换的文件还原，绝不留下半套修改。
        """
        if proposal.status != EvolutionStatus.GATE4_PASSED:
            return False, f"提案状态错误: {proposal.status.value}（需先通过 4 道门）"

        # 确保提案已存储
        if proposal.proposal_id not in self._proposals:
            self.store_proposal(proposal)

        # ── 阶段一：解析路径并写临时文件（此时还没动任何真实文件）──
        plan: list[tuple[str, Path, Optional[Path]]] = []
        try:
            for fc in proposal.file_changes:
                path = fc.get("path", "")
                action = fc.get("action", "modify")
                target = _resolve_in_root(self.project_root, path)
                if target is None:
                    raise ValueError(f"路径越界，拒绝应用: {path}")

                if action == "delete":
                    plan.append((action, target, None))
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = target.with_name(f"{target.name}.l4tmp_{proposal.proposal_id}")
                tmp_path.write_text(fc.get("new_content", ""), encoding="utf-8")
                plan.append((action, target, tmp_path))
        except Exception as e:
            for _, _, tmp_path in plan:
                if tmp_path is not None:
                    _silent_unlink(tmp_path)
            self._journal_append("apply_failed", proposal, error=str(e))
            return False, f"应用失败: {e}"

        # ── 阶段二：替换；先记下原内容，失败时按逆序还原 ──
        undo: list[tuple[Path, Optional[bytes]]] = []
        try:
            for action, target, tmp_path in plan:
                undo.append((target, target.read_bytes() if target.exists() else None))
                if action == "delete":
                    if target.exists():
                        target.unlink()
                elif tmp_path is not None:
                    os.replace(str(tmp_path), str(target))
        except Exception as e:
            for target, original in reversed(undo):
                try:
                    if original is None:
                        # 原本不存在 → 删掉半成品
                        _silent_unlink(target)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(original)
                except Exception:
                    logger.exception("L4 应用失败后还原文件出错: %s", target)
            for _, _, tmp_path in plan:
                if tmp_path is not None:
                    _silent_unlink(tmp_path)
            self._journal_append("apply_failed", proposal, error=str(e))
            return False, f"应用失败（已回滚）: {e}"

        proposal.status = EvolutionStatus.APPLIED
        proposal.applied_at = time.time()
        self._journal_append("proposal_applied", proposal)
        return True, "应用成功"

    def rollback_proposal(self, proposal_id: str) -> tuple[bool, str]:
        """回滚提案"""
        proposal = self._proposals.get(proposal_id)
        if not proposal:
            return False, f"提案不存在: {proposal_id}"

        if proposal.status != EvolutionStatus.APPLIED:
            return False, f"提案状态错误: {proposal.status.value}（只能回滚已应用的提案）"

        if not proposal.is_rollback_window_open:
            return False, "已超过 24 小时回退窗口"

        try:
            backup_path = self.project_root / "data" / "evolution_backups" / f"proposal_{proposal_id}"
            if not backup_path.exists():
                return False, f"备份不存在: {backup_path}"

            # 恢复文件
            root = self.project_root.resolve()
            for fc in proposal.file_changes:
                path = fc.get("path", "")
                action = fc.get("action", "modify")
                full_path = _resolve_in_root(self.project_root, path)
                if full_path is None:
                    return False, f"路径越界，拒绝回滚: {path}"
                rel_path = full_path.relative_to(root)
                backup_file = backup_path / rel_path
                newfile_marker = backup_path / (str(rel_path) + ".newfile_marker")

                if action in ("modify", "delete") and backup_file.exists():
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(backup_file), str(full_path))

                elif action == "create" and newfile_marker.exists():
                    # 新建的文件，回滚时删除
                    if full_path.exists():
                        full_path.unlink()

            proposal.status = EvolutionStatus.ROLLED_BACK
            proposal.rolled_back_at = time.time()
            self._journal_append("proposal_rolled_back", proposal)
            return True, "回滚成功"

        except Exception as e:
            self._journal_append("rollback_failed", proposal, error=str(e))
            return False, f"回滚失败: {e}"

    def stats(self) -> dict:
        """统计信息"""
        total = len(self._proposals)
        applied = sum(1 for p in self._proposals.values() if p.status == EvolutionStatus.APPLIED)
        rolled_back = sum(1 for p in self._proposals.values() if p.status == EvolutionStatus.ROLLED_BACK)
        pending = sum(1 for p in self._proposals.values() if p.status == EvolutionStatus.PENDING_REVIEW)
        failed = sum(1 for p in self._proposals.values() if "failed" in p.status.value)

        return {
            "total": total,
            "applied": applied,
            "rolled_back": rolled_back,
            "pending_review": pending,
            "failed": failed,
            "success_rate": round(applied / max(total, 1), 2),
            "rollback_count": rolled_back,
            "in_rollback_window": sum(
                1 for p in self._proposals.values()
                if p.status == EvolutionStatus.APPLIED and p.is_rollback_window_open
            ),
        }


# ═══════════════════════════════════════════════════
# 统一 L4 自进化控制器
# ═══════════════════════════════════════════════════

class L4SelfEvolution:
    """L4 自进化控制器（沙箱自动进化模式）

    工作流程：
    1. 创建提案
    2. 运行 4 道门
    3. 白名单 + 低风险 → 自动应用
    4. 核心模块 → 人工审批
    5. 24h 内可回滚
    """

    def __init__(
        self,
        project_root: Optional[str] = None,
        auto_apply: bool = True,
    ) -> None:
        self.gate = ViabilityGate(project_root=project_root)
        self.archive = EvolutionArchive(project_root=project_root)
        self.auto_apply = auto_apply
        self._proposal_counter = 0

    def create_proposal(
        self,
        title: str,
        file_changes: list[dict],
        description: str = "",
        author: str = "ai_self_evolve",
    ) -> EvolutionProposal:
        """创建一个新的自进化提案"""
        self._proposal_counter += 1
        timestamp = int(time.time())
        pid = f"evo_{timestamp}_{self._proposal_counter:04d}"

        # 合并所有 diff 内容用于风险评估
        all_diff = "\n".join(
            fc.get("diff", "") or fc.get("new_content", "") or ""
            for fc in file_changes
        )

        # 评估整体风险（取最高风险的文件）
        risk = RiskLevel.SAFE
        for fc in file_changes:
            file_risk = _assess_risk(
                fc.get("path", ""),
                fc.get("diff", "") or fc.get("new_content", "") or "",
            )
            if _RISK_ORDER[file_risk] > _RISK_ORDER[risk]:
                risk = file_risk

        proposal = EvolutionProposal(
            proposal_id=pid,
            title=title,
            description=description,
            file_changes=file_changes,
            risk_level=risk,
            author=author,
        )

        self.archive.store_proposal(proposal)
        return proposal

    async def process_proposal(
        self,
        proposal: EvolutionProposal,
        test_command: Optional[str] = None,
    ) -> dict:
        """处理提案（跑 4 道门 + 自动应用/待审批）"""
        result = {
            "proposal_id": proposal.proposal_id,
            "title": proposal.title,
            "risk_level": proposal.risk_level.value,
            "can_auto_apply": proposal.can_auto_apply,
        }

        # 运行 4 道门
        all_passed, gate_summary = self.gate.run_all_gates(proposal, test_command)
        result["gates"] = gate_summary

        if not all_passed:
            result["action"] = "blocked"
            result["reason"] = gate_summary.get("failed_at", "unknown")
            return result

        # 通过 4 道门
        if proposal.can_auto_apply and self.auto_apply:
            # 白名单 + 低风险 → 自动应用
            applied, msg = self.archive.apply_proposal(proposal)
            result["action"] = "auto_applied" if applied else "apply_failed"
            result["apply_message"] = msg
        else:
            # 核心模块或高风险 → 人工审批
            proposal.status = EvolutionStatus.PENDING_REVIEW
            result["action"] = "pending_review"
            result["reason"] = "核心模块或高风险修改，需人工审批"
            self.archive._journal_append("pending_review", proposal)

        return result

    def approve_and_apply(self, proposal_id: str) -> tuple[bool, str]:
        """人工审批并应用"""
        proposal = self.archive.get_proposal(proposal_id)
        if not proposal:
            return False, f"提案不存在: {proposal_id}"

        if proposal.status != EvolutionStatus.PENDING_REVIEW:
            return False, f"提案状态错误: {proposal.status.value}"

        proposal.status = EvolutionStatus.APPROVED
        self.archive._journal_append("proposal_approved", proposal)

        # 人工审批视同通过所有 gate，先做回滚准备
        ok4, _ = self.gate.gate4_rollback_prep(proposal)
        if not ok4:
            return False, "回滚准备失败"

        proposal.status = EvolutionStatus.GATE4_PASSED
        return self.archive.apply_proposal(proposal)

    def reject_proposal(self, proposal_id: str, reason: str = "") -> tuple[bool, str]:
        """拒绝提案"""
        proposal = self.archive.get_proposal(proposal_id)
        if not proposal:
            return False, f"提案不存在: {proposal_id}"

        proposal.status = EvolutionStatus.REJECTED
        self.archive._journal_append("proposal_rejected", proposal, reason=reason)
        return True, "已拒绝"

    def rollback(self, proposal_id: str) -> tuple[bool, str]:
        """回滚提案"""
        return self.archive.rollback_proposal(proposal_id)

    def get_stats(self) -> dict:
        """获取统计信息"""
        return self.archive.stats()
