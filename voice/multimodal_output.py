"""Aerie · 云栖 v11.3 — Multimodal Output Engine.

Unified TTS, image generation, and rich media output management.
Extends the existing v9.0 TTSEngine with scene templates, caching,
and fallback chains.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class VoiceStyle(str, Enum):
    """语音风格预设"""
    WARM = "warm"              # 温暖治愈
    CALM = "calm"              # 冷静知性
    PLAYFUL = "playful"        # 活泼俏皮
    SERIOUS = "serious"        # 严肃认真
    INTIMATE = "intimate"      # 亲昵温柔
    MORNING = "morning"        # 清晨活力
    NIGHT = "night"            # 夜晚低语


class TTSProvider(str, Enum):
    MINIMAX = "minimax"
    EDGE_TTS = "edge_tts"
    OPENAI = "openai"
    LOCAL = "local"


class ImageProvider(str, Enum):
    OPENAI = "openai"
    STABLE_DIFFUSION = "stable_diffusion"
    DOODLE = "doodle"          # fallback: 简单 SVG 占位


@dataclass
class TTSResult:
    """TTS 合成结果"""
    success: bool
    audio_path: Optional[str] = None
    duration_sec: float = 0.0
    text: str = ""
    style: str = VoiceStyle.WARM
    provider: str = ""
    error: str = ""
    cached: bool = False

    @property
    def is_valid(self) -> bool:
        return self.success and bool(self.audio_path) and Path(self.audio_path).exists()


@dataclass
class ImageResult:
    """图片生成结果"""
    success: bool
    image_path: Optional[str] = None
    prompt: str = ""
    width: int = 1024
    height: int = 1024
    provider: str = ""
    error: str = ""
    cached: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return self.success and bool(self.image_path) and Path(self.image_path).exists()


# ========== 场景化语音模板 ==========

SCENE_VOICE_STYLES: dict[str, dict[str, Any]] = {
    "boot_greeting": {
        "style": VoiceStyle.WARM,
        "speed": 0.95,
        "volume": 0.8,
        "description": "启动问候",
    },
    "morning_brief": {
        "style": VoiceStyle.MORNING,
        "speed": 1.0,
        "volume": 0.85,
        "description": "早安播报",
    },
    "night_greeting": {
        "style": VoiceStyle.NIGHT,
        "speed": 0.85,
        "volume": 0.65,
        "description": "晚安问候",
    },
    "anniversary": {
        "style": VoiceStyle.INTIMATE,
        "speed": 0.9,
        "volume": 0.75,
        "description": "纪念日祝福",
    },
    "casual_chat": {
        "style": VoiceStyle.WARM,
        "speed": 1.0,
        "volume": 0.8,
        "description": "日常聊天",
    },
    "serious_talk": {
        "style": VoiceStyle.SERIOUS,
        "speed": 0.95,
        "volume": 0.8,
        "description": "严肃话题",
    },
    "playful": {
        "style": VoiceStyle.PLAYFUL,
        "speed": 1.1,
        "volume": 0.85,
        "description": "俏皮互动",
    },
    "calm_support": {
        "style": VoiceStyle.CALM,
        "speed": 0.9,
        "volume": 0.7,
        "description": "安抚支持",
    },
}


# ========== TTS 缓存 ==========

class TTSCache:
    """TTS 结果缓存，避免重复合成相同文本"""

    def __init__(self, cache_dir: str | Path = "data/tts_cache", max_entries: int = 200) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_entries = max_entries
        self._index_path = self.cache_dir / "_index.json"
        self._index: dict[str, dict[str, Any]] = {}
        self._load_index()

    def _load_index(self) -> None:
        import json
        if self._index_path.exists():
            try:
                self._index = json.loads(self._index_path.read_text(encoding="utf-8"))
            except Exception:
                self._index = {}

    def _save_index(self) -> None:
        import json
        try:
            self._index_path.write_text(
                json.dumps(self._index, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _key(self, text: str, style: str, provider: str) -> str:
        raw = f"{provider}:{style}:{text.strip()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def get(self, text: str, style: str, provider: str) -> Optional[str]:
        key = self._key(text, style, provider)
        entry = self._index.get(key)
        if not entry:
            return None
        path = entry.get("path")
        if path and Path(path).exists():
            entry["last_used"] = time.time()
            self._save_index()
            return path
        # 缓存失效
        del self._index[key]
        self._save_index()
        return None

    def put(self, text: str, style: str, provider: str, audio_path: str) -> None:
        key = self._key(text, style, provider)
        self._index[key] = {
            "path": audio_path,
            "text": text[:100],
            "style": style,
            "provider": provider,
            "created": time.time(),
            "last_used": time.time(),
        }
        # 清理过期缓存
        if len(self._index) > self.max_entries:
            sorted_entries = sorted(
                self._index.items(), key=lambda x: x[1].get("last_used", 0)
            )
            for k, _ in sorted_entries[: len(self._index) - self.max_entries]:
                del self._index[k]
        self._save_index()


# ========== 扩展 TTS 引擎 ==========

class EnhancedTTSEngine:
    """增强版 TTS 引擎，支持多 Provider、场景化风格、缓存回退"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        provider: TTSProvider = TTSProvider.MINIMAX,
        cache: Optional[TTSCache] = None,
        default_style: VoiceStyle = VoiceStyle.WARM,
    ) -> None:
        self.api_key = api_key or os.getenv("MINIMAX_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
        self.provider = provider
        self.cache = cache or TTSCache()
        self.default_style = default_style
        self._httpx_client = None
        self._edge_tts_available = False
        self._init_edge_tts()

    def _init_edge_tts(self) -> None:
        try:
            import edge_tts  # noqa: F401
            self._edge_tts_available = True
        except ImportError:
            pass

    @property
    def is_available(self) -> bool:
        return bool(self.api_key) or self._edge_tts_available

    def _get_scene_config(self, scene: Optional[str]) -> dict[str, Any]:
        if scene and scene in SCENE_VOICE_STYLES:
            return SCENE_VOICE_STYLES[scene]
        return {
            "style": self.default_style,
            "speed": 1.0,
            "volume": 0.8,
        }

    async def synthesize(
        self,
        text: str,
        scene: Optional[str] = None,
        style: Optional[VoiceStyle] = None,
        output_name: Optional[str] = None,
        use_cache: bool = True,
    ) -> TTSResult:
        """合成语音，支持场景化风格与缓存"""
        if not text or not text.strip():
            return TTSResult(success=False, error="empty text")

        config = self._get_scene_config(scene)
        voice_style = style or config.get("style", self.default_style)
        speed = config.get("speed", 1.0)
        volume = config.get("volume", 0.8)

        # 查缓存
        if use_cache:
            cached = self.cache.get(text, voice_style.value, self.provider.value)
            if cached:
                return TTSResult(
                    success=True,
                    audio_path=cached,
                    text=text,
                    style=voice_style.value,
                    provider=self.provider.value,
                    cached=True,
                )

        # 尝试各 Provider
        providers_try = [self.provider]
        if self._edge_tts_available and self.provider != TTSProvider.EDGE_TTS:
            providers_try.append(TTSProvider.EDGE_TTS)

        last_error = ""
        for prov in providers_try:
            try:
                result = await self._synthesize_with_provider(
                    text, prov, voice_style, speed, volume, output_name
                )
                if result.success and result.audio_path:
                    if use_cache:
                        self.cache.put(text, voice_style.value, prov.value, result.audio_path)
                    return result
                last_error = result.error
            except Exception as e:
                last_error = str(e)
                logger.warning("TTS provider %s failed: %s", prov, e)

        return TTSResult(
            success=False,
            text=text,
            style=voice_style.value,
            error=last_error or "all providers failed",
        )

    async def _synthesize_with_provider(
        self,
        text: str,
        provider: TTSProvider,
        style: VoiceStyle,
        speed: float,
        volume: float,
        output_name: Optional[str] = None,
    ) -> TTSResult:
        if provider == TTSProvider.MINIMAX:
            return await self._minimax_tts(text, style, speed, volume, output_name)
        if provider == TTSProvider.EDGE_TTS:
            return await self._edge_tts(text, style, speed, volume, output_name)
        return TTSResult(success=False, error=f"unsupported provider: {provider}")

    async def _minimax_tts(
        self,
        text: str,
        style: VoiceStyle,
        speed: float,
        volume: float,
        output_name: Optional[str],
    ) -> TTSResult:
        if not self.api_key:
            return TTSResult(success=False, error="no API key")

        import httpx
        if self._httpx_client is None:
            self._httpx_client = httpx.AsyncClient(timeout=30.0)

        voice_map = {
            VoiceStyle.WARM: "female-qingxin",
            VoiceStyle.CALM: "female-yunxi",
            VoiceStyle.PLAYFUL: "female-qingxin",
            VoiceStyle.SERIOUS: "female-yunxi",
            VoiceStyle.INTIMATE: "female-qingxin",
            VoiceStyle.MORNING: "female-qingxin",
            VoiceStyle.NIGHT: "female-yunxi",
        }
        voice_id = voice_map.get(style, "female-qingxin")

        output_dir = Path("data/tts")
        output_dir.mkdir(parents=True, exist_ok=True)
        name = output_name or f"tts_{hashlib.md5(text.encode()).hexdigest()[:12]}"
        out_path = output_dir / f"{name}.wav"

        try:
            resp = await self._httpx_client.post(
                "https://api.minimaxi.com/v1/text_to_speech",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "speech-01",
                    "voice_id": voice_id,
                    "text": text,
                    "speed": speed,
                    "vol": volume,
                    "output_format": "wav",
                },
            )
            if resp.status_code == 200:
                out_path.write_bytes(resp.content)
                return TTSResult(
                    success=True,
                    audio_path=str(out_path),
                    text=text,
                    style=style.value,
                    provider="minimax",
                )
            return TTSResult(success=False, error=f"HTTP {resp.status_code}: {resp.text[:100]}")
        except Exception as e:
            return TTSResult(success=False, error=str(e))

    async def _edge_tts(
        self,
        text: str,
        style: VoiceStyle,
        speed: float,
        volume: float,
        output_name: Optional[str],
    ) -> TTSResult:
        if not self._edge_tts_available:
            return TTSResult(success=False, error="edge_tts not available")

        try:
            import edge_tts
            output_dir = Path("data/tts")
            output_dir.mkdir(parents=True, exist_ok=True)
            name = output_name or f"tts_{hashlib.md5(text.encode()).hexdigest()[:12]}"
            out_path = output_dir / f"{name}.mp3"

            voice_map = {
                VoiceStyle.WARM: "zh-CN-XiaoxiaoNeural",
                VoiceStyle.CALM: "zh-CN-XiaoyiNeural",
                VoiceStyle.PLAYFUL: "zh-CN-XiaoxiaoNeural",
                VoiceStyle.SERIOUS: "zh-CN-YunxiNeural",
                VoiceStyle.INTIMATE: "zh-CN-XiaoxiaoNeural",
                VoiceStyle.MORNING: "zh-CN-XiaoxiaoNeural",
                VoiceStyle.NIGHT: "zh-CN-XiaoyiNeural",
            }
            voice = voice_map.get(style, "zh-CN-XiaoxiaoNeural")

            rate_str = f"+{int((speed - 1) * 100)}%" if speed >= 1 else f"{int((speed - 1) * 100)}%"
            volume_str = f"+{int((volume - 1) * 100)}%" if volume >= 0.5 else f"{int((volume - 1) * 100)}%"

            communicate = edge_tts.Communicate(text, voice, rate=rate_str, volume=volume_str)
            await communicate.save(str(out_path))

            return TTSResult(
                success=True,
                audio_path=str(out_path),
                text=text,
                style=style.value,
                provider="edge_tts",
            )
        except Exception as e:
            return TTSResult(success=False, error=str(e))

    async def synthesize_scene(
        self,
        scene: str,
        text: str,
        **kwargs: Any,
    ) -> TTSResult:
        """按场景合成语音（便捷方法）"""
        return await self.synthesize(text, scene=scene, **kwargs)


