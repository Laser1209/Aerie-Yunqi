"""TDD tests for Task P1-D.2: 表情包入口 (sticker gate).

覆盖:
  - 表情包数据结构: Sticker 含 id / path / label / emotions / scenes
  - 情绪标签 StickerEmotion 与场景标签 StickerScene
  - StickerCatalog 注册与按情绪 / 场景标签检索
  - StickerGate 发送审计 (send_audit 记录每次发送)
  - 用户关闭开关: 关闭后禁止发送并审计拒绝, 重新开启后恢复
"""

from __future__ import annotations

import time

import pytest


# ── 数据结构: 表情包 ─────────────────────────────
def test_sticker_has_emotion_and_scene_tags():
    from core.sticker_gate import Sticker

    s = Sticker(
        id="s1",
        path="stickers/joy.gif",
        label="开心",
        emotions=["joy", "thanks"],
        scenes=["celebration", "daily"],
    )
    assert s.id == "s1"
    assert s.path == "stickers/joy.gif"
    assert s.label == "开心"
    assert "joy" in s.emotions
    assert "thanks" in s.emotions
    assert "celebration" in s.scenes
    assert "daily" in s.scenes


# ── 数据结构: 标签枚举 ───────────────────────────
def test_sticker_emotion_enum_values():
    from core.sticker_gate import StickerEmotion

    assert StickerEmotion.JOY.value == "joy"
    assert StickerEmotion.LOVE.value == "love"
    assert StickerEmotion.ENCOURAGE.value == "encourage"
    assert StickerEmotion.THANKS.value == "thanks"


def test_sticker_scene_enum_values():
    from core.sticker_gate import StickerScene

    assert StickerScene.GREETING.value == "greeting"
    assert StickerScene.CELEBRATION.value == "celebration"
    assert StickerScene.CONSOLE.value == "console"
    assert StickerScene.FAREWELL.value == "farewell"


# ── 标签检索 ─────────────────────────────────────
@pytest.fixture
def catalog():
    from core.sticker_gate import Sticker, StickerCatalog

    cat = StickerCatalog()
    cat.register(
        Sticker(
            id="s_joy",
            path="stickers/joy.gif",
            label="开心",
            emotions=["joy"],
            scenes=["celebration", "greeting"],
        )
    )
    cat.register(
        Sticker(
            id="s_love",
            path="stickers/love.gif",
            label="爱你",
            emotions=["love"],
            scenes=["daily"],
        )
    )
    cat.register(
        Sticker(
            id="s_cheer",
            path="stickers/cheer.gif",
            label="加油",
            emotions=["encourage", "joy"],
            scenes=["console", "greeting"],
        )
    )
    return cat


def test_catalog_search_by_emotion(catalog):
    joy = catalog.search(emotion="joy")
    ids = {s.id for s in joy}
    assert ids == {"s_joy", "s_cheer"}


def test_catalog_search_by_scene(catalog):
    greeting = catalog.search(scene="greeting")
    ids = {s.id for s in greeting}
    assert ids == {"s_joy", "s_cheer"}


def test_catalog_search_by_emotion_and_scene(catalog):
    # 既要 encourage 情绪又要 greeting 场景
    matches = catalog.search(emotion="encourage", scene="greeting")
    ids = {s.id for s in matches}
    assert ids == {"s_cheer"}


def test_catalog_search_no_match_returns_empty(catalog):
    assert catalog.search(emotion="love", scene="farewell") == []


def test_catalog_search_no_filter_returns_all(catalog):
    assert len(catalog.search()) == 3


def test_catalog_register_duplicate_id_raises(catalog):
    from core.sticker_gate import Sticker

    with pytest.raises(ValueError):
        catalog.register(Sticker(id="s_joy", path="dup.gif"))


def test_catalog_get_by_id(catalog):
    assert catalog.get("s_love").label == "爱你"
    assert catalog.get("missing") is None


# ── 发送审计 ─────────────────────────────────────
def test_send_audit_records_entry():
    from core.sticker_gate import Sticker, StickerGate

    gate = StickerGate()
    s = Sticker(id="s1", path="a.gif", emotions=["joy"], scenes=["daily"])
    assert gate.allow_send(s, user_id="u1") is True
    assert len(gate.send_audit) == 1
    entry = gate.send_audit[0]
    assert entry["sticker_id"] == "s1"
    assert entry["user_id"] == "u1"
    assert entry["status"] == "sent"
    assert entry["timestamp"] > 0


def test_send_audit_accumulates():
    from core.sticker_gate import Sticker, StickerGate

    gate = StickerGate()
    s = Sticker(id="s1", path="a.gif", emotions=["joy"], scenes=["daily"])
    gate.allow_send(s, user_id="u1")
    time.sleep(0.01)
    gate.allow_send(s, user_id="u2")
    assert len(gate.send_audit) == 2
    assert gate.send_audit[1]["timestamp"] >= gate.send_audit[0]["timestamp"]


# ── 用户关闭开关 ─────────────────────────────────
def test_gate_enabled_by_default():
    from core.sticker_gate import StickerGate

    gate = StickerGate()
    assert gate.is_enabled is True


def test_disable_gate_blocks_send():
    from core.sticker_gate import Sticker, StickerGate

    gate = StickerGate()
    gate.set_enabled(False)
    assert gate.is_enabled is False
    s = Sticker(id="s1", path="a.gif", emotions=["joy"], scenes=["daily"])
    assert gate.allow_send(s, user_id="u1") is False


def test_denied_send_still_audited():
    from core.sticker_gate import Sticker, StickerGate

    gate = StickerGate()
    gate.set_enabled(False)
    s = Sticker(id="s1", path="a.gif", emotions=["joy"], scenes=["daily"])
    gate.allow_send(s, user_id="u1")
    assert len(gate.send_audit) == 1
    assert gate.send_audit[0]["status"] == "denied_disabled"
    assert gate.send_audit[0]["sticker_id"] == "s1"


def test_enable_restores_send():
    from core.sticker_gate import Sticker, StickerGate

    gate = StickerGate()
    gate.set_enabled(False)
    gate.set_enabled(True)
    s = Sticker(id="s1", path="a.gif", emotions=["joy"], scenes=["daily"])
    assert gate.allow_send(s, user_id="u1") is True
    assert gate.send_audit[-1]["status"] == "sent"
