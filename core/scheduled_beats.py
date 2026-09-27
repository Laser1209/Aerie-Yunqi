"""Aerie · ScheduledBeats — 承诺节拍存储（Promise Beats 子系统）.

她自己说出口、需要在未来某个时刻兑现的事（例："好几天闷家里了 想出去走走"
→ 一两小时后拍一张她在外面的照片），在落定的那一刻被提取为一条 ScheduledBeat。

本模块只负责**确定性的存取与状态流转**，不做语义提取、不触发任何行为：
- ``pending``：已排期、等待到期；
- ``fired``：已成功兑现（恰好一次，fired 后永不重新进入 due）；
- ``failed``：超过重试窗口仍未兑现（落审计，不静默丢失、不永生重试）；
- ``cancelled``：兑现前话题被提前终结（如她改口）。

持久化为单个 JSON 文件（默认 ``data/scheduled_beats.json``），原子写。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from core.companion_state import _atomic_write_json, _load_json
from core.paths import data_dir

# 同一 source_text 在该窗口内只允许产生一条 beat（防同一轮重复提取）。
_DEDUP_WINDOW_SEC = 300.0


@dataclass
class ScheduledBeat:
    """一条待兑现的承诺节拍。"""

    id: str
    kind: str                  # 兑现类型，第一版仅 "go_out"
    topic: str                 # 承诺的归纳（出图/上下文素材）
    source_text: str           # 她的原话（审计 + 幂等指纹）
    created_at: float
    due_at: float              # 到期时刻
    status: str = "pending"    # pending / fired / failed / cancelled
    place_hint: str = ""       # 地点提示（可空，由世界模拟选点）
    fired_at: float = 0.0
    attempts: int = 0

    @property
    def is_pending(self) -> bool:
        return self.status == "pending"


class BeatStore:
    """ScheduledBeat 的持久化存储（同步、原子写）。"""

    def __init__(
        self,
        path: Optional[Path | str] = None,
        *,
        max_pending: int = 2,
        clock: Any = None,
    ) -> None:
        self._path = Path(path) if path is not None else self.default_path()
        self._max_pending = max(1, int(max_pending))
        self._clock = clock or time.time
        self._beats: list[ScheduledBeat] = self._load()

    # ── 基础访问 ───────────────────────────────────────

    @staticmethod
    def default_path() -> Path:
        return data_dir() / "scheduled_beats.json"

    def all(self) -> list[ScheduledBeat]:
        return list(self._beats)

    def reload(self) -> None:
        """重新从磁盘读取，看到其他实例/进程写入的最新状态。"""
        self._beats = self._load()

    def get(self, beat_id: str) -> Optional[ScheduledBeat]:
        for beat in self._beats:
            if beat.id == beat_id:
                return beat
        return None

    def pending_count(self) -> int:
        return sum(1 for b in self._beats if b.is_pending)

    # ── 写入 ───────────────────────────────────────────

    def schedule(
        self,
        *,
        kind: str,
        topic: str,
        source_text: str,
        delay_sec: float,
        place_hint: str = "",
        now: Optional[float] = None,
    ) -> Optional[ScheduledBeat]:
        """排期一条新 beat。

        三种情况不产生新 beat 并返回 None：
        - 已有同原话（source_text）的 beat 在去重窗口内（幂等）；
        - pending 已达 ``max_pending`` 上限（防堆积）；
        - delay_sec <= 0。
        """
        moment = float(now) if now is not None else self._now()
        delay_sec = float(delay_sec)
        if delay_sec <= 0:
            return None
        if self._has_recent_source(source_text, moment):
            return None
        if self.pending_count() >= self._max_pending:
            return None

        beat = ScheduledBeat(
            id=uuid.uuid4().hex[:12],
            kind=str(kind),
            topic=str(topic),
            source_text=str(source_text),
            created_at=moment,
            due_at=moment + delay_sec,
            place_hint=str(place_hint or ""),
        )
        self._beats.append(beat)
        self._save()
        return beat

    def due(self, now: Optional[float] = None) -> list[ScheduledBeat]:
        """到期且仍 pending 的 beat（按 due_at 升序）。fired 永不返回。"""
        moment = float(now) if now is not None else self._now()
        pending = [b for b in self._beats if b.is_pending and b.due_at <= moment]
        pending.sort(key=lambda b: b.due_at)
        return pending

    def mark_fired(self, beat_id: str, now: Optional[float] = None) -> bool:
        """兑现成功：pending → fired。返回是否命中并写盘。"""
        beat = self.get(beat_id)
        if beat is None or not beat.is_pending:
            return False
        beat.status = "fired"
        beat.fired_at = float(now) if now is not None else self._now()
        beat.attempts += 1
        self._save()
        return True

    def mark_attempt(self, beat_id: str) -> bool:
        """记录一次兑现尝试（仍未成功，下轮重试）。"""
        beat = self.get(beat_id)
        if beat is None or not beat.is_pending:
            return False
        beat.attempts += 1
        self._save()
        return True

    def mark_failed(self, beat_id: str) -> bool:
        """超过重试窗口：pending → failed（不静默丢失）。"""
        beat = self.get(beat_id)
        if beat is None or not beat.is_pending:
            return False
        beat.status = "failed"
        self._save()
        return True

    def cancel(self, beat_id: str) -> bool:
        """兑现前取消：pending → cancelled。"""
        beat = self.get(beat_id)
        if beat is None or not beat.is_pending:
            return False
        beat.status = "cancelled"
        self._save()
        return True

    # ── 内部 ───────────────────────────────────────────

    def _now(self) -> float:
        return float(self._clock())

    def _has_recent_source(self, source_text: str, now: float) -> bool:
        fingerprint = str(source_text or "").strip()
        if not fingerprint:
            return False
        for beat in self._beats:
            if beat.source_text.strip() != fingerprint:
                continue
            if now - beat.created_at <= _DEDUP_WINDOW_SEC:
                return True
        return False

    def _save(self) -> None:
        payload = {"beats": [asdict(b) for b in self._beats]}
        _atomic_write_json(self._path, payload)

    def _load(self) -> list[ScheduledBeat]:
        data = _load_json(self._path)
        if not data:
            return []
        raw_beats = data.get("beats")
        if not isinstance(raw_beats, list):
            return []
        beats: list[ScheduledBeat] = []
        for item in raw_beats:
            if not isinstance(item, dict):
                continue
            try:
                beats.append(
                    ScheduledBeat(
                        id=str(item["id"]),
                        kind=str(item.get("kind") or ""),
                        topic=str(item.get("topic") or ""),
                        source_text=str(item.get("source_text") or ""),
                        created_at=float(item.get("created_at") or 0.0),
                        due_at=float(item.get("due_at") or 0.0),
                        status=str(item.get("status") or "pending"),
                        place_hint=str(item.get("place_hint") or ""),
                        fired_at=float(item.get("fired_at") or 0.0),
                        attempts=int(item.get("attempts") or 0),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return beats
