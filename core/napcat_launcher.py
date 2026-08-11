"""Aerie · 云栖 v0.1.0-beta.1 — NapCat launcher (manual control via API + watchdog).

Exposes status query and start/stop for the Electron NapCat panel.
A watchdog task auto-respawns the NapCat process when it exits or when the
WS port stays closed too long, so QQ messages are not silently lost while
the process is down. The watchdog only acts on processes launched by this
instance (``_owns_process``), never on externally-managed NapCat.
"""

from __future__ import annotations
import asyncio
import logging
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_NAPCAT_DIR = _PROJECT_ROOT / "NapCat" / "NapCat.Shell"
_LAUNCHER_BAT = _NAPCAT_DIR / "launcher-user.bat"
_QRCODE_PATH = _NAPCAT_DIR / "cache" / "qrcode.png"

# Watchdog tunables: grace period before a started process is judged dead,
# poll interval, and how long the WS port may stay closed before force-restart.
_WATCHDOG_GRACE_SECONDS = 60.0
_WATCHDOG_POLL_SECONDS = 5.0
_WATCHDOG_PORT_STALL_SECONDS = 60.0
_WATCHDOG_MAX_BACKOFF_SECONDS = 120.0


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
        self._watchdog_task: asyncio.Task | None = None
        self._watchdog_stopped = False
        self._consecutive_failures = 0
        self._port_stall_since: float | None = None

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
            self._spawn()
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

    def _spawn(self) -> None:
        """Launch the NapCat process via launcher-user.bat (sync)."""
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
        self._port_stall_since = None
        self._start_watchdog()

    # ── watchdog ──────────────────────────────────────────────

    def _start_watchdog(self) -> None:
        """Start the background respawn watcher (no-op if already running)."""
        if self._watchdog_task is not None and not self._watchdog_task.done():
            return
        self._watchdog_stopped = False
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

    def _stop_watchdog(self) -> None:
        """Stop the background respawn watcher."""
        self._watchdog_stopped = True
        if self._watchdog_task is not None:
            task = self._watchdog_task
            self._watchdog_task = None
            if not task.done():
                task.cancel()

    async def _watchdog_loop(self) -> None:
        """Auto-respawn NapCat when it dies or the WS port stalls.

        Only acts on processes launched by this instance (``_owns_process``).
        A grace period right after spawn gives the process time to boot, and
        exponential backoff prevents a respawn storm on repeated crashes.
        """
        try:
            while not self._watchdog_stopped:
                await asyncio.sleep(_WATCHDOG_POLL_SECONDS)
                if self._watchdog_stopped:
                    break
                if not self._owns_process or self._proc is None:
                    continue

                proc_alive = self._proc.poll() is None
                port_open = _port_is_open(port=self.ws_port)
                now = time.monotonic()

                if proc_alive and port_open:
                    self._consecutive_failures = 0
                    self._port_stall_since = None
                    continue

                if proc_alive and not port_open:
                    # Process alive but WS port closed → track stall duration;
                    # only act after the grace window to allow slow boots.
                    if self._port_stall_since is None:
                        self._port_stall_since = now
                    if now - self._port_stall_since < _WATCHDOG_GRACE_SECONDS:
                        continue
                    # Grace elapsed and port still closed → force-restart.
                    self._logs.append(
                        "[watchdog] WebSocket 端口持续未就绪，强制重启 NapCat"
                    )
                    _terminate_process_tree(self._proc)
                    self._proc = None
                    self._owns_process = False

                if not self._owns_process:
                    continue

                # Process has exited (or was force-killed above) → respawn.
                await self._respawn()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("NapCat watchdog loop error")
            self._watchdog_task = None

    async def _respawn(self) -> None:
        """Respawn NapCat with exponential backoff to avoid crash storms."""
        self._consecutive_failures += 1
        delay = min(
            _WATCHDOG_PORT_STALL_SECONDS / 2 * (2 ** min(self._consecutive_failures - 1, 4)),
            _WATCHDOG_MAX_BACKOFF_SECONDS,
        )
        self._logs.append(
            f"[watchdog] NapCat 进程已退出，{int(delay)}s 后自动重启 "
            f"(连续失败 {self._consecutive_failures} 次)"
        )
        logger.warning(
            "NapCat process exited; respawning in %.0fs (failure #%d)",
            delay, self._consecutive_failures,
        )
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise
        if self._watchdog_stopped:
            return
        try:
            self._spawn()
        except Exception:
            logger.exception("NapCat respawn failed")

    async def stop(self) -> dict:
        """Stop NapCat process."""
        # Stop the watchdog first so it never respawns a process the user
        # explicitly stopped.
        self._stop_watchdog()
        self._consecutive_failures = 0
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
