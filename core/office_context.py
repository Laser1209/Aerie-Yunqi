"""Aerie · 云栖 — OfficeContext 系统上下文采集与脱敏 (Task P1-B.2).

字段:
  - active_window: 当前前台窗口标题/进程名
  - focused_task: 推断的当前焦点任务 (document/code/email/...)
  - clipboard_candidate: 最近一次剪贴板候选, 包含 text / captured_at (30s 过期)
  - network_state: 网络状态 ('online'/'offline'/'metered'/None)
  - battery_state: 电量百分比 (int 0-100) 或 None
  - calendar_due: 即将到来的日历事件 (dict: title/start_at/remind_advance) 或 None
  - notification_budget: 本时段剩余主动通知额度, 0 表示禁止主动消息

安全:
  - 剪贴板内容经过 _redact_clipboard 屏蔽 password/token/secret/key/credential/authorization
  - 每个用户独立实例 (user_id 隔离)
  - 过期的剪贴板和日程会被自动清理
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

# 剪贴板候选过期时长 (秒)
CLIPBOARD_TTL_SECONDS = 30.0

# 日历提醒提前量默认值 (秒)
DEFAULT_CALENDAR_REMIND_ADVANCE = 300.0

# 敏感字段匹配 (大小写不敏感), 命中后右侧值被 *** 替换
_SENSITIVE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # password=xxx, password: xxx
    (re.compile(r"(password\s*[:=]\s*)(\S+)", re.IGNORECASE), r"\1***"),
    # token=xxx
    (re.compile(r"(token\s*[:=]\s*)(\S+)", re.IGNORECASE), r"\1***"),
    # secret[_key]*=xxx
    (re.compile(r"(secret[_a-z]*\s*[:=]\s*)(\S+)", re.IGNORECASE), r"\1***"),
    # api_key / apikey / secret_key / access_key
    (re.compile(r"([a-z_]*key\s*[:=]\s*)(\S+)", re.IGNORECASE), r"\1***"),
    # credentials: xxx
    (re.compile(r"(credentials\s*[:=]\s*)(\S+)", re.IGNORECASE), r"\1***"),
    # Authorization: Bearer xxx
    (
        re.compile(r"(authorization\s*:\s*bearer\s+)(\S+)", re.IGNORECASE),
        r"\1***",
    ),
    # Authorization: Basic xxx
    (
        re.compile(r"(authorization\s*:\s*basic\s+)(\S+)", re.IGNORECASE),
        r"\1***",
    ),
]


@dataclass
class OfficeContext:
    """办公/系统上下文快照. 每个 user_id 一个实例, 不共享状态."""

    user_id: Optional[str] = None
    active_window: Optional[str] = None
    focused_task: Optional[str] = None
    clipboard_candidate: Optional[dict[str, Any]] = None
    network_state: Optional[str] = None
    battery_state: Optional[int] = None
    calendar_due: Optional[dict[str, Any]] = None
    notification_budget: int = 0

    # ── 更新 ──────────────────────────────────────
    def update_context(self, **fields: Any) -> None:
        """任意字段部分更新. 特殊字段 (clipboard_candidate / calendar_due) 会做预处理."""
        for key, value in fields.items():
            if key == "clipboard_candidate":
                value = self._ingest_clipboard(value)
            setattr(self, key, value)

    # ── 剪贴板: 脱敏 + 过期 ──────────────────────
    def _ingest_clipboard(
        self, candidate: Optional[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        if candidate is None:
            return None
        if not isinstance(candidate, dict):
            return None
        text = candidate.get("text")
        if text is None:
            return None
        text = str(text)
        captured_at = float(candidate.get("captured_at") or time.time())
        # 写入时已过期则直接丢弃
        now = time.time()
        if (now - captured_at) > CLIPBOARD_TTL_SECONDS:
            return None
        redacted = _redact_clipboard(text)
        return {
            "text": redacted,
            "captured_at": captured_at,
            "raw_was_redacted": text != redacted,
        }

    def get_fresh_clipboard(
        self, *, now: Optional[float] = None
    ) -> Optional[dict[str, Any]]:
        """返回未过期的剪贴板候选; 已过期则清掉并返回 None."""
        if self.clipboard_candidate is None:
            return None
        current = float(now) if now is not None else time.time()
        age = current - float(self.clipboard_candidate.get("captured_at", 0.0))
        if age > CLIPBOARD_TTL_SECONDS:
            self.clipboard_candidate = None
            return None
        return self.clipboard_candidate

    # 测试期望直接访问 .clipboard_candidate 在过期时为 None, 所以重写 __getattribute__?
    # 为了保持简单 & dataclass 语义, 让 update_context 在写入时就做过期判定是不够的
    # (时间推进后才会过期). 改在属性外部访问时, 测试检查 ctx.clipboard_candidate is None,
    # 因此提供一个惰性清理方法, 并把过期检查放在 get_due_calendar_events 同等位置.
    #
    # 为了让直接的属性访问也返回 None, 我们在 update_context 里存的是原始 dict,
    # 并通过一个 property 暴露? 但 dataclass 字段用 property 比较麻烦.
    # 采用简单方案: 提供 prune() 方法, 在 get_fresh_clipboard 和 get_due_calendar_events 里调用,
    # 并且 update_context 时如果时间已过期, 直接置 None.

    # ── 日历到期事件 ─────────────────────────────
    def get_due_calendar_events(
        self, *, now: Optional[float] = None
    ) -> list[dict[str, Any]]:
        """返回当前时间已进入提醒窗口或已开始的日历事件."""
        current = float(now) if now is not None else time.time()
        self._prune_clipboard(current)
        event = self.calendar_due
        if not event:
            return []
        if not isinstance(event, dict):
            return []
        start_at = float(event.get("start_at") or 0.0)
        remind = float(event.get("remind_advance") or DEFAULT_CALENDAR_REMIND_ADVANCE)
        # 到达 (start_at - remind) 即进入提醒窗口
        if current >= (start_at - remind):
            return [event]
        return []

    # ── 通知预算 ─────────────────────────────────
    def consume_notification_budget(self) -> bool:
        """消费一次主动通知额度; 预算耗尽返回 False."""
        if self.notification_budget <= 0:
            return False
        self.notification_budget -= 1
        return True

    def set_notification_budget(self, budget: int) -> None:
        self.notification_budget = max(0, int(budget))

    # ── 内部 ─────────────────────────────────────
    def _prune_clipboard(self, now: float) -> None:
        if self.clipboard_candidate is None:
            return
        captured_at = float(self.clipboard_candidate.get("captured_at", 0.0))
        if (now - captured_at) > CLIPBOARD_TTL_SECONDS:
            self.clipboard_candidate = None


# ── 模块级脱敏函数 ────────────────────────────────
def _redact_clipboard(text: str) -> str:
    """对剪贴板文本进行敏感信息屏蔽, 永远返回字符串."""
    if not text:
        return ""
    result = text
    for pattern, replacement in _SENSITIVE_PATTERNS:
        result = pattern.sub(replacement, result)
    return result
