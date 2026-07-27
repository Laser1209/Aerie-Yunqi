"""Aerie · 云栖 — ActionRegistry 工具注册与风险控制 (Task P1-B.3).

该模块同时承载两套接口:

1. Phase 12 确定性世界动作 (历史, 保留 WorldAction / parse / exists / choose_safe_action /
   execute(WorldAction, world_snapshot=...)), 由 core.world_simulation 使用.
2. P1-B 办公工具注册 (新增):
   - RiskLevel.LOW / MEDIUM / HIGH
   - register(action_id, handler, risk_level, label)
   - execute(action_id: str, params: dict, confirm_callback=None) -> dict
   - audit_log: 每次执行记录 action_id / risk_level / timestamp / result
   - register_builtin_low_risk(): 内置 open_url / show_status / adjust_volume /
     adjust_brightness 四个低风险工具

两套接口通过参数类型自动分发, 互不干扰.
"""

from __future__ import annotations

import enum
import logging
import time
import webbrowser
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ── 风险等级 ────────────────────────────────────────
class RiskLevel(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# ── Phase 12 WorldAction (保留) ─────────────────────
@dataclass(frozen=True)
class WorldAction:
    action_type: str
    params: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "type": self.action_type,
            "params_keys": sorted(str(key) for key in self.params.keys()),
            "reason": self.reason,
        }


# ── 注册条目 ────────────────────────────────────────
@dataclass
class _RegisteredAction:
    action_id: str
    handler: Callable[..., Any]
    risk_level: RiskLevel
    label: str


# ── 审计日志条目 ────────────────────────────────────
@dataclass
class AuditEntry:
    action_id: str
    risk_level: str
    timestamp: float
    result: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "risk_level": self.risk_level,
            "timestamp": self.timestamp,
            "result": self.result,
        }


# ── 内置低风险工具 handler ─────────────────────────
def _builtin_open_url(params: dict[str, Any]) -> dict[str, Any]:
    url = str(params.get("url") or "").strip()
    if not url:
        return {"status": "error", "reason": "missing url"}
    try:
        webbrowser.open(url)
        opened = True
    except Exception as exc:  # pragma: no cover - 平台相关
        logger.debug("open_url webbrowser.open failed: %s", exc)
        opened = False
    return {"status": "ok", "opened": opened, "url": url}


def _builtin_show_status(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "ok",
        "battery": params.get("battery"),
        "network": params.get("network"),
        "active_window": params.get("active_window"),
    }


def _builtin_adjust_volume(params: dict[str, Any]) -> dict[str, Any]:
    level = params.get("level")
    return {"status": "ok", "volume": level}


def _builtin_adjust_brightness(params: dict[str, Any]) -> dict[str, Any]:
    level = params.get("level")
    return {"status": "ok", "brightness": level}


_BUILTIN_LOW_RISK: dict[str, tuple[Callable[..., Any], str]] = {
    "open_url": (_builtin_open_url, "打开网址"),
    "show_status": (_builtin_show_status, "显示状态"),
    "adjust_volume": (_builtin_adjust_volume, "调整音量"),
    "adjust_brightness": (_builtin_adjust_brightness, "调整亮度"),
}


