#!/usr/bin/env python3
"""Aerie 24-hour runtime monitor.

Long-running asyncio daemon that collects system metrics, backend health,
API responsiveness and DB snapshots, writing JSON Lines into D:\\Aerie\\24H-LOG
with hourly rotation, plus an hourly storage-integrity check and a sentinel
watchdog that detects collection stalls.

Run:  python scripts/24h_monitor.py [--backend http://127.0.0.1:7890] [--loop-hours 24]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import socket
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import psutil
import aiohttp

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
LOG_ROOT = Path(os.getenv("AERIE_24H_LOG", r"D:\Aerie\24H-LOG"))

# Collection intervals (seconds)
SYS_INTERVAL = int(os.getenv("AERIE_SYS_INTERVAL", "30"))
HEALTH_INTERVAL = int(os.getenv("AERIE_HEALTH_INTERVAL", "60"))
DB_INTERVAL = int(os.getenv("AERIE_DB_INTERVAL", "7200"))     # every 2h
STORAGE_CHECK_INTERVAL = int(os.getenv("AERIE_STORAGE_INTERVAL", "3600"))  # every 1h

# Alerts
ALERT_CPU_PCT = 85.0
ALERT_MEM_PCT = 90.0
ALERT_DISK_FREE_GB = 5.0

# Ports that should stay bound by the backend
BACKEND_PORTS = (7890, 7891)

SUBDIRS = (
    "00_STARTUP", "01_SYSTEM_METRICS", "02_HEALTH", "03_API",
    "04_LOGS", "05_ERRORS", "06_ANOMALY", "07_DB", "08_REPORT", "09_STATE",
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_ROOT / "04_LOGS" / "monitor.log", encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
log = logging.getLogger("aerie.24hmonitor")


# ---------------------------------------------------------------------------
# File output helpers (JSON Lines, hourly rotation)
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now()


def _ts_ms(dt: datetime | None = None) -> str:
    """Millisecond-precise ISO-8601 timestamp, e.g. 2026-08-11T12:00:00.123."""
    return (dt or _now()).isoformat(timespec="milliseconds")


def _write_jsonl(subdir: str, record: dict) -> None:
    """Append one JSON record to an hourly file under LOG_ROOT/<subdir>.

    Records carry a millisecond-precise `ts`; files are bucketed by hour to
    keep volume manageable while every line stays individually traceable.
    """
    ts = record.get("ts") or _now()
    if isinstance(ts, datetime):
        record["ts"] = _ts_ms(ts)
    hour = ts.strftime("%Y%m%d_%H") if isinstance(ts, datetime) else _now().strftime("%Y%m%d_%H")
    out_dir = LOG_ROOT / subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{subdir}_{hour}.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_error(level: str, module: str, message: str, detail: dict | None = None) -> None:
    """P0-P3 error record into 05_ERRORS (always current-date file)."""
    record = {
        "ts": _now(),
        "level": level,
        "module": module,
        "message": message,
        "detail": detail or {},
    }
    _write_jsonl("05_ERRORS", record)


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------
async def collect_system_metrics() -> dict:
    """CPU / memory / disk / network / per-process RSS / port state."""
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage(str(LOG_ROOT.anchor + os.sep) if os.name == "nt" else "/")
    net = psutil.net_io_counters()
    proc = psutil.Process()
    ports = {}
    for p in BACKEND_PORTS:
        ports[p] = _port_open(p)

    return {
        "ts": _now(),
        "cpu_percent": psutil.cpu_percent(interval=1),
        "mem_percent": vm.percent,
        "mem_used_gb": round(vm.used / 1024**3, 2),
        "mem_total_gb": round(vm.total / 1024**3, 2),
        "process_rss_mb": round(proc.memory_info().rss / 1024**2, 2),
        "process_cpu": proc.cpu_percent(interval=None),
        "disk_free_gb": round(disk.free / 1024**3, 2),
        "disk_total_gb": round(disk.total / 1024**3, 2),
        "net_sent_mb": round(net.bytes_sent / 1024**2, 2),
        "net_recv_mb": round(net.bytes_recv / 1024**2, 2),
        "ports": ports,
    }


async def collect_health(backend: str, session: aiohttp.ClientSession) -> dict:
    """GET /api/health with latency; timeout marks unhealthy."""
    started = time.monotonic()
    try:
        async with session.get(f"{backend}/api/health", timeout=aiohttp.ClientTimeout(total=10)) as resp:
            body = await resp.json()
            latency_ms = (time.monotonic() - started) * 1000
            return {
                "ts": _now(),
                "http_status": resp.status,
                "latency_ms": round(latency_ms, 1),
                "overall": body.get("overall", "unknown"),
                "uptime_seconds": body.get("uptime_seconds"),
                "backend_instance_id": body.get("backend_instance_id", ""),
                "components": body.get("components", {}),
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "ts": _now(),
            "http_status": 0,
            "latency_ms": None,
            "overall": "unreachable",
            "error": str(exc),
        }


async def collect_api_probe(backend: str, session: aiohttp.ClientSession) -> dict:
    """Small GET probe for response-time stats; runs on a coarse cadence."""
    started = time.monotonic()
    try:
        async with session.get(f"{backend}/api/health", timeout=aiohttp.ClientTimeout(total=8)) as resp:
            latency_ms = (time.monotonic() - started) * 1000
            return {
                "ts": _now(),
                "endpoint": "/api/health",
                "status": resp.status,
                "latency_ms": round(latency_ms, 1),
                "ok": 200 <= resp.status < 300,
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "ts": _now(),
            "endpoint": "/api/health",
            "status": 0,
            "latency_ms": None,
            "ok": False,
            "error": str(exc),
        }


async def collect_db_snapshot() -> dict:
    """Sizes of key DB / data files under project data/."""
    data_dir = ROOT / "data"
    targets = [".sqlite3", ".json", ".db"]
    files = []
    if data_dir.exists():
        for f in sorted(data_dir.rglob("*")):
            if f.is_file() and f.suffix.lower() in targets:
                files.append({
                    "path": str(f.relative_to(ROOT)),
                    "size_kb": round(f.stat().st_size / 1024, 1),
                })
    return {"ts": _now(), "files": files}


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


# ---------------------------------------------------------------------------
# Storage integrity + alerting
# ---------------------------------------------------------------------------
async def check_storage() -> None:
    """Verify disk space, file write integrity and timestamp continuity."""
    free_gb = psutil.disk_usage(str(LOG_ROOT)).free / 1024**3
    if free_gb < ALERT_DISK_FREE_GB:
        _write_error("P1", "storage", f"disk free below threshold: {free_gb:.2f}GB")

    # Write probe: round-trip a marker file to prove writability
    probe = LOG_ROOT / "09_STATE" / "storage_probe.tmp"
    try:
        probe.write_text(_now().isoformat(), encoding="utf-8")
        if probe.stat().st_size == 0:
            _write_error("P1", "storage", "probe file empty, write failed")
        probe.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        _write_error("P0", "storage", f"cannot write to LOG_ROOT: {exc}")
        raise

    # Timestamp-continuity spot check on newest metrics file
    mdir = LOG_ROOT / "01_SYSTEM_METRICS"
    files = sorted(mdir.glob("*.jsonl"))
    if files:
        last = files[-1]
        try:
            lines = last.read_text(encoding="utf-8").strip().splitlines()
            if lines:
                last_ts = json.loads(lines[-1])["ts"]
                gap = (_now() - datetime.fromisoformat(last_ts)).total_seconds()
                if gap > SYS_INTERVAL * 3:
                    _write_error("P2", "storage", f"metrics gap detected: {gap:.0f}s")
        except Exception as exc:  # noqa: BLE001
            _write_error("P2", "storage", f"metrics continuity check failed: {exc}")


# ---------------------------------------------------------------------------
# Sentinel: ensure each collector produces fresh data; else record stall.
# ---------------------------------------------------------------------------
class Sentinel:
    def __init__(self) -> None:
        self.last = {}

    def touch(self, key: str) -> None:
        self.last[key] = time.monotonic()

    async def run(self, interval: int = 300) -> None:
        while True:
            await asyncio.sleep(interval)
            now = time.monotonic()
            for key, stale_after in (
                ("sys", SYS_INTERVAL * 3),
                ("health", HEALTH_INTERVAL * 3),
                ("db", DB_INTERVAL * 2),
            ):
                last = self.last.get(key)
                if last is None or (now - last) > stale_after:
                    _write_error("P0", "sentinel", f"collector stalled: {key}")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
async def _metrics_loop(sentinel: Sentinel) -> None:
    while True:
        rec = await collect_system_metrics()
        _write_jsonl("01_SYSTEM_METRICS", rec)
        sentinel.touch("sys")
        _evaluate_alerts(rec)
        await asyncio.sleep(SYS_INTERVAL)


async def _health_loop(backend: str, session: aiohttp.ClientSession, sentinel: Sentinel) -> None:
    while True:
        rec = await collect_health(backend, session)
        _write_jsonl("02_HEALTH", rec)
        sentinel.touch("health")
        await asyncio.sleep(HEALTH_INTERVAL)


async def _api_loop(backend: str, session: aiohttp.ClientSession) -> None:
    # API response stats on a coarser cadence (every 5 min) to keep volume low.
    while True:
        rec = await collect_api_probe(backend, session)
        _write_jsonl("03_API", rec)
        await asyncio.sleep(300)


async def _db_loop(sentinel: Sentinel) -> None:
    while True:
        rec = await collect_db_snapshot()
        _write_jsonl("07_DB", rec)
        sentinel.touch("db")
        await asyncio.sleep(DB_INTERVAL)


async def _storage_loop() -> None:
    while True:
        try:
            await check_storage()
        except Exception:  # noqa: BLE001
            log.exception("storage check fatal")
            return  # abort monitor if storage is unusable
        await asyncio.sleep(STORAGE_CHECK_INTERVAL)


def _evaluate_alerts(rec: dict) -> None:
    if rec["cpu_percent"] > ALERT_CPU_PCT:
        _write_error("P2", "resources", "cpu above alert threshold",
                     {"cpu_percent": rec["cpu_percent"]})
    if rec["mem_percent"] > ALERT_MEM_PCT:
        _write_error("P2", "resources", "memory above alert threshold",
                     {"mem_percent": rec["mem_percent"]})
    for port, open_ in rec["ports"].items():
        if not open_:
            _write_error("P1", "resources", f"backend port {port} not listening")


def _setup_dirs() -> None:
    for name in SUBDIRS:
        (LOG_ROOT / name).mkdir(parents=True, exist_ok=True)
    # startup baseline snapshot
    _write_jsonl("00_STARTUP", {
        "ts": _now(),
        "pid": os.getpid(),
        "log_root": str(LOG_ROOT),
        "git_commit": _git_commit(),
        "intervals": {
            "sys": SYS_INTERVAL, "health": HEALTH_INTERVAL,
            "db": DB_INTERVAL, "storage": STORAGE_CHECK_INTERVAL,
        },
    })


def _git_commit() -> str:
    try:
        import subprocess
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(ROOT), timeout=3, stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:  # noqa: BLE001
        return "unknown"


async def main(backend: str, loop_hours: float) -> None:
    _setup_dirs()
    sentinel = Sentinel()

    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        tasks = [
            asyncio.create_task(_metrics_loop(sentinel)),
            asyncio.create_task(_health_loop(backend, session, sentinel)),
            asyncio.create_task(_api_loop(backend, session)),
            asyncio.create_task(_db_loop(sentinel)),
            asyncio.create_task(_storage_loop()),
            asyncio.create_task(sentinel.run()),
        ]
        try:
            await asyncio.sleep(loop_hours * 3600)
        except asyncio.CancelledError:
            pass
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            log.info("monitor finished after %.1fh", loop_hours)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Aerie 24h runtime monitor")
    ap.add_argument("--backend", default="http://127.0.0.1:7890")
    ap.add_argument("--loop-hours", type=float, default=24.0)
    args = ap.parse_args()
    try:
        asyncio.run(main(args.backend, args.loop_hours))
    except KeyboardInterrupt:
        log.info("monitor interrupted by user")
