"""Aerie · 云栖 — 打包后端验证脚本（集成测试 + 生产模拟）。

从 electron-builder 产物的 resources/python 目录直接 spawn 自包含运行时，
用隔离的 AERIE_DATA_DIR + PYTHONNOUSERSITE=1（禁用用户站点包，模拟干净机器）
验证后端能无网络、无外部依赖地启动并暴露核心接口。

验证项：
  1. 运行时 python.exe 存在且可执行；
  2. /api/health 返回 200（后端就绪）；
  3. /api/skills/list 返回非空技能列表（skills 目录已随包分发）。

用法：
    python scripts/verify_packaged_backend.py [--python-dir DIR] [--port N]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PYTHON_DIR = ROOT / "electron" / "dist" / "win-unpacked" / "resources" / "python"


def _get(url: str, timeout: float = 5.0):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "ignore")
        return resp.status, json.loads(body)


def _emit(line: str, result_file: Path | None) -> None:
    print(line, flush=True)
    if result_file is not None:
        with result_file.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-dir", type=str, default=str(DEFAULT_PYTHON_DIR))
    parser.add_argument("--port", type=int, default=7899)
    parser.add_argument("--result-file", type=str, default="")
    args = parser.parse_args()

    result_file = Path(args.result_file) if args.result_file else None
    if result_file is not None and result_file.exists():
        result_file.unlink()

    py_dir = Path(args.python_dir)
    runtime_exe = py_dir / "runtime" / "python.exe"
    main_py = py_dir / "main.py"

    if not runtime_exe.exists():
        _emit(f"FAIL: runtime python.exe missing: {runtime_exe}", result_file)
        return 1
    if not main_py.exists():
        _emit(f"FAIL: main.py missing: {main_py}", result_file)
        return 1

    data_dir = tempfile.mkdtemp(prefix="aerie_verify_")
    log_dir = os.path.join(data_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)

    env = {
        **os.environ,
        "PYTHONNOUSERSITE": "1",  # 模拟干净机器：不加载用户全局 site-packages
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
        "AERIE_DATA_DIR": data_dir,
        "AERIE_DB_PATH": os.path.join(data_dir, "aerie.db"),
        "AERIE_BACKEND_PORT": str(args.port),
        "LOG_DIR": log_dir,
    }

    stderr_path = Path(data_dir) / "backend-stderr.log"
    stderr_handle = stderr_path.open("wb")
    proc = subprocess.Popen(
        [str(runtime_exe), str(main_py)],
        cwd=str(py_dir),
        env=env,
        stdout=subprocess.DEVNULL,
        # A PIPE can deadlock a cold-starting backend when its diagnostics
        # exceed the unread pipe buffer. Use the isolated temp directory.
        stderr=stderr_handle,
    )

    def read_stderr() -> str:
        try:
            stderr_handle.flush()
            return stderr_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""

    base = f"http://127.0.0.1:{args.port}"
    try:
        health_status = None
        deadline = time.time() + 180
        while time.time() < deadline:
            if proc.poll() is not None:
                stderr = read_stderr()
                _emit(f"FAIL: backend exited early (code={proc.returncode})", result_file)
                _emit(stderr[-4000:], result_file)
                return 1
            try:
                status, _ = _get(base + "/api/health", timeout=3)
                health_status = status
                break
            except (urllib.error.URLError, OSError, ValueError):
                time.sleep(2)

        if health_status != 200:
            stderr = read_stderr()
            _emit(f"FAIL: /api/health did not return 200 (got {health_status})", result_file)
            _emit(stderr[-4000:], result_file)
            return 1
        _emit("PASS: /api/health -> 200", result_file)

        _, skills = _get(base + "/api/skills/list", timeout=10)
        items = skills.get("skills", skills) if isinstance(skills, dict) else skills
        if isinstance(items, list) and len(items) > 0:
            names = [i.get("name") for i in items if isinstance(i, dict)]
            _emit(f"PASS: /api/skills/list -> {len(items)} skills", result_file)
            _emit("  sample: " + str(names[:6]), result_file)
        else:
            _emit(f"FAIL: /api/skills/list empty or unexpected: {str(skills)[:300]}", result_file)
            return 1

        _emit("RESULT: OK", result_file)
        return 0
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        stderr_handle.close()
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
