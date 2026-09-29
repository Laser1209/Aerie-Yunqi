"""byted-seedream skill 的离线回归：请求装配、错误如实透出、stub 契约。

不发真实请求（测试不该依赖外部服务与真实密钥），只验证「发给 Ark 的东西对不对」
与「各类失败怎么报」—— 后者是重点：这个项目已经吃过「跑不了的能力假装跑得了」
的亏（模型看到工具在清单里就以为有）。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUN_PY = ROOT / "skills" / "cloud" / "byted-seedream" / "run.py"


def _load_skill():
    spec = importlib.util.spec_from_file_location("skill_byted_seedream", RUN_PY)
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


class _PostStub:
    def __init__(self):
        self.calls: list[dict] = []
        self.response = _response(200, {"data": [{"url": "https://x/y.png", "size": "2048x2048"}]})


@pytest.fixture()
def skill():
    return _load_skill()


@pytest.fixture()
def post(monkeypatch):
    stub = _PostStub()

    def _post(url, **kwargs):
        stub.calls.append({"url": url, **kwargs})
        return stub.response

    monkeypatch.setattr("requests.post", _post)
    return stub


def test_missing_prompt(skill, monkeypatch):
    monkeypatch.setenv("SEEDREAM_KEY", "k")
    assert skill.run({})["error"] == "missing prompt"


def test_missing_key_returns_stub(skill, monkeypatch):
    monkeypatch.delenv("SEEDREAM_KEY", raising=False)
    result = skill.run({"prompt": "一只猫"})
    assert result["status"] == "stub"
    assert "credential_missing" in result["error"]


def test_success_passes_through_image_url(skill, monkeypatch, post):
    monkeypatch.setenv("SEEDREAM_KEY", "sk-test")

    result = skill.run({"prompt": "一只戴墨镜的猫"})

    assert result["status"] == "ok"
    assert result["image_url"] == "https://x/y.png"
    assert result["size"] == "2048x2048"

    call = post.calls[0]
    assert call["url"] == "https://ark.cn-beijing.volces.com/api/v3/images/generations"
    assert call["headers"]["Authorization"] == "Bearer sk-test"
    assert call["json"] == {
        "model": "doubao-seedream-5-0-260128",
        "prompt": "一只戴墨镜的猫",
        "size": "2K",
    }
    assert call["timeout"] == 120


def test_model_and_size_can_be_overridden(skill, monkeypatch, post):
    monkeypatch.setenv("SEEDREAM_KEY", "k")
    skill.run({"prompt": "p", "model": "ep-2026xxxx", "size": "2048x2048"})
    assert post.calls[0]["json"]["model"] == "ep-2026xxxx"
    assert post.calls[0]["json"]["size"] == "2048x2048"


def test_http_error_is_surfaced_not_swallowed(skill, monkeypatch, post):
    monkeypatch.setenv("SEEDREAM_KEY", "bad")
    post.response = _response(401, text='{"error":{"code":"ApiKey.Invalid"}}')

    result = skill.run({"prompt": "p"})

    assert result["status"] == "error"
    assert result["error"].startswith("http_401")
    assert "ApiKey.Invalid" in result["error"]


def test_non_json_body_is_reported(skill, monkeypatch, post):
    monkeypatch.setenv("SEEDREAM_KEY", "k")
    post.response = _response(200, payload=None, text="<html>gateway</html>")

    result = skill.run({"prompt": "p"})

    assert result["status"] == "error"
    assert result["error"] == "invalid_json_response"


def test_empty_data_is_reported(skill, monkeypatch, post):
    monkeypatch.setenv("SEEDREAM_KEY", "k")
    post.response = _response(200, payload={"data": []})

    result = skill.run({"prompt": "p"})

    assert result["status"] == "error"
    assert result["error"] == "empty_result"


def test_request_exception_is_reported(skill, monkeypatch):
    monkeypatch.setenv("SEEDREAM_KEY", "k")

    def _boom(url, **kwargs):
        raise ConnectionError("tls handshake failed")

    monkeypatch.setattr("requests.post", _boom)

    result = skill.run({"prompt": "p"})

    assert result["status"] == "error"
    assert result["error"].startswith("request_failed")


def test_long_error_body_is_truncated(skill, monkeypatch, post):
    monkeypatch.setenv("SEEDREAM_KEY", "k")
    post.response = _response(500, text="x" * 5000)

    result = skill.run({"prompt": "p"})

    assert result["error"].endswith("…")
    assert len(result["error"]) < 600
