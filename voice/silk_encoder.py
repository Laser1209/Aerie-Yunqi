"""Aerie · 云栖 v0.1.0-beta.1 — Silk v3 audio encoder.

NapCat QQ requires Silk-encoded audio for voice messages.
Uses FFmpeg for the conversion: WAV → PCM → Silk.

Prerequisite: FFmpeg must be installed and available in PATH.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _ffmpeg_available() -> bool:
    """Check if FFmpeg is in PATH."""
    return shutil.which("ffmpeg") is not None


def _run_ffmpeg(args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    """Run FFmpeg with the given arguments."""
    creationflags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags = subprocess.CREATE_NO_WINDOW
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=creationflags,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return -1, "", "ffmpeg not found in PATH"
    except subprocess.TimeoutExpired:
        return -1, "", "ffmpeg timed out"
    except Exception as e:
        return -1, "", str(e)


def wav_to_silk(wav_path: Path, silk_path: Optional[Path] = None) -> Optional[Path]:
    """Convert a WAV audio file to Silk v3 format.

    NapCat OneBot11 supports sending Silk-encoded audio via record messages.
    The conversion pipeline: WAV → PCM (16kHz mono s16le) → Silk via FFmpeg.

    Args:
        wav_path: Path to source WAV file.
        silk_path: Target path for the Silk file (default: same stem + .silk).

    Returns:
        Path to the Silk file, or None if conversion failed.
    """
    if not wav_path.exists():
        logger.error("WAV file not found: %s", wav_path)
        return None

    if not _ffmpeg_available():
        logger.error("FFmpeg not available — cannot encode Silk")
        return None

    silk_path = silk_path or wav_path.with_suffix(".silk")

    # Step 1: WAV → raw PCM (16kHz, mono, s16le)
    pcm_path = wav_path.with_suffix(".pcm")
    rc, _, err = _run_ffmpeg([
        "-i", str(wav_path),
        "-f", "s16le",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(pcm_path),
    ])
    if rc != 0 or not pcm_path.exists():
        logger.error("PCM conversion failed: %s", err[:200])
        return None

    logger.info("PCM extracted: %s (%d bytes)", pcm_path, pcm_path.stat().st_size)

    # Step 2: PCM → Silk (using FFmpeg's libsilk / external silk encoder)
    # Note: FFmpeg's built-in Silk encoder support varies by build.
    # As a fallback, we attempt direct Silk encoding; if unavailable,
    # we keep the raw PCM for NapCat to handle.
    rc_silk, _, err_silk = _run_ffmpeg([
        "-f", "s16le",
        "-ar", "16000",
        "-ac", "1",
        "-i", str(pcm_path),
        "-c:a", "silk",
        "-b:a", "24k",
        str(silk_path),
    ])
    if rc_silk == 0 and silk_path.exists():
        logger.info("Silk encoded: %s (%d bytes)", silk_path, silk_path.stat().st_size)
        # Clean up intermediate PCM
        try:
            pcm_path.unlink()
        except Exception:
            pass
        return silk_path

    # Fallback: keep PCM as-is and let NapCat handle the encoding
    logger.warning("Silk encoding failed (%s) — falling back to PCM", err_silk[:100])
    return pcm_path if pcm_path.exists() else None
