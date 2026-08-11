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
import yaml

_START = time.monotonic()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
LOG_ROOT = Path(os.getenv("AERIE_24H_LOG", r"D:\Aerie\24H-LOG"))
PROBES_FILE = Path(os.getenv("AERIE_PROBES_FILE", ROOT / "config" / "monitor_probes.yaml"))
# Persisted resume state (cognition watermark, etc.) so a restart continues
# seamlessly instead of re-recording already-captured data.
STATE_FILE = Path(os.getenv("AERIE_STATE_FILE", LOG_ROOT / "09_STATE" / "monitor_state.json"))

# Collection intervals (seconds)
SYS_INTERVAL = int(os.getenv("AERIE_SYS_INTERVAL", "30"))
HEALTH_INTERVAL = int(os.getenv("AERIE_HEALTH_INTERVAL", "60"))
DB_INTERVAL = int(os.getenv("AERIE_DB_INTERVAL", "7200"))     # every 2h
STORAGE_CHECK_INTERVAL = int(os.getenv("AERIE_STORAGE_INTERVAL", "3600"))  # every 1h
COGNITION_INTERVAL = int(os.getenv("AERIE_COGNITION_INTERVAL", "60"))     # every 1m
COGNITION_BATCH = int(os.getenv("AERIE_COGNITION_BATCH", "50"))

# Alerts
ALERT_CPU_PCT = 85.0
ALERT_MEM_PCT = 90.0
ALERT_DISK_FREE_GB = 5.0

# Ports that should stay bound by the backend
BACKEND_PORTS = (7890, 7891)

# Frontend (Electron) process names / markers for full-stack monitoring
ELECTRON_MARKERS = ("electron",)

