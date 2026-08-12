"""Aerie · decision_log — 候选决策证据日志（append-only）.

伪主观性 Principle 的**证据层**：所有"候选 → 选择 → 动机句"全量落盘，
供世界仪表盘实时展示与后台复盘——用户可看到伊塔每时刻从哪几个候选中
选了哪个（candidates / chosen / reason / fallback）。

- 按日切片轮转：decision_log_YYYYMMDD.jsonl（追加不重写，天然规避
  原子写竞争；切片时同步 gzip 归档）。
- 全存不裁剪：日频 <= 23 条/天（话题动机 <=5 + 行为 10 + 移动 1-8），
  约 4MB/年，无 5MB 阈值死逻辑。
- 线程安全：append 用锁。
"""

from __future__ import annotations

import gzip
import json
import logging
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.paths import data_dir

logger = logging.getLogger(__name__)

# 决策类型
KIND_TOPIC_MOTIVE = "topic_motive"  # 话题动机（主动消息续接/再造/新话题）
KIND_BEHAVIOR = "behavior"  # 行为选择（DailyPlanner slot / set_activity）
KIND_MOVEMENT = "movement"  # 移动目标


class DecisionLogger:
    """Append-only decision evidence log with daily rotation."""

    def __init__(self, log_dir: Optional[Path] = None) -> None:
        self._log_dir = Path(log_dir) if log_dir else data_dir()
        self._lock = threading.Lock()

    # ── 写入 ───────────────────────────────────────────

    def append(
        self,
        kind: str,
        candidates: list[dict[str, Any]],
        chosen: dict[str, Any],
        *,
        reason: str = "",
        fallback: bool = False,
        narrative: Optional[str] = None,
    ) -> str:
        """写入一条决策日志。返回 event_id。"""
        entry = {
            "event_id": uuid.uuid4().hex[:12],
            "ts": datetime.now().isoformat(timespec="seconds"),
            "kind": kind,
            "candidates": candidates,
            "chosen": chosen,
            "reason": reason,
            "fallback": bool(fallback),
            "narrative": narrative,
        }
        path = self._current_path()
        line = json.dumps(entry, ensure_ascii=False)
        with self._lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                logger.warning("decision log append failed", exc_info=True)
        return entry["event_id"]

    # ── 读取 ───────────────────────────────────────────

    def recent(self, limit: int = 30) -> list[dict[str, Any]]:
        """读取最近 N 条决策（跨当前日文件，按 ts 降序）。"""
        entries: list[dict[str, Any]] = []
        today = datetime.now()
        # 仅读当前文件即可满足"最新 30 条"（日频 <=23 条）
        path = self._current_path()
        if not path.exists():
            return entries
        with self._lock:
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            except Exception:
                logger.warning("decision log read failed", exc_info=True)
        entries.sort(key=lambda e: e.get("ts", ""), reverse=True)
        return entries[:limit]

    def _current_path(self) -> Path:
        date_str = datetime.now().strftime("%Y%m%d")
        return self._log_dir / f"decision_log_{date_str}.jsonl"

    # ── 归档（按日切片时同步 gzip）─────────────────────

    def archive(self, date_str: str) -> None:
        """把指定日期的日志文件 gzip 归档为 decision_log_YYYYMMDD.jsonl.gz。"""
        path = self._log_dir / f"decision_log_{date_str}.jsonl"
        if not path.exists():
            return
        gz_path = path.with_suffix(".jsonl.gz")
        try:
            with path.open("rb") as fin, gzip.open(gz_path, "wb") as fout:
                fout.write(fin.read())
            path.unlink()
            logger.info("[DecisionLog] archived %s", path.name)
        except Exception:
            logger.warning("[DecisionLog] archive failed for %s", date_str, exc_info=True)
