"""Aerie · 云栖 — QQ 引擎网关（进程管理 + 配置自动注入 + watchdog）。

统一管理本地 QQ 引擎进程：

- **配置自动注入**：启动前检查引擎的 OneBot11 网络配置（``onebot11_<uin>.json``），
  确保 WS 端口、鉴权 token、消息格式（array）、心跳与 Aerie 设定一致；
  缺失时自动生成，避免手工维护配置。
- **进程生命周期**：启动 / 停止 / 状态查询 / 二维码读取，供状态页面板调用。
- **watchdog**：进程退出或 WS 端口长时间关闭时自动重启（指数退避防重启风暴），
  只在进程由本实例拉起（``_owns_process``）时生效，不干扰外部自管的引擎。

对外暴露 :class:`QQEngineGateway` 与单例 :func:`get_gateway`。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_ENGINE_DIR = _PROJECT_ROOT / "data" / "qq_engine"

# 网关 token 持久化位置（自动生成后落盘，与 settings 中的 qq.token 同源）
_TOKEN_MARKER = "data/qq_gateway_token.txt"


def _resolve_engine_dir(settings: dict | None) -> Path:
    """Resolve engine directory：环境变量 > settings.qq_engine.dir > 默认。"""
    env_dir = os.environ.get("AERIE_QQ_ENGINE_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    cfg_dir = (settings or {}).get("qq_engine", {}).get("dir")
    if cfg_dir:
        return Path(str(cfg_dir)).expanduser()
    return _DEFAULT_ENGINE_DIR


def get_gateway_token(settings: dict | None) -> str:
    """返回统一的 QQ 引擎鉴权 token。

    优先级：settings.qq.token > data/qq_gateway_token.txt（自动生成并落盘）。
    OneBot11 配置注入与 WS 客户端连接共用同一个 token，保证鉴权一致。
    """
    configured = (settings or {}).get("qq", {}).get("token")
    if configured and str(configured).strip():
        return str(configured).strip()
    marker = _PROJECT_ROOT / _TOKEN_MARKER
    try:
        if marker.exists():
            saved = marker.read_text(encoding="utf-8").strip()
            if saved:
                return saved
    except Exception:
        pass
    token = secrets.token_hex(16)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(token, encoding="utf-8")
    except Exception:
        logger.exception("gateway token persist failed")
    return token


def _port_is_open(host: str = "127.0.0.1", port: int = 3001) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except (OSError, TimeoutError):
        return False


def _terminate_process_tree(proc: subprocess.Popen) -> None:
    """Terminate only the process tree launched by this instance."""
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


_LAUNCHER_CANDIDATES = ("launcher-user.bat", "launcher.bat", "qq-engine.bat")


def _find_launcher(engine_dir: Path) -> Path:
    """Return the first existing launcher script (Shell 包 / 一键包启动器名不同)。"""
    for name in _LAUNCHER_CANDIDATES:
        candidate = engine_dir / name
        if candidate.exists():
            return candidate
    return engine_dir / _LAUNCHER_CANDIDATES[0]


# Watchdog tunables
_WATCHDOG_GRACE_SECONDS = 60.0
_WATCHDOG_POLL_SECONDS = 5.0
_WATCHDOG_PORT_STALL_SECONDS = 60.0
_WATCHDOG_MAX_BACKOFF_SECONDS = 120.0


class QQEngineGateway:
    """QQ 引擎进程网关：配置注入 + 启动/停止 + watchdog + QR 码。"""

    def __init__(self, settings: dict | None = None) -> None:
        self.settings = settings or {}
        qq_cfg = self.settings.get("qq", {}) or {}
        self.ws_port = int(qq_cfg.get("ws_port", 3001))
        self.engine_dir = _resolve_engine_dir(self.settings)
        self.launcher_bat = _find_launcher(self.engine_dir)
        self.qrcode_path = self.engine_dir / "cache" / "qrcode.png"
        self._proc: subprocess.Popen | None = None
        self._owns_process = False
        self._logs: list[str] = []
        self._phase = "idle"  # idle | starting | qr_pending | connected
        self._error_code = ""
        self._watchdog_task: asyncio.Task | None = None
        self._watchdog_stopped = False
        self._consecutive_failures = 0
        self._port_stall_since: float | None = None

    def _refresh_paths(self) -> None:
        """Re-resolve engine paths（下载解压后目录可能已更新，启动前刷新）。"""
        self.engine_dir = _resolve_engine_dir(self.settings)
        self.launcher_bat = _find_launcher(self.engine_dir)
        self.qrcode_path = self.engine_dir / "cache" / "qrcode.png"

    # ── OneBot11 配置自动注入 ────────────────────────────

    def ensure_config(self) -> dict:
        """确保引擎的 OneBot11 网络配置与 Aerie 设定一致。

        - 扫描 ``config/onebot11_<uin>.json`` / ``onebot11.json``；
        - 缺失则创建；存在但端口/token/格式/心跳不符则备份后重写；
        - token 来自 settings.qq.token 或自动生成（与 WS 客户端共用）。
        """
        config_dir = self.engine_dir / "config"
        if not config_dir.is_dir():
            return {"ok": False, "changed": False, "message": "engine config dir missing"}

        token = get_gateway_token(self.settings)
        candidates = sorted(config_dir.glob("onebot11*.json"))
        if not candidates:
            # 无账号级配置 → 创建通用 onebot11.json
            candidates = [config_dir / "onebot11.json"]

        changed_any = False
        for path in candidates:
            changed = self._patch_onebot_config(path, token)
            changed_any = changed_any or changed
        return {
            "ok": True,
            "changed": changed_any,
            "token": token,
            "ws_port": self.ws_port,
            "config_files": [str(p) for p in candidates],
        }

    def _patch_onebot_config(self, path: Path, token: str) -> bool:
        """重写单个 OneBot11 网络配置文件，返回是否发生变更。"""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = {"network": {}}
        network = payload.setdefault("network", {})
        servers = network.setdefault("websocketServers", [])

        desired = {
            "name": "Aerie-OneBot11",
            "enable": True,
            "host": "127.0.0.1",
            "port": self.ws_port,
            "enableHeartbeat": True,
            "heartbeatInterval": 15000,
            "enableForcePushEvent": True,
            "messagePostFormat": "array",
            "reportSelfMessage": False,
            "token": token,
            "debug": False,
            "autoDelete": False,
        }
        if not servers:
            servers.append(desired)
            changed = True
        else:
            changed = False
            for idx, server in enumerate(servers):
                if not isinstance(server, dict):
                    continue
                # 合并期望字段（覆盖手工/旧配置，保证与 Aerie 一致）
                merged = dict(desired)
                merged.update({k: v for k, v in server.items() if k not in desired})
                # 显式覆盖关键字段
                merged["name"] = "Aerie-OneBot11"
                merged["enable"] = True
                merged["port"] = self.ws_port
                merged["token"] = token
                merged["messagePostFormat"] = "array"
                merged["enableHeartbeat"] = True
                servers[idx] = merged
                changed = True  # 统一走重写（确保字段完整）
                break
            if not changed:
                servers.append(desired)
                changed = True

        # 修改前备份，避免写坏配置无法回退
        if changed:
            try:
                backup = path.with_suffix(path.suffix + ".bak")
                backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception:
                logger.debug("onebot config backup failed", exc_info=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("[QQGateway] patched engine OneBot11 config: %s (port=%s token=%s..)",
                        path.name, self.ws_port, token[:6])
        return changed

    # ── 状态 ─────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return current engine status for API."""
        qr_exists = self.qrcode_path.exists()
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

    # ── 启动 / 停止 ──────────────────────────────────────

    async def start(self) -> dict:
        """启动 QQ 引擎进程（启动前先注入 OneBot11 配置）。"""
        self._refresh_paths()
        if self._proc and self._proc.poll() is None:
            return {"ok": False, "message": "QQ engine already running"}
        if self._proc is not None:
            self._proc = None
            self._owns_process = False

        if _port_is_open(port=self.ws_port):
            self._phase = "connected"
            self._error_code = ""
            return {
                "ok": True,
                "message": "QQ engine was already running outside Aerie",
                "already_running": True,
                "owned": False,
            }

        if not self.launcher_bat.exists():
            self._phase = "error"
            self._error_code = "launcher_not_found"
            return {
                "ok": False,
                "message": "QQ engine launcher is unavailable",
                "error_code": self._error_code,
            }

        # 配置注入：确保 OneBot11 端口/token/格式与 Aerie 一致
        cfg_result = self.ensure_config()
        if not cfg_result.get("ok"):
            self._phase = "error"
            self._error_code = "config_inject_failed"
            return {
                "ok": False,
                "message": "QQ engine config injection failed",
                "error_code": self._error_code,
            }

        self._phase = "starting"
        self._error_code = ""
        self._logs.clear()
        self._logs.append("[系统] 正在启动 QQ 引擎...")
        if cfg_result.get("changed"):
            self._logs.append("[系统] OneBot11 配置已注入（token/端口/格式）")

        try:
            self._spawn()
            self._logs.append("[系统] 引擎进程已启动，等待端口...")

            # Poll for port open
            for i in range(30):  # max 30s
                await asyncio.sleep(1)
                if _port_is_open(port=self.ws_port):
                    self._phase = "connected"
                    self._logs.append("[系统] WebSocket 端口已就绪，已连接")
                    return {"ok": True, "port_open": True, "message": "QQ engine connected"}
                # Check for QR code during wait
                if self.qrcode_path.exists():
                    self._phase = "qr_pending"
                    self._logs.append("[系统] 检测到二维码，请用手机QQ扫码登录")
                    return {
                        "ok": True,
                        "port_open": False,
                        "qrcode_available": True,
                        "message": "QR code ready",
                        "owned": True,
                    }

            self._logs.append("[系统] 等待超时，请检查引擎日志")
            self._phase = "error"
            self._error_code = "engine_start_timeout"
            return {
                "ok": False,
                "port_open": False,
                "message": "QQ engine did not become ready in time",
                "error_code": self._error_code,
                "owned": True,
            }

        except Exception:
            if self._proc is not None and self._owns_process:
                _terminate_process_tree(self._proc)
            self._proc = None
            self._owns_process = False
            self._phase = "error"
            self._error_code = "engine_start_failed"
            self._logs.append("[错误] 启动失败")
            logger.exception("QQ engine start error")
            return {
                "ok": False,
                "message": "QQ engine failed to start",
                "error_code": self._error_code,
            }

    def _spawn(self) -> None:
        """Launch the engine process via launcher-user.bat (sync)."""
        if sys.platform == "win32":
            self._proc = subprocess.Popen(
                [str(self.launcher_bat)],
                cwd=str(self.engine_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    | subprocess.CREATE_NEW_PROCESS_GROUP
                ),
            )
        else:
            self._proc = subprocess.Popen(
                [str(self.launcher_bat)],
                cwd=str(self.engine_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        self._owns_process = True
        self._port_stall_since = None
        self._start_watchdog()

    async def stop(self) -> dict:
        """Stop engine process."""
        # Stop the watchdog first so it never respawns a process the user
        # explicitly stopped.
        self._stop_watchdog()
        self._consecutive_failures = 0
        if not self._owns_process and _port_is_open(port=self.ws_port):
            self._phase = "connected"
            return {
                "ok": True,
                "message": "QQ engine was already running outside Aerie",
                "owned": False,
            }
        if self._proc is not None and self._owns_process:
            _terminate_process_tree(self._proc)
            self._logs.append("[系统] QQ 引擎已停止")
        self._proc = None
        self._owns_process = False
        for _ in range(20):
            if not _port_is_open(port=self.ws_port):
                break
            await asyncio.sleep(0.25)
        if _port_is_open(port=self.ws_port):
            self._phase = "error"
            self._error_code = "engine_residual_port"
            return {
                "ok": False,
                "message": "QQ engine stopped but its port is still in use",
                "error_code": self._error_code,
                "owned": False,
            }
        self._phase = "idle"
        self._error_code = ""
        return {"ok": True, "message": "QQ engine stopped", "owned": False}

    def read_qrcode(self) -> bytes | None:
        """Read QR code image bytes for display in the UI."""
        if not self.qrcode_path.exists():
            return None
        return self.qrcode_path.read_bytes()

    # ── watchdog ─────────────────────────────────────────

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
        """Auto-respawn the engine when it dies or the WS port stalls.

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
                        "[watchdog] WebSocket 端口持续未就绪，强制重启引擎"
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
            logger.exception("QQ engine watchdog loop error")
            self._watchdog_task = None

    async def _respawn(self) -> None:
        """Respawn engine with exponential backoff to avoid crash storms."""
        self._consecutive_failures += 1
        delay = min(
            _WATCHDOG_PORT_STALL_SECONDS / 2 * (2 ** min(self._consecutive_failures - 1, 4)),
            _WATCHDOG_MAX_BACKOFF_SECONDS,
        )
        self._logs.append(
            f"[watchdog] 引擎进程已退出，{int(delay)}s 后自动重启 "
            f"(连续失败 {self._consecutive_failures} 次)"
        )
        logger.warning(
            "QQ engine process exited; respawning in %.0fs (failure #%d)",
            delay, self._consecutive_failures,
        )
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise
        if self._watchdog_stopped:
            return
        try:
            # 重启前同样注入配置（目录可能被更新）
            try:
                self.ensure_config()
            except Exception:
                logger.exception("engine config re-inject failed before respawn")
            self._spawn()
        except Exception:
            logger.exception("QQ engine respawn failed")


_GATEWAY: QQEngineGateway | None = None


def get_gateway(settings: dict | None = None) -> QQEngineGateway:
    global _GATEWAY
    if _GATEWAY is None:
        _GATEWAY = QQEngineGateway(settings)
    return _GATEWAY
