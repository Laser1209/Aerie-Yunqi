"""Aerie · 云栖 v9.0 — TTS engine using MiniMax TTS API.

Generates WAV audio from text, styled as Yita's voice.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# MiniMax TTS API endpoint (OpenAI-compatible speech endpoint, or native)
MINIMAX_TTS_URL = "https://api.minimaxi.com/v1/text_to_speech"

# Yita voice parameters — low, calm, with subtle warmth
YITA_VOICE_ID = "female-qingxin"      # MiniMax preset closest to Yita
YITA_SPEED = 0.9                       # slightly slower, deliberate
YITA_VOLUME = 0.8                      # not too loud

# Fallback: TTS output directory
TTS_OUTPUT_DIR = Path("data/tts")
TTS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


class TTSEngine:
    """Text-to-speech engine for Yita's voice output."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: str = YITA_VOICE_ID,
        speed: float = YITA_SPEED,
        volume: float = YITA_VOLUME,
    ) -> None:
        self.api_key = api_key or os.getenv("MINIMAX_API_KEY", "")
        self.voice_id = voice_id
        self.speed = speed
        self.volume = volume
        if not self.api_key:
            logger.warning("MINIMAX_API_KEY not set — TTS will be unavailable")

    async def synthesize(self, text: str, output_name: Optional[str] = None) -> Optional[Path]:
        """Convert text to speech, return path to generated WAV file.

        Returns None if TTS is unavailable or fails.
        """
        if not self.api_key or not text.strip():
            return None

        output_name = output_name or f"tts_{hash(text) & 0xFFFFFFFF:08x}"
        output_path = TTS_OUTPUT_DIR / f"{output_name}.wav"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    MINIMAX_TTS_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "speech-01",
                        "voice_id": self.voice_id,
                        "text": text,
                        "speed": self.speed,
                        "vol": self.volume,
                        "output_format": "wav",
                    },
                )
                if resp.status_code == 200:
                    output_path.write_bytes(resp.content)
                    logger.info("TTS saved: %s (%d bytes)", output_path, len(resp.content))
                    return output_path
                else:
                    logger.warning("MiniMax TTS failed: HTTP %d — %s", resp.status_code, resp.text[:200])
                    return None
        except Exception as e:
            logger.warning("MiniMax TTS error: %s", e)
            return None

    async def synthesize_to_path(self, text: str, target_path: Path) -> bool:
        """Synthesize and save directly to target_path. Returns True on success."""
        result = await self.synthesize(text, output_name=target_path.stem)
        if result:
            import shutil
            shutil.move(str(result), str(target_path))
            return True
        return False