# ── 注册表 ──────────────────────────────────────────
class ActionRegistry:
    """统一的动作注册表.

    - Phase 12 世界动作接口 (wait / set_activity / parse / exists / choose_safe_action)
    - P1-B 办公工具接口 (register / execute(action_id, params, ...) / audit_log)
    """

    def __init__(self) -> None:
        # Phase 12 内置
        self._world_actions: dict[str, str] = {
            "wait": "No-op safe fallback",
            "set_activity": "Update simulated activity",
        }
        # P1-B 注册
        self._registered: dict[str, _RegisteredAction] = {}
        self.audit_log: list[dict[str, Any]] = []

    # ─────────────────────────────────────────────
    # Phase 12 API (保持原行为)
    # ─────────────────────────────────────────────
    def exists(self, action_type: str) -> bool:
        return str(action_type or "") in self._world_actions

    def parse(self, proposal: dict[str, Any] | None) -> WorldAction:
        payload = proposal if isinstance(proposal, dict) else {}
        action_type = str(payload.get("type") or "wait")
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        if not self.exists(action_type):
            return self.choose_safe_action(reason="unknown_action")
        if action_type == "set_activity":
            activity = str(params.get("activity") or "").strip()
            if not activity:
                return self.choose_safe_action(reason="invalid_activity")
            return WorldAction("set_activity", {"activity": activity[:80]})
        return WorldAction("wait", reason=str(payload.get("reason") or ""))

    def choose_safe_action(self, *, reason: str = "safe_fallback") -> WorldAction:
        return WorldAction("wait", reason=reason)

    def _execute_world(
        self,
        action: WorldAction,
        *,
        world_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if action.action_type == "set_activity":
            return {
                "status": "ok",
                "action": "set_activity",
                "activity": action.params.get("activity", "idle"),
            }
        return {
            "status": "ok",
            "action": "wait",
            "reason": action.reason or "no_action",
            "previous_activity": (world_snapshot or {}).get("activity", "idle"),
        }

    # ─────────────────────────────────────────────
    # P1-B 办公工具 API
    # ─────────────────────────────────────────────
    def is_registered(self, action_id: str) -> bool:
        return str(action_id or "") in self._registered

    def register(
        self,
        action_id: str,
        handler: Callable[..., Any],
        risk_level: RiskLevel | str,
        *,
        label: str = "",
    ) -> None:
        aid = str(action_id or "").strip()
        if not aid:
            raise ValueError("action_id 不能为空")
        if aid in self._registered:
            raise ValueError(f"action already registered: {aid}")
        if not callable(handler):
            raise ValueError("handler must be callable")
        if isinstance(risk_level, str):
            risk_level = RiskLevel(risk_level.upper())
        self._registered[aid] = _RegisteredAction(
            action_id=aid,
            handler=handler,
            risk_level=risk_level,
            label=str(label or aid),
        )

    def register_builtin_low_risk(self) -> None:
        """注册内置低风险办公工具 (幂等, 已存在的跳过)."""
        for aid, (handler, label) in _BUILTIN_LOW_RISK.items():
            if aid not in self._registered:
                self._registered[aid] = _RegisteredAction(
                    action_id=aid,
                    handler=handler,
                    risk_level=RiskLevel.LOW,
                    label=label,
                )

    def execute(
        self,
        target: Any,
        params: Optional[dict[str, Any]] = None,
        *,
        confirm_callback: Optional[Callable[[str, dict[str, Any]], bool]] = None,
        world_snapshot: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """统一执行入口.

        - 若 target 是 WorldAction → 走 Phase 12 世界动作路径.
        - 若 target 是 str (action_id) → 走 P1-B 办公工具路径.
        """
        if isinstance(target, WorldAction):
            return self._execute_world(target, world_snapshot=world_snapshot)
        if isinstance(target, str):
            return self._execute_registered(
                target, params or {}, confirm_callback=confirm_callback
            )
        # 兜底: 未知类型
        return {"status": "unknown", "reason": "unsupported target type"}

    def _execute_registered(
        self,
        action_id: str,
        params: dict[str, Any],
        *,
        confirm_callback: Optional[Callable[[str, dict[str, Any]], bool]],
    ) -> dict[str, Any]:
        entry = self._registered.get(action_id)
        ts = time.time()
        if entry is None:
            result: dict[str, Any] = {
                "status": "unknown",
                "reason": f"action not registered: {action_id}",
            }
            self._audit(action_id, "UNKNOWN", ts, result)
            return result

        # 风险拦截: MEDIUM/HIGH 必须有 confirm_callback 且返回 True
        if entry.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH):
            if confirm_callback is None:
                result = {
                    "status": "denied",
                    "reason": (
                        f"action '{action_id}' requires explicit user confirmation "
                        f"(risk_level={entry.risk_level.value})"
                    ),
                }
                self._audit(action_id, entry.risk_level.value, ts, result)
                return result
            try:
                allowed = bool(confirm_callback(action_id, params or {}))
            except Exception as exc:  # pragma: no cover
                result = {
                    "status": "denied",
                    "reason": f"confirm_callback raised: {exc}",
                }
                self._audit(action_id, entry.risk_level.value, ts, result)
                return result
            if not allowed:
                result = {
                    "status": "denied",
                    "reason": "user denied confirmation",
                }
                self._audit(action_id, entry.risk_level.value, ts, result)
                return result

        # 执行 handler
        try:
            handler_result = entry.handler(params or {})
        except Exception as exc:
            result = {"status": "error", "reason": f"handler raised: {exc}"}
            self._audit(action_id, entry.risk_level.value, time.time(), result)
            return result

        if isinstance(handler_result, dict):
            result = dict(handler_result)
            result.setdefault("status", "ok")
        else:
            result = {"status": "ok", "result": handler_result}
        self._audit(action_id, entry.risk_level.value, time.time(), result)
        return result

    # ── 审计 ─────────────────────────────────────
    def _audit(
        self, action_id: str, risk_level: str, ts: float, result: dict[str, Any]
    ) -> None:
        self.audit_log.append(
            {
                "action_id": action_id,
                "risk_level": risk_level,
                "timestamp": ts,
                "result": result,
            }
        )

    def clear_audit_log(self) -> None:
        self.audit_log = []
