"""Aerie · 云栖 v0.1.0-beta.1 — NapCat launcher (manual control via API).

Exposes status query and start/stop for the Electron NapCat panel.
Does NOT auto-start — user clicks "Start" in the UI.
"""

from __future__ import annotations
import asyncio
import logging
import socket
import subprocess
import sys
from datetime import datetime
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


def _terminate_process_tree(proc: subprocess.Popen) -> None:
    """Terminate only the NapCat process tree launched by this instance."""
    if sys.platform == "win32":
        completed = subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
        if completed.returncode == 0:
            return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            proc.kill()
        except OSError:
            pass


class NapcatLauncher:
    def __init__(self, settings: dict | None = None) -> None:
        self.settings = settings or {}
        napcat_cfg = self.settings.get("napcat", {})
        self.ws_port = int(napcat_cfg.get("ws_port", 3001))
        self._proc: subprocess.Popen | None = None
        self._owns_process = False
        self._logs: list[str] = []
        self._phase = "idle"  # idle | starting | qr_pending | connected
        self._error_code = ""

    def get_status(self) -> dict:
        """Return current NapCat status for API."""
        qr_exists = _QRCODE_PATH.exists()
        running = self._proc is not None and self._proc.poll() is None
        port_open = _port_is_open(port=self.ws_port)
        if port_open:
            phase = "connected"
        elif running and qr_exists:
            phase = "qr_pending"
        elif running and self._phase != "error":
            phase = "starting"
        elif self._phase == "error":
            phase = "error"
        else:
            phase = "idle"
        self._phase = phase
        return {
            "running": running or port_open,
            "ws_port_open": port_open,
            "pid": self._proc.pid if running and self._owns_process else None,
            "phase": phase,
            "qrcode_available": qr_exists,
            "owned": bool(running and self._owns_process),
            "error_code": self._error_code if phase == "error" else "",
        }

    def get_logs(self, limit: int = 50) -> list[str]:
        return self._logs[-limit:]

    def add_log(self, text: str) -> None:
        """Append a liveness line to the Status-page running-log box (e.g. QQ client heartbeat)."""
        stamp = datetime.now().strftime("%H:%M:%S")
        self._logs.append(f"[{stamp}] {text}")
        if len(self._logs) > 1000:
            del self._logs[: len(self._logs) - 1000]

    async def start(self) -> dict:
        """Launch NapCat via launcher-user.bat."""
        if self._proc and self._proc.poll() is None:
            return {"ok": False, "message": "NapCat already running"}
        if self._proc is not None:
            self._proc = None
            self._owns_process = False

        if _port_is_open(port=self.ws_port):
            self._phase = "connected"
            self._error_code = ""
            return {
                "ok": True,
                "message": "NapCat was already running outside Aerie",
                "already_running": True,
                "owned": False,
            }

        if not _LAUNCHER_BAT.exists():
            self._phase = "error"
            self._error_code = "launcher_not_found"
            return {
                "ok": False,
                "message": "NapCat launcher is unavailable",
                "error_code": self._error_code,
            }

        self._phase = "starting"
        self._error_code = ""
        self._logs.clear()
        self._logs.append("[系统] 正在启动 NapCat...")

        try:
            if sys.platform == "win32":
                self._proc = subprocess.Popen(
                    [str(_LAUNCHER_BAT)],
                    cwd=str(_NAPCAT_DIR),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=(
                        subprocess.CREATE_NO_WINDOW
                        | subprocess.CREATE_NEW_PROCESS_GROUP
                    ),
                )
            else:
                self._proc = subprocess.Popen(
                    [str(_LAUNCHER_BAT)],
                    cwd=str(_NAPCAT_DIR),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            self._owns_process = True

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
                    return {
                        "ok": True,
                        "port_open": False,
                        "qrcode_available": True,
                        "message": "QR code ready",
                        "owned": True,
                    }

            self._logs.append("[系统] 等待超时，请检查NapCat日志")
            self._phase = "error"
            self._error_code = "napcat_start_timeout"
            return {
                "ok": False,
                "port_open": False,
                "message": "NapCat did not become ready in time",
                "error_code": self._error_code,
                "owned": True,
            }

        except Exception:
            if self._proc is not None and self._owns_process:
                _terminate_process_tree(self._proc)
            self._proc = None
            self._owns_process = False
            self._phase = "error"
            self._error_code = "napcat_start_failed"
            self._logs.append("[错误] 启动失败")
            logger.exception("NapCat start error")
            return {
                "ok": False,
                "message": "NapCat failed to start",
                "error_code": self._error_code,
            }

    async def stop(self) -> dict:
        """Stop NapCat process."""
        if not self._owns_process and _port_is_open(port=self.ws_port):
            self._phase = "connected"
            return {
                "ok": True,
                "message": "NapCat was already running outside Aerie",
                "owned": False,
            }
        if self._proc is not None and self._owns_process:
            _terminate_process_tree(self._proc)
            self._logs.append("[系统] NapCat 已停止")
        self._proc = None
        self._owns_process = False
        for _ in range(20):
            if not _port_is_open(port=self.ws_port):
                break
            await asyncio.sleep(0.25)
        if _port_is_open(port=self.ws_port):
            self._phase = "error"
            self._error_code = "napcat_residual_port"
            return {
                "ok": False,
                "message": "NapCat stopped but its port is still in use",
                "error_code": self._error_code,
                "owned": False,
            }
        self._phase = "idle"
        self._error_code = ""
        return {"ok": True, "message": "NapCat stopped", "owned": False}

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
