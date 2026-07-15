"""Aerie · 云栖 v9.0 — System resource monitor."""

from __future__ import annotations

import os
import platform
import time
from typing import Optional

import psutil


class SystemMonitor:
    """CPU / memory / disk / network / Python proc info."""

    def __init__(self) -> None:
        self._boot_time = time.time()

    def get_stats(self) -> dict:
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(str(os.getcwd()))
        net = psutil.net_io_counters()
        uptime = time.time() - self._boot_time
        return {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "cpu_percent": cpu,
            "memory": {
                "total_mb": round(mem.total / 1024 / 1024, 1),
                "used_mb": round(mem.used / 1024 / 1024, 1),
                "percent": mem.percent,
            },
            "disk": {
                "total_gb": round(disk.total / 1024 / 1024 / 1024, 1),
                "used_gb": round(disk.used / 1024 / 1024 / 1024, 1),
                "percent": disk.percent,
            },
            "network": {
                "sent_mb": round(net.bytes_sent / 1024 / 1024, 1),
                "recv_mb": round(net.bytes_recv / 1024 / 1024, 1),
            },
            "python_proc": self._python_proc_info(),
            "uptime_seconds": round(uptime, 1),
        }

    def _python_proc_info(self) -> dict:
        try:
            p = psutil.Process(os.getpid())
            mem_info = p.memory_info()
            return {
                "pid": p.pid,
                "name": p.name(),
                "rss_mb": round(mem_info.rss / 1024 / 1024, 1),
                "vms_mb": round(mem_info.vms / 1024 / 1024, 1),
                "cpu_percent": p.cpu_percent(interval=0.05),
                "threads": p.num_threads(),
            }
        except Exception:
            return {"pid": os.getpid(), "rss_mb": 0}
