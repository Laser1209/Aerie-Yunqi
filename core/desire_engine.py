"""Aerie · 云栖 v0.1.0-beta.1 — Desire Engine: 24h polling, 伊塔「想」发才发.

Block-4B R2.1: 5 变量叠加 + 5min 心跳 + cooldown + 持久化.

设计目标:
  - 不靠 cron 触发, 24h 持续轮询, 让伊塔「自己感觉到想发」.
  - 5 变量 (user_absence_hours / emotion_overdraft / patience_loss /
    weather_impact / time_of_day_boost) 加权累加.
  - 阈值触发分两档: care (低) + voice (高 + 时段).
  - 持续 cooldown 防止被拒后狂推.

配置源: config/persona_behavior.yaml → desire
持久化: data/desire_state.json (atomic write)
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from core.behavior_sampler import emit_probability, sample_once
from core.paths import data_dir, project_root

logger = logging.getLogger(__name__)

# 语音窗口: 22:00 - 23:30 适合发语音
VOICE_WINDOW_START = "22:00"
VOICE_WINDOW_END = "23:30"

# 冷却: 连续 3 次被拒, 强制 cooldown 12h
COOLDOWN_REJECT_THRESHOLD = 3
COOLDOWN_HOURS_DEFAULT = 12

# tick 间隔下限保护 (即使 cfg 配了 1s, 也不允许 < 30s)
TICK_MIN_SECONDS = 30

# mtime 抖动容差 (API 保存配置会写文件, 秒级 mtime 相同则视为未变)
_MTIME_EPS = 1e-6


def _behavior_config_path() -> Path:
    """persona_behavior.yaml 路径；与 topic_lifecycle/image_tiering 同源热加载。"""
    return project_root() / "config" / "persona_behavior.yaml"


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON atomically (tempfile + replace)."""
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_state(path: Path) -> dict:
    """Load persisted state; return default empty state on missing/corrupt."""
    if not path.exists():
        return _default_state()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _default_state()
        return data
    except Exception:
        logger.warning("desire state corrupt, resetting")
        return _default_state()


def _default_state() -> dict:
    return {
        "score": 0.0,
        "ts": 0.0,
        "cooldown_until_ts": 0.0,
        "reject_count": 0,
        "last_trigger": "",
        "last_variables": {},
        "history": [],  # last 50 tick snapshots
    }


def _parse_hhmm(s: str) -> tuple[int, int]:
    parts = s.strip().split(":")
    return int(parts[0]), int(parts[1])


def _in_voice_window(now: datetime | None = None) -> bool:
    """True if current time falls in the voice window (default 22:00-23:30)."""
    now = now or datetime.now()
    sh, sm = _parse_hhmm(VOICE_WINDOW_START)
    eh, em = _parse_hhmm(VOICE_WINDOW_END)
    cur = now.hour * 60 + now.minute
    return sh * 60 + sm <= cur <= eh * 60 + em


