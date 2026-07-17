"""Aerie · 云栖 v11.1 — 全局预算跟踪 (S2 M2.2).

跟踪全局 LLM 使用预算，支持日/周/月维度，三档预算状态：
  - normal   ( > 50% 剩余 )  — 正常路由
  - low      ( 20%-50% 剩余)  — 降级一档
  - critical ( < 20% 剩余 )  — 降到最低档

与 ProviderRouter 配合使用，根据预算状态动态选择 Provider。

预算数据持久化到 JSON 文件，支持重启后恢复。
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, List

logger = logging.getLogger(__name__)


# ── Budget Status ────────────────────────────────────

class BudgetStatus(str):
    NORMAL = "normal"
    LOW = "low"
    CRITICAL = "critical"


# ── Usage Record ─────────────────────────────────────

@dataclass
class PeriodUsage:
    """一个周期内的使用量."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    call_count: int = 0
    provider_usage: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # provider_usage: {provider_name: {input_tokens, output_tokens, cost, calls}}

    def add_call(
        self,
        provider_name: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        """记录一次调用."""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_tokens += input_tokens + output_tokens
        self.cost_usd += cost_usd
        self.call_count += 1

        if provider_name not in self.provider_usage:
            self.provider_usage[provider_name] = {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
                "call_count": 0,
            }
        p = self.provider_usage[provider_name]
        p["input_tokens"] += input_tokens
        p["output_tokens"] += output_tokens
        p["total_tokens"] += input_tokens + output_tokens
        p["cost_usd"] += cost_usd
        p["call_count"] += 1

    def reset(self) -> None:
        """重置周期数据."""
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.cost_usd = 0.0
        self.call_count = 0
        self.provider_usage.clear()


# ── Budget Config ────────────────────────────────────

@dataclass
class BudgetConfig:
    """预算配置."""
    # 月预算（美元），None 表示不限制
    monthly_budget_usd: Optional[float] = None
    # 周预算（美元），None 表示自动 = 月预算 / 4.3
    weekly_budget_usd: Optional[float] = None
    # 日预算（美元），None 表示自动 = 月预算 / 30
    daily_budget_usd: Optional[float] = None

    # 预算阈值（剩余百分比）
    low_threshold_pct: float = 0.50      # 低于 50% → low
    critical_threshold_pct: float = 0.20  # 低于 20% → critical

    # 预算周期锚点（每月几号重置月预算）
    monthly_reset_day: int = 1
    # 每周重置日（0=周一，6=周日）
    weekly_reset_day: int = 0  # 周一

    def compute_effective(self) -> Dict[str, Optional[float]]:
        """计算有效的日/周/月预算."""
        monthly = self.monthly_budget_usd
        weekly = self.weekly_budget_usd
        daily = self.daily_budget_usd

        if monthly is not None:
            if weekly is None:
                weekly = monthly / 4.3
            if daily is None:
                daily = monthly / 30.0

        return {
            "monthly": monthly,
            "weekly": weekly,
            "daily": daily,
        }


# ── Budget Tracker ───────────────────────────────────

class BudgetTracker:
    """
    全局预算跟踪器 (v11.1.0 S2 M2.2).

    跟踪日/周/月三个维度的使用量，根据剩余预算比例
    返回预算状态（normal/low/critical），供 ProviderRouter 动态路由。

    用法::

        tracker = BudgetTracker(config, data_file="budget.json")
        tracker.load()

        # 记录一次调用
        tracker.record_call(provider_name, input_tokens, output_tokens, cost)

        # 获取当前预算状态
        status = tracker.get_status()
        # → "normal" | "low" | "critical"

        # 获取剩余预算比例
        pct = tracker.get_remaining_pct()  # 0.0 - 1.0
    """

    def __init__(
        self,
        config: BudgetConfig | None = None,
        data_file: str = "budget_data.json",
    ) -> None:
        self.config = config or BudgetConfig()
        self.data_file = data_file

        # 各周期使用量
        self.daily = PeriodUsage()
        self.weekly = PeriodUsage()
        self.monthly = PeriodUsage()

        # 周期标识（用于判断是否需要重置）
        self._daily_key: str = ""
        self._weekly_key: str = ""
        self._monthly_key: str = ""

        self._init_period_keys()

    # ── Period Key Management ───────────────────────

    def _init_period_keys(self) -> None:
        """初始化周期标识."""
        now = datetime.now()
        self._daily_key = now.strftime("%Y-%m-%d")
        self._weekly_key = self._get_week_key(now)
        self._monthly_key = now.strftime("%Y-%m")

    def _get_week_key(self, dt: datetime) -> str:
        """获取周标识（ISO 周号）."""
        iso = dt.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"

    def _check_and_reset(self) -> None:
        """检查周期是否结束，结束则重置."""
        now = datetime.now()

        # 日周期
        new_daily = now.strftime("%Y-%m-%d")
        if new_daily != self._daily_key:
            self.daily.reset()
            self._daily_key = new_daily
            logger.info("Daily budget reset: %s", new_daily)

        # 周周期
        new_weekly = self._get_week_key(now)
        if new_weekly != self._weekly_key:
            self.weekly.reset()
            self._weekly_key = new_weekly
            logger.info("Weekly budget reset: %s", new_weekly)

        # 月周期
        new_monthly = now.strftime("%Y-%m")
        if new_monthly != self._monthly_key:
            self.monthly.reset()
            self._monthly_key = new_monthly
            logger.info("Monthly budget reset: %s", new_monthly)

    # ── Public API ──────────────────────────────────

    def record_call(
        self,
        provider_name: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        """记录一次 LLM 调用."""
        self._check_and_reset()

        self.daily.add_call(provider_name, input_tokens, output_tokens, cost_usd)
        self.weekly.add_call(provider_name, input_tokens, output_tokens, cost_usd)
        self.monthly.add_call(provider_name, input_tokens, output_tokens, cost_usd)

        self.save()

    def get_status(self) -> str:
        """
        获取当前预算状态.

        取最严格的周期状态（哪个周期最紧张，就用哪个的状态）。
        如果没有配置预算，返回 normal。
        """
        self._check_and_reset()

        effective = self.config.compute_effective()
        statuses = []

        if effective["daily"] is not None and effective["daily"] > 0:
            daily_remaining = max(0, 1 - self.daily.cost_usd / effective["daily"])
            statuses.append(self._pct_to_status(daily_remaining))

        if effective["weekly"] is not None and effective["weekly"] > 0:
            weekly_remaining = max(0, 1 - self.weekly.cost_usd / effective["weekly"])
            statuses.append(self._pct_to_status(weekly_remaining))

        if effective["monthly"] is not None and effective["monthly"] > 0:
            monthly_remaining = max(0, 1 - self.monthly.cost_usd / effective["monthly"])
            statuses.append(self._pct_to_status(monthly_remaining))

        if not statuses:
            return BudgetStatus.NORMAL

        # 取最严格的
        severity = {BudgetStatus.NORMAL: 0, BudgetStatus.LOW: 1, BudgetStatus.CRITICAL: 2}
        return max(statuses, key=lambda s: severity.get(s, 0))

    def get_remaining_pct(self) -> float:
        """
        获取剩余预算比例 (0.0 - 1.0).

        取最严格的周期的剩余比例。
        """
        self._check_and_reset()

        effective = self.config.compute_effective()
        remaining_pcts = []

        if effective["daily"] is not None and effective["daily"] > 0:
            daily_pct = max(0, 1 - self.daily.cost_usd / effective["daily"])
            remaining_pcts.append(daily_pct)

        if effective["weekly"] is not None and effective["weekly"] > 0:
            weekly_pct = max(0, 1 - self.weekly.cost_usd / effective["weekly"])
            remaining_pcts.append(weekly_pct)

        if effective["monthly"] is not None and effective["monthly"] > 0:
            monthly_pct = max(0, 1 - self.monthly.cost_usd / effective["monthly"])
            remaining_pcts.append(monthly_pct)

        if not remaining_pcts:
            return 1.0  # 无预算限制，视为 100%

        return min(remaining_pcts)

    def get_usage_summary(self) -> Dict[str, Any]:
        """获取使用量摘要（用于展示）."""
        self._check_and_reset()
        effective = self.config.compute_effective()

        return {
            "status": self.get_status(),
            "remaining_pct": round(self.get_remaining_pct() * 100, 1),
            "daily": {
                "used": round(self.daily.cost_usd, 4),
                "limit": round(effective["daily"], 4) if effective["daily"] else None,
                "remaining": round(effective["daily"] - self.daily.cost_usd, 4)
                if effective["daily"] else None,
                "tokens": self.daily.total_tokens,
                "calls": self.daily.call_count,
            },
            "weekly": {
                "used": round(self.weekly.cost_usd, 4),
                "limit": round(effective["weekly"], 4) if effective["weekly"] else None,
                "remaining": round(effective["weekly"] - self.weekly.cost_usd, 4)
                if effective["weekly"] else None,
                "tokens": self.weekly.total_tokens,
                "calls": self.weekly.call_count,
            },
            "monthly": {
                "used": round(self.monthly.cost_usd, 4),
                "limit": round(effective["monthly"], 4) if effective["monthly"] else None,
                "remaining": round(effective["monthly"] - self.monthly.cost_usd, 4)
                if effective["monthly"] else None,
                "tokens": self.monthly.total_tokens,
                "calls": self.monthly.call_count,
            },
            "providers": {
                name: {
                    "calls": data["call_count"],
                    "cost": round(data["cost_usd"], 4),
                    "tokens": data["total_tokens"],
                }
                for name, data in self.monthly.provider_usage.items()
            },
        }

    # ── Helpers ─────────────────────────────────────

    def _pct_to_status(self, remaining_pct: float) -> str:
        """剩余比例 → 预算状态."""
        if remaining_pct <= self.config.critical_threshold_pct:
            return BudgetStatus.CRITICAL
        elif remaining_pct <= self.config.low_threshold_pct:
            return BudgetStatus.LOW
        else:
            return BudgetStatus.NORMAL

    # ── Persistence ─────────────────────────────────

    def save(self) -> None:
        """保存预算数据到文件."""
        try:
            data = {
                "version": 1,
                "daily_key": self._daily_key,
                "weekly_key": self._weekly_key,
                "monthly_key": self._monthly_key,
                "daily": asdict(self.daily),
                "weekly": asdict(self.weekly),
                "monthly": asdict(self.monthly),
                "saved_at": datetime.now().isoformat(),
            }
            os.makedirs(os.path.dirname(self.data_file) or ".", exist_ok=True)
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            logger.exception("Failed to save budget data")

    def load(self) -> bool:
        """从文件加载预算数据."""
        try:
            if not os.path.exists(self.data_file):
                return False

            with open(self.data_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._daily_key = data.get("daily_key", self._daily_key)
            self._weekly_key = data.get("weekly_key", self._weekly_key)
            self._monthly_key = data.get("monthly_key", self._monthly_key)

            # 检查是否过期，过期则不加载（会自动重置）
            now = datetime.now()
            if data.get("daily_key") == now.strftime("%Y-%m-%d"):
                self._load_usage(self.daily, data.get("daily", {}))
            if data.get("weekly_key") == self._get_week_key(now):
                self._load_usage(self.weekly, data.get("weekly", {}))
            if data.get("monthly_key") == now.strftime("%Y-%m"):
                self._load_usage(self.monthly, data.get("monthly", {}))

            logger.info("Budget data loaded from %s", self.data_file)
            return True
        except Exception:
            logger.exception("Failed to load budget data")
            return False

    def _load_usage(self, usage: PeriodUsage, data: Dict[str, Any]) -> None:
        """从 dict 加载使用量."""
        usage.input_tokens = data.get("input_tokens", 0)
        usage.output_tokens = data.get("output_tokens", 0)
        usage.total_tokens = data.get("total_tokens", 0)
        usage.cost_usd = data.get("cost_usd", 0.0)
        usage.call_count = data.get("call_count", 0)
        usage.provider_usage = data.get("provider_usage", {})
