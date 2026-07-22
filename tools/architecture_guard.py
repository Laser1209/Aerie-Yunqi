"""P2-00 架构守护风险测试 — 静态边界扫描器.

本脚本对 Aerie 主应用代码树执行四项架构不变量检查，对应 ADR-P2-001
「验证与证据」与主计划 R-01「架构守护测试」的要求：

  RULE-001  单一主链       — core/ 下仅允许一个生产 Pipeline / ContextBuilder
                              类定义；禁止 pipeline_v2.py 等平行实现文件；
                              Companion 是唯一组合根。
  RULE-002  跨库所有权      — world_service/ 不得 import core.database；
                              core/ 业务模块不得直接读写 world.db。
  RULE-003  World 副作用边界 — world_service/ 不得 import qq_client / send_queue
                              / 图片 Provider / 通知 / 系统命令工具。
  RULE-004  Renderer→Sidecar — electron/src/renderer/ 不得硬编码 sidecar
                              endpoint（127.0.0.1:7890 / localhost:PORT），
                              应通过 preload.js 暴露的 window.aerie IPC 桥接。

严重级别:
  ERROR    — 硬架构不变量违规（RULE-001 ~ RULE-003），exit 1。
  WARNING  — 架构债务 / 潜在风险（RULE-004），exit 0 但报告列出。

扫描范围显式排除:
  Spotlight/  .codex-deploy-aerie-spotlight/  android-client/
  documents/Android/  .codex-temp/  node_modules/  __pycache__/
  electron/_tmp_asar*  tests/  (测试桩中的 Pipeline/ContextBuilder 合法)

用法:
  python tools/architecture_guard.py            # 扫描 + 报告
  python tools/architecture_guard.py --json     # 机器可读 JSON 输出
  python tools/architecture_guard.py --root PATH # 指定项目根
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence

# ─── 常量 ────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent

# 显式扫描目标目录 — 只检查架构关键模块，避免遍历 .venv/models/NapCat 等无关目录
SCAN_PY_DIRS: tuple[str, ...] = (
    "core",
    "world_service",
    "communication",
    "config",
    "tools",
)
SCAN_JS_DIR = "electron/src/renderer"

# 排除子目录（在扫描目标内部进一步排除）
EXCLUDED_SUBDIRS: frozenset[str] = frozenset({
    "__pycache__",
    "node_modules",
    "vendor",
    "_tmp_asar",
})

# 扫描的文件扩展名
PY_EXTS = {".py"}
JS_EXTS = {".js", ".mjs", ".cjs"}

# ─── RULE-001: 单一主链 ─────────────────────────────────────────────

# 允许定义 Pipeline / ContextBuilder 类的文件（相对 ROOT posix 路径）
ALLOWED_PIPELINE_FILES = {"core/pipeline.py"}
ALLOWED_CONTEXT_BUILDER_FILES = {"core/context_builder.py"}

# 禁止存在的平行实现文件名模式
FORBIDDEN_V2_PATTERNS = [
    re.compile(r"pipeline_v\d+\.py$", re.IGNORECASE),
    re.compile(r"context_builder_v\d+\.py$", re.IGNORECASE),
    re.compile(r"pipeline_new\.py$", re.IGNORECASE),
    re.compile(r"context_builder_new\.py$", re.IGNORECASE),
]

# 组合根：Companion 类应在 core/companion.py 中实例化 Pipeline
COMPOSITION_ROOT = "core/companion.py"
PIPELINE_INSTANTIATION = re.compile(r"=\s*Pipeline\s*\(")
CONTEXT_BUILDER_INSTANTIATION = re.compile(r"=\s*ContextBuilder\s*\(")

# ─── RULE-002: 跨库所有权 ───────────────────────────────────────────

# world_service 不得 import 的 core 模块
WORLD_FORBIDDEN_CORE_IMPORTS = [
    "core.database",
    "core.db",
    "core.pipeline",
    "core.context_builder",
    "core.companion",
]

# core/ 不得直接操作 world.db 的模式（排除注释行）
WORLD_DB_WRITE_PATTERN = re.compile(
    r'(?:sqlite3\.connect|open)\s*\(\s*[^)]*world\.db',
    re.IGNORECASE,
)
WORLD_DB_DML_PATTERN = re.compile(
    r'world\.db.*(?:INSERT|UPDATE|DELETE|CREATE TABLE|DROP)',
    re.IGNORECASE,
)

# ─── RULE-003: World 副作用边界 ─────────────────────────────────────

WORLD_FORBIDDEN_SIDE_EFFECT_IMPORTS = [
    "communication.qq_client",
    "communication.send_queue",
    "qq_client",
    "send_queue",
    "image_provider",
    "notification",
    "notifier",
]

WORLD_FORBIDDEN_OS_CALLS = [
    re.compile(r"\bos\.system\b"),
    re.compile(r"\bsubprocess\.(?:run|call|Popen|check_output)\b"),
]

# ─── RULE-004: Renderer→Sidecar 直连 ────────────────────────────────

# renderer 中禁止硬编码的 sidecar 端点模式
SIDECAR_URL_PATTERN = re.compile(
    r'(?:https?://)?(?:127\.0\.0\.1|localhost)[:/]\d{4,5}',
    re.IGNORECASE,
)

SCAN_JS_DIR = "electron/src/renderer"

# ─── 数据结构 ────────────────────────────────────────────────────────


@dataclass
class Violation:
    """单条架构违规记录。"""

    rule_id: str
    severity: str  # "ERROR" | "WARNING"
    file: str
    line: int
    message: str


@dataclass
class GuardReport:
    """守护扫描报告。"""

    violations: list[Violation] = field(default_factory=list)
    files_scanned: int = 0
    rules_checked: list[str] = field(default_factory=lambda: [
        "RULE-001", "RULE-002", "RULE-003", "RULE-004",
    ])

    @property
    def errors(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "ERROR"]

    @property
    def warnings(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "WARNING"]

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "files_scanned": self.files_scanned,
            "total_violations": len(self.violations),
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "violations": [asdict(v) for v in self.violations],
        }


# ─── 工具函数 ────────────────────────────────────────────────────────


def _is_excluded_segment(path: Path) -> bool:
    """判断文件路径中是否包含排除的子目录段。"""
    parts = set(path.parts)
    return bool(parts & EXCLUDED_SUBDIRS)


def _iter_py_files(root: Path) -> list[Path]:
    """遍历架构关键目录中的 Python 源文件。"""
    result: list[Path] = []
    for subdir in SCAN_PY_DIRS:
        base = root / subdir
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if _is_excluded_segment(path):
                continue
            result.append(path)
    return result


def _iter_js_files(root: Path, subdir: str | None = None) -> list[Path]:
    """遍历 renderer 目录中的 JS 源文件。"""
    target = subdir or SCAN_JS_DIR
    base = root / target
    if not base.is_dir():
        return []
    result: list[Path] = []
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in JS_EXTS:
            continue
        if _is_excluded_segment(path):
            continue
        result.append(path)
    return result


def _read_lines(path: Path) -> list[str]:
    """安全读取文件行（UTF-8 / GBK 回退）。"""
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            return path.read_text(encoding=encoding).splitlines()
        except (UnicodeDecodeError, OSError):
            continue
    return []


def _strip_comment(line: str) -> str:
    """去除 Python 行注释（粗略，用于 RULE-002 注释豁免）。"""
    # 不处理字符串内的 #，对静态扫描足够
    idx = line.find("#")
    if idx >= 0:
        return line[:idx]
    return line


# ─── RULE-001: 单一主链 ─────────────────────────────────────────────

_PIPELINE_CLASS_RE = re.compile(r"^\s*class\s+Pipeline\b")
_CONTEXT_BUILDER_CLASS_RE = re.compile(r"^\s*class\s+ContextBuilder\b")


def check_single_main_chain(root: Path) -> list[Violation]:
    """RULE-001: core/ 下仅允许一个生产 Pipeline / ContextBuilder 定义。

    同时禁止 pipeline_v2.py 等平行实现文件，并验证 Companion 是组合根。
    """
    violations: list[Violation] = []

    # 1. 扫描所有 .py 文件中的 class Pipeline / class ContextBuilder 定义
    for path in _iter_py_files(root):
        rel = path.relative_to(root).as_posix()
        lines = _read_lines(path)
        for i, line in enumerate(lines, 1):
            if _PIPELINE_CLASS_RE.match(line):
                if rel not in ALLOWED_PIPELINE_FILES:
                    violations.append(Violation(
                        rule_id="RULE-001",
                        severity="ERROR",
                        file=rel,
                        line=i,
                        message=f"Pipeline 类定义出现在非授权文件 {rel}（仅允许 {', '.join(ALLOWED_PIPELINE_FILES)}）",
                    ))
            if _CONTEXT_BUILDER_CLASS_RE.match(line):
                if rel not in ALLOWED_CONTEXT_BUILDER_FILES:
                    violations.append(Violation(
                        rule_id="RULE-001",
                        severity="ERROR",
                        file=rel,
                        line=i,
                        message=f"ContextBuilder 类定义出现在非授权文件 {rel}（仅允许 {', '.join(ALLOWED_CONTEXT_BUILDER_FILES)}）",
                    ))

    # 2. 禁止平行实现文件
    for path in _iter_py_files(root):
        rel = path.relative_to(root).as_posix()
        for pattern in FORBIDDEN_V2_PATTERNS:
            if pattern.search(rel):
                violations.append(Violation(
                    rule_id="RULE-001",
                    severity="ERROR",
                    file=rel,
                    line=1,
                    message=f"禁止的平行实现文件 {rel}（不得存在 v2/new 变体）",
                ))

    # 3. 验证组合根：Companion 在 core/companion.py 中实例化 Pipeline + ContextBuilder
    comp_path = root / COMPOSITION_ROOT
    if comp_path.is_file():
        lines = _read_lines(comp_path)
        has_pipeline = any(PIPELINE_INSTANTIATION.search(line) for line in lines)
        has_context = any(CONTEXT_BUILDER_INSTANTIATION.search(line) for line in lines)
        if not has_pipeline:
            violations.append(Violation(
                rule_id="RULE-001",
                severity="ERROR",
                file=COMPOSITION_ROOT,
                line=0,
                message="组合根 Companion 未实例化 Pipeline（缺失 = Pipeline( 构造）",
            ))
        if not has_context:
            violations.append(Violation(
                rule_id="RULE-001",
                severity="ERROR",
                file=COMPOSITION_ROOT,
                line=0,
                message="组合根 Companion 未实例化 ContextBuilder（缺失 = ContextBuilder( 构造）",
            ))
    else:
        violations.append(Violation(
            rule_id="RULE-001",
            severity="ERROR",
            file=COMPOSITION_ROOT,
            line=0,
            message="组合根文件 core/companion.py 不存在",
        ))

    return violations


# ─── RULE-002: 跨库所有权 ───────────────────────────────────────────

_IMPORT_RE = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))")


def check_cross_ownership(root: Path) -> list[Violation]:
    """RULE-002: world_service/ 不得 import core 关键模块；core/ 不得直接写 world.db。"""
    violations: list[Violation] = []

    # 1. world_service/ 不得 import core.database / core.pipeline 等
    world_dir = root / "world_service"
    if world_dir.is_dir():
        for path in world_dir.rglob("*.py"):
            if _is_excluded_segment(path):
                continue
            rel = path.relative_to(root).as_posix()
            lines = _read_lines(path)
            for i, line in enumerate(lines, 1):
                m = _IMPORT_RE.match(line)
                if not m:
                    continue
                imported = (m.group(1) or m.group(2) or "").strip()
                for forbidden in WORLD_FORBIDDEN_CORE_IMPORTS:
                    if imported == forbidden or imported.startswith(forbidden + "."):
                        violations.append(Violation(
                            rule_id="RULE-002",
                            severity="ERROR",
                            file=rel,
                            line=i,
                            message=f"world_service 不得 import {forbidden}（跨库所有权违规）",
                        ))

    # 2. core/ 不得直接读写 world.db（排除注释）
    core_dir = root / "core"
    if core_dir.is_dir():
        for path in core_dir.rglob("*.py"):
            if _is_excluded_segment(path):
                continue
            rel = path.relative_to(root).as_posix()
            lines = _read_lines(path)
            for i, line in enumerate(lines, 1):
                code = _strip_comment(line)
                if WORLD_DB_WRITE_PATTERN.search(code):
                    violations.append(Violation(
                        rule_id="RULE-002",
                        severity="ERROR",
                        file=rel,
                        line=i,
                        message="core/ 不得直接 sqlite3.connect/open world.db（所有权属于 world_service）",
                    ))
                if WORLD_DB_DML_PATTERN.search(code):
                    violations.append(Violation(
                        rule_id="RULE-002",
                        severity="ERROR",
                        file=rel,
                        line=i,
                        message="core/ 不得直接对 world.db 执行 DML（所有权属于 world_service）",
                    ))

    return violations


# ─── RULE-003: World 副作用边界 ─────────────────────────────────────


def check_world_side_effect_boundary(root: Path) -> list[Violation]:
    """RULE-003: world_service/ 不得 import 通信/图片/通知/系统命令模块。"""
    violations: list[Violation] = []

    world_dir = root / "world_service"
    if not world_dir.is_dir():
        return violations

    for path in world_dir.rglob("*.py"):
        if _is_excluded_segment(path):
            continue
        rel = path.relative_to(root).as_posix()
        lines = _read_lines(path)
        for i, line in enumerate(lines, 1):
            # 检查禁止的 import
            m = _IMPORT_RE.match(line)
            if m:
                imported = (m.group(1) or m.group(2) or "").strip()
                for forbidden in WORLD_FORBIDDEN_SIDE_EFFECT_IMPORTS:
                    if imported == forbidden or imported.startswith(forbidden + "."):
                        violations.append(Violation(
                            rule_id="RULE-003",
                            severity="ERROR",
                            file=rel,
                            line=i,
                            message=f"world_service 不得 import {forbidden}（World 副作用边界违规）",
                        ))

            # 检查禁止的 OS 调用
            code = _strip_comment(line)
            for pattern in WORLD_FORBIDDEN_OS_CALLS:
                if pattern.search(code):
                    violations.append(Violation(
                        rule_id="RULE-003",
                        severity="ERROR",
                        file=rel,
                        line=i,
                        message=f"world_service 不得调用 {pattern.pattern}（World 须无副作用）",
                    ))

    return violations


# ─── RULE-004: Renderer→Sidecar 直连 ────────────────────────────────


def check_renderer_sidecar_boundary(root: Path) -> list[Violation]:
    """RULE-004: renderer 不得硬编码 sidecar endpoint，应通过 IPC 桥接。

    severity=WARNING — 这是架构债务检测，当前存在既有违规，报告但不阻断。
    """
    violations: list[Violation] = []

    renderer_path = root / SCAN_JS_DIR
    if not renderer_path.is_dir():
        return violations

    for path in _iter_js_files(root, SCAN_JS_DIR):
        rel = path.relative_to(root).as_posix()
        lines = _read_lines(path)
        for i, line in enumerate(lines, 1):
            # 跳过 vendor 第三方库
            if "/vendor/" in rel or rel.startswith("electron/src/renderer/vendor/"):
                continue
            if SIDECAR_URL_PATTERN.search(line):
                violations.append(Violation(
                    rule_id="RULE-004",
                    severity="WARNING",
                    file=rel,
                    line=i,
                    message="renderer 硬编码 sidecar endpoint，应通过 window.aerie IPC 桥接访问",
                ))

    return violations


# ─── 主入口 ──────────────────────────────────────────────────────────


def run_all_checks(root: Path) -> GuardReport:
    """执行全部四项架构守护检查，返回报告。"""
    report = GuardReport()

    all_violations: list[Violation] = []
    all_violations.extend(check_single_main_chain(root))
    all_violations.extend(check_cross_ownership(root))
    all_violations.extend(check_world_side_effect_boundary(root))
    all_violations.extend(check_renderer_sidecar_boundary(root))

    report.violations = all_violations

    # 统计扫描文件数
    py_files = _iter_py_files(root)
    js_files = _iter_js_files(root, SCAN_JS_DIR)
    report.files_scanned = len(py_files) + len(js_files)

    return report


def format_report(report: GuardReport) -> str:
    """格式化人类可读报告。"""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("Aerie 架构守护风险测试 — Architecture Guard Report")
    lines.append("=" * 72)
    lines.append(f"扫描文件数: {report.files_scanned}")
    lines.append(f"检查规则: {', '.join(report.rules_checked)}")
    lines.append("")

    if not report.violations:
        lines.append("[PASS] 所有架构不变量检查通过，零违规。")
    else:
        # 按规则分组
        for rule_id in report.rules_checked:
            rule_vs = [v for v in report.violations if v.rule_id == rule_id]
            if not rule_vs:
                lines.append(f"[OK]   {rule_id} — 通过")
                continue
            errors = [v for v in rule_vs if v.severity == "ERROR"]
            warnings = [v for v in rule_vs if v.severity == "WARNING"]
            status = "FAIL" if errors else "WARN"
            lines.append(f"[{status}] {rule_id} — {len(errors)} error(s), {len(warnings)} warning(s)")
            for v in rule_vs:
                lines.append(f"  {v.severity:>7}  {v.file}:{v.line}  {v.message}")
            lines.append("")

    lines.append("-" * 72)
    if report.passed:
        lines.append(f"结果: PASS (0 errors, {len(report.warnings)} warnings)")
    else:
        lines.append(f"结果: FAIL ({len(report.errors)} errors, {len(report.warnings)} warnings)")
    lines.append("=" * 72)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aerie 架构守护风险测试 — 静态边界扫描器",
    )
    parser.add_argument(
        "--root", type=Path, default=ROOT,
        help="项目根目录（默认: 脚本上级目录）",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="输出机器可读 JSON 格式",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    report = run_all_checks(root)

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_report(report))

    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
