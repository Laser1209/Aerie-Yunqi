"""Part D 自我进化：人工确认（D1）/ 模型主动提案（D2）/ 待审推送（D3）契约测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest


def _make_project(root: Path) -> Path:
    (root / "skills").mkdir(parents=True, exist_ok=True)
    (root / "core").mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def l4(tmp_path):
    from core.self_evolve_l4 import L4SelfEvolution

    root = _make_project(tmp_path / "proj")
    return L4SelfEvolution(project_root=str(root), auto_apply=True), root


# Gate3 要求"必须真跑测试"：给一个必然成功且极快的命令，别在测试里跑全量。
_TEST_CMD = "python -m pytest --version"


# ── D1 白名单内也需人工确认 ──────────────────────────────

def test_whitelisted_low_risk_proposal_waits_for_review(l4):
    evolver, root = l4
    proposal = evolver.create_proposal(
        title="白名单改动",
        file_changes=[{"path": "skills/x.py", "action": "create", "new_content": "pass"}],
    )

    result = asyncio.run(evolver.process_proposal(proposal, test_command=_TEST_CMD))

    assert result["action"] == "pending_review", result
    assert "白名单内也不例外" in result["reason"]
    assert not (root / "skills" / "x.py").exists(), "未审批前绝不许落盘"


def test_approval_applies_only_when_auto_apply_enabled(tmp_path):
    from core.self_evolve_l4 import L4SelfEvolution

    root = _make_project(tmp_path / "proj")
    evolver = L4SelfEvolution(project_root=str(root), auto_apply=False)
    proposal = evolver.create_proposal(
        title="仅记录审批结论",
        file_changes=[{"path": "skills/y.py", "action": "create", "new_content": "pass"}],
    )
    asyncio.run(evolver.process_proposal(proposal, test_command=_TEST_CMD))

    ok, msg = evolver.approve_and_apply(proposal.proposal_id)

    assert ok is True
    assert "未自动落盘" in msg
    assert not (root / "skills" / "y.py").exists()


# ── D2 模型主动提案：只登记，不写文件 ────────────────────

def test_model_proposal_registers_pending_without_touching_files(l4, monkeypatch):
    evolver, root = l4
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())

    from tools.self_evolve_tools import propose_self_improvement

    monkeypatch.setattr(
        "core.companion.get_companion",
        lambda: SimpleNamespace(l4_evolution=evolver),
    )
    result = propose_self_improvement(
        summary="话题复现的额度应该跨重启持久化",
        detail="现在重启就清零，容易一天多发",
        target_hint="core/topic_resurface.py",
    )

    assert result["status"] == "ok"
    assert result["pending"] is True
    proposal = evolver.archive.get_proposal(result["proposal_id"])
    assert proposal is not None
    assert proposal.file_changes == []
    assert proposal.metadata.get("requested_by_model") is True

    after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    # 只允许 journal / 备份索引这类元数据文件增长，绝不许出现被改的"目标文件"
    assert not any("topic_resurface" in name for name in after)
    assert set(after) - set(before) <= {
        "data/evolution_archive/evolution_journal.jsonl",
    }, after


def test_model_proposal_reports_unavailable_without_evolver(monkeypatch):
    from tools.self_evolve_tools import propose_self_improvement

    monkeypatch.setattr("core.companion.get_companion", lambda: SimpleNamespace())

    result = propose_self_improvement(summary="随便提一句")

    assert result["status"] == "unavailable"
    assert "未启用" in result["error"]


def test_model_proposal_requires_summary():
    from tools.self_evolve_tools import propose_self_improvement

    assert propose_self_improvement(summary="   ")["error"] == "missing summary"


# ── D3 待审推送（SSE / Electron stderr 桥）────────────────

def test_pending_proposal_emits_event(l4, monkeypatch):
    evolver, _root = l4
    captured: list[tuple[str, dict]] = []

    from core import chat_events

    monkeypatch.setattr(
        chat_events, "emit", lambda event_type, **payload: captured.append((event_type, payload))
    )

    proposal = evolver.create_proposal(
        title="推事件",
        file_changes=[{"path": "skills/z.py", "action": "create", "new_content": "pass"}],
    )
    asyncio.run(evolver.process_proposal(proposal, test_command=_TEST_CMD))

    assert captured, "待审提案必须推事件给界面"
    event_type, payload = captured[-1]
    assert event_type == "self_evolve_proposed"
    assert payload["proposal_id"] == proposal.proposal_id
    assert payload["pending_count"] >= 1


# ── 工具注册 ────────────────────────────────────────────

def test_self_evolve_tool_registers():
    from core.tool_registry import ToolRegistry
    from tools.self_evolve_tools import register_self_evolve_tools

    registry = ToolRegistry()
    register_self_evolve_tools(registry)

    names = set(registry.list_names()) if hasattr(registry, "list_names") else set(registry._tools)
    assert "propose_self_improvement" in names
