"""Phase 12 deterministic world action registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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


class ActionRegistry:
    """Finite action registry for deterministic in-process world rules."""

    def __init__(self) -> None:
        self._actions: dict[str, str] = {
            "wait": "No-op safe fallback",
            "set_activity": "Update simulated activity",
        }

    def exists(self, action_type: str) -> bool:
        return str(action_type or "") in self._actions

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

    def execute(
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