SUBDIRS = (
    "00_STARTUP", "01_SYSTEM_METRICS", "02_HEALTH", "03_API",
    "04_LOGS", "05_ERRORS", "06_ANOMALY", "07_DB", "08_REPORT", "09_STATE",
    "10_COGNITION",
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
def _electron_procs() -> list[dict]:
    """Find Electron (frontend) processes for full-stack liveness tracking."""
    found = []
    for p in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent"]):
        try:
            name = (p.info.get("name") or "").lower()
            if any(m in name for m in ELECTRON_MARKERS):
                found.append({
                    "pid": p.info["pid"],
                    "name": p.info.get("name"),
                    "rss_mb": round((p.info.get("memory_info") or psutil.Process(p.info["pid"]).memory_info()).rss / 1024**2, 2),
                    "cpu": p.info.get("cpu_percent") or 0.0,
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


async def collect_system_metrics() -> dict:
    """CPU / memory / disk / network / per-process RSS / port / frontend state."""
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage(str(LOG_ROOT.anchor + os.sep) if os.name == "nt" else "/")
    net = psutil.net_io_counters()
    proc = psutil.Process()
    ports = {}
    for p in BACKEND_PORTS:
        ports[p] = _port_open(p)

    frontend = _electron_procs()
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
        "frontend": {
            "running": bool(frontend),
            "proc_count": len(frontend),
            "total_rss_mb": round(sum(f["rss_mb"] for f in frontend), 2),
            "procs": frontend,
        },
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
                "overall": body.get("status") or body.get("overall", "unknown"),
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
                ("cognition", COGNITION_INTERVAL * 3),
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
    """Config-driven real API probe runner (see config/monitor_probes.yaml).

    Each enabled probe fires on its own interval; latency/status go to 03_API.
    POST probes with `poll: true` follow the chat request queue to completion
    to measure full end-to-end dialogue latency.
    """
    probes = _load_probes()
    log.info("loaded %d enabled probe(s) from %s", len(probes), PROBES_FILE)
    while True:
        now = time.monotonic()
        for probe in probes:
            if now >= probe["next_run"]:
                probe["next_run"] = now + float(probe.get("interval_sec", 300))
                rec = await _run_probe(backend, session, probe)
                _write_jsonl("03_API", rec)
        await asyncio.sleep(5)


def _load_probes() -> list[dict]:
    if not PROBES_FILE.exists():
        _write_error("P2", "probes", f"probes config missing: {PROBES_FILE}")
        return []
    try:
        data = yaml.safe_load(PROBES_FILE.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        _write_error("P2", "probes", f"failed to parse {PROBES_FILE}: {exc}")
        return []
    probes = []
    for p in data.get("probes", []):
        if not p.get("enabled", False):
            continue
        probes.append({**p, "next_run": time.monotonic()})
    return probes


async def _request_json(session: aiohttp.ClientSession, method: str, url: str,
                        timeout: float, json_body: dict | None = None):
    started = time.monotonic()
    async with session.request(
        method, url, json=json_body,
        timeout=aiohttp.ClientTimeout(total=timeout),
    ) as resp:
        try:
            body = await resp.json()
        except Exception:  # noqa: BLE001
            body = None
        return resp.status, body, (time.monotonic() - started) * 1000


async def _run_probe(backend: str, session: aiohttp.ClientSession, probe: dict) -> dict:
    name, path = probe["name"], probe["path"]
    method = str(probe.get("method", "GET")).upper()
    timeout = float(probe.get("timeout_sec", 10))
    try:
        if method == "POST":
            status, body, latency_ms = await _request_json(
                session, "POST", f"{backend}{path}", timeout, json_body=probe.get("body"))
        else:
            status, body, latency_ms = await _request_json(session, "GET", f"{backend}{path}", timeout)
        ok = 200 <= status < 300
        rec = {"ts": _now(), "name": name, "method": method, "path": path,
               "status": status, "latency_ms": round(latency_ms, 1), "ok": ok}
        if ok and probe.get("poll"):
            rec.update(await _poll_chat(backend, session, body, probe))
        return rec
    except Exception as exc:  # noqa: BLE001
        return {"ts": _now(), "name": name, "method": method, "path": path,
                "status": 0, "latency_ms": None, "ok": False, "error": str(exc)}


async def _poll_chat(backend: str, session: aiohttp.ClientSession,
                     submit_body: dict | None, probe: dict) -> dict:
    """Poll the request queue until the chat request reaches a terminal state."""
    request_id = (submit_body or {}).get("request_id")
    if not request_id:
        return {"error": "no request_id in submit response"}
    started = time.monotonic()
    final_status = "unknown"
    while time.monotonic() - started < float(probe.get("poll_timeout_sec", 180)):
        await asyncio.sleep(float(probe.get("poll_interval_sec", 5)))
        try:
            status, body, _ = await _request_json(
                session, "GET", f"{backend}/api/chat/requests/{request_id}",
                float(probe.get("timeout_sec", 10)))
            final_status = str((body or {}).get("status", f"http{status}"))
            if status == 404 or final_status.lower() in ("completed", "failed", "cancelled", "error"):
                break
        except Exception as exc:  # noqa: BLE001
            final_status = f"poll_error:{exc}"
            break
    return {"request_id": request_id, "final_status": final_status,
            "roundtrip_ms": round((time.monotonic() - started) * 1000, 1)}


def _cog_json(value: Any) -> Any:
    """Parse a JSON-string column (stage_*, react_trace, decision_trace)."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:  # noqa: BLE001
        return str(value)


def _scan_tools(obj: Any, out: list[dict], depth: int = 0) -> None:
    """Recursively collect tool/skill call markers from stage_tools/react_trace.

    Recognizes dicts carrying a tool/tool_name/name/skill key with a string
    value, capturing the tool name and a truncated args snapshot.
    """
    if depth > 8 or out is None:
        return
    if isinstance(obj, dict):
        tool = obj.get("tool") or obj.get("tool_name") or obj.get("skill") \
            or obj.get("name")
        if isinstance(tool, str) and tool:
            args = obj.get("args") or obj.get("arguments") or obj.get("params")
            out.append({
                "tool": tool,
                "args": json.dumps(args, ensure_ascii=False)[:500] if args else None,
            })
        for v in obj.values():
            _scan_tools(v, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _scan_tools(v, out, depth + 1)


def _truncate_text(value: Any, limit: int = 2000) -> Any:
    """Truncate long JSON text to bound per-message volume on disk."""
    if value is None:
        return None
    s = json.dumps(value, ensure_ascii=False)
    if len(s) <= limit:
        return value
    return {"_truncated": True, "_len": len(s), "head": s[:limit]}


def _extract_cognition(row: dict) -> dict:
    """Condense a full cognition_log row into a traceable 10_COGNITION record."""
    stages = {s: (_cog_json(row.get(f"stage_{s}")) is not None) for s in (
        "route", "emotion", "threshold", "context", "brain",
        "tools", "split", "postprocess", "output",
    )}
    present = [s for s, ok in stages.items() if ok]

    # Tool / skill calls across the tools stage and the ReAct chain
    tools: list[dict] = []
    _scan_tools(_cog_json(row.get("stage_tools")), tools)
    _scan_tools(_cog_json(row.get("react_trace")), tools)

    react = _cog_json(row.get("react_trace"))
    return {
        "ts": _now(),
        "cognition_id": row.get("id"),
        "source": row.get("source"),
        "user_id": row.get("user_id"),
        "user_message": _truncate_text(row.get("user_message"), 500),
        "route_mode": row.get("route_mode"),
        "is_command": row.get("is_command"),
        "duration_ms": row.get("duration_ms"),
        "stages_present": present,
        "tool_calls": tools,
        "decision_trace": _truncate_text(_cog_json(row.get("decision_trace")), 800),
        "react_trace": _truncate_text(react, 3000),
    }


def _load_state() -> dict:
    """Load persisted resume state (cognition watermark, ...)."""
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return {}


def _save_state(state: dict) -> None:
    """Atomically persist resume state so a restart can resume seamlessly."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except Exception:  # noqa: BLE001
        pass


def _cognition_disk_watermark() -> int:
    """Highest cognition_id already written to disk (for clean resume)."""
    m = 0
    cog_dir = LOG_ROOT / "10_COGNITION"
    if not cog_dir.exists():
        return 0
    for f in cog_dir.glob("*.jsonl"):
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    rid = json.loads(line).get("cognition_id")
                    if isinstance(rid, int) and rid > m:
                        m = rid
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            continue
    return m


async def _cognition_loop(backend: str, session: aiohttp.ClientSession,
                          sentinel: Sentinel) -> None:
    """Capture agent's internal dialogue flow via /api/cognition endpoints.

    Polls recent trace ids, fetches full detail for every newly-observed row,
    and condenses each into 10_COGNITION so the 9-stage pipeline, the ReAct
    thought chain (react_trace) and tool/skill calls are fully recorded.

    Resume-aware: the highest processed cognition_id is persisted (and also
    recovered from existing 10_COGNITION data), so a monitor restart continues
    from the watermark instead of re-recording already-captured traces.
    """
    state = _load_state()
    seen: set[int] = set()
    watermark = int(state.get("cognition_max_id") or _cognition_disk_watermark() or 0)
    if watermark:
        log.info("cognition resumes from watermark=%s", watermark)
    while True:
        try:
            _, body, _ = await _request_json(
                session, "GET", f"{backend}/api/cognition/recent?limit=200",
                timeout=10, json_body=None)
            traces = (body or {}).get("traces") or []
            # Only ids strictly above the watermark are new; this prevents a
            # restart from re-capturing already-recorded rows that still
            # appear in the recent window.
            new_ids = [t["id"] for t in traces
                       if isinstance(t.get("id"), int)
                       and t["id"] > watermark and t["id"] not in seen]
            max_new = 0
            for rid in new_ids[:COGNITION_BATCH]:
                seen.add(rid)
                max_new = max(max_new, rid)
                try:
                    st, detail, _ = await _request_json(
                        session, "GET", f"{backend}/api/cognition/{rid}", timeout=10)
                    if st == 200 and detail:
                        _write_jsonl("10_COGNITION", _extract_cognition(detail))
                    elif st != 404:
                        _write_error("P2", "cognition", f"detail fetch status {st}",
                                     {"cognition_id": rid})
                except Exception as exc:  # noqa: BLE001
                    _write_error("P2", "cognition", f"detail fetch failed: {exc}",
                                 {"cognition_id": rid})
            if max_new > 0:
                watermark = max(watermark, max_new)
                state["cognition_max_id"] = watermark
                _save_state(state)
        except Exception as exc:  # noqa: BLE001
            # Backend down is normal; log once per cycle at most.
            _write_error("P2", "cognition", f"recent fetch failed: {exc}")
        sentinel.touch("cognition")
        await asyncio.sleep(COGNITION_INTERVAL)


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
    fe = rec.get("frontend") or {}
    if not fe.get("running"):
        _write_error("P1", "frontend", "Electron frontend not running")


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
            asyncio.create_task(_cognition_loop(backend, session, sentinel)),
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
            log.info("monitor finished after %.1fh (%.0fs)",
                     loop_hours, (time.monotonic() - _START) % 100000)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Aerie 24h runtime monitor")
    ap.add_argument("--backend", default="http://127.0.0.1:7890")
    ap.add_argument("--loop-hours", type=float, default=24.0)
    args = ap.parse_args()
    try:
        asyncio.run(main(args.backend, args.loop_hours))
    except KeyboardInterrupt:
        log.info("monitor interrupted by user")
