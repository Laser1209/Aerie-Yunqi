"""Aerie · 云栖 v9.0 — NapCat launcher integration.

Bridges the AI system with NapCat's two startup scripts:

  - launcher.bat          (admin / UAC elevation)
  - launcher-user.bat     (user mode, no admin)

The launcher probes the WebSocket port (default 3001) to detect
whether NapCat is already running. When not, it spawns the chosen
``.bat`` via ``subprocess.Popen`` (no console window) and tails a
log file. The QQ WebSocket client (``communication.qq_client``)
will keep retrying the connection, so the launcher just needs to
make sure NapCat is up and the WS port is reachable.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


# Default port NapCat WebSocket listens on.
DEFAULT_WS_PORT = 3001
# Max seconds to wait for the port to come up after a launch.
DEFAULT_PORT_READY_TIMEOUT = 45


@dataclass
class NapCatStatus:
    """Lightweight snapshot of the launcher state."""

    installed: bool = False
    running: bool = False
    ws_port_open: bool = False
    launcher_dir: str = ""
    user_launcher: str = ""
    admin_launcher: str = ""
    pid: Optional[int] = None
    last_error: str = ""
    last_action: str = ""
    last_action_at: float = 0.0
    config: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "installed": self.installed,
            "running": self.running,
            "ws_port_open": self.ws_port_open,
            "launcher_dir": self.launcher_dir,
            "user_launcher": self.user_launcher,
            "admin_launcher": self.admin_launcher,
            "pid": self.pid,
            "last_error": self.last_error,
            "last_action": self.last_action,
            "last_action_at": self.last_action_at,
            "ws_port": self.config.get("ws_port", DEFAULT_WS_PORT),
        }


class NapCatLauncher:
    """Manages the NapCat lifecycle for the AI system."""

    def __init__(self, config: Optional[dict] = None) -> None:
        cfg = config or {}
        napcat_cfg = cfg.get("napcat", {}) if isinstance(cfg, dict) else {}
        qq_cfg = cfg.get("qq", {}) if isinstance(cfg, dict) else {}

        self.ws_port: int = int(napcat_cfg.get("ws_port", qq_cfg.get("napcat_ws_port", DEFAULT_WS_PORT)))
        self.shell_dir: str = napcat_cfg.get(
            "shell_dir",
            str(Path(__file__).resolve().parents[1] / "NapCat" / "NapCat.Shell"),
        )
        self.prefer_user: bool = bool(napcat_cfg.get("prefer_user_launcher", True))
        self.auto_start: bool = bool(napcat_cfg.get("auto_start", True))
        self.log_path: str = napcat_cfg.get(
            "log_path",
            str(Path(__file__).resolve().parents[1] / "logs" / "napcat_launcher.log"),
        )
        self.port_ready_timeout: int = int(napcat_cfg.get("port_ready_timeout", DEFAULT_PORT_READY_TIMEOUT))

        self._proc: Optional[subprocess.Popen] = None
        self._log_handle = None
        self._status = NapCatStatus(
            launcher_dir=self.shell_dir,
            user_launcher=str(Path(self.shell_dir) / "launcher-user.bat"),
            admin_launcher=str(Path(self.shell_dir) / "launcher.bat"),
            config={"ws_port": self.ws_port},
        )
        self._refresh_install_state()

    # ------------------------------------------------------------------ utils
    def _refresh_install_state(self) -> None:
        user_bat = Path(self._status.user_launcher)
        admin_bat = Path(self._status.admin_launcher)
        if user_bat.exists() or admin_bat.exists():
            self._status.installed = True

    def _open_log(self) -> None:
        try:
            log_file = Path(self.log_path)
            log_file.parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = open(log_file, "a", encoding="utf-8", errors="ignore")
            self._log_handle.write(
                f"\n===== [{time.strftime('%Y-%m-%d %H:%M:%S')}] napcat launcher log =====\n"
            )
            self._log_handle.flush()
        except Exception as e:  # noqa: BLE001
            logger.warning("open napcat log failed: %s", e)
            self._log_handle = None

    def _log(self, line: str) -> None:
        msg = f"[{time.strftime('%H:%M:%S')}] {line}"
        logger.info(msg)
        if self._log_handle is not None:
            try:
                self._log_handle.write(msg + "\n")
                self._log_handle.flush()
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _check_port(host: str, port: int, timeout: float = 0.6) -> bool:
        """Return True if ``host:port`` accepts a TCP connection."""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except Exception:  # noqa: BLE001
            return False

    def is_port_open(self) -> bool:
        return self._check_port("127.0.0.1", self.ws_port)

    def is_process_alive(self) -> bool:
        if self._proc is None:
            return False
        return self._proc.poll() is None

    def refresh_status(self) -> NapCatStatus:
        self._status.ws_port_open = self.is_port_open()
        self._status.running = self._status.ws_port_open or self.is_process_alive()
        if self._proc and not self.is_process_alive() and self._status.pid is not None:
            # Proc exited but port is still up → NapCat likely owned by another launcher.
            self._status.pid = None
        return self._status

    # --------------------------------------------------------------- control
    async def start(self, prefer_user: Optional[bool] = None, wait_port: bool = True) -> dict:
        """Launch NapCat and (optionally) wait until the WS port is open.

        Returns a dict with keys: started, running, port_open, message.
        """
        if not self._status.installed:
            self._status.last_error = "NapCat launcher scripts not found"
            self._log("start failed: launcher scripts missing")
            return {"started": False, "running": False, "port_open": False, "message": self._status.last_error}

        self.refresh_status()
        if self._status.running and (self._status.ws_port_open or self.is_process_alive()):
            return {"started": False, "running": True, "port_open": self._status.ws_port_open, "message": "already running"}

        use_user = self.prefer_user if prefer_user is None else prefer_user
        script = self._status.user_launcher if use_user else self._status.admin_launcher
        script_path = Path(script)
        if not script_path.exists():
            # Fall back to whichever launcher exists.
            alt = self._status.admin_launcher if use_user else self._status.user_launcher
            if Path(alt).exists():
                script = alt
                script_path = Path(script)
            else:
                self._status.last_error = f"launcher script not found: {script}"
                self._log(self._status.last_error)
                return {"started": False, "running": False, "port_open": False, "message": self._status.last_error}

        self._open_log()
        self._log(f"launching: {script}")
        try:
            # Windows-only: hide the new console window completely.
            creationflags = 0
            if platform.system() == "Windows" and hasattr(subprocess, "CREATE_NO_WINDOW"):
                creationflags = subprocess.CREATE_NO_WINDOW
            self._proc = subprocess.Popen(
                ["cmd.exe", "/c", str(script_path)],
                cwd=str(script_path.parent),
                stdout=self._log_handle if self._log_handle else subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                close_fds=True,
            )
            self._status.pid = self._proc.pid
            self._status.last_action = "start"
            self._status.last_action_at = time.time()
            self._log(f"spawned pid={self._proc.pid}")
        except Exception as e:  # noqa: BLE001
            self._status.last_error = f"spawn failed: {e}"
            self._log(self._status.last_error)
            return {"started": False, "running": False, "port_open": False, "message": self._status.last_error}

        if not wait_port:
            return {"started": True, "running": True, "port_open": False, "message": "started, waiting externally"}

        ok = await self.wait_for_port()
        self.refresh_status()
        return {
            "started": True,
            "running": self._status.running,
            "port_open": self._status.ws_port_open,
            "message": "ready" if ok else "started but WS port not yet open",
        }

    async def wait_for_port(self, timeout: Optional[int] = None) -> bool:
        """Poll the WS port until it is open or the timeout elapses."""
        secs = timeout if timeout is not None else self.port_ready_timeout
        deadline = time.time() + max(1, int(secs))
        while time.time() < deadline:
            if self.is_port_open():
                self._log(f"WS port {self.ws_port} is open")
                return True
            await asyncio.sleep(1.0)
        self._log(f"WS port {self.ws_port} not ready within {secs}s")
        return False

    async def stop(self) -> dict:
        """Stop NapCat. Best-effort: kills the tracked process and any QQ child."""
        if not self.is_process_alive() and not self.is_port_open():
            return {"stopped": True, "message": "already stopped"}
        # Try graceful first
        stopped = False
        if self._proc is not None:
            try:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                    stopped = True
                except Exception:  # noqa: BLE001
                    self._proc.kill()
                    stopped = True
            except Exception as e:  # noqa: BLE001
                self._log(f"terminate failed: {e}")
        # Belt-and-suspenders: also kill QQ.exe and NapCatWinBootMain.exe.
        for exe in ("QQ.exe", "NapCatWinBootMain.exe"):
            try:
                subprocess.run(
                    ["taskkill", "/IM", exe, "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
            except Exception:  # noqa: BLE001
                pass
        self._proc = None
        self._status.pid = None
        self._status.last_action = "stop"
        self._status.last_action_at = time.time()
        self._log("stopped")
        self.refresh_status()
        return {"stopped": True, "running": self._status.running, "port_open": self._status.ws_port_open}

    def shutdown(self) -> None:
        try:
            if self._log_handle is not None:
                self._log_handle.close()
        except Exception:  # noqa: BLE001
            pass


# Convenience singleton used by the API layer and the Companion.
_LAUNCHER: Optional[NapCatLauncher] = None


def get_launcher(config: Optional[dict] = None) -> NapCatLauncher:
    global _LAUNCHER
    if _LAUNCHER is None:
        from config.persona_loader import load_settings

        cfg = config or load_settings()
        _LAUNCHER = NapCatLauncher(cfg)
    return _LAUNCHER
