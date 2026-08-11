"""Parse importtime.log and generate a Chinese Markdown report.

Reads e:/Agent_reply/importtime.log (produced by boot_trace.ps1) and
writes e:/Agent_reply/Aerie_Obsidian_Vault/boot_trace_data.md.

Usage:
    python scripts/boot_trace_parser.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IMPORTTIME_LOG = PROJECT_ROOT / "importtime.log"
REPORT_MD = PROJECT_ROOT / "Aerie_Obsidian_Vault" / "boot_trace_data.md"
PROBE_DURATION_FILE = PROJECT_ROOT / "boot_probe_duration.tmp"
STDOUT_FILE = PROJECT_ROOT / "boot_stdout.tmp"


def parse_importtime_log(log_path: Path) -> list[dict]:
    """Parse importtime.log into a list of {self_ms, cum_ms, module} dicts."""
    entries: list[dict] = []
    if not log_path.exists():
        return entries
    with log_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.rstrip("\n")
            # Format: "import time:       self_us | cum_us |   module.name"
            parts = line.split("|")
            if len(parts) != 3:
                continue
            head = parts[0].strip()  # "import time:       123"
            if not head.startswith("import time:"):
                continue
            try:
                self_us = int(head.replace("import time:", "").strip())
                cum_us = int(parts[1].strip())
                module = parts[2].strip()
                entries.append({
                    "self_ms": round(self_us / 1000.0, 2),
                    "cum_ms": round(cum_us / 1000.0, 2),
                    "module": module,
                })
            except (ValueError, IndexError):
                continue
    return entries


def categorize(module: str) -> str | None:
    """Map a module name to a heavy-dependency category."""
    cats = [
        ("chromadb",       ["chromadb"]),
        ("onnxruntime",    ["onnxruntime", "onnx"]),
        ("torch",          ["torch"]),
        ("tensorflow",     ["tensorflow"]),
        ("sentence_trans", ["sentence_transformers"]),
        ("sqlalchemy",     ["sqlalchemy", "aiosqlite"]),
        ("fastapi/uvicorn", ["fastapi", "uvicorn", "starlette"]),
        ("pydantic",       ["pydantic"]),
        ("numpy/pandas",   ["numpy", "pandas"]),
        ("httpx/requests", ["httpx", "requests"]),
        ("yaml/toml/dotenv", ["yaml", "toml", "dotenv"]),
        ("aerie_internal", ["core.", "config.", "communication.", "tools.", "world_", "memory."]),
    ]
    for cat, keywords in cats:
        for kw in keywords:
            if kw in module:
                return cat
    return None


def build_report(
    entries: list[dict],
    probe_duration_s: float,
    exit_code: int,
    python_version: str,
) -> str:
    lines: list[str] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    total_self_ms = sum(e["self_ms"] for e in entries)
    top_cum = sorted(entries, key=lambda x: x["cum_ms"], reverse=True)[:30]
    top_self = sorted(entries, key=lambda x: x["self_ms"], reverse=True)[:20]

    # Category totals
    cat_self: dict[str, float] = defaultdict(float)
    cat_count: dict[str, int] = defaultdict(int)
    for e in entries:
        cat = categorize(e["module"])
        if cat:
            cat_self[cat] += e["self_ms"]
            cat_count[cat] += 1

    # Header
    lines.append("# Aerie Import 耗时实测数据")
    lines.append("")
    lines.append(f"> 生成时间: {now}")
    lines.append(f"> 测量方法: `python -X importtime scripts/boot_trace_probe.py 2> importtime.log`")
    lines.append(f"> Python: {python_version}")
    lines.append("> 测量范围: 仅 import 阶段（不含运行时 ChromaDB 初始化、ONNX 模型加载、QQ 连接等业务初始化）")
    lines.append("")

    # Section 1: Overview
    lines.append("## 1. 总览")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|---|---|")
    lines.append(f"| Probe 总耗时 | **{round(probe_duration_s, 2)} 秒** |")
    lines.append(f"| Import 条目数 | {len(entries)} |")
    lines.append(f"| 所有模块 self 累计 | {round(total_self_ms, 0)} ms ≈ {round(total_self_ms / 1000.0, 2)} s |")
    if top_cum:
        lines.append(f"| 最重导入链 | `{top_cum[0]['module']}` ({top_cum[0]['cum_ms']} ms cumulative) |")
    if top_self:
        lines.append(f"| 自身耗时最大模块 | `{top_self[0]['module']}` ({top_self[0]['self_ms']} ms self) |")
    lines.append(f"| Probe 退出码 | {exit_code} |")
    lines.append("")

    # Section 2: Category breakdown
    lines.append("## 2. 重型依赖分类汇总")
    lines.append("")
    lines.append("| 类别 | self 累计 (ms) | 模块数 | 占 self 总比 |")
    lines.append("|---|---|---|---|")
    pct_base = total_self_ms if total_self_ms > 0 else 1
    for cat in sorted(cat_self.keys(), key=lambda k: cat_self[k], reverse=True):
        v = cat_self[cat]
        pct = round(v / pct_base * 100, 1)
        lines.append(f"| {cat} | {round(v, 0)} | {cat_count[cat]} | {pct}% |")
    lines.append("")

    # Section 3: Top 30 by cumulative
    lines.append("## 3. Top 30 慢导入（按累计耗时 cumulative）")
    lines.append("")
    lines.append("> cumulative = 自己 + 所有递归子模块的导入耗时")
    lines.append("")
    lines.append("| # | 累计 (ms) | 自身 (ms) | 模块 |")
    lines.append("|---|---|---|---|")
    for i, e in enumerate(top_cum, 1):
        lines.append(f"| {i} | {e['cum_ms']} | {e['self_ms']} | `{e['module']}` |")
    lines.append("")

    # Section 4: Top 20 by self
    lines.append("## 4. Top 20 自身耗时最重的模块（按 self time）")
    lines.append("")
    lines.append("> self = 仅该模块自己（不含子模块）的导入耗时，反映该模块自身的初始化成本")
    lines.append("")
    lines.append("| # | 自身 (ms) | 累计 (ms) | 模块 |")
    lines.append("|---|---|---|---|")
    for i, e in enumerate(top_self, 1):
        lines.append(f"| {i} | {e['self_ms']} | {e['cum_ms']} | `{e['module']}` |")
    lines.append("")

    # Section 5: Auto-diagnosis
    lines.append("## 5. 关键发现")
    lines.append("")
    findings: list[str] = []
    if probe_duration_s > 5:
        findings.append(f"- ⚠️ **Import 阶段本身就耗时 {round(probe_duration_s, 1)} 秒**，这是启动优化的隐形大头之一")
    if probe_duration_s > 10:
        findings.append(f"- 🔴 Import 耗时 {round(probe_duration_s, 1)}s 已超过 Nielsen 10s 注意力极限")
    for cat in sorted(cat_self.keys(), key=lambda k: cat_self[k], reverse=True):
        v = cat_self[cat]
        if v > 2000:
            findings.append(f"- 🔴 `{cat}` 类 self 累计 {round(v, 0)} ms ({round(v/1000, 1)}s)，强烈建议改为函数内懒加载")
        elif v > 500:
            findings.append(f"- ⚠️ `{cat}` 类 self 累计 {round(v, 0)} ms，可考虑懒加载")
    # Check specific critical modules
    critical_modules = ["chromadb", "onnxruntime", "torch", "sentence_transformers", "sqlalchemy"]
    for cm in critical_modules:
        matching = [e for e in entries if cm in e["module"]]
        if matching:
            worst = max(matching, key=lambda x: x["self_ms"])
            if worst["self_ms"] > 1000:
                findings.append(f"- 🔴 `{worst['module']}` 单模块 self {worst['self_ms']} ms，是启动优化的明确靶点")
    if not findings:
        findings.append("- ✅ Import 阶段无明显瓶颈，启动慢主要来自运行时初始化（QQ 连接、ChromaDB、ONNX 等）")
    lines.extend(findings)
    lines.append("")

    # Section 6: Raw data references
    lines.append("## 6. 原始数据")
    lines.append("")
    lines.append("- 完整日志: [importtime.log](file:///e:/Agent_reply/importtime.log)")
    lines.append("- 探针脚本: [scripts/boot_trace_probe.py](file:///e:/Agent_reply/scripts/boot_trace_probe.py)")
    lines.append("- 测量脚本: [scripts/boot_trace.ps1](file:///e:/Agent_reply/scripts/boot_trace.ps1)")
    lines.append("- 解析脚本: [scripts/boot_trace_parser.py](file:///e:/Agent_reply/scripts/boot_trace_parser.py)")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    if not IMPORTTIME_LOG.exists():
        print(f"[ERROR] {IMPORTTIME_LOG} not found. Run boot_trace.ps1 first.")
        return 1

    entries = parse_importtime_log(IMPORTTIME_LOG)
    if not entries:
        print(f"[ERROR] No entries parsed from {IMPORTTIME_LOG}")
        return 1

    # Read probe duration (written by boot_trace.ps1 with possible BOM)
    probe_duration = 0.0
    if PROBE_DURATION_FILE.exists():
        try:
            # utf-8-sig strips BOM automatically; errors="ignore" for safety
            probe_duration = float(
                PROBE_DURATION_FILE.read_text(encoding="utf-8-sig", errors="ignore").strip()
            )
        except (ValueError, OSError):
            pass

    # Read exit code
    exit_code = 0
    exit_code_file = PROJECT_ROOT / "boot_probe_exitcode.tmp"
    if exit_code_file.exists():
        try:
            exit_code = int(exit_code_file.read_text(encoding="utf-8-sig", errors="ignore").strip())
        except (ValueError, OSError):
            pass

    # Read stdout for confirmation message
    stdout_content = ""
    if STDOUT_FILE.exists():
        stdout_content = STDOUT_FILE.read_text(encoding="utf-8", errors="ignore").strip()

    # Get Python version
    import subprocess
    try:
        py_ver = subprocess.check_output(
            ["C:\\Python314\\python.exe", "-c", "import sys; print(sys.version)"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode("utf-8", errors="ignore").strip()
    except Exception:
        py_ver = "unknown"

    report = build_report(entries, probe_duration, exit_code, py_ver)

    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text(report, encoding="utf-8")

    # Console summary
    print(f"[OK] Parsed {len(entries)} entries")
    print(f"[OK] Probe duration: {round(probe_duration, 2)}s")
    print(f"[OK] Report: {REPORT_MD}")
    print()
    print("Top 5 heaviest (cumulative):")
    top5 = sorted(entries, key=lambda x: x["cum_ms"], reverse=True)[:5]
    for e in top5:
        print(f"  {e['cum_ms']:>8.1f} ms  {e['module']}")
    print()
    print("Top 5 heaviest (self):")
    top5s = sorted(entries, key=lambda x: x["self_ms"], reverse=True)[:5]
    for e in top5s:
        print(f"  {e['self_ms']:>8.1f} ms  {e['module']}")
    print()
    if stdout_content:
        print(f"Probe stdout: {stdout_content}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
