"""Aerie · 云栖 — NapCat 运行时受控安装（内置官方引导器 + 程序化下载）。

## 为什么需要这个模块

NapCat Shell 的 ``napimain.exe`` 需要一个**外部 QQ.exe** 作为注入宿主
（``napimain.exe <QQ.exe> <napiloader.dll> <nativeLoader.cjs>``）。此前启动器从
Windows 注册表取系统 QQ，用户的机器上是 **QQ Beta 通道**（``D:\\QQ_Beta``，会跟随
Beta 自动升级）——注入后账号被风控、连一段时间就要求重新登录。

本模块把"QQ 从哪来"收进**我们受控的目录**，并保证登录全程不弹 QQ 客户端窗口：

* **主路径（silent / 可自动化）**：按官方引导器**完全相同的下载源**取
  QQ 与 NapCat.Shell.zip，安装/解压到 ``data/napcat-runtime/``，全程无 GUI；
* **兜底路径（manual）**：内置官方 OneKey 引导器 ``NapCatInstaller.exe``，
  需要人工介入时由面板一键拉起，**工作目录固定为同一个受控目录**，
  避免它把东西装到不可预期的位置。

## 设计约束

* 运行时不读仓库外任何路径；目标目录由配置决定，默认 ``data/napcat-runtime``；
* 下载源与版本号是**常量**（与官方引导器内置的一致），换版本只改这里；
* 所有阻塞操作（下载/安装/解压）由调用方放进 ``asyncio.to_thread``，
  本模块不依赖事件循环，便于单测。
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── 下载源 ────────────────────────────────────────────────────
# 【实测结论 2026-09-28】腾讯官方 CDN 对**非浏览器直连返回 403**（防盗链），
# 且旧版 hash 路径（OneKey 引导器内置的那个）已是 404。因此：
#   1. **本地安装包优先** —— 用户用浏览器下载后放进受控目录即可（最可靠）；
#   2. 远程下载仅"尽力而为"，失败时给出明确原因（不会静默降级）。
# 版本号写死在文件名里，换版本只需改这两行。
QQ_INSTALLER_URL = "https://qqdl.gtimg.cn/qqfile/QQNTV2/9.9.36/release/e8e54bbb/QQ_9.9.36_260924_x86_01.exe"
QQ_INSTALLER_FILENAME = "QQ_9.9.36_260924_x86_01.exe"

# NapCat Shell 本体：官方源 → 镜像源，依次尝试（与 napcat_downloader 同源）。
NAPCAT_SHELL_SOURCES: tuple[str, ...] = (
    "https://github.com/NapNeko/NapCatQQ/releases/latest/download/NapCat.Shell.zip",
    "https://github.moeyy.xyz/https://github.com/NapNeko/NapCatQQ/releases/latest/download/NapCat.Shell.zip",
)

_PER_SOURCE_TIMEOUT_SECONDS = 60 * 30
_DOWNLOAD_CHUNK = 256 * 1024


def runtime_root(settings: dict | None = None) -> Path:
    """受控运行时根目录：环境变量 > settings.napcat.runtime_dir > data/napcat-runtime。"""
    env_dir = os.environ.get("AERIE_NAPCAT_RUNTIME_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    cfg_dir = (settings or {}).get("napcat", {}).get("runtime_dir")
    if cfg_dir:
        return Path(str(cfg_dir)).expanduser()
    from core.paths import data_dir

    return data_dir() / "napcat-runtime"


def qq_target_dir(settings: dict | None = None) -> Path:
    """受控 QQ 安装目录（QQ.exe 所在目录的候选根）。"""
    return runtime_root(settings) / "QQ"


def bundled_installer_path() -> Path | None:
    """内置官方 OneKey 引导器路径（打包后由 extraResources 一并拷贝）。"""
    env_dir = os.environ.get("AERIE_NAPCAT_ONEKEY_DIR")
    base = Path(env_dir).expanduser() if env_dir else _PROJECT_ROOT / "NapCat" / "OneKey"
    candidate = base / "NapCatInstaller.exe"
    return candidate if candidate.exists() else None


def bundled_boot_exe() -> Path | None:
    """内置的**无头**启动器 ``NapCatWinBootMain.exe``（无需注册表、可显式指定 QQ）。"""
    env_dir = os.environ.get("AERIE_NAPCAT_ONEKEY_DIR")
    base = Path(env_dir).expanduser() if env_dir else _PROJECT_ROOT / "NapCat" / "OneKey"
    candidate = base / "bootmain" / "NapCatWinBootMain.exe"
    return candidate if candidate.exists() else None


def installer_drop_dir(settings: dict | None = None) -> Path:
    """本地安装包投放目录：用户用浏览器下载 QQ 安装包后放这里即可离线安装。

    为什么不直接下载：腾讯官方 CDN 对非浏览器直连返回 403（实测），
    而浏览器下载是用户手上最可靠的途径 —— 所以把"投递点"固定下来，
    由程序负责静默安装与目录收口，这正是"内置引导器 + 规定下载位置"的落地形态。
    """
    return runtime_root(settings) / "installer"


def find_local_installer(settings: dict | None = None) -> Path | None:
    """找本地 QQ 安装包：显式配置 > 投放目录里的第一个 QQ*.exe。"""
    explicit = os.environ.get("AERIE_QQ_INSTALLER") or (settings or {}).get("napcat", {}).get("qq_installer")
    if explicit:
        candidate = Path(str(explicit)).expanduser()
        if candidate.exists():
            return candidate
    drop = installer_drop_dir(settings)
    if drop.exists():
        for candidate in sorted(drop.glob("QQ*.exe")):
            return candidate
    return None


def resolve_qq_exe(settings: dict | None = None) -> Path | None:
    """在受控目录里找 QQ.exe（安装产物可能嵌在版本子目录，故递归查找）。"""
    root = qq_target_dir(settings)
    if not root.exists():
        return None
    direct = root / "QQ.exe"
    if direct.exists():
        return direct
    for found in root.rglob("QQ.exe"):
        return found
    return None


class NapcatInstaller:
    """受控安装 NapCat QQ 运行时（进度可轮询，线程安全）。"""

    def __init__(self, settings: dict | None = None) -> None:
        self.settings = settings or {}
        self.root = runtime_root(self.settings)
        self.qq_dir = qq_target_dir(self.settings)
        self._state = "idle"  # idle | downloading | installing | extracting | done | error
        self._progress = 0.0
        self._message = ""
        self._error = ""
        self._lock = threading.Lock()

    # ── 状态 ────────────────────────────────────────────────
    def _set(self, state: str, message: str = "", progress: float | None = None) -> None:
        with self._lock:
            self._state = state
            if message:
                self._message = message
            if progress is not None:
                self._progress = progress

    def status(self) -> dict:
        qq_exe = resolve_qq_exe(self.settings)
        local = find_local_installer(self.settings)
        with self._lock:
            state, progress, message, error = (
                self._state, round(self._progress, 3), self._message, self._error,
            )
        return {
            "state": state,
            "progress": progress,
            "message": message,
            "error": error,
            "installed": qq_exe is not None,
            "qq_exe": str(qq_exe) if qq_exe else "",
            "runtime_dir": str(self.root),
            "installer_embedded": bundled_installer_path() is not None,
            # 本地投放的安装包与投放目录：面板据此告诉用户"把安装包放这里"。
            "local_installer": str(local) if local else "",
            "installer_drop_dir": str(installer_drop_dir(self.settings)),
        }

    def is_running(self) -> bool:
        with self._lock:
            return self._state in ("downloading", "installing", "extracting")

    # ── 主路径：程序化安装受控 QQ ────────────────────────────
    def install_qq_runtime(self) -> dict:
        """下载并安装固定版本的官方 QQ 到受控目录（阻塞，调用方用 to_thread）。"""
        if self.is_running():
            return {"ok": False, "message": "安装已在进行中", "error_code": "already_running"}
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            # 本地安装包优先：腾讯 CDN 对直连返回 403，浏览器下载才是可靠途径。
            local = find_local_installer(self.settings)
            if local is not None:
                installer = local
                self._set("installing", f"使用本地安装包：{installer.name}", progress=0.5)
            else:
                installer = self.root / QQ_INSTALLER_FILENAME
                self._set("downloading", "正在从腾讯官方 CDN 下载 QQ 安装包…", progress=0.0)
                self._download(QQ_INSTALLER_URL, installer)

            self._set("installing", "正在静默安装 QQ 到受控目录…", progress=0.75)
            if not self._silent_install(installer):
                self._set("extracting", "静默安装未生效，改用解包方式…", progress=0.8)
                self._seven_zip_extract(installer, self.qq_dir)

            qq_exe = resolve_qq_exe(self.settings)
            if qq_exe is None:
                self._set("error", "安装完成但未找到 QQ.exe", progress=0.0)
                self._error = "qq_exe_not_found"
                return {"ok": False, "message": "未能在受控目录中找到 QQ.exe", "error_code": "qq_exe_not_found"}

            # 只清理"我们下载的那一份"，用户自己投放的安装包保持原样（可复用）。
            if local is None:
                try:
                    installer.unlink(missing_ok=True)
                except OSError:
                    pass
            self._set("done", f"QQ 运行时已就绪：{qq_exe}", progress=1.0)
            logger.info("[NapCat] controlled QQ runtime installed at %s", qq_exe)
            return {"ok": True, "message": "QQ 运行时安装完成", "qq_exe": str(qq_exe)}
        except Exception as exc:  # noqa: BLE001
            logger.exception("controlled QQ runtime install failed")
            self._error = str(exc)
            self._set("error", f"安装失败：{exc}", progress=0.0)
            return {"ok": False, "message": f"QQ 运行时安装失败：{exc}", "error_code": "install_failed"}

    def _silent_install(self, installer: Path) -> bool:
        """NSIS 静默安装：``/S`` + ``/D=<dir>``（``/D`` 必须是最后一个参数且不带引号）。"""
        if sys.platform != "win32" or not installer.exists():
            return False
        target = str(self.qq_dir)
        try:
            completed = subprocess.run(
                [str(installer), "/S", f"/D={target}"],
                capture_output=True,
                timeout=900,
                check=False,
                cwd=str(self.root),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("silent QQ install did not complete: %s", exc)
            return False
        if completed.returncode != 0:
            logger.warning("silent QQ install exit=%s", completed.returncode)
        return resolve_qq_exe(self.settings) is not None

    def _seven_zip_extract(self, installer: Path, target: Path) -> None:
        """静默安装失败时用内置 7z 解包（官方引导器同款手段）。"""
        seven_zip = Path(
            os.environ.get("AERIE_NAPCAT_ONEKEY_DIR")
            or (_PROJECT_ROOT / "NapCat" / "OneKey")
        ) / "7z.exe"
        if sys.platform != "win32" or not seven_zip.exists():
            raise RuntimeError("7z extractor unavailable")
        target.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [str(seven_zip), "x", "-y", f"-o{target}", str(installer)],
            capture_output=True,
            timeout=900,
            check=True,
            cwd=str(self.root),
        )

    def _download(self, url: str, dest: Path) -> None:
        req = Request(url, headers={"User-Agent": "Aerie-Cloud"})
        with urlopen(req, timeout=_PER_SOURCE_TIMEOUT_SECONDS) as resp, open(dest, "wb") as fh:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(_DOWNLOAD_CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if total:
                    self._set(
                        "downloading",
                        f"正在下载官方 QQ 安装包… {done // 1024 // 1024}MB / {total // 1024 // 1024}MB",
                        progress=min(done / total * 0.75, 0.75),
                    )

    # ── 兜底路径：内置官方引导器 ─────────────────────────────
    def launch_bundled_installer(self) -> dict:
        """拉起内置官方 OneKey 引导器，工作目录固定为受控目录。

        引导器是 GUI 程序（无静默参数），因此这一步只负责**把它放在正确的目录里启动**，
        由用户点完安装；产物会落在受控目录内，仍由 ``resolve_qq_exe`` 收口。
        """
        installer = bundled_installer_path()
        if installer is None:
            return {"ok": False, "message": "未找到内置引导器", "error_code": "installer_missing"}
        if sys.platform != "win32":
            return {"ok": False, "message": "仅支持 Windows", "error_code": "unsupported_platform"}
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(
                [str(installer)],
                cwd=str(self.root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            logger.exception("launch bundled NapCat installer failed")
            return {"ok": False, "message": f"引导器启动失败：{exc}", "error_code": "launch_failed"}
        self._set("installing", "已拉起内置引导器，请在窗口中完成安装", progress=0.1)
        return {"ok": True, "message": "已在受控目录中启动内置引导器", "runtime_dir": str(self.root)}


_INSTALLER: NapcatInstaller | None = None


def get_installer(settings: dict | None = None) -> NapcatInstaller:
    global _INSTALLER
    if _INSTALLER is None:
        _INSTALLER = NapcatInstaller(settings)
    return _INSTALLER
