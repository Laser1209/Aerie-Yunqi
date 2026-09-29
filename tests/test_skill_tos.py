"""volcengine-tos skill 的离线回归：SDK 调用装配、四类 action、失败如实透出。

本机未安装 `tos` SDK（这正是 ``requires_module: tos`` 闸门存在的意义），
所以这里用一个假的 tos 模块替掉它 —— 验证的是"我们怎么调 SDK"和"出错怎么报"，
不是 SDK 本身。
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUN_PY = ROOT / "skills" / "cloud" / "volcengine-tos" / "run.py"


def _load_skill():
    spec = importlib.util.spec_from_file_location("skill_volcengine_tos", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TosClientError(Exception):
    def __init__(self, message="client boom", cause="bad arg"):
        super().__init__(message)
        self.message = message
        self.cause = cause


class TosServerError(Exception):
    def __init__(self, message="Access Denied", code="AccessDenied",
                 request_id="req-abc", status_code=403):
        super().__init__(message)
        self.message = message
        self.code = code
        self.request_id = request_id
        self.status_code = status_code


class FakeHttpMethodType:
    Http_Method_Get = "GET"


def _install_fake_tos(monkeypatch, client, error: Exception | None = None):
    """装一个假的 tos 包。``error`` 非空时任何调用都抛它（用于测失败路径）。"""
    mod = types.ModuleType("tos")
    exc = types.ModuleType("tos.exceptions")
    exc.TosClientError = TosClientError
    exc.TosServerError = TosServerError
    enum_mod = types.ModuleType("tos.enum")
    enum_mod.HttpMethodType = FakeHttpMethodType

    class _RecordingClient:
        def __getattr__(self, name):
            def _call(*args, **kwargs):
                if error is not None:
                    raise error
                return getattr(client, name)(*args, **kwargs)

            return _call

    mod.TosClientV2 = lambda ak, sk, endpoint, region: _RecordingClient()
    mod.exceptions = exc
    monkeypatch.setitem(sys.modules, "tos", mod)
    monkeypatch.setitem(sys.modules, "tos.exceptions", exc)
    monkeypatch.setitem(sys.modules, "tos.enum", enum_mod)


@pytest.fixture()
def skill():
    return _load_skill()


@pytest.fixture()
def creds(monkeypatch):
    monkeypatch.setenv("TOS_ACCESS_KEY", "AK-test")
    monkeypatch.setenv("TOS_SECRET_KEY", "SK-test")
    monkeypatch.setenv("TOS_REGION", "cn-beijing")
    monkeypatch.setenv("TOS_ENDPOINT", "tos-cn-beijing.volces.com")
    monkeypatch.setenv("TOS_BUCKET", "my-bucket")


class FakeClient:
    def __init__(self):
        self.calls: list[tuple] = []

    def upload_file(self, bucket, key, path, **kwargs):
        self.calls.append(("upload_file", bucket, key, path, kwargs))
        return types.SimpleNamespace(request_id="req-upload")

    def get_object_to_file(self, bucket, key, path):
        self.calls.append(("get_object_to_file", bucket, key, path))
        Path(path).write_bytes(b"downloaded")

    def pre_signed_url(self, method, bucket, key, **kwargs):
        self.calls.append(("pre_signed_url", method, bucket, key, kwargs))
        return types.SimpleNamespace(signed_url="https://signed.example/x")

    def list_objects(self, bucket, **kwargs):
        self.calls.append(("list_objects", bucket, kwargs))
        return types.SimpleNamespace(
            contents=[
                types.SimpleNamespace(key="a.txt", size=3, last_modified="2026-01-01"),
                types.SimpleNamespace(key="b.txt", size=5, last_modified="2026-01-02"),
            ],
            is_truncated=False,
        )


# ── 闸门与参数校验 ────────────────────────────────────


def test_unknown_action_rejected(skill, creds):
    assert "unknown action" in skill.run({"action": "drop"})["error"]


def test_missing_credentials_returns_stub(skill, monkeypatch):
    monkeypatch.delenv("TOS_ACCESS_KEY", raising=False)
    result = skill.run({"action": "list"})
    assert result["status"] == "stub"
    assert "credential_missing" in result["error"]


def test_missing_sdk_is_reported_readably(skill, creds, monkeypatch):
    """闸门之外再兜一道：真到调用时缺 SDK 也要给可执行的提示。"""
    monkeypatch.setitem(sys.modules, "tos", None)  # import tos → ImportError
    result = skill.run({"action": "list"})
    assert result["status"] == "error"
    assert "pip install tos" in result["error"]


def test_missing_key_is_reported(skill, creds, monkeypatch):
    _install_fake_tos(monkeypatch, FakeClient())
    assert skill.run({"action": "sign_url"})["error"] == "missing key"


def test_missing_bucket_is_reported(skill, monkeypatch):
    for name in ("TOS_ACCESS_KEY", "TOS_SECRET_KEY", "TOS_REGION", "TOS_ENDPOINT"):
        monkeypatch.setenv(name, "x")
    monkeypatch.delenv("TOS_BUCKET", raising=False)
    _install_fake_tos(monkeypatch, FakeClient())
    assert "missing bucket" in skill.run({"action": "list"})["error"]


# ── 四个 action ───────────────────────────────────────


def test_upload_uses_resumable_upload(skill, creds, monkeypatch, tmp_path):
    client = FakeClient()
    _install_fake_tos(monkeypatch, client)
    local = tmp_path / "report.pdf"
    local.write_bytes(b"x" * 10)

    result = skill.run({"action": "upload", "key": "docs/report.pdf", "file_path": str(local)})

    assert result["status"] == "ok"
    assert result["size"] == 10
    assert result["request_id"] == "req-upload"
    name, bucket, key, path, kwargs = client.calls[0]
    assert (name, bucket, key, path) == ("upload_file", "my-bucket", "docs/report.pdf", str(local))
    assert kwargs["task_num"] == 3  # 分片并发：大文件才跑得动


def test_upload_reports_missing_local_file(skill, creds, monkeypatch):
    _install_fake_tos(monkeypatch, FakeClient())
    result = skill.run({"action": "upload", "key": "k", "file_path": "Z:/nope/none.bin"})
    assert result["status"] == "error"
    assert "file not found" in result["error"]


def test_download_writes_local_file(skill, creds, monkeypatch, tmp_path):
    client = FakeClient()
    _install_fake_tos(monkeypatch, client)
    target = tmp_path / "out.bin"

    result = skill.run({"action": "download", "key": "a.bin", "file_path": str(target)})

    assert result["status"] == "ok"
    assert target.read_bytes() == b"downloaded"
    assert result["size"] == 10


def test_download_reports_missing_target_dir(skill, creds, monkeypatch):
    _install_fake_tos(monkeypatch, FakeClient())
    result = skill.run({"action": "download", "key": "a", "file_path": "Z:/nope/a.bin"})
    assert result["status"] == "error"
    assert "目标目录不存在" in result["error"]


def test_sign_url_uses_get_and_default_expires(skill, creds, monkeypatch):
    client = FakeClient()
    _install_fake_tos(monkeypatch, client)

    result = skill.run({"action": "sign_url", "key": "a.txt"})

    assert result["url"] == "https://signed.example/x"
    assert result["expires"] == 3600
    name, method, bucket, key, kwargs = client.calls[0]
    assert (name, method, bucket, key) == ("pre_signed_url", "GET", "my-bucket", "a.txt")
    assert kwargs["expires"] == 3600


def test_sign_url_respects_custom_expires(skill, creds, monkeypatch):
    client = FakeClient()
    _install_fake_tos(monkeypatch, client)
    skill.run({"action": "sign_url", "key": "a.txt", "expires": 60})
    assert client.calls[0][4]["expires"] == 60


def test_list_returns_items_and_clamps_max_keys(skill, creds, monkeypatch):
    client = FakeClient()
    _install_fake_tos(monkeypatch, client)

    result = skill.run({"action": "list", "prefix": "docs/", "max_keys": 99999})

    assert result["count"] == 2
    assert result["items"][0]["key"] == "a.txt"
    assert result["truncated"] is False
    assert client.calls[0][2] == {"prefix": "docs/", "max_keys": 1000}  # 收口到上限


def test_list_rejects_non_numeric_max_keys(skill, creds, monkeypatch):
    _install_fake_tos(monkeypatch, FakeClient())
    assert skill.run({"action": "list", "max_keys": "many"})["error"] == "invalid max_keys"


def test_bucket_arg_overrides_env(skill, creds, monkeypatch):
    client = FakeClient()
    _install_fake_tos(monkeypatch, client)
    skill.run({"action": "list", "bucket": "other-bucket"})
    assert client.calls[0][1] == "other-bucket"


# ── 失败如实透出 ──────────────────────────────────────


def test_server_error_carries_code_and_request_id(skill, creds, monkeypatch):
    """服务端拒绝时，code 与 request_id 是排查的关键，必须带出来。"""
    _install_fake_tos(monkeypatch, FakeClient(), error=TosServerError())

    result = skill.run({"action": "list"})

    assert result["status"] == "error"
    assert "AccessDenied" in result["error"]
    assert result["request_id"] == "req-abc"
    assert result["http_status"] == 403


def test_client_error_is_reported(skill, creds, monkeypatch):
    _install_fake_tos(monkeypatch, FakeClient(), error=TosClientError(message="param invalid"))

    result = skill.run({"action": "list"})

    assert result["status"] == "error"
    assert "client_error" in result["error"]
    assert "param invalid" in result["error"]