class DesireEngine:
    """5-variable, 5min-tick polling engine.

    Block-4B R2.1: the engine does not rely on a cron schedule. Instead it
    runs a single async loop that wakes every ``tick_seconds`` and re-scores
    the desire state. When the score crosses the care or voice trigger, it
    delegates to the existing PushScheduler scenes (``idle_care`` /
    ``voice_miss``) so all the policy / quiet-period / daily-cap rules
    remain in one place.
    """

    def __init__(
        self,
        companion: Any,
        behavior_cfg: dict | None = None,
        *,
        state_path: str | Path | None = None,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self.companion = companion
        cfg = (behavior_cfg or {}).get("desire", {}) or {}
        self.cfg = cfg
        # 热加载探测点：记住配置源 mtime，之后每次触发判定前比对（见 reload_config_if_changed）
        self._cfg_path = _behavior_config_path()
        self._cfg_mtime = self._read_cfg_mtime()
        self.tick_seconds = max(
            int(cfg.get("tick_seconds", 300)),
            TICK_MIN_SECONDS,
        )
        self.triggers = cfg.get("triggers", {"care": 50, "voice": 80, "cooldown_hours": 12})
        self.cooldown_hours = int(self.triggers.get("cooldown_hours", COOLDOWN_HOURS_DEFAULT))
        # 阶段 5: 阈值阶梯 → 调制 p + 采样。采样温度 τ / 概率上下限从配置读取
        # (persona_behavior.yaml → desire.triggers)，代码仅兜底；rng 可注入以固定 seed 复现。
        self.sampling_tau = float(self.triggers.get("tau", 8.0))
        self.p_floor = float(self.triggers.get("p_floor", 0.02))
        self.p_ceiling = float(self.triggers.get("p_ceiling", 0.95))
        self.rng = rng
        self.variables_cfg = cfg.get("variables", {}) or {}
        self.state_path = (
            Path(state_path) if state_path is not None else data_dir() / "desire_state.json"
        )
        self.state: dict = _load_state(self.state_path)
        # Append-only ring of last 50 tick snapshots
        self._task: asyncio.Task | None = None
        self._stopped = False
        # Last user message ts (updated by mark_user_active from companion)
        self._last_user_ts: float = time.time()
        # Last trigger ts to space identical triggers
        self._last_care_ts: float = 0.0
        self._last_voice_ts: float = 0.0
        # 阶段 5: 采样放行标记 (scene, ts)，供 ProactiveJudge 复用决定、避免二次采样。
        self._emit_grant: tuple[str, float] | None = None

    # ── Config hot-reload ────────────────────────────
    def _read_cfg_mtime(self) -> float | None:
        try:
            return self._cfg_path.stat().st_mtime
        except OSError:
            return None

    def reload_config_if_changed(self) -> bool:
        """配置源 mtime 变了就重读 desire 段；未变则零开销返回。

        只覆盖「可在线调参」的字段（阈值 / 采样温度 / 概率上下限 / tick /
        冷却小时），不动运行态状态（score / cooldown_until / history）。
        YAML 不可用或解析失败时保持现状，绝不抛错打断欲望循环。
        """
        mtime = self._read_cfg_mtime()
        if mtime is None or mtime <= (self._cfg_mtime or 0.0) + _MTIME_EPS:
            return False
        self._cfg_mtime = mtime
        try:
            import yaml

            raw = yaml.safe_load(self._cfg_path.read_text(encoding="utf-8")) or {}
        except Exception:
            logger.warning("desire 配置热加载失败，沿用当前参数", exc_info=True)
            return False
        cfg = (raw.get("desire", {}) if isinstance(raw, dict) else {}) or {}
        if not cfg:
            return False
        self.cfg = cfg
        self.triggers = cfg.get("triggers", self.triggers) or self.triggers
        self.cooldown_hours = int(
            self.triggers.get("cooldown_hours", COOLDOWN_HOURS_DEFAULT)
        )
        self.sampling_tau = float(self.triggers.get("tau", 8.0))
        self.p_floor = float(self.triggers.get("p_floor", 0.02))
        self.p_ceiling = float(self.triggers.get("p_ceiling", 0.95))
        self.tick_seconds = max(int(cfg.get("tick_seconds", self.tick_seconds)), TICK_MIN_SECONDS)
        self.variables_cfg = cfg.get("variables", {}) or self.variables_cfg
        logger.info(
            "desire 配置已热加载: tau=%.2f floor=%.2f ceil=%.2f tick=%ds",
            self.sampling_tau,
            self.p_floor,
            self.p_ceiling,
            self.tick_seconds,
        )
        return True

    # ── Lifecycle ─────────────────────────────────────
    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stopped = False
        self._task = asyncio.create_task(self._loop(), name="desire-loop")
        logger.info("desire engine started: tick=%ds", self.tick_seconds)

    async def stop(self) -> None:
        self._stopped = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("desire engine stopped")

    # ── Markers (called by companion) ───────────────
    def mark_user_active(self) -> None:
        """Reset the user-absence clock. Called on inbound QQ message."""
        self._last_user_ts = time.time()

    def mark_rejected(self) -> None:
        """User visibly rejected a desire push. Increment counter."""
        self.state["reject_count"] = int(self.state.get("reject_count", 0)) + 1
        if self.state["reject_count"] >= COOLDOWN_REJECT_THRESHOLD:
            self.set_cooldown(self.cooldown_hours)
            self.state["reject_count"] = 0
        self._save_state()

    def set_cooldown(self, hours: float) -> None:
        """Force a cooldown window (manual API or auto-trigger)."""
        self.state["cooldown_until_ts"] = time.time() + float(hours) * 3600.0
        self._save_state()
        logger.info("desire cooldown set: %.1fh", float(hours))

    # ── Loop ─────────────────────────────────────────
    async def _loop(self) -> None:
        while not self._stopped:
            try:
                await asyncio.sleep(self.tick_seconds)
                if self._stopped:
                    return
                await self._tick()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("desire loop error; continuing")

    async def _tick(self) -> None:
        # 每拍先探测配置源 mtime，用户改 persona_behavior.yaml → desire 后即时生效。
        self.reload_config_if_changed()
        var_values = self._read_variables()
        score = self._score_from_variables(var_values)
        self.state["score"] = round(score, 2)
        self.state["ts"] = time.time()
        self.state["last_variables"] = var_values
        # Append bounded history
        hist = self.state.setdefault("history", [])
        hist.append({
            "ts": time.time(),
            "score": round(score, 2),
            "variables": var_values,
        })
        if len(hist) > 50:
            self.state["history"] = hist[-50:]

        # Cooldown gate
        if self._is_in_cooldown():
            self._save_state()
            return

        # 阶段 5: 阈值阶梯 → 调制 p + 采样（唯一行为层采样点）。
        now = time.time()
        scene = self._decide_trigger(score, now)
        if scene:
            self.state["last_trigger"] = scene
            self._save_state()
            await self._trigger_scene(scene)
            return

        self._save_state()

    def _decide_trigger(self, score: float, now: float) -> str | None:
        """由 score 得到触发场景；改为「调制 p + 采样」，固定 seed 可复现。

        p = floor + (ceiling - floor) * sigmoid((score - care) / tau)：
        care 是概率拐点，不再「score >= care 就发」——低于 care 仍有非零概率
        (低分不被饿死)，高于 care 也可能不发射 (保留未发射样本)。采样只做一次。
        """
        care = float(self.triggers.get("care", 50))
        voice = float(self.triggers.get("voice", 80))
        p = emit_probability(
            score,
            reference=care,
            tau=self.sampling_tau,
            floor=self.p_floor,
            ceiling=self.p_ceiling,
        )
        if not sample_once(p, self.rng):
            return None
        # Anti-spam: identical trigger at most once per 30 minutes.
        if (
            score >= voice
            and _in_voice_window(datetime.fromtimestamp(now))
            and (now - self._last_voice_ts) > 1800
        ):
            self._last_voice_ts = now
            return "voice_miss"
        if (now - self._last_care_ts) > 1800:
            self._last_care_ts = now
            return "idle_care"
        return None

    async def _trigger_scene(self, scene_name: str) -> None:
        # 采样已在 _decide_trigger 完成（本决策链唯一采样点）：用 emit_grant 标记
        # 本次触发由欲望引擎放行，ProactiveJudge 复用该决定、不再二次采样。
        self._emit_grant = (str(scene_name), time.time())
        try:
            if not self.companion or not self.companion.push_scheduler:
                return
            await self.companion.push_scheduler.trigger(scene_name)
        except Exception:
            logger.exception("desire trigger scene %s failed", scene_name)
        finally:
            self._emit_grant = None

    # ── Variable readers ─────────────────────────────
    def _read_variables(self) -> dict[str, float]:
        """Read each configured variable; missing sources default to 0."""
        out: dict[str, float] = {}
        for name in self.variables_cfg.keys():
            try:
                out[name] = float(self._read_one(name) or 0.0)
            except Exception:
                out[name] = 0.0
        return out

    def _read_one(self, name: str) -> float:
        """Read a single variable value from companion state."""
        if name == "user_absence_hours":
            return (time.time() - self._last_user_ts) / 3600.0
        if name == "emotion_overdraft":
            try:
                state = self.companion.get_primary_emotion_state() if self.companion else {}
                pad = state.get("pad", {}) or {}
                # High arousal + low pleasure = "overdraft"
                return max(0.0, (pad.get("A", 0.0) - 0.0) * 30.0)
            except Exception:
                return 0.0
        if name == "patience_loss":
            try:
                state = self.companion.get_primary_emotion_state() if self.companion else {}
                th = state.get("thresholds", {}) or {}
                v = th.get("patience", {}).get("value", 0) if isinstance(th.get("patience"), dict) else 0
                return float(v or 0)
            except Exception:
                return 0.0
        if name == "weather_impact":
            try:
                from core import brief_fetcher
                today = datetime.now().strftime("%Y-%m-%d")
                brief = brief_fetcher.load_brief(today) or {}
                w = brief.get("weather") or {}
                desc = (w.get("desc") or "").lower()
                if "雨" in desc or "rain" in desc:
                    return 8.0
                if "阴" in desc or "cloud" in desc:
                    return 4.0
                return 0.0
            except Exception:
                return 0.0
        if name == "time_of_day_boost":
            h = datetime.now().hour
            if 22 <= h <= 23:
                return 15.0
            if 19 <= h < 22:
                return 8.0
            if 5 <= h < 8:
                return 6.0
            return 0.0
        if name == "anniversary_boost":
            # 简单读 anniversary 表: 今天是否有纪念日
            try:
                from core.database import Database
                db = Database()
                today = datetime.now().strftime("%Y-%m-%d")
                rows = db.query(
                    "SELECT COUNT(*) AS c FROM anniversary WHERE date = ?",
                    (today,),
                )
                c = rows[0]["c"] if rows else 0
                return 30.0 if c > 0 else 0.0
            except Exception:
                return 0.0
        return 0.0

    def _score_from_variables(self, values: dict[str, float]) -> float:
        total = 0.0
        for name, v in self.variables_cfg.items():
            try:
                mx = float(v.get("max", 1))
                wt = float(v.get("weight", 0))
                if mx <= 0:
                    continue
                # Clamp to [0, max], then scale by max*weight
                val = max(0.0, min(values.get(name, 0.0), mx))
                total += (val / mx) * mx * wt
            except Exception:
                continue
        return total

    def _is_in_cooldown(self) -> bool:
        until = float(self.state.get("cooldown_until_ts", 0) or 0)
        return time.time() < until

    def _save_state(self) -> None:
        try:
            _atomic_write_json(self.state_path, self.state)
        except Exception:
            logger.exception("desire state save failed")

    # ── Public snapshot ──────────────────────────────
    def get_state(self) -> dict:
        return {
            "score": self.state.get("score", 0.0),
            "ts": self.state.get("ts", 0.0),
            "cooldown_until_ts": self.state.get("cooldown_until_ts", 0.0),
            "in_cooldown": self._is_in_cooldown(),
            "reject_count": self.state.get("reject_count", 0),
            "last_trigger": self.state.get("last_trigger", ""),
            "tick_seconds": self.tick_seconds,
            "triggers": self.triggers,
            "variables": self.state.get("last_variables", {}),
            "variable_labels": {k: v.get("label", k) for k, v in self.variables_cfg.items()},
            "user_absence_hours": round((time.time() - self._last_user_ts) / 3600.0, 2),
        }
