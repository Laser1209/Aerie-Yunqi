"""Local entitlement and usage metering for the first commercial test.

This is deliberately payment-provider agnostic: it supports a local free
plan and an explicit trial, while a future verified webhook can update the
same state without changing chat or provider code.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PLAN_LIMITS: dict[str, dict[str, int | None]] = {
    "free": {"cloud_calls_month": 100, "cloud_tokens_month": 100_000},
    "trial": {"cloud_calls_month": 500, "cloud_tokens_month": 500_000},
    "pro": {"cloud_calls_month": None, "cloud_tokens_month": None},
}

PLAN_FEATURES: dict[str, list[str]] = {
    "free": ["local_chat", "basic_memory", "single_persona", "single_workspace"],
    "trial": [
        "local_chat", "basic_memory", "multi_persona", "workspace_recipes",
        "proactive_scheduling", "companion_studio_connectors",
    ],
    "pro": [
        "local_chat", "advanced_memory", "multi_persona", "workspace_recipes",
        "proactive_scheduling", "companion_studio_connectors", "priority_updates",
    ],
}

# Prices are display metadata for the pilot only. Payment is intentionally not
# implied until a jurisdiction and provider are selected and verified.
PLAN_PRICING: dict[str, dict[str, Any]] = {
    "free": {"currency": "CNY", "monthly_software_cents": 0, "label": "免费本地版"},
    "trial": {"currency": "CNY", "monthly_software_cents": 0, "label": "14 天 Pro 试用"},
    "pro": {"currency": "CNY", "monthly_software_cents": 2900, "label": "Pro 月订阅（建议测试价）"},
}


def _month_key(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m")


class EntitlementStore:
    def __init__(self, path: str | Path | None = None) -> None:
        configured = os.getenv("AERIE_ENTITLEMENT_PATH", "").strip()
        if path:
            self.path = Path(path)
        elif configured:
            self.path = Path(configured)
        else:
            from core.paths import data_dir

            self.path = data_dir() / "entitlement.json"

    def _default(self) -> dict[str, Any]:
        return {"plan": "free", "trial_ends_at": None, "usage": {}}

    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else self._default()
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return self._default()

    def _write(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix="entitlement-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temp_name, self.path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    def _effective_plan(self, state: dict[str, Any], now: datetime) -> str:
        plan = str(state.get("plan") or "free").lower()
        if plan == "trial":
            try:
                if datetime.fromisoformat(str(state.get("trial_ends_at"))).astimezone(timezone.utc) <= now:
                    return "free"
            except (TypeError, ValueError):
                return "free"
        return plan if plan in PLAN_LIMITS else "free"

    def snapshot(self, now: datetime | None = None) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        state = self._read()
        plan = self._effective_plan(state, current)
        usage = state.get("usage") if isinstance(state.get("usage"), dict) else {}
        month = _month_key(current)
        month_usage = usage.get(month) if isinstance(usage.get(month), dict) else {}
        return {
            "plan": plan,
            "trial_ends_at": state.get("trial_ends_at"),
            "period": month,
            "usage": {
                "cloud_calls": int(month_usage.get("cloud_calls", 0) or 0),
                "cloud_tokens": int(month_usage.get("cloud_tokens", 0) or 0),
            },
            "limits": PLAN_LIMITS[plan],
            "features": PLAN_FEATURES[plan],
            "pricing": PLAN_PRICING[plan],
            "source": "local",
        }

    def activate_trial(self, days: int = 14, now: datetime | None = None) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        state = self._read()
        existing = state.get("trial_ends_at")
        if existing:
            try:
                if datetime.fromisoformat(str(existing)).astimezone(timezone.utc) > current:
                    return self.snapshot(current)
            except (TypeError, ValueError):
                pass
        state["plan"] = "trial"
        state["trial_ends_at"] = (current + timedelta(days=max(1, min(days, 30)))).isoformat()
        self._write(state)
        return self.snapshot(current)

    def record_usage(self, *, cloud_calls: int = 0, cloud_tokens: int = 0,
                     now: datetime | None = None) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        state = self._read()
        month = _month_key(current)
        usage = state.setdefault("usage", {})
        month_usage = usage.setdefault(month, {})
        month_usage["cloud_calls"] = max(0, int(month_usage.get("cloud_calls", 0))) + max(0, int(cloud_calls))
        month_usage["cloud_tokens"] = max(0, int(month_usage.get("cloud_tokens", 0))) + max(0, int(cloud_tokens))
        self._write(state)
        return self.snapshot(current)

    def check(self, *, cloud_calls: int = 0, cloud_tokens: int = 0,
              now: datetime | None = None) -> dict[str, Any]:
        snap = self.snapshot(now)
        reasons: list[str] = []
        for key, requested, label in (
            ("cloud_calls", cloud_calls, "cloud_calls_month"),
            ("cloud_tokens", cloud_tokens, "cloud_tokens_month"),
        ):
            limit = snap["limits"].get(label)
            if limit is not None and snap["usage"][key] + max(0, int(requested)) > limit:
                reasons.append(label)
        return {"allowed": not reasons, "reasons": reasons, **snap}
