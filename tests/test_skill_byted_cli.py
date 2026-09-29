"""byted-mediakit / byted-bp-cdn-pagesdeploy —— CLI 子进程型 skill 的回归测试。

两者都靠本机官方 CLI（`mediakit-cli` / `@byteplus/nest`），测试重点：

- **安全边界**：白名单外的 action 一律拒绝；argv 由固定前缀拼出，不走 shell；
- **参数校验**：越界的输出/资源目录直接被拒（路径不得逃出项目根）；
- **失败如实**：CLI 缺失 / 退出码非 0 时不假装成功。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

_SKILLS_ROOT = Path(__file__).resolve().parent.parent / "skills" / "cloud"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, _SKILLS_ROOT / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mediakit():
    return _load("skill_mediakit_test", "byted-mediakit/run.py")


@pytest.fixture
def bppages():
    return _load("skill_bppages_test", "byted-bp-cdn-pagesdeploy/run.py")


def _fake_cli(monkeypatch, module, *, returncode=0, stdout="{}", stderr=""):
    """假装 CLI 存在；记录 argv，并回一段可控输出。"""
    calls: list[list[str]] = []
    monkeypatch.setattr(module.shutil, "which", lambda _n: r"C:\fake\cli.exe")

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        assert kwargs.get("shell") is False, "绝不能经 shell 执行"
        assert kwargs.get("timeout"), "必须有超时上限"
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    return calls


# ── byted-mediakit ──────────────────────────────────────

def test_mediakit_rejects_unknown_action(mediakit, monkeypatch):
    calls = _fake_cli(monkeypatch, mediakit)

    result = mediakit.run({"action": "rm-rf"})

    assert "unsupported action" in result["error"]
    assert "enhance_video" in result["allowed"]
    assert calls == [], "非法 action 绝不能真的执行"


def test_mediakit_reports_missing_cli(mediakit, monkeypatch):
    monkeypatch.setattr(mediakit.shutil, "which", lambda _n: None)

    result = mediakit.run({"action": "help"})

    assert result["status"] == "error"
    assert "mediakit-cli" in result["error"]


def test_mediakit_enhance_video_argv(mediakit, monkeypatch):
    calls = _fake_cli(monkeypatch, mediakit, stdout='{"task_id": "amk-1"}')

    result = mediakit.run({
        "action": "enhance_video",
        "video_url": "https://example.com/a.mp4",
        "resolution": "1080P",
    })

    assert result["status"] == "ok"
    assert calls == [[
        r"C:\fake\cli.exe", "video", "enhance-video",
        "--video-url", "https://example.com/a.mp4",
        "--resolution", "1080p",
    ]]


def test_mediakit_enhance_video_rejects_bad_resolution(mediakit, monkeypatch):
    calls = _fake_cli(monkeypatch, mediakit)

    result = mediakit.run({
        "action": "enhance_video",
        "video_url": "https://example.com/a.mp4",
        "resolution": "超高清",
    })

    assert result["error"] == "invalid arguments"
    assert calls == []


def test_mediakit_trim_video_confines_output_dir(mediakit, monkeypatch):
    calls = _fake_cli(monkeypatch, mediakit)

    result = mediakit.run({
        "action": "trim_video",
        "video_url": "a.mp4",
        "start_time": 1,
        "end_time": 5,
        "output_path": r"C:\Windows\System32",
    })

    assert result["error"] == "invalid arguments"
    assert calls == [], "越界输出目录必须被拒"


def test_mediakit_trim_video_rejects_inverted_range(mediakit, monkeypatch, tmp_path):
    calls = _fake_cli(monkeypatch, mediakit)
    monkeypatch.setattr(mediakit, "_PROJECT_ROOT", tmp_path)

    result = mediakit.run({
        "action": "trim_video",
        "video_url": "a.mp4",
        "start_time": 8,
        "end_time": 3,
        "output_path": str(tmp_path),
    })

    assert result["error"] == "invalid arguments"
    assert calls == []


def test_mediakit_trim_video_argv(mediakit, monkeypatch, tmp_path):
    calls = _fake_cli(monkeypatch, mediakit, stdout="done")
    monkeypatch.setattr(mediakit, "_PROJECT_ROOT", tmp_path)

    result = mediakit.run({
        "action": "trim_video",
        "video_url": "a.mp4",
        "start_time": 3,
        "end_time": 8,
        "output_path": str(tmp_path),
    })

    assert result["status"] == "ok"
    assert calls == [[
        r"C:\fake\cli.exe", "--local", "editing", "trim-video",
        "--video-url", "a.mp4",
        "--start-time", "3", "--end-time", "8",
        "--output-path", str(tmp_path),
    ]]


def test_mediakit_query_task_poll_flag(mediakit, monkeypatch):
    calls = _fake_cli(monkeypatch, mediakit, stdout='{"status": "completed"}')

    mediakit.run({"action": "query_task", "task_id": "amk-9", "poll_complete": "true"})

    assert calls == [[
        r"C:\fake\cli.exe", "shared", "query-task",
        "--task-id", "amk-9", "--poll-complete",
    ]]


def test_mediakit_surfaces_cli_failure(mediakit, monkeypatch):
    _fake_cli(monkeypatch, mediakit, returncode=1, stdout="", stderr="api key not set")

    result = mediakit.run({"action": "enhance_video", "video_url": "a.mp4"})

    assert result["status"] == "error"
    assert "mediakit-cli init" in result["error"]


# ── byted-bp-cdn-pagesdeploy ────────────────────────────

def test_bppages_rejects_unknown_action(bppages, monkeypatch):
    calls = _fake_cli(monkeypatch, bppages)

    result = bppages.run({"action": "delete-everything"})

    assert "unsupported action" in result["error"]
    assert calls == []


def test_bppages_reports_missing_cli(bppages, monkeypatch):
    monkeypatch.setattr(bppages.shutil, "which", lambda _n: None)

    result = bppages.run({"action": "version"})

    assert result["status"] == "error"
    assert "@byteplus/nest" in result["error"]


def test_bppages_deploy_rejects_bad_project_name(bppages, monkeypatch, tmp_path):
    calls = _fake_cli(monkeypatch, bppages)
    monkeypatch.setattr(bppages, "_PROJECT_ROOT", tmp_path)
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("x", encoding="utf-8")

    result = bppages.run({
        "action": "deploy",
        "project_name": "Bad_Name",
        "assets_dir": str(site),
    })

    assert result["error"] == "invalid arguments"
    assert calls == []


def test_bppages_deploy_requires_index_html(bppages, monkeypatch, tmp_path):
    calls = _fake_cli(monkeypatch, bppages)
    monkeypatch.setattr(bppages, "_PROJECT_ROOT", tmp_path)
    site = tmp_path / "site"
    site.mkdir()

    result = bppages.run({
        "action": "deploy",
        "project_name": "demo-site",
        "assets_dir": str(site),
    })

    assert result["error"] == "invalid arguments"
    assert calls == []


def test_bppages_deploy_argv(bppages, monkeypatch, tmp_path):
    calls = _fake_cli(monkeypatch, bppages, stdout="created")
    monkeypatch.setattr(bppages, "_PROJECT_ROOT", tmp_path)
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("x", encoding="utf-8")

    result = bppages.run({
        "action": "deploy",
        "project_name": "demo-site",
        "assets_dir": str(site),
    })

    assert result["status"] == "ok"
    assert calls == [[
        r"C:\fake\cli.exe", "pages", "create",
        "--name", "demo-site", "--assets", str(site), "--deploy",
    ]]


def test_bppages_domain_add_argv(bppages, monkeypatch):
    calls = _fake_cli(monkeypatch, bppages, stdout="ok")

    bppages.run({
        "action": "domain_add",
        "pages_id": "p-2e9hpae39m2sqksy",
        "domain": "www.example.com",
    })

    assert calls == [[
        r"C:\fake\cli.exe", "pages", "domain", "add",
        "-p", "p-2e9hpae39m2sqksy", "--domain", "www.example.com",
    ]]


def test_bppages_hints_on_nestjs_collision(bppages, monkeypatch):
    _fake_cli(monkeypatch, bppages, returncode=1, stderr="unknown command 'pages'")

    result = bppages.run({"action": "version"})

    assert result["status"] == "error"
    assert "@byteplus/nest" in result["error"]
