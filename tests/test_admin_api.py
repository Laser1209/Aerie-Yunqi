"""Aerie · P4b 管理 API HTTP 集成测试（§3.5.2）.

经 FastAPI TestClient 走真实 HTTP 链：
- 未解锁访问 → 403
- unlock 门闩 → token 校验
- 会话级联软删 / 恢复 / purge
- 记忆 / 审计 / 状态 端点
- 锁定后 token 失效
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


class _FakeRuntimeConfig:
    def __init__(self) -> None:
        self.values: dict = {"admin_unlocked": False}
        self.revision = 0

    def snapshot(self) -> dict:
        return {"revision": self.revision, "values": dict(self.values)}

    def update(self, changes: dict, *, expected_revision: int) -> dict:
        if int(expected_revision) != self.revision:
            raise RuntimeError("revision conflict")
        self.values.update(changes)
        self.revision += 1
        return self.snapshot()


@pytest.fixture
def api_env(tmp_path, monkeypatch):
    """隔离 data 目录 + mock companion + 重置 admin 单例。"""
    monkeypatch.setenv("AERIE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AERIE_MAIN_PROCESS_TOKEN", "test-main-token")

    companion = MagicMock()
    companion.runtime_config_service = _FakeRuntimeConfig()
    companion.topic_tracker = MagicMock()
    companion.topic_tracker.reset = MagicMock()
    companion.memory = MagicMock()
    companion.get_primary_user_selection = MagicMock(
        return_value=SimpleNamespace(user_id=1, as_dict=lambda: {"primaryUserId": 1, "source": "test"})
    )

    from core import api_server

    # 让 AdminService 以当前环境重新构造（避免复用其它测试的实例）
    api_server._admin_service_instance = None
    with patch.object(api_server, "get_companion", return_value=companion):
        yield {"client": TestClient(api_server.app), "data_dir": tmp_path / "data"}
    api_server._admin_service_instance = None


def _seed_conversation(db, conversation_id: str, content: str) -> None:
    db.insert(
        "conversations",
        {"conversation_id": conversation_id, "actor_id": None, "channel": "desktop"},
    )
    db.insert(
        "turns",
        {
            "turn_id": f"turn-{conversation_id}",
            "conversation_id": conversation_id,
            "status": "completed",
            "created_at": "2026-08-01 10:00:00",
        },
    )
    db.insert(
        "messages",
        {
            "message_id": f"msg-{conversation_id}",
            "conversation_id": conversation_id,
            "turn_id": f"turn-{conversation_id}",
            "role": "user",
            "content": content,
            "sequence": 1,
            "channel": "desktop",
        },
    )


def test_admin_latch_gates_all_endpoints(api_env):
    client = api_env["client"]
    assert client.get("/api/admin/status").json()["unlocked"] is False
    # 未解锁 → 403
    assert client.get("/api/admin/conversations").status_code == 403
    assert client.post("/api/admin/conversations/trash", json={"conversation_ids": ["x"]}).status_code == 403
    # 解锁 → 拿到 token
    token = client.post("/api/admin/unlock").json()["token"]
    assert token
    headers = {"X-Aerie-Admin-Token": token}
    assert client.get("/api/admin/status", headers=headers).json()["unlocked"] is True
    # 错误 token → 403
    assert client.get("/api/admin/conversations", headers={"X-Aerie-Admin-Token": "wrong"}).status_code == 403
    # 锁定后 token 失效
    client.post("/api/admin/lock")
    assert client.get("/api/admin/conversations", headers=headers).status_code == 403


def test_admin_cross_origin_guard_blocks_web_pages(api_env):
    """任意网页（http/https Origin）跨源调用管理 API 一律 403（安全审查 #1 修复）。"""
    client = api_env["client"]
    evil = {"Origin": "https://evil.example"}
    # 跨源网页不能解锁（拿不到 token）
    assert client.post("/api/admin/unlock", headers=evil).status_code == 403
    # 跨源网页不能访问任何管理端点
    assert client.get("/api/admin/status", headers=evil).status_code == 403
    assert client.get("/api/admin/conversations", headers=evil).status_code == 403
    assert client.post(
        "/api/admin/trash/purge", headers=evil, json={"all": True}
    ).status_code == 403
    # 合法来源不受影响：无 Origin（同源/内部调用）与 file://（Electron）
    assert client.post("/api/admin/unlock").status_code == 200
    assert client.get("/api/admin/status", headers={"Origin": "file://"}).status_code == 200
    assert client.get("/api/admin/status", headers={"Origin": "null"}).status_code == 200


def test_admin_conversation_trash_restore_purge_chain(api_env):
    from core.database import Database

    client = api_env["client"]
    token = client.post("/api/admin/unlock").json()["token"]
    headers = {"X-Aerie-Admin-Token": token}

    _seed_conversation(Database(), "conv-api-a", "接口测试消息")
    listed = client.get("/api/admin/conversations", headers=headers).json()
    assert any(c["conversation_id"] == "conv-api-a" for c in listed["items"])

    # 软删
    trashed = client.post(
        "/api/admin/conversations/trash", headers=headers,
        json={"conversation_ids": ["conv-api-a"]},
    ).json()
    assert trashed["trashed_messages"] == 1
    assert client.post(
        "/api/admin/conversations/trash", headers=headers,
        json={"conversation_ids": []},
    ).status_code == 400

    # 恢复
    restored = client.post(
        "/api/admin/conversations/restore", headers=headers,
        json={"conversation_ids": ["conv-api-a"]},
    ).json()
    assert restored["restored_messages"] == 1

    # purge（回收站为空时返回 0 计数）
    purged = client.post("/api/admin/trash/purge", headers=headers, json={"all": False}).json()
    assert "messages" in purged


def test_admin_memory_audit_state(api_env):
    from core.database import Database

    client = api_env["client"]
    token = client.post("/api/admin/unlock").json()["token"]
    headers = {"X-Aerie-Admin-Token": token}

    # 记忆端点（含回收站视图）
    mem = client.get("/api/admin/memory?layer=long_term", headers=headers).json()
    assert "items" in mem and "total" in mem

    # 状态文件查看
    states = client.get("/api/admin/state", headers=headers).json()
    kinds = {s["kind"] for s in states["items"]}
    assert kinds == {"desire", "proactive", "topic", "runtime"}

    # 审计（unlock 不落审计，trash 才落）
    client.post("/api/admin/conversations/trash", headers=headers, json={"conversation_ids": ["nope-1"]})
    audit = client.get("/api/admin/audit?limit=10", headers=headers).json()
    assert audit["items"], "审计必须有记录"
    assert audit["items"][0]["actor"] == "local_user"
