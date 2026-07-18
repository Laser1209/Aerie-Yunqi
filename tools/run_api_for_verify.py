"""Aerie · 云栖 v13.9.8 — Lightweight API server bootstrap (Block-5D R5).

Boots the FastAPI app on 7890 in a detached background process, sufficient
for verify_* suites that only need HTTP endpoints. Avoids spinning up the
full Companion / QQ / NapCat stack.

The process is spawned with DETACHED_PROCESS so it survives the parent
shell (the dev loop reuses terminals, which otherwise kills threads).

Usage:
    python tools/run_api_for_verify.py start    # start detached
    python tools/run_api_for_verify.py stop     # kill the detached proc
    python tools/run_api_for_verify.py status   # check port 7890
"""
from __future__ import annotations
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PORT = 7890
PID_FILE = PROJECT_ROOT / "tmp" / ".api_for_verify.pid"
LOG_FILE = PROJECT_ROOT / "logs" / "verify-api.log"


def _check_port() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=1.0):
            return True
    except OSError:
        return False


def _wait_port(deadline_s: float = 30.0) -> bool:
    end = time.time() + deadline_s
    while time.time() < end:
        if _check_port():
            return True
        time.sleep(0.3)
    return False


def start() -> int:
    if _check_port():
        print(f"[ok] API already up on {PORT}")
        return 0

    # Use a throwaway DB so verify runs are isolated.
    os.environ.setdefault("AERIE_DB_PATH", str(PROJECT_ROOT / "tmp" / "verify_runtime.db"))
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Spawn a detached child running the API. The child re-execs python
    # so it can outlive the calling shell.
    child_script = PROJECT_ROOT / "tmp" / ".api_worker.py"
    db_path = str(PROJECT_ROOT / "tmp" / "verify_runtime.db")
    child_script.write_text(
        "import os, sys\n"
        f"sys.path.insert(0, r'{PROJECT_ROOT}')\n"
        f"os.environ['AERIE_DB_PATH'] = r'{db_path}'\n"
        "import asyncio, logging\n"
        "logging.basicConfig(level='WARNING', format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')\n"
        "from core.companion import Companion\n"
        "from config.persona_loader import load_settings\n"
        "import uvicorn\n"
        "from core.api_server import app\n"
        "\n"
        "async def _boot():\n"
        "    comp = Companion(settings=load_settings())\n"
        "    await comp.start()\n"
        "\n"
        f"asyncio.run(_boot())\n"
        f"uvicorn.run(app, host='127.0.0.1', port={PORT}, log_level='warning')\n",
        encoding="utf-8",
    )

    # On Windows: DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP keeps the
    # child alive after the parent shell exits.
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    with open(LOG_FILE, "ab") as logf:
        proc = subprocess.Popen(
            [sys.executable, str(child_script)],
            stdin=subprocess.DEVNULL,
            stdout=logf,
            stderr=logf,
            close_fds=True,
            creationflags=flags,
        )
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    print(f"[ok] spawning API child pid={proc.pid}, log={LOG_FILE}")

    if _wait_port(30.0):
        print(f"[ok] API listening on {PORT}")
        return 0
    print(f"[err] API did not come up on {PORT} within 30s")
    return 1


def stop() -> int:
    if not _check_port() and not PID_FILE.exists():
        print("[ok] API not running")
        return 0

    pid_str = ""
    if PID_FILE.exists():
        try:
            pid_str = PID_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            pass

    # Try the recorded pid first, then sweep any process bound to the port.
    pids: set[str] = set()
    if pid_str.isdigit():
        pids.add(pid_str)
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-NetTCPConnection -LocalPort {PORT} -ErrorAction SilentlyContinue | "
             f"Select-Object -ExpandProperty OwningProcess"],
            capture_output=True, text=True, timeout=10,
        )
        for line in (out.stdout or "").splitlines():
            line = line.strip()
            if line.isdigit():
                pids.add(line)
    except Exception:
        pass

    for pid in pids:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", pid],
                           capture_output=True, timeout=5)
            print(f"[ok] killed pid {pid}")
        except Exception as e:
            print(f"[warn] kill {pid} failed: {e}")

    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except OSError:
        pass
    return 0


def status() -> int:
    if _check_port():
        print(f"[ok] API is listening on {PORT}")
        return 0
    print(f"[--] API is NOT listening on {PORT}")
    return 1


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    if cmd == "start":
        return start()
    if cmd == "stop":
        return stop()
    if cmd == "status":
        return status()
    print(f"Usage: {sys.argv[0]} start|stop|status")
    return 2


if __name__ == "__main__":
    sys.exit(main())
