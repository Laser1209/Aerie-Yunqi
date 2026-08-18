"""Aerie · 云栖 — 自包含 Python 运行时构建脚本。

背景（问题根因）：
    旧打包方案把开发机的 `.venv` 原样塞进安装包，但 `.venv/Scripts/python.exe`
    只是"重定向器"，运行时按 `.venv/pyvenv.cfg` 的 `home` 字段去找基础解释器
    （例如 `C:\\Python314\\python.exe`）。换到没装 Python 的干净机器上，这个
    重定向器起不来，后端直接 `ECONNREFUSED`。旧方案只能在用户首次启动时
    联网下载 embeddable Python 兜底，属于不可靠的临时方案。

本脚本方案（自包含嵌入式运行时）：
    1. 从 `.venv/pyvenv.cfg` 读取基础解释器真实路径（`home` 字段）；
    2. 把基础解释器**完整拷贝**为 `electron/runtime-build/`，得到一个真实、
       可迁移的 `python.exe`（无需重定向、无需下载）；
    3. 用 `.venv/Lib/site-packages` 覆盖运行时的三方依赖目录，剔除
       pip/setuptools/wheel/pytest 等开发期专用包，减小体积。

产物：`electron/runtime-build/`，由 electron-builder 通过 extraResources
复制到 `resources/python/runtime/`。Electron 直接 spawn 该 `python.exe`。

用法：
    python scripts/build_python_runtime.py [--out DIR]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "electron" / "runtime-build"

# 基础解释器安装目录中，开发/打包都不需要的目录（相对 base 根，Windows 分隔符）。
BASE_EXCLUDE_REL = {
    "Doc",
    "include",
    "libs",
    "tcl",
    "Scripts",
    "Lib\\test",
    "Lib\\idlelib",
    "Lib\\tkinter",
    "Lib\\turtledemo",
    "Lib\\ensurepip",
    "Lib\\lib2to3",
    "Lib\\site-packages",  # 稍后用 .venv 的 site-packages 整体覆盖
}

# 顶层无用的说明文件。
BASE_EXCLUDE_FILES = {"LICENSE.txt", "NEWS.txt"}

# 开发期专用包（按目录名精确剔除，避免误伤 numpy._pytesttester 等内部文件）。
SITE_EXCLUDE_DIRS = {
    "pip",
    "setuptools",
    "wheel",
    "pytest",
    "_pytest",
    "pytest_asyncio",
}

# 上述包的 .dist-info/.egg-info 元数据（按前缀剔除）。
SITE_EXCLUDE_DIST_PREFIXES = (
    "pip-",
    "setuptools-",
    "wheel-",
    "pytest-",
    "pytest_asyncio-",
)


def read_base_home(venv_cfg: Path) -> Path:
    """从 venv 的 pyvenv.cfg 读取基础解释器 home 路径。"""
    if not venv_cfg.exists():
        raise SystemExit(f"未找到 {venv_cfg}")
    for line in venv_cfg.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("home"):
            value = line.split("=", 1)[1].strip()
            base = Path(value)
            if not (base / "python.exe").exists():
                raise SystemExit(f"基础解释器 python.exe 不存在: {base / 'python.exe'}")
            return base
    raise SystemExit(f"{venv_cfg} 缺少 home 字段")


def make_ignore_base(base: Path):
    """构造 shutil.copytree 的 ignore 回调：跳过 base 里的开发期冗余。"""

    def ignore(directory, names):
        rel_dir = os.path.relpath(directory, base)
        if rel_dir == ".":
            rel_dir = ""
        ignored = set()
        for name in names:
            rel = (os.path.join(rel_dir, name) if rel_dir else name).replace("/", "\\")
            if rel in BASE_EXCLUDE_REL or rel in BASE_EXCLUDE_FILES:
                ignored.add(name)
        return ignored

    return ignore


def make_ignore_site():
    """复制 .venv site-packages 时剔除开发期专用包与缓存。"""

    def ignore(directory, names):
        ignored = set()
        for name in names:
            if name == "__pycache__":
                ignored.add(name)
            elif name in SITE_EXCLUDE_DIRS:
                ignored.add(name)
            else:
                lowered = name.lower()
                for prefix in SITE_EXCLUDE_DIST_PREFIXES:
                    if lowered.startswith(prefix):
                        ignored.add(name)
                        break
        return ignored

    return ignore


def copy_base(base: Path, out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(base, out, ignore=make_ignore_base(base))
    print(f"[runtime] copied base interpreter: {base} -> {out}")


def overlay_site_packages(venv_site: Path, out: Path) -> None:
    target = out / "Lib" / "site-packages"
    if target.exists():
        shutil.rmtree(target)
    if not venv_site.exists():
        raise SystemExit(f".venv site-packages 不存在: {venv_site}")
    shutil.copytree(venv_site, target, ignore=make_ignore_site())
    print(f"[runtime] overlaid site-packages: {venv_site} -> {target}")


def verify(out: Path) -> None:
    exe = out / "python.exe"
    if not exe.exists():
        raise SystemExit(f"构建产物缺少 python.exe: {exe}")

    r = subprocess.run(
        [str(exe), "--version"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    print(f"[runtime] python --version -> {(r.stdout or r.stderr or '').strip()}")

    probe = (
        "import fastapi, uvicorn, aiohttp, websockets, httpx, psutil, yaml, "
        "dotenv, argon2, apscheduler, openai, markitdown, docx, markdown, "
        "edge_tts, PIL, pytesseract, feedparser, trafilatura; "
        "import win32api, win32com.client, pywinauto, pyautogui; "
        "print('imports ok')"
    )
    r = subprocess.run(
        [str(exe), "-s", "-c", probe],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if r.returncode != 0:
        print("[runtime] import probe FAILED:")
        print(r.stderr)
        raise SystemExit("运行时 import 自检失败")
    print(f"[runtime] import probe -> {(r.stdout or '').strip()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build self-contained Python runtime")
    parser.add_argument("--out", type=str, default=str(DEFAULT_OUT))
    args = parser.parse_args()

    out = Path(args.out)
    venv_cfg = ROOT / ".venv" / "pyvenv.cfg"
    venv_site = ROOT / ".venv" / "Lib" / "site-packages"

    base = read_base_home(venv_cfg)
    copy_base(base, out)
    overlay_site_packages(venv_site, out)
    verify(out)

    size_mb = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 1024 / 1024
    print(f"[runtime] done. size={size_mb:.1f} MB at {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
