"""gh-cli（GitHub 只读查询）—— 第二个可执行型 skill 的回归测试。

重点在**安全边界**：调用方不能拼出任意 gh 子命令，写入类动作必须被拒。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SKILL_RUN = Path(__file__).resolve().parent.parent / "skills" / "cloud" / "gh-cli" / "run.py"
FAKE_GH = r"C:\fake\gh.exe"


@pytest.fixture
def gh():
    spec = importlib.util.spec_from_file_location("skill_gh_test", SKILL_RUN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_cli(monkeypatch, gh):
    """假装 gh 存在；返回记录 argv 的容器，默认回一段合法 JSON。"""
    calls: list[list[str]] = []

    monkeypatch.setattr(gh.shutil, "which", lambda _n: FAKE_GH)

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        assert kwargs.get("shell") is False, "绝不能经 shell 执行"
        assert kwargs.get("timeout"), "必须有超时上限"
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps([{"number": 1, "title": "t"}]),
            stderr="",
        )

    monkeypatch.setattr(gh.subprocess, "run", fake_run)
    return calls


def test_missing_action_is_rejected(gh):
    assert gh.run({})["error"] == "missing action"


def test_unknown_action_is_rejected_with_allowlist(gh, fake_cli):
    """白名单外一律拒绝 —— 这是"不能拼任意子命令"的第一道闸。"""
    result = gh.run({"action": "pr_merge"})

    assert "unsupported action" in result["error"]
    assert "pr_list" in result["allowed"]
    assert fake_cli == [], "非法 action 绝不能真的执行"


def test_write_style_action_is_not_in_whitelist(gh):
    for action in ("pr_create", "pr_merge", "pr_close", "repo_delete", "auth_login"):
        assert action not in gh._ACTIONS


def test_pr_view_requires_numeric_number(gh, fake_cli):
    assert gh.run({"action": "pr_view"})["error"] == "missing number"
    assert gh.run({"action": "pr_view", "number": "abc"})["error"] == "missing number"
    assert fake_cli == []


def test_search_requires_query(gh, fake_cli):
    assert gh.run({"action": "search_repos"})["error"] == "missing query"
    assert fake_cli == []


def test_pr_list_builds_expected_argv(gh, fake_cli):
    result = gh.run({"action": "pr_list", "repo": "o/r", "limit": 5, "state": "closed"})

    assert result["status"] == "ok"
    assert result["count"] == 1
    assert result["items"][0]["number"] == 1

    argv = fake_cli[0]
    assert argv[:3] == [FAKE_GH, "pr", "list"]
    assert "--limit" in argv and "5" in argv
    assert "--repo" in argv and "o/r" in argv
    assert "--state" in argv and "closed" in argv
    assert "--json" in argv


def test_pr_view_passes_number_positionally(gh, fake_cli):
    gh.run({"action": "pr_view", "number": 42})

    argv = fake_cli[0]
    assert argv[:3] == [FAKE_GH, "pr", "view"]
    assert "42" in argv
    assert "--limit" not in argv, "详情类动作不该带 --limit"


def test_limit_is_clamped(gh, fake_cli):
    gh.run({"action": "pr_list", "limit": 9999})
    assert "50" in fake_cli[0]

    fake_cli.clear()
    gh.run({"action": "pr_list", "limit": "not-a-number"})
    assert "10" in fake_cli[0]


def test_invalid_state_is_ignored_not_passed_through(gh, fake_cli):
    gh.run({"action": "pr_list", "state": "whatever; rm -rf /"})
    assert "--state" not in fake_cli[0]


def test_repo_view_does_not_get_limit(gh, fake_cli):
    """`repo_view` 查看单个仓库，不接受 --limit（真机冒烟实测 unknown flag）。"""
    gh.run({"action": "repo_view", "repo": "o/r"})

    argv = fake_cli[0]
    assert "--limit" not in argv
    assert argv[:3] == [FAKE_GH, "repo", "view"]
    assert "--json" in argv


def test_repo_view_takes_repo_as_positional_not_flag(gh, fake_cli):
    """`gh repo view <repository>`：仓库是位置参数，传 --repo 会被判未知参数。"""
    gh.run({"action": "repo_view", "repo": "o/r"})

    argv = fake_cli[0]
    assert "--repo" not in argv
    assert "o/r" in argv
    assert argv.index("o/r") == 3     # 紧跟 repo view 之后


def test_search_repos_gets_limit_and_query(gh, fake_cli):
    gh.run({"action": "search_repos", "query": "llm agent", "limit": 3})

    argv = fake_cli[0]
    assert argv[:3] == [FAKE_GH, "search", "repos"]
    assert "llm agent" in argv
    assert "--limit" in argv and "3" in argv


def test_missing_cli_reports_error(gh, monkeypatch):
    monkeypatch.setattr(gh.shutil, "which", lambda _n: None)

    result = gh.run({"action": "pr_list"})

    assert result["status"] == "error"
    assert "不可用" in result["error"]


def test_timeout_reports_error(gh, monkeypatch):
    monkeypatch.setattr(gh.shutil, "which", lambda _n: FAKE_GH)

    def boom(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="gh", timeout=30)

    monkeypatch.setattr(gh.subprocess, "run", boom)

    assert "超时" in gh.run({"action": "pr_list"})["error"]


def test_not_logged_in_gives_actionable_message(gh, monkeypatch):
    monkeypatch.setattr(gh.shutil, "which", lambda _n: FAKE_GH)
    monkeypatch.setattr(
        gh.subprocess, "run",
        lambda *a, **k: SimpleNamespace(
            returncode=1, stdout="", stderr="To get started with GitHub CLI, please run: gh auth login",
        ),
    )

    result = gh.run({"action": "pr_list"})

    assert result["status"] == "error"
    assert "gh auth login" in result["error"]


def test_non_json_output_is_surfaced_not_faked_as_empty(gh, monkeypatch):
    """gh 偶尔返回非 JSON：如实回传原文，不要假装"查到 0 条"。"""
    monkeypatch.setattr(gh.shutil, "which", lambda _n: FAKE_GH)
    monkeypatch.setattr(
        gh.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="not json at all", stderr=""),
    )

    result = gh.run({"action": "repo_view"})

    assert result["status"] == "ok"
    assert "not json at all" in result["raw"]
    assert result["items"] == []


def test_single_object_payload_is_wrapped_into_items(gh, monkeypatch):
    monkeypatch.setattr(gh.shutil, "which", lambda _n: FAKE_GH)
    monkeypatch.setattr(
        gh.subprocess, "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout=json.dumps({"nameWithOwner": "o/r"}), stderr="",
        ),
    )

    result = gh.run({"action": "repo_view"})

    assert result["count"] == 1
    assert result["items"][0]["nameWithOwner"] == "o/r"


def test_skill_declares_cli_requirement():
    """SKILL.md 必须声明 requires_cli，否则没装 gh 的机器会暴露一个必炸的工具。"""
    text = (SKILL_RUN.parent / "SKILL.md").read_text(encoding="utf-8")
    assert "requires_cli: gh" in text
    assert "cloud_call_not_implemented" not in text
