"""Aerie · 云栖 — 伊塔出站收藏表情包（QQ 收藏 GIF 表情）发送器.

背景：账号「伊塔」在 QQ 收藏夹里预先配备了一批表情包。本模块让伊塔
在合适时机把它们发给用户：

- ``fetch_custom_face``（QQ 引擎扩展接口）拉取收藏表情 URL 列表。
- 用视觉模型给每张表情打「情绪标签」（懒加载 + JSON 缓存），供规则按情绪挑图。
- 发送前由调用方注入一个「轻量 LLM 决策」回调，决定这条回复要不要配表情。
- 规则从收藏里挑一张匹配情绪的表情，通过 ``send_image`` 直接发 URL（无需下载）。

所有失败一律降级：拉不到收藏 → 不发表情；视觉打标不可用 → 随机挑；
LLM 决策失败 → 确定性兜底。绝不阻塞主回复链路。
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 情绪键 → 中文种子词（用于把视觉描述/标签映射到情绪键）
EMOTION_SEEDS: dict[str, tuple[str, ...]] = {
    "joy": ("开心", "高兴", "笑", "嘿嘿", "哈哈", "happy", "joy"),
    "love": ("喜欢", "爱你", "抱抱", "亲亲", "比心", "heart", "love"),
    "encourage": ("加油", "棒", "厉害", "赞", "鼓掌", "give", "鼓励"),
    "console": ("安慰", "别难过", "摸摸", "抱抱", "陪你"),
    "greeting": ("你好", "嗨", "早安", "晚安", "hello", "hi"),
    "farewell": ("再见", "拜拜", "回聊"),
    "cute": ("可爱", "卖萌", "喵", "狗狗", "猫猫", "撒娇", "cute"),
    "cool": ("酷", "帅", "墨镜", "cool"),
    "shy": ("害羞", "脸红", "捂脸"),
    "angry": ("生气", "哼", "发怒"),
    "sad": ("难过", "哭", "委屈", "心碎"),
    "surprised": ("惊讶", "震惊", "哇", "？"),
    "sleepy": ("困", "晚安", "睡", "打哈欠"),
    "thanks": ("谢谢", "感谢", "么么哒", "thank"),
}

_VISION_QUESTION = (
    "用一个或多个中文词描述这张表情包传达的情绪或含义，词与词用逗号分隔，"
    "例如：开心,可爱。只输出词本身，不要解释，不要标点以外的符号。"
)

# 确定性兜底：情绪强烈程度 → 是否自动配表情（LLM 决策不可用时的退路）
_STICKER_WORTHY_EMOTIONS = {"joy", "love", "cute", "encourage", "console", "greeting", "cute", "thanks"}


def emotion_keys_for_description(description: str) -> list[str]:
    """把视觉模型给出的描述/标签映射到情绪键列表。"""
    text = str(description or "")
    if not text:
        return []
    keys: list[str] = []
    for key, seeds in EMOTION_SEEDS.items():
        if any(seed in text for seed in seeds):
            keys.append(key)
    return keys


class QQStickerLibrary:
    """收藏表情库：拉取、打标、按情绪挑图。

    - 情绪标签懒加载：只有 ``pick`` 需要匹配时才对未打标的表情打标（限量），
      结果缓存在 JSON 里，后续复用。
    - 视觉不可用或打标失败时，``pick`` 退化为随机挑一张。
    """

    def __init__(
        self,
        qq_client: Any,
        vision: Any = None,
        cache_path: str | Path | None = None,
        tag_limit: int = 16,
    ) -> None:
        self.qq = qq_client
        self.vision = vision
        self.cache_path = Path(cache_path) if cache_path else _PROJECT_ROOT / "data" / "qq_sticker_cache.json"
        self.tag_limit = int(tag_limit)
        # url -> {"tags": [...], "desc": str, "ts": float}
        self._cache: dict[str, dict] = {}
        self._urls: list[str] = []
        self._last_refresh = 0.0
        self._load_cache()

    # ── 缓存 ───────────────────────────────────
    def _load_cache(self) -> None:
        try:
            if self.cache_path.exists():
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                self._cache = {k: v for k, v in (data.get("stickers") or {}).items() if isinstance(v, dict)}
                self._urls = list(self._cache.keys())
        except Exception:
            logger.debug("qq sticker cache load failed", exc_info=True)

    def _save_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps({"stickers": self._cache}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            logger.debug("qq sticker cache save failed", exc_info=True)

    # ── 拉取 ───────────────────────────────────
    async def refresh(self, count: int = 48) -> list[str]:
        """拉取收藏表情 URL，合并/去重并缓存。失败返回当前列表。"""
        if not self.qq:
            return self._urls
        try:
            fetched = await self.qq.fetch_custom_face(count=count)
        except Exception as e:
            logger.warning("qq fetch_custom_face failed: %s", e)
            fetched = []
        if fetched:
            self._urls = list(dict.fromkeys(fetched))  # 去重保序
            for url in self._urls:
                self._cache.setdefault(url, {"tags": [], "desc": "", "ts": 0.0})
            # 移除已不存在的
            self._cache = {k: v for k, v in self._cache.items() if k in set(self._urls)}
            self._save_cache()
            self._last_refresh = time.time()
        return self._urls

    @property
    def available(self) -> bool:
        return bool(self._urls)

    def size(self) -> int:
        return len(self._urls)

    # ── 打标（懒加载）──────────────────────────
    def _needs_tagging(self) -> list[str]:
        return [u for u in self._urls if not self._cache.get(u, {}).get("tags")]

    async def tag_new(self, limit: int | None = None) -> int:
        """对未打标的表情打标，最多 ``limit`` 张（默认 self.tag_limit）。"""
        if not self.vision:
            return 0
        pending = self._needs_tagging()
        limit = self.tag_limit if limit is None else int(limit)
        done = 0
        for url in pending[:limit]:
            desc = await self._describe_url(url)
            if not desc:
                continue
            tags = emotion_keys_for_description(desc)
            self._cache[url] = {
                "tags": tags or ["unknown"],
                "desc": desc[:120],
                "ts": time.time(),
            }
            done += 1
        if done:
            self._save_cache()
        return done

    async def _describe_url(self, url: str) -> str:
        """下载 URL → 视觉描述。失败返回空串。"""
        path = await self._download(url)
        if not path:
            return ""
        try:
            return await self.vision.describe(path, question=_VISION_QUESTION)
        except Exception:
            logger.debug("qq sticker vision describe failed: %s", url, exc_info=True)
            return ""
        finally:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass

    async def _download(self, url: str) -> str | None:
        import httpx

        dest = _PROJECT_ROOT / "data" / "qq_media" / f"sticker_tag_{uuid.uuid4().hex}.img"
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
            return str(dest)
        except Exception as e:
            logger.debug("qq sticker download failed (%s): %s", url[:60], e)
            return None

    # ── 挑图 ───────────────────────────────────
    def pick(self, emotion: str = "") -> str | None:
        """按情绪挑一张表情 URL；未打标或无匹配时随机。"""
        if not self._urls:
            return None
        emotion = (emotion or "").strip()
        if emotion:
            matches = [
                u for u in self._urls
                if emotion in (self._cache.get(u, {}).get("tags") or [])
            ]
            if matches:
                return random.choice(matches)
        tagged = [u for u in self._urls if self._cache.get(u, {}).get("tags")]
        if tagged:
            return random.choice(tagged)
        return random.choice(self._urls)


class QQStickerSender:
    """出站表情发送器。

    流程：库就绪 → 调用方决策回调（决定要不要 + 情绪）→ 规则挑图 → send_image。
    - ``decide``：``Callable[[str, str], Awaitable[tuple[bool, str]]]``，
      入参 (reply_text, emotion_label)，返回 (是否发送, 情绪键)。失败时用
      ``_fallback_decide`` 确定性兜底。
    - 发送前有节流（每用户最小间隔）与审计。
    """

    def __init__(
        self,
        qq_client: Any,
        library: QQStickerLibrary | None = None,
        decide: Optional[Callable[..., Any]] = None,
        min_interval: float = 90.0,
        gate: Any = None,
    ) -> None:
        self.qq = qq_client
        self.library = library or QQStickerLibrary(qq_client=qq_client)
        self.decide = decide
        self.min_interval = float(min_interval)
        self.gate = gate
        self._last_sent: dict[int, float] = {}

    async def maybe_send(self, user_id: int, reply_text: str, emotion_label: str = "") -> bool:
        """尝试给 ``user_id`` 发一张收藏表情。返回是否发送成功。"""
        if not self.qq:
            return False
        # 1. 库就绪
        if not self.library.available:
            try:
                await self.library.refresh()
            except Exception:
                logger.debug("sticker refresh failed", exc_info=True)
            if not self.library.available:
                logger.info("no QQ favorite stickers available; skip send")
                return False

        # 2. 决策：要不要 + 情绪
        should, emotion = await self._decide(reply_text, emotion_label)
        if not should:
            return False

        # 3. 尽量为情绪打标，然后挑图
        try:
            await self.library.tag_new(limit=6)
        except Exception:
            logger.debug("sticker tag_new failed", exc_info=True)
        url = self.library.pick(emotion)
        if not url:
            return False

        # 4. 节流
        now = time.time()
        last = self._last_sent.get(int(user_id), 0.0)
        if now - last < self.min_interval:
            return False
        self._last_sent[int(user_id)] = now

        # 5. 发送（send_image 直接发 URL）
        try:
            ok = await self.qq.send_image(int(user_id), url)
        except Exception as e:
            logger.warning("sticker send_image failed for %s: %s", user_id, e)
            return False
        if self.gate is not None:
            try:
                self.gate.allow_send(url, str(user_id))
            except Exception:
                pass
        return ok

    async def _decide(self, reply_text: str, emotion_label: str) -> tuple[bool, str]:
        if self.decide is not None:
            try:
                result = self.decide(reply_text, emotion_label)
                if hasattr(result, "__await__"):
                    result = await result
                if isinstance(result, (tuple, list)) and len(result) == 2:
                    should, emotion = bool(result[0]), str(result[1] or emotion_label or "")
                    return should, emotion
            except Exception:
                logger.debug("sticker decide failed; fallback", exc_info=True)
        return self._fallback_decide(reply_text, emotion_label)

    @staticmethod
    def _fallback_decide(reply_text: str, emotion_label: str) -> tuple[bool, str]:
        """确定性兜底：情绪标签值得发 → 发；否则不发。"""
        emo = (emotion_label or "").strip().lower()
        if emo in _STICKER_WORTHY_EMOTIONS:
            return True, emo
        return False, emo
