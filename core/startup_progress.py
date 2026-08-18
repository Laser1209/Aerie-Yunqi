"""Aerie · 云栖 — 后端启动进度追踪器(全局单例)。

记录后端启动各阶段状态与耗时,供前端进度条轮询展示"哪些组件在启动"。
轻量、非阻塞:仅在关键启动阶段调用 mark_step 埋点,任何调用失败都不影响启动。

用法:
    from core.startup_progress import mark_step, get_startup_progress
    mark_step("companion", "running", "初始化组件")
    mark_step("companion", "done", "")
    get_startup_progress().snapshot()  # -> {steps: [...], elapsed_ms, finished}
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

_STEP_FINAL = {"done", "error", "skipped"}


class StartupProgress:
    """线程安全的启动进度记录器(单例)。"""

    def __init__(self) -> None:
        self.started_at = time.time()
        self.finished = False
        self._steps: list[dict] = []
        self._lock = None  # 惰性导入 threading,避免导入开销

    def _ensure_lock(self):
        if self._lock is None:
            import threading

            self._lock = threading.Lock()
        return self._lock

    def mark(self, name: str, status: str = "running", detail: str = "") -> None:
        """记录/更新一个启动阶段。status ∈ running|done|error|skipped。"""
        lock = self._ensure_lock()
        with lock:
            for s in self._steps:
                if s["name"] == name:
                    s["status"] = status
                    if detail:
                        s["detail"] = detail
                    if status in _STEP_FINAL and s.get("elapsed_ms") is None:
                        s["elapsed_ms"] = int((time.time() - s["_t0"]) * 1000)
                    return
            self._steps.append(
                {
                    "name": name,
                    "status": status,
                    "detail": detail,
                    "elapsed_ms": None,
                    "_t0": time.time(),
                }
            )

    def finish(self) -> None:
        self.finished = True
        self.mark("__finish__", "done", "")

    def snapshot(self) -> dict:
        """返回给前端的进度快照(去掉内部 _t0 字段)。"""
        return {
            "started_at": self.started_at,
            "finished": self.finished,
            "elapsed_ms": int((time.time() - self.started_at) * 1000),
            "steps": [
                {
                    "name": s["name"],
                    "status": s["status"],
                    "detail": s["detail"],
                    "elapsed_ms": s.get("elapsed_ms"),
                }
                for s in self._steps
                if s["name"] != "__finish__"
            ],
        }


_progress = StartupProgress()


def get_startup_progress() -> StartupProgress:
    return _progress


def mark_step(name: str, status: str = "running", detail: str = "") -> None:
    try:
        _progress.mark(name, status, detail)
    except Exception:  # noqa: BLE001
        logger.warning("startup_progress mark failed: %s", name, exc_info=True)


__all__ = ["StartupProgress", "get_startup_progress", "mark_step"]
