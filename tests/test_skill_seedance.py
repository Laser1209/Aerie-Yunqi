"""byted-seedance skill 的离线回归：两段式任务、请求装配、失败如实透出。

视频生成是异步任务，skill 拆成 create / get 两段。这里全部 mock，不碰网络与
真实密钥。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUN_PY = ROOT / "skills" / "cloud" / "byted-seedance" / "run.py"


def _load_skill():
    spec = importlib.util.spec_from_file_location("skill_byted_seedance", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _response(status_code=200, payload=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if payload is None:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = payload
    return resp


class _Stub:
    def __init__(self):
        self.calls: list[dict] = []
        self.response = _response(200, {"id": "cgt-2026-test"})

    def install(self, monkeypatch):
        def _call(method):
            def _inner(url, **kwargs):
                self.calls.append({"method": method, "url": url, **kwargs})
                return self.response

            return _inner

        monkeypatch.setattr("requests.post", _call("post"))
        monkeypatch.setattr("requests.get", _call("get"))


@pytest.fixture()
def skill():
    return _load_skill()


@pytest.fixture()
def http(monkeypatch):
    stub = _Stub()
    stub.install(monkeypatch)
    return stub


def test_unknown_action_is_rejected(skill, monkeypatch):
    monkeypatch.setenv("SEEDANCE_KEY", "k")
    result = skill.run({"action": "delete"})
    assert "unknown action" in result["error"]


def test_missing_key_returns_stub(skill, monkeypatch):
    monkeypatch.delenv("SEEDANCE_KEY", raising=False)
    result = skill.run({"prompt": "一只猫在跳舞"})
    assert result["status"] == "stub"
    assert "credential_missing" in result["error"]


def test_create_requires_prompt(skill, monkeypatch):
    monkeypatch.setenv("SEEDANCE_KEY", "k")
    assert skill.run({"action": "create"})["error"] == "missing prompt"


def test_create_returns_task_id_and_sends_expected_payload(skill, monkeypatch, http):
    monkeypatch.setenv("SEEDANCE_KEY", "sd-test")

    result = skill.run({"prompt": "一只猫在跳舞"})

    assert result["status"] == "ok"
    assert result["task_id"] == "cgt-2026-test"
    assert result["task_status"] == "queued"

    call = http.calls[0]
    assert call["method"] == "post"
    assert call["url"] == "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"
    assert call["headers"]["Authorization"] == "Bearer sd-test"
    assert call["json"] == {
        "model": "doubao-seedance-2-0-260128",
        "content": [{"type": "text", "text": "一只猫在跳舞"}],
        "ratio": "adaptive",
        "duration": 5,
    }


def test_create_with_image_url_adds_reference_item(skill, monkeypatch, http):
    monkeypatch.setenv("SEEDANCE_KEY", "k")

    skill.run({"prompt": "让画面动起来", "image_url": "https://x/first.png",
               "ratio": "9:16", "duration": 8, "watermark": True})

    payload = http.calls[0]["json"]
    assert payload["ratio"] == "9:16"
    assert payload["duration"] == 8
    assert payload["watermark"] is True
    assert payload["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "https://x/first.png"},
    }


def test_create_http_error_is_surfaced(skill, monkeypatch, http):
    monkeypatch.setenv("SEEDANCE_KEY", "bad")
    http.response = _response(401, text='{"error":{"code":"ApiKey.Invalid"}}')

    result = skill.run({"prompt": "p"})

    assert result["status"] == "error"
    assert result["error"].startswith("http_401")
    assert "ApiKey.Invalid" in result["error"]


def test_create_without_id_is_reported(skill, monkeypatch, http):
    monkeypatch.setenv("SEEDANCE_KEY", "k")
    http.response = _response(200, payload={"status": "queued"})

    result = skill.run({"prompt": "p"})

    assert result["status"] == "error"
    assert result["error"] == "no_task_id"


def test_get_requires_task_id(skill, monkeypatch):
    monkeypatch.setenv("SEEDANCE_KEY", "k")
    assert skill.run({"action": "get"})["error"] == "missing task_id"


def test_get_running_has_no_video_url(skill, monkeypatch, http):
    monkeypatch.setenv("SEEDANCE_KEY", "k")
    http.response = _response(200, payload={"id": "cgt-1", "status": "running"})

    result = skill.run({"action": "get", "task_id": "cgt-1"})

    assert result["status"] == "ok"
    assert result["task_status"] == "running"
    assert "video_url" not in result
    assert http.calls[0]["url"].endswith("/tasks/cgt-1")


def test_get_succeeded_returns_video_url(skill, monkeypatch, http):
    monkeypatch.setenv("SEEDANCE_KEY", "k")
    http.response = _response(200, payload={
        "id": "cgt-1",
        "status": "succeeded",
        "content": {"video_url": "https://x/v.mp4"},
    })

    result = skill.run({"action": "get", "task_id": "cgt-1"})

    assert result["task_status"] == "succeeded"
    assert result["video_url"] == "https://x/v.mp4"


def test_get_succeeded_but_url_missing_exposes_raw(skill, monkeypatch, http):
    """字段名若与预期不同，不能让调用方猜 —— 把原始报文附上。"""
    monkeypatch.setenv("SEEDANCE_KEY", "k")
    http.response = _response(200, payload={"id": "cgt-1", "status": "succeeded", "weird": 1})

    result = skill.run({"action": "get", "task_id": "cgt-1"})

    assert "video_url" not in result
    assert "weird" in result["raw"]


def test_get_failed_carries_error(skill, monkeypatch, http):
    monkeypatch.setenv("SEEDANCE_KEY", "k")
    http.response = _response(200, payload={
        "id": "cgt-1", "status": "failed", "error": {"code": "ContentPolicyViolation"},
    })

    result = skill.run({"action": "get", "task_id": "cgt-1"})

    assert result["status"] == "ok"  # 查询本身成功
    assert result["task_status"] == "failed"
    assert "ContentPolicyViolation" in result["error"]


def test_extract_video_url_supports_multiple_shapes(skill):
    f = skill._extract_video_url
    assert f({"content": {"video_url": "a"}}) == "a"
    assert f({"content": [{"video_url": "b"}]}) == "b"
    assert f({"video_url": "c"}) == "c"
    assert f({"url": "d"}) == "d"
    assert f({"nothing": 1}) == ""


def test_get_http_error_is_surfaced(skill, monkeypatch, http):
    monkeypatch.setenv("SEEDANCE_KEY", "k")
    http.response = _response(404, text="task not found")

    result = skill.run({"action": "get", "task_id": "cgt-nope"})

    assert result["status"] == "error"
    assert result["error"].startswith("http_404")
