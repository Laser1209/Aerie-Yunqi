"""Aerie · 云栖 — 拉取并解压 ffmpeg.exe / ffprobe.exe 到 ffmpeg/bin/。

背景：
    项目内置 ffmpeg（见 core/qq_media.py / core/multimodal_input.py）用于
    语音转码与音频时长探测，代码期望 `ffmpeg/bin/ffmpeg.exe` 与
    `ffmpeg/bin/ffprobe.exe`。旧 `ffmpeg/ffmpeg.zip` 是截断的损坏文件，无法使用。

本脚本：
    1. 按优先级从 GitHub 代理 / 官方源下载 BtbN 的 win64-lgpl 静态构建；
    2. 从 zip 中解出 ffmpeg.exe 与 ffprobe.exe 到 `ffmpeg/bin/`；
    3. 校验两个文件存在，失败返回非零。

用法（需联网，一次性执行）：
    python scripts/fetch_ffmpeg.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FFMPEG_DIR = ROOT / "ffmpeg"
BIN_DIR = FFMPEG_DIR / "bin"
TMP_ZIP = FFMPEG_DIR / "_ffmpeg_download.zip"

# 优先走国内可达的 GitHub 加速代理，失败回退官方 GitHub。
SOURCES = (
    "https://ghfast.top/https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-lgpl.zip",
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-lgpl.zip",
)

NEEDED = ("ffmpeg.exe", "ffprobe.exe")


def _download(url: str) -> bool:
    TMP_ZIP.unlink(missing_ok=True)
    print(f"[ffmpeg] downloading: {url}")
    r = subprocess.run(
        ["curl.exe", "-L", "-f", "--retry", "1", "-o", str(TMP_ZIP), url],
        check=False,
    )
    if r.returncode != 0:
        print(f"[ffmpeg] curl failed (exit={r.returncode})")
        return False
    if not TMP_ZIP.exists() or TMP_ZIP.stat().st_size < 1_000_000:
        print("[ffmpeg] downloaded file too small / missing, treat as failed")
        return False
    return True


def _extract() -> None:
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(TMP_ZIP) as z:
        for name in z.namelist():
            base = Path(name).name
            if base not in NEEDED:
                continue
            target = BIN_DIR / base
            with z.open(name) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            print(f"[ffmpeg] extracted {base} ({target.stat().st_size} bytes)")


def main() -> int:
    for url in SOURCES:
        if not _download(url):
            continue
        try:
            _extract()
        except (zipfile.BadZipFile, OSError) as e:
            print(f"[ffmpeg] extract failed: {e}")
            continue
        finally:
            TMP_ZIP.unlink(missing_ok=True)

        if all((BIN_DIR / n).exists() for n in NEEDED):
            print("[ffmpeg] OK: ffmpeg/bin/ffmpeg.exe + ffprobe.exe ready")
            return 0

    print("[ffmpeg] all sources failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
