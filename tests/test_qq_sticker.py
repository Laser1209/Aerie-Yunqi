"""Tests for core.qq_sticker — 伊塔出站收藏表情包发送器.

覆盖：fetch_custom_face 拉取、视觉打标缓存、按情绪挑图、轻量 LLM 决策、
以及降级回退。全部用 mock 隔离外部依赖，不联网。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.qq_sticker import (
    QQStickerLibrary,
    QQStickerSender,
    emotion_keys_for_description,
)


def _qq(faces=("http://a/1.gif", "http://a/2.gif")):
    qq = MagicMock()
    qq.fetch_custom_face = AsyncMock(return_value=list(faces))
    qq.send_image = AsyncMock(return_value=True)
    return qq


# ── 情绪关键词映射 ──────────────────────────────
def test_emotion_keys_mapping():
    assert "joy" in emotion_keys_for_description("开心,可爱")
    assert "cute" in emotion_keys_for_description("开心,可爱")
    assert emotion_keys_for_description("") == []


# ── 拉取 + 打标 + 按情绪挑图 ─────────────────────
@pytest.mark.asyncio
async def test_refresh_and_pick_by_emotion(tmp_path):
    qq = _qq()
    vis = MagicMock()
    vis.describe = AsyncMock(side_effect=lambda p, q: "开心,可爱" if "1.gif" in p else "加油,棒")

    lib = QQStickerLibrary(qq_client=qq, vision=vis, cache_path=tmp_path / "c.json")
    lib._download = AsyncMock(side_effect=lambda u: "local_" + u.split("/")[-1])

    await lib.refresh()
    assert lib.size() == 2
    assert await lib.tag_new() == 2
    assert lib.pick("joy").endswith("1.gif")
    assert lib.pick("encourage").endswith("2.gif")


@pytest.mark.asyncio
async def test_no_vision_falls_back_to_random(tmp_path):
    qq = _qq()
    lib = QQStickerLibrary(qq_client=qq, vision=None, cache_path=tmp_path / "c.json")
    await lib.refresh()
    # 无视觉 → 打标为 0，但仍能随机挑一张
    assert await lib.tag_new() == 0
    assert lib.pick("joy") in {"http://a/1.gif", "http://a/2.gif"}


# ── 发送器：决策 + 节流 + 发送 ────────────────────
@pytest.mark.asyncio
async def test_sender_decides_yes_and_sends(tmp_path):
    qq = _qq()
    lib = QQStickerLibrary(qq_client=qq, vision=None, cache_path=tmp_path / "c.json")
    lib.refresh = AsyncMock(return_value=["http://a/1.gif", "http://a/2.gif"])
    lib._urls = ["http://a/1.gif", "http://a/2.gif"]
    lib.available = True

    async def decide(text, emo):
        return True, "joy"

    snd = QQStickerSender(qq_client=qq, library=lib, decide=decide, min_interval=0)
    ok = await snd.maybe_send(123, "想你", "joy")
    assert ok
    qq.send_image.assert_awaited_once()
    assert qq.send_image.call_args[0][0] == 123


@pytest.mark.asyncio
async def test_sender_decides_no_skips(tmp_path):
    qq = _qq()
    lib = QQStickerLibrary(qq_client=qq, vision=None, cache_path=tmp_path / "c.json")
    lib.refresh = AsyncMock(return_value=["http://a/1.gif"])
    lib._urls = ["http://a/1.gif"]
    lib.available = True

    async def decide(text, emo):
        return False, ""

    snd = QQStickerSender(qq_client=qq, library=lib, decide=decide, min_interval=0)
    assert await snd.maybe_send(124, "好的", "neutral") is False
    qq.send_image.assert_not_awaited()


# ── 确定性兜底 ───────────────────────────────────
def test_fallback_decide():
    assert QQStickerSender._fallback_decide("x", "joy")[0] is True
    assert QQStickerSender._fallback_decide("x", "neutral")[0] is False
