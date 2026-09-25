"""C5：本地 HTTP 敏感写端点的跨源守卫测试。

不验证业务逻辑，只验证 Origin 门闩：
- 任意公网网页 Origin 调权限切换/审批/工作区写端点 → 403；
- Electron file://、同源、无 Origin 的内部调用 → 不被门闩拦截。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.api_server import _is_sensitive_request, app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


EVIL_ORIGIN = "https://evil.example.com"


# ────────────────────────────────────────────── 纯判定函数


def test_sensitive_classification():
    # admin 前缀全方法敏感
    assert _is_sensitive_request("/api/admin/status", "GET") is True
    # 电脑操控：写敏感、读不敏感
    assert _is_sensitive_request("/api/computer_control/mode", "PUT") is True
    assert _is_sensitive_request("/api/computer_control/approvals/x/approve", "POST") is True
    assert _is_sensitive_request("/api/computer_control/mode", "GET") is False
    assert _is_sensitive_request("/api/computer_control/approvals/pending", "GET") is False
    # 工作区：写敏感（os.startfile 也是 POST）、浏览不敏感
    assert _is_sensitive_request("/api/workspace/roots/temp", "POST") is True
    assert _is_sensitive_request("/api/workspace/open", "POST") is True
    assert _is_sensitive_request("/api/workspace/tree", "GET") is False
    # 无关路径
    assert _is_sensitive_request("/api/stats/tokens", "POST") is False
    # 预检请求放行（实际写请求仍会被拦）
    assert _is_sensitive_request("/api/computer_control/mode", "OPTIONS") is False


# ────────────────────────────────────────────── HTTP 层


def test_set_mode_blocked_for_cross_site(client):
    resp = client.put(
        "/api/computer_control/mode",
        json={"mode": "full"},
        headers={"Origin": EVIL_ORIGIN},
    )
    assert resp.status_code == 403
    assert resp.json()["errorCode"] == "cross_origin_denied"


def test_approve_blocked_for_cross_site(client):
    resp = client.post(
        "/api/computer_control/approvals/call-1/approve",
        json={"whitelist": True},
        headers={"Origin": EVIL_ORIGIN},
    )
    assert resp.status_code == 403


def test_workspace_temp_root_blocked_for_cross_site(client):
    resp = client.post(
        "/api/workspace/roots/temp",
        json={"path": r"C:\Windows"},
        headers={"Origin": EVIL_ORIGIN},
    )
    assert resp.status_code == 403


def test_workspace_open_blocked_for_cross_site(client):
    resp = client.post(
        "/api/workspace/open",
        json={"path": "x"},
        headers={"Origin": EVIL_ORIGIN},
    )
    assert resp.status_code == 403


def test_admin_still_blocked_for_cross_site(client):
    resp = client.get("/api/admin/status", headers={"Origin": EVIL_ORIGIN})
    assert resp.status_code == 403


@pytest.mark.parametrize("origin", ["file://", "null", "app://", ""])
def test_electron_and_internal_origins_pass_guard(client, origin):
    headers = {"Origin": origin} if origin else {}
    resp = client.put(
        "/api/computer_control/mode", json={"mode": "full"}, headers=headers
    )
    # 过了 Origin 门闩即可：业务层可能返回 200/400/500，但绝不是 403 cross_origin
    if resp.status_code == 403:
        assert resp.json().get("errorCode") != "cross_origin_denied"


def test_same_origin_passes_guard(client):
    resp = client.post(
        "/api/workspace/roots/temp",
        json={"path": r"C:\Windows"},
        headers={"Origin": "http://testserver"},
    )
    if resp.status_code == 403:
        assert resp.json().get("errorCode") != "cross_origin_denied"


def test_read_endpoint_not_guard_blocked(client):
    resp = client.get(
        "/api/computer_control/mode", headers={"Origin": EVIL_ORIGIN}
    )
    if resp.status_code == 403:
        assert resp.json().get("errorCode") != "cross_origin_denied"
