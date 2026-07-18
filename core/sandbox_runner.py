"""Aerie · 云栖 v13.9.8 — Sandbox runner (Phase 9 Batch 6).

Generates a textual *preview* of a proposed new tool, so the user can
see exactly what the tool would do **before** approving it for actual
registration. We do NOT execute any real code here — the sandbox is a
deterministic text generator that:

  1) renders the tool's signature (name + description + parameters)
  2) produces a plausible simulated invocation + output
  3) surfaces risk points (file I/O, network, exec, system call)
  4) gives an overall safety_check verdict

This is the "提议+沙箱预演" compromise the user picked — proposals
must be human-reviewed before they touch the live tool registry.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)


# ── Risk catalogue ─────────────────────────────────
# These are conservative: any tool whose name/description touches one of
# these patterns gets flagged. Reviewers can still approve, but they
# must do it consciously.
_RISK_PATTERNS: list[tuple[str, str]] = [
    (r"\bexec(ute)?\b", "执行任意代码 / arbitrary code execution"),
    (r"\bsubprocess\b", "启动子进程 / spawn child process"),
    (r"\bos\.system\b", "调用系统 shell / shell call"),
    (r"\beval\b", "运行 Python eval / eval()"),
    (r"\bcompile\b", "动态编译代码 / runtime compile"),
    (r"\bwrite_file\b|\bopen\(.*['\"]w['\"]", "写文件 / file write"),
    (r"\bdelete_file\b|\bos\.remove\b|\brmtree\b", "删除文件 / file deletion"),
    (r"\bnetwork\b|\bhttp(s)?://|\bcurl\b|\bwget\b", "网络请求 / network call"),
    (r"\bemail\b|\bsmtp\b", "发送邮件 / email send"),
    (r"\bshell\b", "Shell 操作 / shell operation"),
    (r"\bsudo\b|\badmin\b", "提权 / privilege escalation"),
    (r"\bdatabase\b|\bDROP TABLE\b|\bDELETE FROM\b", "破坏性数据库操作 / destructive DB"),
    (r"\bapi_key\b|\bsecret\b|\btoken\b", "涉及密钥 / secrets involved"),
]

_HIGH_RISK_SAFETY = "high_risk"
_CAUTION_SAFETY = "caution"
_SAFE_SAFETY = "safe"


def _assess_safety(name: str, description: str) -> tuple[str, list[str]]:
    """Return (safety_check, risk_points)."""
    text = (name + " " + description).lower()
    risks: list[str] = []
    for pattern, label in _RISK_PATTERNS:
        if re.search(pattern, text):
            risks.append(label)
    # Deduplicate while preserving order.
    seen: set[str] = set()
    uniq = []
    for r in risks:
        if r in seen:
            continue
        seen.add(r)
        uniq.append(r)
    if uniq:
        verdict = _HIGH_RISK_SAFETY if len(uniq) >= 2 else _CAUTION_SAFETY
    else:
        verdict = _SAFE_SAFETY
    return verdict, uniq


def _fake_invocation(tool_name: str, parameters: dict) -> dict:
    """Build a synthetic sample call. Picks example values by parameter name."""
    example_args: dict[str, Any] = {}
    props = (parameters or {}).get("properties", {}) or {}
    for k, spec in props.items():
        t = (spec.get("type") or "string").lower()
        if t == "string":
            example_args[k] = f"sample_{k}"
        elif t in ("integer", "number"):
            example_args[k] = 1
        elif t == "boolean":
            example_args[k] = False
        elif t == "array":
            example_args[k] = []
        elif t == "object":
            example_args[k] = {}
        else:
            example_args[k] = None
    return example_args


def _fake_output(name: str) -> str:
    """Generate a plausible textual output the tool might return."""
    return ("[simulated] tool '" + name + "' would have run with the sample\n"
            "arguments below. No real side effect was performed. This is a\n"
            "preview only — the tool is not yet registered in the live\n"
            "registry. Review the safety check before approving.")


class SandboxRunner:
    """Stateless text-only sandbox that previews a proposed tool."""

    def __init__(self) -> None:
        self._last_preview: dict | None = None

    @property
    def last_preview(self) -> dict | None:
        return self._last_preview

    def preview(self, tool_spec: dict) -> dict:
        """Generate a sandbox preview for a proposed tool spec.

        Args:
            tool_spec: {"name": str, "description": str, "parameters": dict,
                        "trigger": str, "rationale": str}

        Returns:
            dict with keys: name, description, parameters, simulated_input,
            simulated_output, risk_points, safety_check, requires_approval,
            ts (ms).
        """
        name = (tool_spec.get("name") or "").strip()
        if not name:
            return {
                "ok": False,
                "error": "tool name is required",
                "safety_check": _HIGH_RISK_SAFETY,
            }
        description = (tool_spec.get("description") or "").strip()
        parameters = tool_spec.get("parameters") or {"type": "object", "properties": {}}
        safety, risks = _assess_safety(name, description)
        sample_args = _fake_invocation(name, parameters)

        preview = {
            "ok": True,
            "name": name,
            "description": description,
            "parameters": parameters,
            "trigger": tool_spec.get("trigger") or "",
            "rationale": tool_spec.get("rationale") or "",
            "simulated_input": {
                "tool": name,
                "arguments": sample_args,
            },
            "simulated_output": _fake_output(name),
            "risk_points": risks,
            "safety_check": safety,
            "requires_approval": safety != _SAFE_SAFETY,
            "ts": int(time.time() * 1000),
            "preview_kind": "sandbox-text-v1",
        }
        self._last_preview = preview
        return preview

    def render(self, preview: dict) -> str:
        """Render a preview as a human-readable text block."""
        if not preview.get("ok"):
            return "[sandbox error] " + str(preview.get("error", "unknown"))
        lines: list[str] = []
        lines.append("─" * 56)
        lines.append("工具: " + preview["name"])
        if preview.get("description"):
            lines.append("描述: " + preview["description"])
        if preview.get("rationale"):
            lines.append("为何需要: " + preview["rationale"])
        if preview.get("trigger"):
            lines.append("触发原因: " + preview["trigger"])
        lines.append("")
        lines.append("【模拟输入 / Simulated input】")
        lines.append(json.dumps(preview.get("simulated_input", {}),
                                ensure_ascii=False, indent=2))
        lines.append("")
        lines.append("【模拟输出 / Simulated output】")
        lines.append(str(preview.get("simulated_output", "")))
        lines.append("")
        lines.append("【安全检查 / Safety check】")
        lines.append("verdict: " + preview.get("safety_check", "?"))
        risks = preview.get("risk_points") or []
        if risks:
            lines.append("risk_points:")
            for r in risks:
                lines.append("  - " + r)
        else:
            lines.append("risk_points: (none)")
        lines.append("requires_approval: "
                     + ("yes" if preview.get("requires_approval") else "no"))
        lines.append("─" * 56)
        return "\n".join(lines)
