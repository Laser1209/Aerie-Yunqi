"""Portal G-1: 角色级对话与记忆隔离 — 集成测试（端到端）.

在迁移 013/014 之上，用 conversation_repository + persona_manager +
memory adapter 三者协同验证角色隔离（不依赖真实 data/，全部走临时
AERIE_DATA_DIR / tempfile）：

0. 迁移链端到端：013/014 后 chat_log / conversations / turns / messages /
   requests / long_term_memory / conversation_summary_buckets / persona_timeline
   8 张目标表均含 persona_id 列（PRAGMA table_info）。
1. 写链端到端：persona_a / persona_b 各写入一轮 turn，
   断言 conversations / turns / requests / messages 行 persona_id 正确落库。
2. 读链端到端：history_page(persona_id=persona_a) 只含 persona_a + NULL 共享；
   persona_b 同理；纯 persona 会话（无 NULL 共享）也不串台；无激活角色时
   显式 None 查询退化为共享兜底（仅 NULL 共享会话可见，persona 专属不串台）。
3. 切换语义：switch_persona("persona_a") 后 active_persona_id() == "persona_a"，
   history_page 不带 persona_id（自动取激活角色）返回 persona_a + NULL 共享。
4. 记忆隔离：LayeredMemorySyncAdapter.store(..., persona_id=...) 写入偏好，
   retrieve 时 persona_a 能召回、persona_b 不能（跨角色零泄漏）。
5. 零污染：module teardown 断言真实 data/personas 无新增文件。

隔离模式参考 tests/test_persona_generator.py（模块顶部设置 AERIE_DATA_DIR
到 tempfile 并重置 PersonaManager._instance）。
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from core.conversation_repository import (
    ConversationRepository,
    active_persona_id,
    resolve_conversation_id,
)
from core.persona_hub.persona_manager import PersonaManager, get_persona_manager

# ── data-dir isolation (never touch the real data/) ──────
_ORIG_INSTANCE = getattr(PersonaManager, "_instance", None)
_ORIG_DATA_DIR = os.environ.get("AERIE_DATA_DIR")
_ISO_TMP = tempfile.mkdtemp(prefix="aerie-iso-test-")
os.environ["AERIE_DATA_DIR"] = _ISO_TMP
PersonaManager._instance = None  # 下一个 get_persona_manager() 使用临时目录

_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent
    / "core"
    / "persona_hub"
    / "preset_templates"
    / "yita_default.json"
)
_REAL_PERSONA_DIR = Path(__file__).resolve().parent.parent / "data" / "personas"

# 对话四元组（user_id 固定 7，模拟同一用户）
_CHANNEL = dict(
    actor_id="a",
    channel="desktop",
    channel_account_id="local",
    user_id=7,
)


def _restore_persona_state() -> None:
    PersonaManager._instance = _ORIG_INSTANCE
    if _ORIG_DATA_DIR is None:
        os.environ.pop("AERIE_DATA_DIR", None)
    else:
        os.environ["AERIE_DATA_DIR"] = _ORIG_DATA_DIR


def _load_template() -> dict:
    with open(_TEMPLATE_PATH, encoding="utf-8") as fp:
        return json.load(fp)


def _make_persona(persona_id: str, name: str) -> dict:
    """深拷贝伊塔模板改 id/name 构造合法人设（参考 test_persona_generator 骨架复制方式）。"""
    data = copy.deepcopy(_load_template())
    data["id"] = persona_id
    data["name"] = name
    data["basic"]["name"] = name
    data["is_builtin"] = False
    return data


def _create_personas() -> None:
    mgr = get_persona_manager()
    ok, msg = mgr.create_persona(_make_persona("persona_a", "角色A"))
    assert ok, f"创建 persona_a 失败: {msg}"
    ok, msg = mgr.create_persona(_make_persona("persona_b", "角色B"))
    assert ok, f"创建 persona_b 失败: {msg}"


def _persist(repo, *, persona_id, request_id, content, reply):
    cid = resolve_conversation_id(persona_id=persona_id, **_CHANNEL)
    result = repo.persist_turn(
        request_id=request_id,
        user_content=content,
        user_attachments=None,
        assistant_segments=[reply],
        persona_id=persona_id,
        **_CHANNEL,
    )
    assert result, f"persist_turn({request_id}) 返回空"
    return cid


def _history_contents(repo, *, persona_id=None):
    page = repo.history_page(persona_id=persona_id, **_CHANNEL)
    return {item["content"] for item in page["items"]}


@pytest.fixture(autouse=True)
def _iso_isolated(tmp_path):
    """每个测试指向独立临时目录并重置 PersonaManager 单例。"""
    PersonaManager._instance = None
    os.environ["AERIE_DATA_DIR"] = str(tmp_path)
    yield
    _restore_persona_state()


@pytest.fixture(scope="module", autouse=True)
def _iso_tmpdir_cleanup():
    """清理模块级临时目录。"""
    yield
    shutil.rmtree(_ISO_TMP, ignore_errors=True)


@pytest.fixture(scope="module", autouse=True)
def _zero_pollution_guard():
    """零污染：真实 data/personas 目录不得出现测试写入的文件。"""
    before = (
        {p.name for p in _REAL_PERSONA_DIR.glob("*.json")}
        if _REAL_PERSONA_DIR.exists()
        else set()
    )
    try:
        yield
    finally:
        after = (
            {p.name for p in _REAL_PERSONA_DIR.glob("*.json")}
            if _REAL_PERSONA_DIR.exists()
            else set()
        )
        assert before == after, (
            f"真实 data/personas 被测试污染: 新增 {sorted(after - before)}"
        )


@pytest.fixture()
def iso_db(tmp_path, monkeypatch):
    """独立临时 SQLite DB（迁移框架开启，含 013/014 persona 列）。"""
    from core.database import Database

    monkeypatch.setenv("AERIE_FEATURE_MIGRATION_FRAMEWORK_V1", "true")
    Database.reset_instance()
    db = Database(tmp_path / "iso.db")
    # conversations.actor_id REFERENCES actors(actor_id)（foreign_keys=ON），
    # 预置测试 actor，避免 persist_turn 时外键约束失败。
    db.execute("INSERT OR IGNORE INTO actors (actor_id) VALUES ('a')")
    try:
        yield db
    finally:
        Database.reset_instance()


def test_migration_chain_persona_columns(iso_db, tmp_path):
    """迁移链端到端：013/014 后 8 张目标表均含 persona_id 列（PRAGMA）。"""
    tables = [
        "chat_log", "conversations", "turns", "messages", "requests",
        "long_term_memory", "conversation_summary_buckets", "persona_timeline",
    ]
    for table in tables:
        cols = {
            row["name"]
            for row in iso_db.query(f"PRAGMA table_info({table})")
        }
        assert "persona_id" in cols, f"迁移 013/014 未给 {table} 加 persona_id 列"


def test_write_chain_persona_rows(iso_db, tmp_path):
    """写链端到端：conversations/turns/requests/messages 行 persona_id 正确落库。"""
    _create_personas()
    repo = ConversationRepository(iso_db, enabled=True)

    cid_a = _persist(
        repo, persona_id="persona_a", request_id="req_a",
        content="你好A", reply="A的回应",
    )
    cid_b = _persist(
        repo, persona_id="persona_b", request_id="req_b",
        content="你好B", reply="B的回应",
    )
    assert cid_a != cid_b, "不同角色的会话 ID 必须不同"

    conv_persona = {
        r["conversation_id"]: r["persona_id"]
        for r in iso_db.query("SELECT conversation_id, persona_id FROM conversations")
    }
    msg_persona = {
        r["conversation_id"]: r["persona_id"]
        for r in iso_db.query(
            "SELECT DISTINCT conversation_id, persona_id FROM messages"
        )
    }
    assert conv_persona[cid_a] == "persona_a"
    assert conv_persona[cid_b] == "persona_b"
    assert msg_persona[cid_a] == "persona_a"
    assert msg_persona[cid_b] == "persona_b"

    turn_personas = {
        r["persona_id"]
        for r in iso_db.query("SELECT DISTINCT persona_id FROM turns")
    }
    req_personas = {
        r["persona_id"]
        for r in iso_db.query("SELECT DISTINCT persona_id FROM requests")
    }
    assert turn_personas == {"persona_a", "persona_b"}
    assert req_personas == {"persona_a", "persona_b"}


def test_read_chain_persona_scoped(iso_db, tmp_path, monkeypatch):
    """读链端到端：persona_a 只看到 A + NULL 共享；persona_b 同理；None 共享兜底。"""
    _create_personas()
    repo = ConversationRepository(iso_db, enabled=True)

    _persist(repo, persona_id=None, request_id="req_shared", content="共享问题", reply="共享回答")
    _persist(repo, persona_id="persona_a", request_id="req_a", content="A的问题", reply="A的回答")
    _persist(repo, persona_id="persona_b", request_id="req_b", content="B的问题", reply="B的回答")

    contents_a = _history_contents(repo, persona_id="persona_a")
    assert contents_a == {"共享问题", "共享回答", "A的问题", "A的回答"}
    assert not (contents_a & {"B的问题", "B的回答"}), "persona_a 不得看到 persona_b 的消息"

    contents_b = _history_contents(repo, persona_id="persona_b")
    assert contents_b == {"共享问题", "共享回答", "B的问题", "B的回答"}
    assert not (contents_b & {"A的问题", "A的回答"}), "persona_b 不得看到 persona_a 的消息"

    # 无激活角色（active_persona_id 为 None）时，显式 None 查询退化为共享兜底：
    # 仅 NULL 共享会话可见（会话 ID 哈希含 persona 维度），persona 专属不串台。
    monkeypatch.setattr(
        "core.conversation_repository.active_persona_id", lambda: None
    )
    none_contents = _history_contents(repo, persona_id=None)
    assert none_contents == {"共享问题", "共享回答"}, f"None 共享兜底异常: {none_contents}"


def test_read_chain_persona_only_no_shared(iso_db, tmp_path):
    """无 NULL 共享会话时，读链也必须只返回本角色（conversation_id 跟随 persona）。"""
    _create_personas()
    repo = ConversationRepository(iso_db, enabled=True)

    _persist(repo, persona_id="persona_a", request_id="req_a", content="A的问题", reply="A的回答")
    _persist(repo, persona_id="persona_b", request_id="req_b", content="B的问题", reply="B的回答")

    contents_a = _history_contents(repo, persona_id="persona_a")
    assert contents_a == {"A的问题", "A的回答"}, f"persona_a 读链异常: {contents_a}"

    contents_b = _history_contents(repo, persona_id="persona_b")
    assert contents_b == {"B的问题", "B的回答"}, f"persona_b 读链异常: {contents_b}"


def test_switch_persona_follows_active_role(iso_db, tmp_path):
    """切换语义：switch_persona 后 history_page 不带 persona_id 自动跟随激活角色。"""
    _create_personas()
    mgr = get_persona_manager()
    repo = ConversationRepository(iso_db, enabled=True)

    _persist(repo, persona_id=None, request_id="req_shared", content="共享问题", reply="共享回答")
    _persist(repo, persona_id="persona_a", request_id="req_a", content="A的问题", reply="A的回答")
    _persist(repo, persona_id="persona_b", request_id="req_b", content="B的问题", reply="B的回答")

    ok, msg = mgr.switch_persona("persona_a")
    assert ok, msg
    assert mgr.get_active_id() == "persona_a"
    assert active_persona_id() == "persona_a"
    assert _history_contents(repo) == {"共享问题", "共享回答", "A的问题", "A的回答"}

    ok, msg = mgr.switch_persona("persona_b")
    assert ok, msg
    assert _history_contents(repo) == {"共享问题", "共享回答", "B的问题", "B的回答"}


def test_memory_isolation_store_retrieve(iso_db, tmp_path):
    """记忆隔离：persona_a 写入的偏好，persona_a 能召回、persona_b 不能。"""
    from memory.layers import LayeredMemory
    from memory.layers.sync_adapter import LayeredMemorySyncAdapter

    layered = LayeredMemory(
        db=iso_db,
        chroma_persist_dir=str(tmp_path / "chroma"),
        permanent_dir=str(tmp_path / "permanent"),
    )
    adapter = LayeredMemorySyncAdapter(layered)

    adapter.store(
        7, "preference", "用户喜欢喝美式咖啡", importance=8, persona_id="persona_a"
    )
    adapter.store(
        7, "preference", "用户喜欢喝抹茶拿铁", importance=8, persona_id="persona_b"
    )

    hits_a = {
        r["content"]
        for r in adapter.retrieve(7, "咖啡", limit=10, persona_id="persona_a")
    }
    hits_b = {
        r["content"]
        for r in adapter.retrieve(7, "咖啡", limit=10, persona_id="persona_b")
    }

    assert "用户喜欢喝美式咖啡" in hits_a
    assert "用户喜欢喝抹茶拿铁" not in hits_a, "persona_a 不得召回 persona_b 的偏好"
    assert "用户喜欢喝抹茶拿铁" in hits_b
    assert "用户喜欢喝美式咖啡" not in hits_b, "persona_b 不得召回 persona_a 的偏好"
