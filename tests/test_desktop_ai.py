import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.computer_control import ComputerController, ControlAction, ControlMode, ControlResult, KeyboardController, WindowManager
from core.desktop_ai import DesktopAITask, load_apps
from core.tool_registry import ToolRegistry
from tools.compute_tools import register_computer_tools


@pytest.fixture
def controller(tmp_path):
    return ComputerController(mode=ControlMode.FULL, persist=False, audit_log_dir=str(tmp_path / "audit"))


@pytest.fixture
def task(controller, tmp_path, monkeypatch):
    apps = {"claude": {"exe": "", "args": [], "window_title": "Claude", "input_hint": "Message", "send_keys": ["enter"], "ready_timeout": 0.01}}
    monkeypatch.setattr(controller.windows, "wait_for_window", Mock(return_value=ControlResult(True, "window_info", {"windows": [{"hwnd": 42, "x": 0, "y": 0, "width": 20, "height": 20}]})))
    monkeypatch.setattr(controller.windows, "focus_window", Mock(return_value=ControlResult(True, "window_focus")))
    monkeypatch.setattr(controller.uia, "focus_input", Mock(return_value=ControlResult(True, "uia_action")))
    monkeypatch.setattr(controller.keyboard, "type_text_reliable", Mock(return_value=ControlResult(True, "key_type")))
    monkeypatch.setattr(controller.keyboard, "hotkey", Mock(return_value=ControlResult(True, "key_press")))
    return DesktopAITask(controller, apps=apps, output_dir=tmp_path / "outputs")


def test_registry_and_tools(controller):
    assert set(load_apps()) == {"claude", "kimi", "trae_cn", "marvis", "workbuddy", "reasonix", "opencode", "trae_work_cn", "stitch"}
    registry = ToolRegistry()
    register_computer_tools(registry, controller)
    assert {"desktop_app_launch", "desktop_app_send", "desktop_app_read", "desktop_app_run", "screenshot", "list_windows", "focus_window"} <= set(registry.get_tools_by_category("system_control"))


def test_window_timeout_and_ambiguity(monkeypatch):
    windows = WindowManager()
    monkeypatch.setattr(windows, "find_window", lambda title: ControlResult(True, "window_info", {"count": 0}))
    assert "超时" in windows.wait_for_window("Claude", 0).error
    monkeypatch.setattr(windows, "find_window", lambda title: ControlResult(True, "window_info", {"count": 2}))
    assert "多个" in windows.wait_for_window("Claude", 100).error


def test_clipboard_chinese(monkeypatch):
    clipboard = SimpleNamespace(OpenClipboard=Mock(), EmptyClipboard=Mock(), SetClipboardText=Mock(), CloseClipboard=Mock(), CF_UNICODETEXT=13)
    monkeypatch.setitem(sys.modules, "win32clipboard", clipboard)
    keyboard = KeyboardController()
    keyboard.hotkey = Mock(return_value=ControlResult(True, "key_press"))
    assert keyboard.type_text_reliable("你好，世界\n第二行").success
    clipboard.SetClipboardText.assert_called_once_with("你好，世界\n第二行", 13)
    clipboard.CloseClipboard.assert_called_once()
    keyboard.hotkey.assert_called_once_with("ctrl", "v")


def test_launch_permission_and_audit(controller, monkeypatch):
    launch = Mock(return_value=ControlResult(True, "app_launch"))
    monkeypatch.setattr(controller, "_launch_app", launch)
    controller.set_mode(ControlMode.MANUAL)
    pending = controller.app_launch("sample.exe")
    assert pending.data["needs_approval"]
    launch.assert_not_called()
    controller.policy.add_blacklist("action", "app_launch")
    assert controller.app_launch("sample.exe").data["blocked"]
    assert all(row["action"] == "app_launch" and row["risk_level"] == "low" for row in controller.get_audit_logs())


def test_launch_low_auto_and_replay(controller, monkeypatch):
    launch = Mock(return_value=ControlResult(True, "app_launch"))
    monkeypatch.setattr(controller, "_launch_app", launch)
    controller.set_mode(ControlMode.AUTO)
    assert controller.app_launch("sample.exe").success
    assert controller._execute_action(ControlAction.APP_LAUNCH, {"exe": "sample.exe", "args": []}, user_approved=True).success
    assert launch.call_count == 2


def test_send_denied_stops_before_input(task):
    task.controller.policy.add_blacklist("action", "uia_action")
    assert not asyncio.run(task.send("claude", "中文任务"))["success"]
    task.controller.keyboard.type_text_reliable.assert_not_called()
    task.controller.keyboard.hotkey.assert_not_called()


