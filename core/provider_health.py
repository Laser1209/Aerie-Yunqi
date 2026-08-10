"""Aerie · 云栖 — LLM provider health & balance tracking.

When a provider account runs out of balance (overdue / insufficient balance /
out of credits / 402), every call against it burns latency before the fallback
chain moves on — and if it is the only account, every reply is delayed.

This module:
- classifies balance-type failures and bans the provider from the rotation
  until its balance recovers (or the process restarts),
- applies a short cooldown to transient rate-limit failures,
- probes known balance endpoints (DeepSeek ``/user/balance``) so an exhausted
  account is detected before the first failed call.

State is persisted to ``data/provider_health.json`` so bans survive the
auto-restart helper. ``AERIE_DISABLED_PROVIDERS`` lets an operator hard-disable
accounts (comma-separated names).
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from core.paths import data_dir

logger = logging.getLogger(__name__)

_BALANCE_ERROR_PATTERNS = (
    "accountoverdueerror", "account overdue", "overdue",
    "insufficient_balance", "insufficient balance", "insufficientbalance",
    "insufficient quota", "no credits", "out of credits", "no balance",
    "payment required", "payment_required", "402",
    "余额不足", "欠费", "余额",
)
_RATE_ERROR_PATTERNS = (
    "429", "rate_limit", "rate limit", "too many requests", "overloaded",
    "server busy", "throttl", "retry after", "quota exceeded",
)

_DISABLED_ENV = "AERIE_DISABLED_PROVIDERS"
_RATE_COOLDOWN_SECONDS = 300
_BALANCE_RECHECK_SECONDS = 3600
_PROBE_TTL_SECONDS = 600
_PROBE_TIMEOUT_SECONDS = 5.0

# 已知的余额/账户信息端点（URL 后缀拼接到 provider.base_url 之后）。
# 未列出的 provider（如火山方舟 doubao）没有公开余额接口，依赖错误驱动判定。
_BALANCE_PROBES: dict[str, str] = {
    "deepseek": "/user/balance",
    "siliconflow": "/user/info",
    "siliconflow-free": "/user/info",
}


def _env_disabled_providers() -> set[str]:
    raw = os.environ.get(_DISABLED_ENV, "").strip()
    return {p.strip().lower() for p in raw.split(",") if p.strip()}


def classify_error(error_text: str) -> str:
    """Classify a provider error as balance / rate_limited / other."""
    t = str(error_text or "").lower()
    for pat in _RATE_ERROR_PATTERNS:
        if pat in t:
            return "rate_limited"
    for pat in _BALANCE_ERROR_PATTERNS:
        if pat in t:
            return "balance"
    return "other"


def _now_text(epoch: float | None = None) -> str:
    ts = (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        if epoch is not None
        else datetime.now(timezone.utc)
    )
    return ts.isoformat()


def _parse_text_time(text: str) -> float:
    try:
        return datetime.fromisoformat(str(text)).timestamp()
    except Exception:
        return 0.0


def _extract_balance(name: str, payload: Any) -> float | None:
    """Best-effort balance extraction from a provider probe response."""
    if not isinstance(payload, dict):
        return None
    if name == "deepseek":
        if payload.get("is_available") is False:
            return 0.0
        infos = payload.get("balance_infos") or []
        if isinstance(infos, list) and infos:
            total = 0.0
            for info in infos:
                if isinstance(info, dict):
                    try:
                        total += float(info.get("total_balance") or 0)
                    except (TypeError, ValueError):
                        pass
            return total
        return None
    for key in ("balance", "total_balance", "credits"):
        val = payload.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


class ProviderHealthManager:
    """Track per-provider health so broken accounts leave the rotation."""

    def __init__(self, state_path: str | Path | None = None) -> None:
        self.path = Path(state_path) if state_path is not None else data_dir() / "provider_health.json"
        self._state: dict[str, Any] = {"version": 1, "providers": {}}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("providers"), dict):
                self._state = data
        except Exception:
            logger.warning("provider health state corrupt: %s", self.path, exc_info=True)

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            tmp.replace(self.path)
        except Exception:
            logger.debug("provider health state save failed", exc_info=True)

    def _entry(self, name: str) -> dict[str, Any]:
        return self._state.setdefault("providers", {}).setdefault(name, {"status": "unknown"})

    def record_failure(self, name: str, error_text: str) -> str:
        """Classify a call failure and persist health; returns kind in
        {banned, cooldown, ok}."""
        name = str(name or "")
        kind = classify_error(error_text)
        entry = self._entry(name)
        if kind == "balance":
            entry.update({
                "status": "banned",
                "reason": "balance_exhausted",
                "detected_at": _now_text(),
                "recheck_after": _now_text(time.time() + _BALANCE_RECHECK_SECONDS),
            })
            logger.warning("Provider %s banned (balance exhausted): %s", name, error_text[:120])
            self._save()
            return "banned"
        if kind == "rate_limited":
            entry.update({
                "status": "cooldown",
                "reason": "rate_limited",
                "cooldown_until": _now_text(time.time() + _RATE_COOLDOWN_SECONDS),
            })
            self._save()
            return "cooldown"
        return "ok"

    def is_banned(self, name: str) -> bool:
        name = str(name or "").lower()
        if name in _env_disabled_providers():
            return True
        entry = self._state.get("providers", {}).get(name) or {}
        status = str(entry.get("status") or "unknown")
        if status == "banned":
            # 余额拉黑带 1 小时复查窗：到期后放行一次重试，充值恢复可自动回归。
            recheck = _parse_text_time(str(entry.get("recheck_after") or ""))
            if recheck > time.time():
                return True
            return False
        if status == "cooldown":
            until = _parse_text_time(str(entry.get("cooldown_until") or ""))
            if until > time.time():
                return True
            entry["status"] = "unknown"
            entry["reason"] = ""
        return False

    def filter_providers(self, providers: list[dict]) -> list[dict]:
        """Drop providers that are banned (or env-disabled)."""
        return [p for p in providers if not self.is_banned(p.get("name", ""))]

    def banned_names(self) -> list[str]:
        return sorted(
            n for n in self._state.get("providers", {})
            if self.is_banned(n)
        )

    def mark_ok(self, name: str) -> None:
        """Clear a ban/cooldown after a successful call (provider recovered)."""
        entry = self._entry(name)
        entry["status"] = "ok"
        entry["reason"] = ""
        entry.pop("recheck_after", None)
        entry.pop("cooldown_until", None)
        entry.pop("detected_at", None)
        self._save()

    def update_balance(self, name: str, balance: float) -> None:
        entry = self._entry(name)
        entry["balance"] = round(float(balance), 4)
        entry["last_checked_at"] = _now_text()
        if balance <= 0:
            entry.update({
                "status": "banned",
                "reason": "balance_exhausted",
                "detected_at": _now_text(),
                "recheck_after": _now_text(time.time() + _BALANCE_RECHECK_SECONDS),
            })
            logger.warning("Provider %s banned by balance probe (balance=%s)", name, balance)
        else:
            entry["status"] = "ok"
            entry["reason"] = ""
        self._save()

    def needs_probe(self, name: str) -> bool:
        entry = self._state.get("providers", {}).get(name) or {}
        last = str(entry.get("last_checked_at") or "")
        if not last:
            return True
        return _parse_text_time(last) + _PROBE_TTL_SECONDS <= time.time()

    async def probe_balances(self, providers: list[dict]) -> dict[str, Any]:
        """Best-effort balance probe for providers with known endpoints."""
        results: dict[str, Any] = {}
        for provider in providers or []:
            name = str(provider.get("name") or "")
            key = str(provider.get("key") or "")
            base = str(provider.get("url") or "").rstrip("/")
            suffix = _BALANCE_PROBES.get(name)
            if not suffix or not key or not base:
                continue
            if not self.needs_probe(name):
                results[name] = self._state.get("providers", {}).get(name) or {}
                continue
            try:
                async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SECONDS) as client:
                    resp = await client.get(
                        base + suffix,
                        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                    )
                if resp.status_code != 200:
                    # 探测失败本身不做余额判定；交给调用链的错误驱动。
                    continue
                balance = _extract_balance(name, resp.json())
                if balance is not None:
                    self.update_balance(name, balance)
                    results[name] = self._state.get("providers", {}).get(name) or {}
            except Exception:
                logger.debug("provider %s balance probe failed", name, exc_info=True)
        return results

    def summary(self) -> dict[str, Any]:
        return {
            "disabled_providers": sorted(_env_disabled_providers()),
            "banned": self.banned_names(),
            "providers": dict(self._state.get("providers", {})),
        }
