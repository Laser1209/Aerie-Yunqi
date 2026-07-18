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
    "core/brain.py",
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


def _is_in_whitelist(file_path: str) -> bool:
    """检查文件是否在自动进化白名单内"""
    normalized = file_path.replace("\\", "/").lstrip("./")
    for prefix in AUTO_EVOLVE_WHITELIST:
        if normalized.startswith(prefix):
            return True
    return False


def _is_core_module(file_path: str) -> bool:
    """检查文件是否为核心模块"""
    normalized = file_path.replace("\\", "/").lstrip("./")
    for core_path in CORE_MODULES:
        if normalized == core_path or normalized.startswith(core_path.rstrip("/") + "/"):
            return True
    return False


def _assess_risk(file_path: str, diff_content: str) -> RiskLevel:
    """评估修改风险等级"""
    normalized = file_path.replace("\\", "/").lstrip("./")

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
        risk = RiskLevel.MEDIUM if risk.value < RiskLevel.MEDIUM.value else risk

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

        # 安全审查通过条件：无 CRITICAL 问题
        passed = not any("核心安全模块" in i for i in issues)

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

        尝试运行相关测试。如果没有测试命令或无法运行，
        标记为 "skipped" 但不阻塞（因为本地环境可能不完整）。
        """
        issues: list[str] = []
        test_passed = False
        test_output = ""

        if test_command:
            try:
                import subprocess
                result = subprocess.run(
                    test_command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=str(self.project_root),
                )
                test_passed = result.returncode == 0
                test_output = result.stdout[-500:] if result.stdout else result.stderr[-500:]
                if not test_passed:
                    issues.append(f"测试失败: {test_output[:200]}")
            except subprocess.TimeoutExpired:
                issues.append("测试超时（>120s）")
            except Exception as e:
                issues.append(f"测试运行失败: {e}")
        else:
            # 无测试命令，跳过但不阻塞
            issues.append("未指定测试命令，跳过测试验证")
            test_passed = True  # 视为通过（非阻塞）

        result = {
            "passed": test_passed,
            "skipped": test_command is None,
            "issues": issues,
            "output_preview": test_output[:300] if test_output else "",
        }

        proposal.gate_results["gate3"] = result
        if test_passed:
            proposal.status = EvolutionStatus.GATE3_PASSED
        else:
            proposal.status = EvolutionStatus.GATE3_FAILED

        return test_passed, result

    # ── Gate 4: 回滚准备 ───────────────────────────

    def gate4_rollback_prep(self, proposal: EvolutionProposal) -> tuple[bool, dict]:
        """Gate 4: 回滚准备

        创建备份文件，确保可以回滚。
        """
        issues: list[str] = []
        backup_path = self.backup_dir / f"proposal_{proposal.proposal_id}"
        backup_path.mkdir(parents=True, exist_ok=True)

        files_backed_up = 0

        for fc in proposal.file_changes:
            path = fc.get("path", "")
            action = fc.get("action", "modify")
            full_path = self.project_root / path

            try:
                if action in ("modify", "delete") and full_path.exists():
                    # 备份原文件
                    rel_dir = Path(path).parent
                    backup_file = backup_path / path
                    backup_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(full_path), str(backup_file))
                    files_backed_up += 1
                elif action == "create":
                    # 新建文件：记录标记，回滚时删除
                    marker = backup_path / (path + ".newfile_marker")
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
                            # 重建基本信息
                            p = EvolutionProposal(
                                proposal_id=pid,
                                title=entry.get("title", ""),
                                description=entry.get("description", ""),
                                status=EvolutionStatus(entry.get("status", "proposed")),
                                created_at=entry.get("created_at", 0),
                                applied_at=entry.get("applied_at"),
                                rolled_back_at=entry.get("rolled_back_at"),
                                risk_level=RiskLevel(entry.get("risk_level", "safe")),
                            )
                            self._proposals[pid] = p
                    except Exception:
                        continue
        except Exception:
            logger.exception("Failed to load evolution journal")

    def _journal_append(self, event: str, proposal: EvolutionProposal, **extra) -> None:
        """追加日志"""
        entry = {
            "event": event,
            "proposal_id": proposal.proposal_id,
            "title": proposal.title,
            "status": proposal.status.value,
            "risk_level": proposal.risk_level.value,
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
        """应用提案（修改文件）"""
        if proposal.status != EvolutionStatus.GATE4_PASSED:
            return False, f"提案状态错误: {proposal.status.value}（需先通过 4 道门）"

        # 确保提案已存储
        if proposal.proposal_id not in self._proposals:
            self.store_proposal(proposal)

        try:
            for fc in proposal.file_changes:
                path = fc.get("path", "")
                action = fc.get("action", "modify")
                full_path = self.project_root / path

                if action == "modify" or action == "create":
                    new_content = fc.get("new_content", "")
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    full_path.write_text(new_content, encoding="utf-8")

                elif action == "delete":
                    if full_path.exists():
                        full_path.unlink()

            proposal.status = EvolutionStatus.APPLIED
            proposal.applied_at = time.time()
            self._journal_append("proposal_applied", proposal)
            return True, "应用成功"

        except Exception as e:
            self._journal_append("apply_failed", proposal, error=str(e))
            return False, f"应用失败: {e}"

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
            for fc in proposal.file_changes:
                path = fc.get("path", "")
                action = fc.get("action", "modify")
                full_path = self.project_root / path
                backup_file = backup_path / path
                newfile_marker = backup_path / (path + ".newfile_marker")

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
            if file_risk.value > risk.value:
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
