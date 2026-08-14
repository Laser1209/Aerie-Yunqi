"""Aerie · 云栖 — NapCat 一键下载/解压服务。

从官方 GitHub Release 下载 ``NapCat.Shell.zip``，解压到 ``data/napcat/``，
定位 ``launcher-user.bat`` 所在目录后写入 ``data/napcat_dir.json``，供
``napcat_launcher`` 读取定位。下载/解压均为阻塞操作，由 API 通过
``asyncio.to_thread`` 调用，避免卡住事件循环；进度与状态线程安全，供前端轮询。
"""

from __future__ import annotations

import json
import logging
import threading
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# 官方源 → 镜像源，依次尝试（GitHub latest 链接会自动 302 到真实 asset）。
# 使用内置 QQ + Node 的完整包（解压即用，无需本机预装 QQ）。
_DOWNLOAD_SOURCES = [
    "https://github.com/NapNeko/NapCatQQ/releases/latest/download/NapCat.Shell.Windows.Node.zip",
    "https://github.moeyy.xyz/https://github.com/NapNeko/NapCatQQ/releases/latest/download/NapCat.Shell.Windows.Node.zip",
]
_PER_SOURCE_TIMEOUT_SECONDS = 10 * 60  # 每个源 10 分钟（完整包较大）
_ZIP_FILENAME = "napcat-shell.zip"

# 解压后可能的启动器文件名（按优先级探测）。
_LAUNCHER_CANDIDATES = ("launcher-user.bat", "launcher.bat", "napcat.bat")


class NapcatDownloader:
    """Download, extract and persist the NapCat directory (progress-reporting)."""

    def __init__(self) -> None:
        from core.paths import data_dir

        self.data_dir = data_dir()
        self.target_root = self.data_dir / "napcat"
        self.marker = self.data_dir / "napcat_dir.json"
        self._state = "idle"  # idle | downloading | extracting | done | error
        self._progress = 0.0
        self._message = ""
        self._error = ""
        self._lock = threading.Lock()

    def status(self) -> dict:
        with self._lock:
            return {
                "state": self._state,
                "progress": round(self._progress, 3),
                "message": self._message,
                "error": self._error,
                "installed": self.marker.exists(),
            }

    def _set(self, state: str, message: str = "", progress: float | None = None) -> None:
        with self._lock:
            self._state = state
            if message:
                self._message = message
            if progress is not None:
                self._progress = progress

    def is_running(self) -> bool:
        with self._lock:
            return self._state in ("downloading", "extracting")

    def download_and_extract(self) -> dict:
        """Blocking download + extract. Call from asyncio.to_thread."""
        if self.is_running():
            return {"ok": False, "message": "NapCat 正在下载中", "error_code": "already_running"}

        try:
            self.target_root.mkdir(parents=True, exist_ok=True)
            zip_path = self.target_root / _ZIP_FILENAME
            self._set("downloading", "正在下载 NapCat…", progress=0.0)
            self._download(zip_path)

            self._set("extracting", "正在解压 NapCat…", progress=0.9)
            napcat_dir = self._extract(zip_path, self.target_root)
            self._write_marker(napcat_dir)

            # 解压成功后删除 zip 节省空间（失败保留便于排查）。
            try:
                zip_path.unlink(missing_ok=True)
            except OSError:
                pass

            self._set("done", f"NapCat 已就绪：{napcat_dir}", progress=1.0)
            logger.info("[NapCat] downloaded and extracted to %s", napcat_dir)
            return {"ok": True, "message": "NapCat 已下载并解压完成", "dir": str(napcat_dir)}
        except Exception as exc:
            logger.exception("NapCat download failed")
            self._set("error", f"下载失败：{exc}", progress=0.0)
            self._error = str(exc)
            return {"ok": False, "message": f"NapCat 下载失败：{exc}", "error_code": "download_failed"}

    def _download(self, dest: Path) -> None:
        last_error: Exception | None = None
        for source in _DOWNLOAD_SOURCES:
            try:
                self._download_from(source, dest)
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("[NapCat] download source failed: %s (%s)", source, exc)
                # 重置下载目标，避免残留半截文件影响下一源
                try:
                    dest.unlink(missing_ok=True)
                except OSError:
                    pass
        if last_error is not None:
            raise last_error
        raise RuntimeError("所有下载源均不可用")

    def _download_from(self, url: str, dest: Path) -> None:
        req = Request(url, headers={"User-Agent": "Aerie-Cloud"})
        with urlopen(req, timeout=_PER_SOURCE_TIMEOUT_SECONDS) as resp, open(dest, "wb") as fh:
            total = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                downloaded += len(chunk)
                if total:
                    self._set(
                        "downloading",
                        f"正在下载 NapCat… {downloaded // 1024 // 1024}MB / {total // 1024 // 1024}MB",
                        progress=min(downloaded / total * 0.9, 0.9),
                    )

    def _extract(self, zip_path: Path, dest: Path) -> Path:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dest)
        return self._find_napcat_dir(dest)

    def _find_napcat_dir(self, root: Path) -> Path:
        """Locate the directory containing a NapCat launcher after extraction."""
        for name in _LAUNCHER_CANDIDATES:
            if (root / name).exists():
                return root
            for found in root.rglob(name):
                return found.parent
        # 退回以 napcat 开头的子目录（不同包解压后的目录名可能不同）
        for child in root.iterdir():
            if child.is_dir() and child.name.lower().startswith("napcat"):
                return child
        return root

    def _write_marker(self, napcat_dir: Path) -> None:
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self.marker.write_text(
            json.dumps({"dir": str(napcat_dir)}, ensure_ascii=False),
            encoding="utf-8",
        )

    def check_update(self) -> dict:
        """Query NapCat latest version from GitHub and compare with installed."""
        latest = self._fetch_latest_version()
        current = self._read_installed_version()
        return {
            "latest": latest,
            "current": current,
            "has_update": bool(latest and current and latest != current),
            "installed": self.marker.exists(),
        }

    def _fetch_latest_version(self) -> str | None:
        try:
            req = Request(
                "https://api.github.com/repos/NapNeko/NapCatQQ/releases/latest",
                headers={"User-Agent": "Aerie-Cloud", "Accept": "application/vnd.github+json"},
            )
            with urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                return payload.get("tag_name") or payload.get("name")
        except Exception:
            logger.warning("fetch NapCat latest version failed", exc_info=True)
            return None

    def _read_installed_version(self) -> str | None:
        if not self.marker.exists():
            return None
        try:
            payload = json.loads(self.marker.read_text(encoding="utf-8"))
            napcat_dir = Path(str(payload.get("dir", "")))
            pkg = napcat_dir / "package.json"
            if not pkg.exists():
                return None
            pkg_payload = json.loads(pkg.read_text(encoding="utf-8"))
            return pkg_payload.get("version")
        except Exception:
            return None


_DOWNLOADER: NapcatDownloader | None = None


def get_downloader() -> NapcatDownloader:
    global _DOWNLOADER
    if _DOWNLOADER is None:
        _DOWNLOADER = NapcatDownloader()
    return _DOWNLOADER
