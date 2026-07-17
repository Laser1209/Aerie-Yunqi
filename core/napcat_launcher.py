"""Aerie · 云栖 v9.0 — NapCat launcher (manual control via API).

Exposes status query and start/stop for the Electron NapCat panel.
Does NOT auto-start — user clicks "Start" in the UI.
"""

from __future__ import annotations
import asyncio
import logging
import socket
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_NAPCAT_DIR = _PROJECT_ROOT / "NapCat" / "NapCat.Shell"
_LAUNCHER_BAT = _NAPCAT_DIR / "launcher-user.bat"
_QRCODE_PATH = _NAPCAT_DIR / "cache" / "qrcode.png"


def _port_is_open(host: str = "127.0.0.1", port: int = 3001) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except (OSError, TimeoutError):
        return False


class NapcatLauncher:
    def __init__(self, settings: dict | None = None) -> None:
        self.settings = settings or {}
        napcat_cfg = self.settings.get("napcat", {})
        self.ws_port = int(napcat_cfg.get("ws_port", 3001))
        self._proc: subprocess.Popen | None = None
        self._logs: list[str] = []
        self._phase = "idle"  # idle | starting | qr_pending | connected

    def get_status(self) -> dict:
        """Return current NapCat status for API."""
        qr_exists = _QRCODE_PATH.exists()
        return {
            "running": self._proc is not None and self._proc.poll() is None,
            "ws_port_open": _port_is_open(port=self.ws_port),
            "pid": self._proc.pid if self._proc else None,
            "phase": self._phase,
            "qrcode_available": qr_exists,
            "qrcode_path": str(_QRCODE_PATH) if qr_exists else None,
        }

    def get_logs(self, limit: int = 50) -> list[str]:
        return self._logs[-limit:]

    async def start(self) -> dict:
        """Launch NapCat via launcher-user.bat."""
        if self._proc and self._proc.poll() is None:
            return {"ok": False, "message": "NapCat already running"}

        if not _LAUNCHER_BAT.exists():
            return {"ok": False, "message": f"launcher not found: {_LAUNCHER_BAT}"}

        self._phase = "starting"
        self._logs.clear()
        self._logs.append("[系统] 正在启动 NapCat...")

        try:
            if sys.platform == "win32":
                self._proc = subprocess.Popen(
                    [str(_LAUNCHER_BAT)],
                    cwd=str(_NAPCAT_DIR),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                self._proc = subprocess.Popen(
                    [str(_LAUNCHER_BAT)],
                    cwd=str(_NAPCAT_DIR),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

            self._logs.append("[系统] NapCat 进程已启动，等待端口...")

            # Poll for port open
            for i in range(30):  # max 30s
                await asyncio.sleep(1)
                if _port_is_open(port=self.ws_port):
                    self._phase = "connected"
                    self._logs.append("[系统] WebSocket 端口已就绪，已连接")
                    return {"ok": True, "port_open": True, "message": "NapCat connected"}
                # Check for QR code during wait
                if _QRCODE_PATH.exists():
                    self._phase = "qr_pending"
                    self._logs.append("[系统] 检测到二维码，请用手机QQ扫码登录")

            self._logs.append("[系统] 等待超时，请检查NapCat日志")
            return {"ok": True, "port_open": False, "message": "Timeout waiting for port"}

        except Exception as e:
            self._phase = "idle"
            msg = str(e)
            self._logs.append(f"[错误] 启动失败: {msg}")
            logger.exception("NapCat start error")
            return {"ok": False, "message": msg}

    async def stop(self) -> dict:
        """Stop NapCat process."""
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._logs.append("[系统] NapCat 已停止")
        self._phase = "idle"
        return {"ok": True, "message": "NapCat stopped"}

    def read_qrcode(self) -> bytes | None:
        """Read QR code image bytes for display in the UI."""
        if not _QRCODE_PATH.exists():
            return None
        return _QRCODE_PATH.read_bytes()


_LAUNCHER: NapcatLauncher | None = None


def get_launcher(settings: dict | None = None) -> NapcatLauncher:
    global _LAUNCHER
    if _LAUNCHER is None:
        _LAUNCHER = NapcatLauncher(settings)
    return _LAUNCHER
