"""defuddle（网页正文提取）—— 第一个可执行型 skill 的回归测试。

它取代了原来的 scaffold 桩（恒返 `cloud_call_not_implemented`）。底层是本机
`defuddle` CLI，不依赖任何云端凭据，因此可以用假 subprocess 完整覆盖。
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SKILL_RUN = Path(__file__).resolve().parent.parent / "skills" / "cloud" / "defuddle" / "run.py"


@pytest.fixture
def defuddle():
    """按 SkillLoader 的方式动态加载 run.py（与本体的加载路径一致）。"""
    spec = importlib.util.spec_from_file_location("skill_defuddle_test", SKILL_RUN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_cli(monkeypatch, defuddle):
    """假装 defuddle CLI 存在；返回记录调用的容器。"""
    calls: list[list[str]] = []

    monkeypatch.setattr(defuddle.shutil, "which", lambda _n: r"C:\fake\defuddle.CMD")

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        assert kwargs.get("shell") is False, "绝不能经 shell 执行（url 可能含特殊字符）"
        assert kwargs.get("timeout"), "必须有超时上限"
        return SimpleNamespace(returncode=0, stdout="# 标题\n\n正文内容", stderr="")

    monkeypatch.setattr(defuddle.subprocess, "run", fake_run)
    return calls


def test_missing_url_is_rejected(defuddle):
    assert defuddle.run({})["error"] == "missing url"
    assert defuddle.run({"url": "   "})["error"] == "missing url"


def test_returns_clean_markdown(defuddle, fake_cli):
    result = defuddle.run({"url": "https://example.com/post"})

    assert result["status"] == "ok"
    assert result["markdown"].startswith("# 标题")
    assert result["chars"] == len(result["markdown"])
    assert result["truncated"] is False

    assert fake_cli == [[
        r"C:\fake\defuddle.CMD", "parse", "https://example.com/post", "--md",
    ]]


def test_frontmatter_flag_is_passed_through(defuddle, fake_cli):
    defuddle.run({"url": "https://example.com/a", "frontmatter": True})
    assert "--frontmatter" in fake_cli[0]


def test_missing_cli_reports_error_instead_of_crashing(defuddle, monkeypatch):
    monkeypatch.setattr(defuddle.shutil, "which", lambda _n: None)

    result = defuddle.run({"url": "https://example.com"})

    assert result["status"] == "error"
    assert "不可用" in result["error"]


def test_timeout_reports_error(defuddle, monkeypatch):
    monkeypatch.setattr(defuddle.shutil, "which", lambda _n: "defuddle")

    def boom(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="defuddle", timeout=45)

    monkeypatch.setattr(defuddle.subprocess, "run", boom)

    result = defuddle.run({"url": "https://slow.example"})

    assert result["status"] == "error"
    assert "超时" in result["error"]


def test_nonzero_exit_surfaces_stderr(defuddle, monkeypatch):
    monkeypatch.setattr(defuddle.shutil, "which", lambda _n: "defuddle")
    monkeypatch.setattr(
        defuddle.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="403 Forbidden"),
    )

    result = defuddle.run({"url": "https://blocked.example"})

    assert result["status"] == "error"
    assert "403" in result["error"]


def test_empty_extraction_is_an_error_not_an_empty_success(defuddle, monkeypatch):
    """页面抽不出正文时不得回一个空 markdown 冒充成功。"""
    monkeypatch.setattr(defuddle.shutil, "which", lambda _n: "defuddle")
    monkeypatch.setattr(
        defuddle.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="   \n ", stderr=""),
    )

    result = defuddle.run({"url": "https://spa.example"})

    assert result["status"] == "error"
    assert "没有提取到正文" in result["error"]


def test_long_content_is_truncated(defuddle, monkeypatch):
    monkeypatch.setattr(defuddle.shutil, "which", lambda _n: "defuddle")
    monkeypatch.setattr(
        defuddle.subprocess, "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="正" * (defuddle._MAX_CHARS + 500), stderr="",
        ),
    )

    result = defuddle.run({"url": "https://long.example"})

    assert result["status"] == "ok"
    assert result["truncated"] is True
    assert "已截断" in result["markdown"]
    assert result["chars"] <= defuddle._MAX_CHARS + 40


# ── 可用性闸门：没装 CLI 的机器上不该暴露这个工具 ────────────────────────


def test_cli_gate_blocks_skill_when_cli_missing(tmp_path, monkeypatch):
    from core import skill_loader as skill_loader_module
    from core.skill_loader import SkillLoader
    from core.skill_router import SkillRouter
    from core.tool_registry import ToolRegistry

    cloud = tmp_path / "cloud"
    skill_dir = cloud / "cli-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: cli-skill\ndescription: d\nrequires_cli: definitely-missing-cli\n---\n\n正文\n",
        encoding="utf-8",
    )
    (skill_dir / "run.py").write_text(
        "def run(args):\n    return {'ok': True}\n", encoding="utf-8",
    )
    monkeypatch.setattr(skill_loader_module, "_SKILL_ROOTS", ((cloud, "cloud"),))
    monkeypatch.setattr(skill_loader_module, "_ALLOWED_BASES", (cloud.resolve(),))
    monkeypatch.setattr(skill_loader_module.shutil, "which", lambda _n: None)

    registry = ToolRegistry()
    loader = SkillLoader(registry, SkillRouter({}))
    loader.discover()

    assert loader.discovered["cli-skill"]["available"] is False
    assert "definitely-missing-cli" in loader.discovered["cli-skill"]["unavailable_reason"]
    assert loader.register_all() == 0
    assert registry.get("cli-skill") is None
