"""TDD tests for Task P1-B.3: ActionRegistry 工具注册与风险控制.

覆盖:
  - 注册并执行低风险工具 (open_url / show_status / adjust_volume / adjust_brightness)
  - 低风险工具直接执行, 返回结果
  - 注册高风险工具 (delete_file / send_message / modify_settings)
  - 高风险工具无 confirm_callback 时拒绝执行
  - 高风险工具提供 confirm_callback 返回 True 时执行
  - 未注册工具执行被拒绝
  - 每次执行写入 audit_log (action_id / risk_level / timestamp / result)
"""

from __future__ import annotations

import time

import pytest


# ── 低风险工具 ─────────────────────────────────────
def test_register_low_risk_action_and_execute():
    from core.action_registry import ActionRegistry, RiskLevel

    reg = ActionRegistry()
    called = []

    def handler(params):
        called.append(params)
        return {"opened": params.get("url")}

    reg.register("open_url", handler, RiskLevel.LOW, label="打开网址")
    result = reg.execute("open_url", {"url": "https://example.com"})
    assert result["status"] == "ok"
    assert result["opened"] == "https://example.com"
    assert called == [{"url": "https://example.com"}]


def test_builtin_low_risk_actions_exist():
    from core.action_registry import ActionRegistry

    reg = ActionRegistry()
    reg.register_builtin_low_risk()
    for action_id in ("open_url", "show_status", "adjust_volume", "adjust_brightness"):
        assert reg.is_registered(action_id), f"{action_id} should be built-in"


def test_low_risk_execute_directly_without_confirm():
    """低风险工具即使不传 confirm_callback 也应直接执行."""
    from core.action_registry import ActionRegistry, RiskLevel

    reg = ActionRegistry()

    def handler(params):
        return {"volume": params.get("level")}

    reg.register("adjust_volume", handler, RiskLevel.LOW, label="调整音量")
    result = reg.execute("adjust_volume", {"level": 50})
    assert result["status"] == "ok"


# ── 高风险工具 ─────────────────────────────────────
def test_high_risk_without_confirm_is_rejected():
    from core.action_registry import ActionRegistry, RiskLevel

    reg = ActionRegistry()

    def handler(params):
        return {"deleted": params.get("path")}

    reg.register("delete_file", handler, RiskLevel.HIGH, label="删除文件")
    result = reg.execute("delete_file", {"path": "C:/secret.txt"})
    assert result["status"] == "denied"
    assert "confirm" in result["reason"].lower() or "confirmation" in result["reason"].lower()


def test_high_risk_with_confirm_callback_returning_true_executes():
    from core.action_registry import ActionRegistry, RiskLevel

    reg = ActionRegistry()

    def handler(params):
        return {"sent_to": params.get("to")}

    def confirm(action_id, params):
        return True

    reg.register("send_message", handler, RiskLevel.HIGH, label="发送消息")
    result = reg.execute("send_message", {"to": "alice", "text": "hi"}, confirm_callback=confirm)
    assert result["status"] == "ok"
    assert result["sent_to"] == "alice"


def test_high_risk_with_confirm_returning_false_is_denied():
    from core.action_registry import ActionRegistry, RiskLevel

    reg = ActionRegistry()
    reg.register("modify_settings", lambda p: {"ok": True}, RiskLevel.HIGH, label="修改设置")
    result = reg.execute(
        "modify_settings",
        {"key": "theme", "value": "dark"},
        confirm_callback=lambda a, p: False,
    )
    assert result["status"] == "denied"


# ── 未注册工具 ─────────────────────────────────────
def test_unregistered_action_is_rejected():
    from core.action_registry import ActionRegistry

    reg = ActionRegistry()
    result = reg.execute("nonexistent_action", {})
    assert result["status"] == "unknown"


# ── MEDIUM 风险 ────────────────────────────────────
def test_medium_risk_requires_confirm():
    from core.action_registry import ActionRegistry, RiskLevel

    reg = ActionRegistry()
    reg.register(
        "clipboard_write",
        lambda p: {"wrote": True},
        RiskLevel.MEDIUM,
        label="写入剪贴板",
    )
    # 无 confirm: 拒绝
    result_no = reg.execute("clipboard_write", {"text": "x"})
    assert result_no["status"] == "denied"
    # confirm=True: 放行
    result_ok = reg.execute(
        "clipboard_write", {"text": "x"}, confirm_callback=lambda a, p: True
    )
    assert result_ok["status"] == "ok"


# ── 审计日志 ───────────────────────────────────────
def test_audit_log_records_every_execution():
    from core.action_registry import ActionRegistry, RiskLevel

    reg = ActionRegistry()
    reg.register("show_status", lambda p: {"battery": 80}, RiskLevel.LOW, label="显示状态")
    reg.execute("show_status", {})
    reg.execute("show_status", {})
    assert len(reg.audit_log) == 2
    entry = reg.audit_log[0]
    assert entry["action_id"] == "show_status"
    assert entry["risk_level"] == "LOW"
    assert entry["timestamp"] > 0
    assert entry["result"]["status"] == "ok"


def test_audit_log_records_denied_executions():
    from core.action_registry import ActionRegistry, RiskLevel

    reg = ActionRegistry()
    reg.register("delete_file", lambda p: {}, RiskLevel.HIGH, label="删除文件")
    reg.execute("delete_file", {"path": "/"})
    assert len(reg.audit_log) == 1
    assert reg.audit_log[0]["result"]["status"] == "denied"


def test_audit_log_timestamp_monotonic():
    from core.action_registry import ActionRegistry, RiskLevel

    reg = ActionRegistry()
    reg.register("open_url", lambda p: {}, RiskLevel.LOW, label="open")
    reg.execute("open_url", {"url": "https://a"})
    time.sleep(0.01)
    reg.execute("open_url", {"url": "https://b"})
    assert reg.audit_log[1]["timestamp"] >= reg.audit_log[0]["timestamp"]


# ── duplicate register ────────────────────────────
def test_register_duplicate_raises():
    from core.action_registry import ActionRegistry, RiskLevel

    reg = ActionRegistry()
    reg.register("open_url", lambda p: {}, RiskLevel.LOW, label="open")
    with pytest.raises(ValueError):
        reg.register("open_url", lambda p: {}, RiskLevel.LOW, label="open")
