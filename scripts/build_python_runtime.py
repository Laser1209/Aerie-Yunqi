"""Aerie · 云栖 — 自包含 Python 运行时构建脚本（wheelhouse 清洁构建）。

背景（问题根因）：
    旧打包方案把开发机的 ``.venv`` 原样塞进安装包：``.venv/Scripts/python.exe``
    只是重定向器（按 pyvenv.cfg 的 home 找基础解释器），换干净机器起不来；
    且 ``site-packages`` 整体覆盖意味着开发机随手 pip install 什么、
    chromadb/torch 等可选重依赖装了多少，都会被原样发布（实测 703MB）。

本脚本方案（清洁构建，与发布契约同源）：
    1. 从 ``.venv/pyvenv.cfg`` 读取基础解释器真实路径（home 字段），
       完整拷贝为产物内真实可迁移的 ``python.exe``；
    2. ``pip download -r requirements-core.txt`` 到独立 wheelhouse，
       依赖闭包只由锁定清单决定，与开发机 venv 里装过什么完全无关；
    3. ``pip install --no-index --find-links <wheelhouse> --target``
       把核心依赖装进一个全新的空 site-packages，不经过开发 venv；
    4. 剪枝（__pycache__ / 包内 tests 等）、import 自检、体积断言、
       Top20 大文件报告。

重型/可选能力（Playwright、本地 ASR、RVC/torch、chromadb）不在本脚本范围，
由 plugins/<pack>/requirements.txt 与阶段 D 的 build_plugin_pack.py 各自装配。

用法：
    python scripts/build_python_runtime.py [--out DIR] [--max-size-mb N]
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
DEFAULT_WHEELHOUSE = ROOT / ".cache" / "runtime-wheelhouse"
CORE_REQUIREMENTS = ROOT / "requirements-core.txt"
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

# 核心 runtime 体积上限（MB）。实测旧 venv 整体拷贝 703MB，移出 chromadb
# 闭包（≥270MB）并剪枝后预期 ~400MB；460MB 为阻断阈值，超限需在本文件
# 说明原因或更新阈值，不允许静默膨胀。
DEFAULT_MAX_SIZE_MB = 460

# 默认官方源：锁定版本可能新于国内镜像同步（实测 fastapi 0.139.2 仅官方源
# 可见）；开发机 pip 缓存（E:/AI-Cache/pip）命中时不产生实际下载。
# 网络受限时可用 --index-url 切清华/华为云镜像。
DEFAULT_INDEX_URL = "https://pypi.org/simple"

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
    "Lib\\site-packages",  # 全新清洁装配，不用 base 自带依赖
}

# 顶层无用的说明文件。
BASE_EXCLUDE_FILES = {"LICENSE.txt", "NEWS.txt"}

# site-packages 剪枝：这些目录名在任何包内出现都可安全删除。
# 仅精确匹配目录名，不碰同名前缀的业务模块。
PRUNE_DIR_NAMES = {"__pycache__", "tests", "_tests", "test", "testing"}


def run(cmd: list[str], *, step: str) -> None:
    """执行构建子步骤；失败即终止并保留现场便于排查。"""
    print(f"[runtime] {step}: {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit(f"[runtime] {step} 失败 (exit {result.returncode})")


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


def copy_base(base: Path, out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(base, out, ignore=make_ignore_base(base))
    print(f"[runtime] copied base interpreter: {base} -> {out}")


def download_wheelhouse(wheelhouse: Path, index_url: str) -> None:
    """按核心锁定清单下载完整依赖闭包（wheelhouse 持久化，可重复构建）。"""
    wheelhouse.mkdir(parents=True, exist_ok=True)
    run(
        [
            str(VENV_PYTHON), "-m", "pip", "download",
            "-r", str(CORE_REQUIREMENTS),
            "-d", str(wheelhouse),
            "-i", index_url,
            "--timeout", "60",
            "--retries", "5",
            # 有 wheel 优先 wheel；pyautogui/pywinauto 等纯 Python 包只有
            # sdist，允许回退（原生编译型包仍必须命中 wheel，否则此处报错）。
            "--prefer-binary",
        ],
        step="download wheelhouse",
    )


def install_clean_site_packages(out: Path, wheelhouse: Path) -> Path:
    """从 wheelhouse 离线安装到全新空目录，杜绝开发 venv 污染。"""
    target = out / "Lib" / "site-packages"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    run(
        [
            str(VENV_PYTHON), "-m", "pip", "install",
            "--no-index",
            "--find-links", str(wheelhouse),
            "-r", str(CORE_REQUIREMENTS),
            "--target", str(target),
            "--no-compile",
        ],
        step="install clean site-packages",
    )
    return target


def prune_site_packages(site_packages: Path) -> int:
    """删除缓存与包内测试目录，返回回收字节数。"""
    freed = 0
    for path in sorted(site_packages.rglob("*"), reverse=True):
        if path.is_dir() and path.name in PRUNE_DIR_NAMES:
            # 只剪"包自带"的测试目录：其父级必须是某个包目录，
            # 避免误伤 site-packages 根本身。
            if path.parent != site_packages or path.name == "__pycache__":
                freed += _dir_size(path)
                shutil.rmtree(path, ignore_errors=True)
    print(f"[runtime] pruned caches/tests, freed {freed / 1024 / 1024:.1f} MB")
    return freed


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


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

    # 探针 1：核心依赖三方库闭包完整（pywin32 的 .pth/DLL 引导也在此被覆盖）。
    third_party_probe = (
        "import fastapi, uvicorn, aiohttp, websockets, httpx, requests, psutil, "
        "yaml, dotenv, argon2, apscheduler, openai, markitdown, docx, markdown, "
        "weasyprint, edge_tts, PIL, pytesseract, feedparser, trafilatura, "
        "numpy, onnxruntime, qrcode, cryptography, loguru; "
        "import win32api, win32com.client, pywinauto, pyautogui; "
        "print('third-party imports ok')"
    )
    r = subprocess.run(
        [str(exe), "-s", "-c", third_party_probe],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if r.returncode != 0:
        print("[runtime] third-party import probe FAILED:")
        print(r.stderr)
        raise SystemExit("运行时三方库自检失败（requirements-core 闭包不完整？）")
    print(f"[runtime] third-party probe -> {(r.stdout or '').strip()}")

    # 探针 2：核心业务模块在瘦依赖下可导入（惰性 import 的 chromadb/torch 缺失
    # 不应影响启动路径；PYTHONPATH 指向项目根，模拟 extraResources 铺排）。
    core_probe = (
        "import core.plugin_host, core.api_server, core.companion; "
        "import tools, voice.multimodal_output; "
        "print('core module imports ok')"
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONNOUSERSITE": "1"}
    r = subprocess.run(
        [str(exe), "-s", "-c", core_probe],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
        cwd=ROOT,
    )
    if r.returncode != 0:
        print("[runtime] core module import probe FAILED:")
        print(r.stderr)
        raise SystemExit("运行时核心模块自检失败（依赖误移出核心？）")
    print(f"[runtime] core module probe -> {(r.stdout or '').strip()}")


def report_size(out: Path, max_size_mb: int) -> float:
    files = [f for f in out.rglob("*") if f.is_file()]
    size_mb = sum(f.stat().st_size for f in files) / 1024 / 1024

    print(f"[runtime] size = {size_mb:.1f} MB (limit {max_size_mb} MB)")
    print("[runtime] top 20 largest files:")
    for f in sorted(files, key=lambda x: x.stat().st_size, reverse=True)[:20]:
        mb = f.stat().st_size / 1024 / 1024
        rel = f.relative_to(out)
        print(f"  {mb:8.1f} MB  {rel}")

    if size_mb > max_size_mb:
        raise SystemExit(
            f"[runtime] 体积断言失败: {size_mb:.1f} MB > {max_size_mb} MB；"
            "新依赖是否该进功能包？或在脚本中更新阈值并注明理由"
        )
    return size_mb


def main() -> int:
    parser = argparse.ArgumentParser(description="Build self-contained Python runtime")
    parser.add_argument("--out", type=str, default=str(DEFAULT_OUT))
    parser.add_argument("--wheelhouse", type=str, default=str(DEFAULT_WHEELHOUSE))
    parser.add_argument("--max-size-mb", type=int, default=DEFAULT_MAX_SIZE_MB)
    parser.add_argument(
        "--index-url",
        type=str,
        default=DEFAULT_INDEX_URL,
        help="pip 下载源（默认清华镜像；官方源 https://pypi.org/simple）",
    )
    args = parser.parse_args()

    if not VENV_PYTHON.exists():
        raise SystemExit(f"需要开发 venv 提供 pip: {VENV_PYTHON} 不存在")
    if not CORE_REQUIREMENTS.exists():
        raise SystemExit(f"缺少核心依赖清单: {CORE_REQUIREMENTS}")

    out = Path(args.out)
    wheelhouse = Path(args.wheelhouse)
    venv_cfg = ROOT / ".venv" / "pyvenv.cfg"

    base = read_base_home(venv_cfg)
    copy_base(base, out)
    download_wheelhouse(wheelhouse, args.index_url)
    site_packages = install_clean_site_packages(out, wheelhouse)
    prune_site_packages(site_packages)
    verify(out)
    report_size(out, args.max_size_mb)

    print(f"[runtime] done. runtime at {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
