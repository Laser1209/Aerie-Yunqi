"""Aerie · 云栖 v0.1.0-beta.1 — NapCat launcher (manual control via API + watchdog).

Exposes status query and start/stop for the Electron NapCat panel.
A watchdog task auto-respawns the NapCat process when it exits or when the
WS port stays closed too long, so QQ messages are not silently lost while
the process is down. The watchdog only acts on processes launched by this
instance (``_owns_process``), never on externally-managed NapCat.
"""

from __future__ import annotations
import asyncio
import io
import json
import logging
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import qrcode

from core.napcat_webui import NapCatWebUIClient, NapCatWebUIError

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_NAPCAT_DIR = _PROJECT_ROOT / "NapCat" / "NapCat.Shell"


def _resolve_napcat_dir(settings: dict | None) -> Path:
    """Resolve NapCat 目录：环境变量 > settings.napcat.dir > 下载配置 > 项目根默认。

    打包后 ``__file__`` 的父目录不再是仓库根，``_DEFAULT_NAPCAT_DIR`` 会落空；
    因此必须允许通过环境变量 / settings 显式指定，或读取「一键下载」落盘的
    ``data/napcat_dir.json``（下载解压后写入，重启后仍能定位）。
    """
    env_dir = os.environ.get("NAPCAT_DIR") or os.environ.get("AERIE_NAPCAT_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    cfg_dir = (settings or {}).get("napcat", {}).get("dir")
    if cfg_dir:
        return Path(str(cfg_dir)).expanduser()
    marker_dir = _read_download_marker()
    if marker_dir:
        return marker_dir
    return _DEFAULT_NAPCAT_DIR


def _read_download_marker() -> Path | None:
    """Read the NapCat directory persisted by the one-click downloader."""
    try:
        from core.paths import data_dir

        marker = data_dir() / "napcat_dir.json"
        if not marker.exists():
            return None
        payload = json.loads(marker.read_text(encoding="utf-8"))
        value = payload.get("dir") if isinstance(payload, dict) else None
        if not value:
            return None
        return Path(str(value)).expanduser()
    except Exception:
        return None


def _find_system_qq_exe() -> Path | None:
    """Resolve the installed QQ.exe path from the uninstall registry entry."""
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\QQ",
        ) as key:
            uninstall, _ = winreg.QueryValueEx(key, "UninstallString")
        candidate = Path(uninstall.strip().strip('"')).parent / "QQ.exe"
        return candidate if candidate.exists() else None
    except OSError:
        return None


def _build_launch_command(napcat_dir: Path) -> list[str] | None:
    """Build the napimain.exe argv for NapCat Framework v4.18+.

    Layout: ``napimain.exe <QQ.exe> <napiloader.dll> <nativeLoader.cjs>``.
    Returns None when any component is missing (caller surfaces a setup error).
    """
    if sys.platform != "win32":
        return None
    boot_main = napcat_dir / "napimain.exe"
    inject_dll = napcat_dir / "napiloader.dll"
    loader_cjs = napcat_dir / "nativeLoader.cjs"
    qq_exe = _find_system_qq_exe()
    if not all(p.exists() for p in (boot_main, inject_dll, loader_cjs)) or qq_exe is None:
        return None
    # NapCat's own loader scripts pass the CJS entry with forward slashes and
    # export NAPCAT_* env vars; napimain resolves the injection target through
    # them, so argv alone leaves coreReady=false forever.
    return [
        str(boot_main),
        str(qq_exe),
        str(inject_dll),
        loader_cjs.as_posix(),
    ]


def _napcat_env(napcat_dir: Path) -> dict[str, str]:
    """Environment variables NapCat's napiLoader exports before napimain."""
    env = dict(os.environ)
    env.update(
        {
            "NAPCAT_INJECT_PATH": str(napcat_dir / "napiloader.dll"),
            "NAPCAT_LAUNCHER_PATH": str(napcat_dir / "napimain.exe"),
            "NAPCAT_MAIN_PATH": (napcat_dir / "nativeLoader.cjs").as_posix(),
        }
    )
    return env

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