# ========== 图片生成 ==========

class ImageGenerator:
    """图片生成器，支持多种 Provider 和 Fallback"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        provider: ImageProvider = ImageProvider.OPENAI,
        output_dir: str | Path = "data/images",
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.provider = provider
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._client = None
        if self.api_key:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(api_key=self.api_key)
            except ImportError:
                pass

    @property
    def is_available(self) -> bool:
        return self._client is not None and bool(self.api_key)

    async def generate(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        style: str = "vivid",
        n: int = 1,
    ) -> ImageResult:
        """生成图片"""
        if not prompt or not prompt.strip():
            return ImageResult(success=False, error="empty prompt")

        # 尝试主 Provider
        try:
            if self.provider == ImageProvider.OPENAI and self._client:
                return await self._openai_generate(prompt, width, height, style, n)
        except Exception as e:
            logger.warning("Image generation failed: %s", e)

        # Fallback: SVG 占位图
        return self._doodle_fallback(prompt, width, height)

    async def _openai_generate(
        self,
        prompt: str,
        width: int,
        height: int,
        style: str,
        n: int,
    ) -> ImageResult:
        if not self._client:
            return ImageResult(success=False, error="no client")

        size_str = f"{width}x{height}"
        resp = await self._client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size=size_str,
            quality="standard",
            style=style,
            n=1,
            response_format="url",
        )

        # 下载图片
        import httpx
        url = resp.data[0].url
        if not url:
            return ImageResult(success=False, error="no image url")

        fname = f"img_{int(time.time())}_{hashlib.md5(prompt.encode()).hexdigest()[:8]}.png"
        out_path = self.output_dir / fname

        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.get(url)
            if r.status_code == 200:
                out_path.write_bytes(r.content)
                return ImageResult(
                    success=True,
                    image_path=str(out_path),
                    prompt=prompt,
                    width=width,
                    height=height,
                    provider="openai",
                )
        return ImageResult(success=False, error=f"download failed: HTTP {r.status_code}")

    def _doodle_fallback(self, prompt: str, width: int, height: int) -> ImageResult:
        """生成 SVG 占位图（DALL·E 不可用时的兜底）"""
        import html
        safe_prompt = html.escape(prompt[:50])
        svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#667eea;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#764ba2;stop-opacity:1" />
    </linearGradient>
  </defs>
  <rect width="{width}" height="{height}" fill="url(#bg)"/>
  <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle"
        fill="white" font-family="sans-serif" font-size="24" font-weight="bold">
    {safe_prompt}
  </text>
</svg>'''
        fname = f"doodle_{int(time.time())}_{hashlib.md5(prompt.encode()).hexdigest()[:8]}.svg"
        out_path = self.output_dir / fname
        out_path.write_text(svg, encoding="utf-8")
        return ImageResult(
            success=True,
            image_path=str(out_path),
            prompt=prompt,
            width=width,
            height=height,
            provider="doodle",
            cached=False,
            metadata={"fallback": True, "format": "svg"},
        )


# ========== 多模态输出调度器 ==========

class MultimodalOutputEngine:
    """统一多模态输出调度器

    协调 TTS、图片生成、富文本输出，确保输出风格一致。
    """

    def __init__(
        self,
        tts_engine: Optional[EnhancedTTSEngine] = None,
        image_generator: Optional[ImageGenerator] = None,
        enable_tts: bool = True,
        enable_image: bool = True,
    ) -> None:
        self.tts = tts_engine or EnhancedTTSEngine()
        self.image_gen = image_generator or ImageGenerator()
        self.enable_tts = enable_tts
        self.enable_image = enable_image
        self._scene_history: list[dict[str, Any]] = []

    async def reply_with_voice(
        self,
        text: str,
        scene: Optional[str] = None,
        style: Optional[VoiceStyle] = None,
    ) -> dict[str, Any]:
        """生成带语音的回复"""
        result = {
            "text": text,
            "audio": None,
            "audio_style": style.value if style else None,
            "scene": scene,
        }

        if self.enable_tts and self.tts.is_available:
            tts_result = await self.tts.synthesize(text, scene=scene, style=style)
            if tts_result.is_valid:
                result["audio"] = tts_result.audio_path
                result["audio_provider"] = tts_result.provider
                result["audio_cached"] = tts_result.cached

        self._scene_history.append({"type": "voice", "scene": scene, "time": time.time()})
        return result

    async def generate_reply_image(
        self,
        prompt: str,
        **kwargs: Any,
    ) -> ImageResult:
        """生成回复配图"""
        if not self.enable_image:
            return ImageResult(success=False, error="image generation disabled")
        return await self.image_gen.generate(prompt, **kwargs)

    def get_available_scenes(self) -> list[dict[str, str]]:
        """获取所有可用场景"""
        return [
            {"key": k, "description": v.get("description", k), "style": v.get("style", "").value}
            for k, v in SCENE_VOICE_STYLES.items()
        ]