def test_send_chinese_audit_redacts(task):
    assert asyncio.run(task.send("claude", "机密中文任务"))["success"]
    task.controller.keyboard.type_text_reliable.assert_called_once_with("机密中文任务")
    assert "机密中文任务" not in task.controller.audit.log_file.read_text(encoding="utf-8")


def test_uia_read_failure_and_artifact(task, monkeypatch):
    monkeypatch.setattr(task.controller.uia, "read_text", lambda handle: ControlResult(False, "uia_action", error="不可读"))
    assert asyncio.run(task.read_output("claude"))["error"] == "不可读"
    monkeypatch.setattr(task.controller.uia, "read_text", lambda handle: ControlResult(True, "uia_action", {"text": "答案：2"}))
    result = asyncio.run(task.read_output("claude"))
    assert result["success"]
    from pathlib import Path
    assert Path(result["artifacts"][0]).read_text(encoding="utf-8") == "答案：2"


def test_unconfigured_launch_does_not_send(task):
    result = asyncio.run(task.run("claude", "1+1=?"))
    assert not result["success"]
    task.controller.keyboard.hotkey.assert_not_called()


def test_run_timeout_without_output(task, monkeypatch):
    monkeypatch.setattr(task.controller, "app_launch", lambda *args: ControlResult(True, "app_launch"))
    monkeypatch.setattr(task.controller.uia, "read_text", lambda handle: ControlResult(True, "uia_action", {"text": "原有文本"}))
    result = asyncio.run(task.run("claude", "任务", timeout=0.02, quiet_period=0.01))
    assert not result["success"] and "超时" in result["error"]


def test_screenshot_failure(task, monkeypatch):
    monkeypatch.setattr(task.controller, "take_screenshot", lambda region: ControlResult(False, "screenshot", error="截图失败"))
    assert asyncio.run(task.read_output("claude", "screenshot"))["error"] == "截图失败"


def test_run_returns_changed_stable_output(task, monkeypatch):
    monkeypatch.setattr(task.controller, "app_launch", lambda *args: ControlResult(True, "app_launch"))
    values = iter(["原有文本", "答案：2", "答案：2"])
    monkeypatch.setattr(task.controller.uia, "read_text", lambda handle: ControlResult(True, "uia_action", {"text": next(values)}))
    result = asyncio.run(task.run("claude", "1+1=?", timeout=3, quiet_period=0.01))
    assert result["success"] and result["text"] == "答案：2"
    assert result["completion"] == "window_quiet"
    task.controller.keyboard.hotkey.assert_called_once()


def test_screenshot_visual_artifacts(task, monkeypatch, tmp_path):
    from PIL import Image
    from unittest.mock import AsyncMock
    image = tmp_path / "capture.png"
    Image.new("RGB", (20, 20)).save(image)
    monkeypatch.setattr(task.controller, "take_screenshot", lambda region: ControlResult(True, "screenshot", {"path": str(image)}))
    task.analyzer = SimpleNamespace(describe=AsyncMock(return_value="可见答案：2"))
    result = asyncio.run(task.read_output("claude", "screenshot"))
    assert result["success"] and len(result["artifacts"]) == 2
    task.analyzer.describe = AsyncMock(return_value="")
    failed = asyncio.run(task.read_output("claude", "screenshot"))
    assert not failed["success"] and failed["artifacts"][0].endswith(".png")


def test_launch_process_arguments_and_missing(controller, monkeypatch, tmp_path):
    executable = tmp_path / "Desktop App.exe"
    executable.touch()
    process = Mock(return_value=SimpleNamespace(pid=123))
    monkeypatch.setattr("subprocess.Popen", process)
    assert controller.app_launch(str(executable), ["--profile", "中文路径"]).success
    process.assert_called_once_with([str(executable.resolve()), "--profile", "中文路径"], shell=False)
    assert not controller.app_launch(str(tmp_path / "missing.exe")).success
    assert process.call_count == 1


def test_text_approval_keeps_payload(controller, monkeypatch):
    controller.set_mode(ControlMode.MANUAL)
    pending = controller.type_text("审批后中文")
    entry = controller._pending_approvals[pending.data["call_id"]]
    assert entry["params"]["text"] == "审批后中文"
    keyboard = Mock(return_value=ControlResult(True, "key_type"))
    monkeypatch.setattr(controller.keyboard, "type_text_reliable", keyboard)
    controller._execute_action(ControlAction.KEY_TYPE, entry["params"], user_approved=True)
    keyboard.assert_called_once_with("审批后中文")