def _list_qq_pids() -> set[int]:
    """Enumerate running QQ.exe PIDs via tasklist (Windows only)."""
    if sys.platform != "win32":
        return set()
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq QQ.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    pids: set[int] = set()
    for line in completed.stdout.splitlines():
        columns = line.split('","')
        if len(columns) < 2:
            continue
        image_name = columns[0].lstrip('"').strip().lower()
        if image_name != "qq.exe":
            continue
        try:
            pids.add(int(columns[1]))
        except ValueError:
            continue
    return pids


def _kill_pid_tree(pid: int) -> None:
    """Force-kill a process tree by root PID (QQ launched by napimain)."""
    if sys.platform != "win32":
        return
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=10,
    )


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
        self.napcat_dir = _resolve_napcat_dir(self.settings)
        self._launch_cmd = _build_launch_command(self.napcat_dir)
        self.qrcode_path = self.napcat_dir / "cache" / "qrcode.png"
        self._proc: subprocess.Popen | None = None
        self._owns_process = False
        self._logs: list[str] = []
        # idle | starting | qr_pending | qr_expired | connected | error
        self._phase = "idle"
        self._error_code = ""
        self._watchdog_task: asyncio.Task | None = None
        self._watchdog_stopped = False
        self._consecutive_failures = 0
        self._port_stall_since: float | None = None
        # WebUI-driven login state (refreshed by the watchdog loop).
        self._webui: NapCatWebUIClient | None = None
        self._webui_port = 6099
        self._login: dict | None = None
        self._ob11_ensured = False
        # napimain.exe is fire-and-forget: it launches QQ.exe (the long-lived
        # injected process) and exits 0. Track the QQ PIDs it created so the
        # watchdog can judge liveness and stop() can tear them down.
        self._owned_qq_pids: set[int] = set()
        self._track_task: asyncio.Task | None = None
        # Latches True after an explicit user stop so the QQ client heartbeat
        # does not silently relaunch NapCat against the user's intent.
        self._user_stopped = False

    @property
    def user_stopped(self) -> bool:
        return self._user_stopped

    def _refresh_paths(self) -> None:
        """Re-resolve NapCat paths（下载解压后配置可能已更新，启动前刷新）。"""
        self.napcat_dir = _resolve_napcat_dir(self.settings)
        self._launch_cmd = _build_launch_command(self.napcat_dir)
        self.qrcode_path = self.napcat_dir / "cache" / "qrcode.png"
        self._webui = None
        self._login = None
        self._ob11_ensured = False
        self._owned_qq_pids = set()

    def _service_alive(self) -> bool:
        """True while any sign of our NapCat stack is alive.

        napimain exits seconds after launch; the QQ process keeps the WebUI
        (6099) and, post-login, the OneBot11 WS (3001) listening.
        """
        if self._proc is not None and self._proc.poll() is None:
            return True
        if _port_is_open(port=self._webui_port):
            return True
        return _port_is_open(port=self.ws_port)

    async def _get_webui(self) -> NapCatWebUIClient | None:
        """Lazily build a WebUI client; unavailable installs yield None."""
        if self._webui is not None:
            return self._webui
        try:
            self._webui = NapCatWebUIClient(self.napcat_dir)
            self._webui_port = self._webui.port
        except NapCatWebUIError:
            self._webui = None
        return self._webui

    def get_status(self) -> dict:
        """Return current NapCat status for API."""
        qr_exists = self.qrcode_path.exists()
        launcher_alive = self._proc is not None and self._proc.poll() is None
        webui_open = _port_is_open(port=self._webui_port)
        port_open = _port_is_open(port=self.ws_port)
        running = launcher_alive or webui_open or port_open
        login = self._login or {}
        is_login = bool(login.get("is_login"))
        qrcode_url = str(login.get("qrcode_url") or "")
        if port_open:
            # OneBot11 WS accepting connections is the fully-ready signal.
            phase = "connected"
        elif is_login:
            # QQ online but the OneBot11 adapter is still coming up.
            phase = "starting"
        elif running and (qrcode_url or qr_exists):
            phase = "qr_expired" if login.get("login_error") else "qr_pending"
        elif running and self._phase != "error":
            phase = "starting"
        elif self._phase == "error":
            phase = "error"
        else:
            phase = "idle"
        self._phase = phase
        return {
            "running": running,
            "ws_port_open": port_open,
            "pid": self._proc.pid if launcher_alive and self._owns_process else None,
            "phase": phase,
            "qrcode_available": phase in ("qr_pending", "qr_expired"),
            "login_error": str(login.get("login_error") or ""),
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
        self._refresh_paths()
        external = _port_is_open(port=self.ws_port) or _port_is_open(port=self._webui_port)
        if external:
            self._phase = "connected"
            self._error_code = ""
            return {
                "ok": True,
                "message": "NapCat was already running outside Aerie",
                "already_running": True,
                "owned": False,
            }
        if self._proc is not None and self._proc.poll() is None:
            return {"ok": False, "message": "NapCat already starting"}
        self._proc = None
        self._owns_process = False
        self._owned_qq_pids = set()

        if self._launch_cmd is None:
            self._phase = "error"
            self._error_code = "launcher_not_found"
            return {
                "ok": False,
                "message": "NapCat launcher is unavailable",
                "error_code": self._error_code,
            }

        self._phase = "starting"
        self._error_code = ""
        self._user_stopped = False
        self._logs.clear()
        self._logs.append("[系统] 正在启动 NapCat...")

        try:
            self._spawn()
            self._logs.append("[系统] NapCat 进程已启动，等待端口...")

            # Poll for readiness: the WebUI (6099) answers before login, the
            # OneBot11 WS port (3001) only exists after login + adapter config.
            for _ in range(45):  # max ~45s
                await asyncio.sleep(1)
                if _port_is_open(port=self.ws_port):
                    self._phase = "connected"
                    self._logs.append("[系统] WebSocket 端口已就绪，已连接")
                    return {"ok": True, "port_open": True, "message": "NapCat connected"}
                login = await self._poll_login_status()
                if login is None:
                    continue
                if login["is_login"]:
                    self._phase = "starting"
                    self._logs.append("[系统] QQ 已登录，等待 OneBot11 端口...")
                    continue
                if login["qrcode_url"]:
                    expired = bool(login["login_error"])
                    self._phase = "qr_expired" if expired else "qr_pending"
                    self._logs.append(
                        "[系统] 二维码已过期，请点击刷新"
                        if expired
                        else "[系统] 检测到二维码，请用手机QQ扫码登录"
                    )
                    return {
                        "ok": True,
                        "port_open": False,
                        "qrcode_available": True,
                        "expired": expired,
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
            if self._owns_process:
                self._teardown_processes()
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
        """Launch napimain.exe (injects NapCat into the system QQ process)."""
        if self._launch_cmd is None:
            raise RuntimeError("napcat launch command unavailable")
        existing_qq = _list_qq_pids()
        self._proc = subprocess.Popen(
            self._launch_cmd,
            cwd=str(self.napcat_dir),
            env=_napcat_env(self.napcat_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=(
                subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
                if sys.platform == "win32"
                else 0
            ),
        )
        self._owns_process = True
        self._port_stall_since = None
        self._start_watchdog()
        self._track_task = asyncio.create_task(self._track_launched_qq(existing_qq))

    async def _track_launched_qq(self, existing_qq: set[int]) -> None:
        """Wait for napimain to hand off, then record the QQ PIDs it created.

        napimain.exe exits 0 right after spawning QQ.exe. The newly appeared
        QQ.exe processes are the real long-lived service we must supervise.
        """
        if self._proc is None:
            return
        deadline = time.monotonic() + 45.0
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                break
            await asyncio.sleep(0.5)
        await asyncio.sleep(1.0)
        launched = _list_qq_pids() - existing_qq
        self._owned_qq_pids |= launched
        if launched:
            logger.info("NapCat injected into QQ PIDs: %s", sorted(launched))

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
                if not self._owns_process:
                    continue

                launcher_alive = self._proc is not None and self._proc.poll() is None
                webui_open = _port_is_open(port=self._webui_port)
                ws_open = _port_is_open(port=self.ws_port)
                now = time.monotonic()

                # Refresh authoritative login state from the WebUI. Before QQ
                # login the OneBot11 port is closed by design, so it must not
                # be treated as a stall.
                login = await self._poll_login_status()
                is_login = bool(login and login.get("is_login"))
                if is_login and not ws_open:
                    await self._ensure_ob11_ws()
                elif not is_login:
                    self._ob11_ensured = False
                    self._port_stall_since = None

                # napimain hands off to QQ.exe and exits 0 by design; the
                # injected QQ keeps the WebUI port alive. Only treat the stack
                # as dead when launcher, WebUI and WS are all gone.
                if launcher_alive or webui_open or ws_open:
                    self._consecutive_failures = 0
                    if ws_open or not is_login:
                        self._port_stall_since = None
                    elif self._port_stall_since is None:
                        self._port_stall_since = now
                    if is_login and not ws_open:
                        if now - self._port_stall_since < _WATCHDOG_GRACE_SECONDS:
                            continue
                        self._logs.append(
                            "[watchdog] WebSocket 端口持续未就绪，强制重启 NapCat"
                        )
                        self._teardown_processes()
                        await self._respawn()
                    continue

                # Whole stack is gone (or was force-killed above) → respawn.
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

    def _teardown_processes(self) -> set[int]:
        """Kill the injected QQ trees and any lingering napimain launcher.

        Returns the QQ PIDs that were targeted (for post-stop liveness checks).
        """
        killed = set(self._owned_qq_pids)
        for pid in sorted(killed):
            _kill_pid_tree(pid)
        if self._proc is not None and self._proc.poll() is None:
            _terminate_process_tree(self._proc)
        self._proc = None
        self._owned_qq_pids = set()
        self._owns_process = False
        return killed

    async def stop(self) -> dict:
        """Stop NapCat process."""
        # Stop the watchdog first so it never respawns a process the user
        # explicitly stopped.
        self._stop_watchdog()
        if self._track_task is not None:
            self._track_task.cancel()
            self._track_task = None
        self._consecutive_failures = 0
        if self._webui is not None:
            try:
                await self._webui.close()
            except Exception:
                logger.debug("WebUI client close failed", exc_info=True)
            self._webui = None
        self._login = None
        self._ob11_ensured = False
        if not self._owns_process and (
            _port_is_open(port=self.ws_port) or _port_is_open(port=self._webui_port)
        ):
            self._phase = "connected"
            return {
                "ok": True,
                "message": "NapCat was already running outside Aerie",
                "owned": False,
            }
        killed_pids: set[int] = set()
        if self._owns_process:
            killed_pids = self._teardown_processes()
            self._logs.append("[系统] NapCat 已停止")
        for _ in range(60):
            ports_closed = not _port_is_open(port=self.ws_port) and not _port_is_open(
                port=self._webui_port
            )
            qq_gone = not (_list_qq_pids() & killed_pids)
            if ports_closed and qq_gone:
                break
            await asyncio.sleep(0.25)
        if _port_is_open(port=self.ws_port) or _port_is_open(port=self._webui_port):
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
        self._user_stopped = True
        return {"ok": True, "message": "NapCat stopped", "owned": False}

    def read_qrcode(self) -> bytes | None:
        """Fallback: stale on-disk QR used only when the WebUI is unreachable."""
        if not self.qrcode_path.exists():
            return None
        return self.qrcode_path.read_bytes()

    async def _poll_login_status(self) -> dict | None:
        """Refresh and return WebUI login state; None when WebUI unavailable."""
        webui = await self._get_webui()
        if webui is None:
            return None
        try:
            self._login = await webui.check_login_status()
            return self._login
        except NapCatWebUIError as exc:
            logger.debug("NapCat WebUI status poll failed: %s", exc)
            return None

    async def _ensure_ob11_ws(self) -> None:
        """After QQ login, add the 127.0.0.1:<ws_port> OneBot11 WS server.

        NapCat ships with an empty ``websocketServers`` list, so without this
        step the QQ account logs in but port 3001 never opens and the backend
        cannot connect. Existing user configuration is never overwritten.
        """
        if self._ob11_ensured:
            return
        webui = await self._get_webui()
        if webui is None:
            return
        try:
            config = await webui.get_ob11_config()
        except NapCatWebUIError as exc:
            logger.debug("OB11 GetConfig failed: %s", exc)
            return
        network = config.setdefault("network", {})
        servers = network.setdefault("websocketServers", [])
        if servers:
            self._ob11_ensured = True
            return
        servers.append({
            "name": "aerie-onebot-ws",
            "enable": True,
            "host": "127.0.0.1",
            "port": self.ws_port,
            "reportSelfMessage": False,
            "enableForcePushEvent": True,
            "debug": False,
            "heartInterval": 30000,
            "messagePostFormat": "array",
            "token": "",
        })
        try:
            await webui.set_ob11_config(config)
        except NapCatWebUIError as exc:
            logger.warning("OB11 SetConfig failed: %s", exc)
            return
        self._ob11_ensured = True
        self._logs.append(f"[系统] 已自动开启 OneBot11 WebSocket（127.0.0.1:{self.ws_port}）")

    async def render_qrcode_png(self) -> bytes | None:
        """Render the current login QR URL to a fresh PNG (in-memory)."""
        login = await self._poll_login_status()
        url = str((login or {}).get("qrcode_url") or "")
        if not url:
            return self.read_qrcode()
        image = qrcode.QRCode(border=2, box_size=10)
        image.add_data(url)
        image.make(fit=True)
        buffer = io.BytesIO()
        image.make_image().save(buffer, format="PNG")
        return buffer.getvalue()

    async def refresh_qrcode(self) -> dict:
        """Ask NapCat for a new login QR, then return the latest status."""
        webui = await self._get_webui()
        if webui is None:
            return {"ok": False, "message": "NapCat WebUI 不可用", "error_code": "webui_unavailable"}
        try:
            await webui.refresh_qrcode()
            await asyncio.sleep(1)
            await self._poll_login_status()
        except NapCatWebUIError as exc:
            return {"ok": False, "message": str(exc), "error_code": "webui_error"}
        self._logs.append("[系统] 已请求新的登录二维码")
        return {"ok": True, **self.get_status()}

    async def quick_login_list(self) -> list[dict]:
        webui = await self._get_webui()
        if webui is None:
            return []
        try:
            accounts = await webui.get_quick_login_list()
        except NapCatWebUIError:
            return []
        return [
            {
                "uin": str(item.get("uin") or ""),
                "nickname": str(item.get("nickName") or ""),
                "is_quick_login": bool(item.get("isQuickLogin")),
            }
            for item in accounts
            if item.get("uin")
        ]

    async def quick_login(self, uin: str) -> dict:
        webui = await self._get_webui()
        if webui is None:
            return {"ok": False, "message": "NapCat WebUI 不可用", "error_code": "webui_unavailable"}
        try:
            await webui.quick_login(str(uin))
            await self._poll_login_status()
        except NapCatWebUIError as exc:
            return {"ok": False, "message": str(exc), "error_code": "webui_error"}
        self._logs.append(f"[系统] 已请求快捷登录 QQ {uin}")
        return {"ok": True, **self.get_status()}


_LAUNCHER: NapcatLauncher | None = None


def get_launcher(settings: dict | None = None) -> NapcatLauncher:
    global _LAUNCHER
    if _LAUNCHER is None:
        _LAUNCHER = NapcatLauncher(settings)
    return _LAUNCHER
