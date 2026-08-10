#!/usr/bin/env python3
"""Aerie 24h monitor watchdog — auto-relaunch on crash/kill.

Keeps ``24h_monitor.py`` alive across restarts: launches it as a child
process and relaunches whenever it exits non-zero (crash / kill). A clean
exit (code 0) means the full loop finished, so the watchdog exits too.

Restart events are appended to ``04_LOGS/monitor_watchdog.log`` so the
test timeline stays traceable.

Run:  python scripts/24h_monitor_watchdog.py [--loop-hours 24] [--backend http://127.0.0.1:7890] [--backoff 5]
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MONITOR = ROOT / "scripts" / "24h_monitor.py"
LOG_ROOT = Path(os.getenv("AERIE_24H_LOG", r"D:\Aerie\24H-LOG"))


def main() -> None:
    ap = argparse.ArgumentParser(description="Aerie 24h monitor watchdog")
    ap.add_argument("--loop-hours", type=float, default=24.0)
    ap.add_argument("--backend", default="http://127.0.0.1:7890")
    ap.add_argument("--backoff", type=float, default=5.0)
    args = ap.parse_args()

    LOG_ROOT.joinpath("04_LOGS").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_ROOT / "04_LOGS" / "monitor_watchdog.log",
                                encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )
    log = logging.getLogger("aerie.watchdog")

    restarts = 0
    while True:
        cmd = [sys.executable, str(MONITOR),
               "--loop-hours", str(args.loop_hours),
               "--backend", args.backend]
        log.info("launching monitor: %s", " ".join(cmd))
        try:
            proc = subprocess.run(cmd, cwd=str(ROOT))
        except Exception as exc:  # noqa: BLE001
            log.exception("failed to spawn monitor: %s", exc)
            time.sleep(args.backoff)
            continue

        if proc.returncode == 0:
            log.info("monitor finished cleanly (loop complete), watchdog exiting")
            break

        restarts += 1
        log.warning("monitor exited code=%s, restart #%d in %.0fs",
                    proc.returncode, restarts, args.backoff)
        time.sleep(args.backoff)


if __name__ == "__main__":
    main()
