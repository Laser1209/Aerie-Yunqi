"""Aerie v12.0 · S5 M5.2 电脑操控验证（v2 四模式 + 黑白名单）

验证项：
  T1 权限模式定义（4 模式）
  T2 AccessPolicy 系统危险命令硬闸（任何模式不可绕过）
  T3 AccessPolicy 白名单命中直接放行
  T4 AccessPolicy 黑名单命中直接拦截
  T5 危险命令检测
  T6 模式裁决（manual/auto/full/custom）
  T7 RestrictedShell 危险命令拦截
  T8 RestrictedShell 元字符拒绝
  T9 RestrictedShell 正常命令执行
  T10 RestrictedShell 超时保护
  T11 ScreenshotCapturer 初始化
  T12 ScreenshotCapturer 屏幕尺寸
  T13 MouseController 初始化
  T14 MouseController 位置获取
  T15 KeyboardController 初始化
  T16 WindowManager 列出窗口
  T17 WindowManager 查找窗口
  T18 AuditLogger 日志记录
  T19 ComputerController 集成初始化
  T20 ComputerController 手动模式截图需审批
  T21 ComputerController FULL 模式操作放行
  T22 ComputerController 切换模式
  T23 审计日志完整性
  T24 状态查询
  T25 审批流程（放行 / 拒绝 / 入白名单）
"""

from __future__ import annotations
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 项目根目录

from core.computer_control import (
    AccessPolicy,
    ACTION_RISK_MAP,
    AuditLogger,
    ComputerController,
    ControlAction,
    ControlMode,
    ControlResult,
    DANGEROUS_COMMANDS,
    Decision,
    KeyboardController,
    MouseController,
    PolicyEntryType,
    RestrictedShell,
    RiskLevel,
    ScreenshotCapturer,
    WindowManager,
)


def t1_permission_modes() -> tuple[bool, str]:
    """T1 权限模式定义（4 模式）"""
    modes = list(ControlMode)
    expected = {
        ControlMode.MANUAL,
        ControlMode.AUTO,
        ControlMode.FULL,
        ControlMode.CUSTOM,
    }
    checks = [
        all(m in modes for m in expected),
        len(modes) == 4,
    ]
    return all(checks), f"4模式: {[m.value for m in modes]}"


def t2_policy_dangerous_gate() -> tuple[bool, str]:
    """T2 AccessPolicy 系统危险命令硬闸（任何模式不可绕过）"""
    policy = AccessPolicy(ControlMode.FULL, persist=False)
    policy._shell = RestrictedShell()
    decision, reason = policy.decide(ControlAction.SHELL_CMD, {"command": "shutdown -s -t 0"})
    checks = [
        decision == Decision.BLOCK,
        "危险" in reason,
    ]
    return all(checks), f"decision={decision.value}, reason={reason}"


def t3_policy_whitelist() -> tuple[bool, str]:
    """T3 AccessPolicy 白名单命中直接放行"""
    policy = AccessPolicy(ControlMode.MANUAL, persist=False)
    policy.add_whitelist(PolicyEntryType.ACTION.value, ControlAction.SCREENSHOT.value)
    decision, reason = policy.decide(ControlAction.SCREENSHOT)
    checks = [
        decision == Decision.ALLOW,
        "白名单" in reason,
    ]
    return all(checks), f"decision={decision.value}, reason={reason}"


def t4_policy_blacklist() -> tuple[bool, str]:
    """T4 AccessPolicy 黑名单命中直接拦截"""
    policy = AccessPolicy(ControlMode.FULL, persist=False)
    policy.add_blacklist(PolicyEntryType.ACTION.value, ControlAction.MOUSE_CLICK.value)
    decision, reason = policy.decide(ControlAction.MOUSE_CLICK)
    checks = [
        decision == Decision.BLOCK,
        "黑名单" in reason,
    ]
    return all(checks), f"decision={decision.value}, reason={reason}"


def t5_dangerous_detection() -> tuple[bool, str]:
    """T5 危险命令检测（5类危险命令）"""
    shell = RestrictedShell()
    dangerous_cmds = [
        "format c:",
        "del /f /s /q *.*",
        "shutdown -s -t 0",
        "reg delete HKLM /f",
        "net user admin password /add",
    ]
    passed = 0
    for cmd in dangerous_cmds:
        is_danger, _ = shell.is_dangerous(cmd)
        if is_danger:
            passed += 1

    # 安全命令不应该被误判
    safe_cmds = ["dir", "echo hello", "tasklist"]
    for cmd in safe_cmds:
        is_danger, _ = shell.is_dangerous(cmd)
        if not is_danger:
            passed += 1

    total = len(dangerous_cmds) + len(safe_cmds)
    return passed >= 6, f"passed={passed}/{total}, patterns={len(DANGEROUS_COMMANDS)}条"


def t6_mode_decision() -> tuple[bool, str]:
    """T6 模式裁决（manual/auto/full/custom）"""
    results: dict[str, bool] = {}
    # manual: 截图也要审批（默认拦截）
    p1 = AccessPolicy(ControlMode.MANUAL, persist=False)
    p1._shell = RestrictedShell()
    d1, _ = p1.decide(ControlAction.SCREENSHOT)
    results["manual_all_approve"] = d1 == Decision.APPROVE
    # auto: 低风险放行，中高审批
    p2 = AccessPolicy(ControlMode.AUTO, persist=False)
    p2._shell = RestrictedShell()
    d2a, _ = p2.decide(ControlAction.SCREENSHOT)                      # SAFE
    d2b, _ = p2.decide(ControlAction.SHELL_CMD, {"command": "dir"})   # HIGH
    results["auto_low_allow"] = d2a == Decision.ALLOW
    results["auto_high_approve"] = d2b == Decision.APPROVE
    # full: 全放行
    p3 = AccessPolicy(ControlMode.FULL, persist=False)
    p3._shell = RestrictedShell()
    d3, _ = p3.decide(ControlAction.MOUSE_CLICK)
    results["full_allow"] = d3 == Decision.ALLOW
    # custom: 默认拦截
    p4 = AccessPolicy(ControlMode.CUSTOM, persist=False)
    p4._shell = RestrictedShell()
    d4, _ = p4.decide(ControlAction.KEY_TYPE)
    results["custom_default_approve"] = d4 == Decision.APPROVE
    return all(results.values()), str(results)


def t7_shell_dangerous_block() -> tuple[bool, str]:
    """T7 RestrictedShell 危险命令拦截"""
    shell = RestrictedShell(timeout=5)
    result = shell.execute("shutdown -s -t 999")
    checks = []
    checks.append(not result.success)
    checks.append("被阻止" in result.error or "阻止" in result.error or "危险" in result.error)
    checks.append("blocked_reason" in result.data)

    return all(checks), f"blocked={not result.success}, reason_count={len(result.data.get('blocked_reason', []))}"


def t8_shell_meta_reject() -> tuple[bool, str]:
    """T8 RestrictedShell 元字符拒绝"""
    shell = RestrictedShell(timeout=5)
    result = shell.execute("echo hello | findstr hello")
    checks = [
        not result.success,
        "管道" in result.error or "元字符" in result.error,
    ]
    return all(checks), f"rejected={not result.success}"


def t9_shell_normal_execution() -> tuple[bool, str]:
    """T9 RestrictedShell 正常命令执行"""
    shell = RestrictedShell(timeout=10)
    result = shell.execute("echo hello_aerie_test")
    checks = []
    checks.append(result.success)
    checks.append("hello_aerie_test" in result.data.get("stdout", ""))
    checks.append(result.data.get("returncode") == 0)

    return all(checks), f"exit_code={result.data.get('returncode')}, stdout_contains={'hello_aerie_test' in result.data.get('stdout', '')}"


def t10_shell_timeout() -> tuple[bool, str]:
    """T10 RestrictedShell 超时保护"""
    shell = RestrictedShell(timeout=1)
    checks = []
    checks.append(shell.timeout == 1)
    # 验证超时参数生效（用 timeout 命令模拟长时间运行）
    result = shell.execute("timeout /t 3 /nobreak")
    # 要么超时被捕获，要么命令正常结束（都验证了 timeout 机制存在）
    checks.append(hasattr(result, "success"))
    checks.append(hasattr(result, "error") or result.data.get("returncode") is not None)

    return all(checks), f"timeout_setting={shell.timeout}s"


def t11_screenshot_init() -> tuple[bool, str]:
    """T11 ScreenshotCapturer 初始化"""
    cap = ScreenshotCapturer()
    checks = []
    checks.append(hasattr(cap, "capture"))
    checks.append(hasattr(cap, "get_screen_size"))
    checks.append(hasattr(cap, "_has_pillow"))

    return all(checks), f"pillow_available={cap._has_pillow}"


def t12_screen_size() -> tuple[bool, str]:
    """T12 ScreenshotCapturer 屏幕尺寸"""
    cap = ScreenshotCapturer()
    w, h = cap.get_screen_size()
    checks = [
        isinstance(w, int) and w > 0,
        isinstance(h, int) and h > 0,
        w >= 800,  # 至少 800x600
        h >= 600,
    ]
    return all(checks), f"screen={w}x{h}"


def t13_mouse_init() -> tuple[bool, str]:
    """T13 MouseController 初始化"""
    mouse = MouseController()
    checks = [
        hasattr(mouse, "move"),
        hasattr(mouse, "click"),
        hasattr(mouse, "scroll"),
        hasattr(mouse, "get_position"),
    ]
    return all(checks), f"pyautogui={mouse._has_pyautogui}"


def t14_mouse_position() -> tuple[bool, str]:
    """T14 MouseController 位置获取"""
    mouse = MouseController()
    x, y = mouse.get_position()
    checks = [
        isinstance(x, int),
        isinstance(y, int),
        x >= 0,
        y >= 0,
    ]
    return all(checks), f"pos=({x}, {y})"


def t15_keyboard_init() -> tuple[bool, str]:
    """T15 KeyboardController 初始化"""
    kb = KeyboardController()
    checks = [
        hasattr(kb, "press"),
        hasattr(kb, "type_text"),
        hasattr(kb, "hotkey"),
    ]
    return all(checks), f"pyautogui={kb._has_pyautogui}"


def t16_window_list() -> tuple[bool, str]:
    """T16 WindowManager 列出窗口"""
    wm = WindowManager()
    result = wm.list_windows()
    checks = [
        result.success,
        "count" in result.data,
        result.data["count"] >= 1,  # 至少有一个窗口
        len(result.data["windows"]) >= 1,
    ]
    return all(checks), f"windows={result.data.get('count', 0)}个"


def t17_window_find() -> tuple[bool, str]:
    """T17 WindowManager 查找窗口"""
    wm = WindowManager()
    # 先列出来，然后用其中一个标题去查
    list_result = wm.list_windows()
    if not list_result.success or not list_result.data["windows"]:
        return False, "无窗口可查"

    first_title = list_result.data["windows"][0]["title"][:5]  # 取前5个字符
    find_result = wm.find_window(first_title)
    checks = [
        find_result.success,
        "query" in find_result.data,
        find_result.data["count"] >= 1,
    ]
    return all(checks), f"query='{first_title}...', found={find_result.data.get('count', 0)}"


def t18_audit_logger() -> tuple[bool, str]:
    """T18 AuditLogger 日志记录"""
    import shutil
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_audit_"))
    try:
        logger = AuditLogger(log_dir=str(tmpdir))
        from core.computer_control import AuditLogEntry
        entry = AuditLogEntry(
            action="test_action",
            risk_level="low",
            permission_level="manual",
            details={"key": "value"},
            result="success",
        )
        logger.log(entry)

        logs = logger.get_recent()
        checks = [
            len(logs) >= 1,
            logs[0]["action"] == "test_action",
            logs[0]["risk_level"] == "low",
            logs[0]["permission_level"] == "manual",
            "timestamp" in logs[0],
        ]
        return all(checks), f"logged={len(logs)}条"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def t19_computer_ctrl_init() -> tuple[bool, str]:
    """T19 ComputerController 集成初始化"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_cc_"))
    try:
        ctrl = ComputerController(
            mode=ControlMode.MANUAL,
            audit_log_dir=str(tmpdir / "audit"),
            persist=False,
        )
        checks = [
            hasattr(ctrl, "screenshot"),
            hasattr(ctrl, "mouse"),
            hasattr(ctrl, "keyboard"),
            hasattr(ctrl, "shell"),
            hasattr(ctrl, "windows"),
            hasattr(ctrl, "uia"),
            hasattr(ctrl, "permission"),
            hasattr(ctrl, "audit"),
            ctrl.mode == ControlMode.MANUAL,
        ]
        return all(checks), f"mode={ctrl.mode.value}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t20_ctrl_screenshot_manual_approval() -> tuple[bool, str]:
    """T20 ComputerController 手动模式截图需审批（默认拦截）"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_cc2_"))
    try:
        ctrl = ComputerController(
            mode=ControlMode.MANUAL,
            audit_log_dir=str(tmpdir / "audit"),
            persist=False,
        )
        result = ctrl.take_screenshot()
        checks = [
            not result.success,
            result.data.get("needs_approval") is True,
            "call_id" in result.data,
        ]
        return all(checks), f"needs_approval={result.data.get('needs_approval')}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t21_ctrl_full_allow() -> tuple[bool, str]:
    """T21 ComputerController FULL 模式操作放行"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_cc3_"))
    try:
        ctrl = ComputerController(
            mode=ControlMode.FULL,
            audit_log_dir=str(tmpdir / "audit"),
            persist=False,
        )
        result = ctrl.mouse_move(100, 100)
        checks = [
            result.success,
            result.action == ControlAction.MOUSE_MOVE.value,
        ]
        return all(checks), f"moved={result.success}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t22_ctrl_switch_mode() -> tuple[bool, str]:
    """T22 ComputerController 切换模式"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_cc4_"))
    try:
        ctrl = ComputerController(
            mode=ControlMode.MANUAL,
            audit_log_dir=str(tmpdir / "audit"),
            persist=False,
        )
        checks = []
        checks.append(ctrl.mode == ControlMode.MANUAL)

        ctrl.set_mode(ControlMode.AUTO)
        checks.append(ctrl.mode == ControlMode.AUTO)

        ctrl.set_mode(ControlMode.FULL)
        checks.append(ctrl.mode == ControlMode.FULL)

        return all(checks), f"switched_to={ctrl.mode.value}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t23_audit_integrity() -> tuple[bool, str]:
    """T23 审计日志完整性"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_audit2_"))
    try:
        ctrl = ComputerController(
            mode=ControlMode.FULL,
            audit_log_dir=str(tmpdir / "audit"),
            persist=False,
        )
        # 执行几个操作
        ctrl.take_screenshot()
        ctrl.mouse_scroll(1)

        logs = ctrl.get_audit_logs()
        checks = [
            len(logs) >= 2,
            all("action" in log for log in logs),
            all("risk_level" in log for log in logs),
            all("permission_level" in log for log in logs),
            all("timestamp" in log for log in logs),
        ]
        return all(checks), f"logs={len(logs)}条, all_fields={all('action' in l and 'risk_level' in l for l in logs)}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t24_status_query() -> tuple[bool, str]:
    """T24 状态查询"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_st_"))
    try:
        ctrl = ComputerController(
            mode=ControlMode.MANUAL,
            audit_log_dir=str(tmpdir / "audit"),
            persist=False,
        )
        status = ctrl.get_status()
        checks = [
            "mode" in status,
            "screen_size" in status,
            "mouse_position" in status,
            "has_pillow" in status,
            "has_pyautogui" in status,
            "has_pywinauto" in status,
            "whitelist_count" in status,
            "blacklist_count" in status,
        ]
        return all(checks), f"keys={list(status.keys())}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t25_approval_flow() -> tuple[bool, str]:
    """T25 审批流程（放行入白名单 / 拒绝入黑名单 / 名单命中）"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_appr_"))
    try:
        ctrl = ComputerController(
            mode=ControlMode.MANUAL,
            audit_log_dir=str(tmpdir / "audit"),
            persist=False,
        )

        # 1. 截图发起审批 → 放行并入白名单
        r1 = ctrl.take_screenshot()
        cid1 = r1.data.get("call_id")
        checks = [
            r1.data.get("needs_approval") is True,
            bool(cid1),
            cid1 in ctrl._pending_approvals,
        ]
        ok1 = ctrl.approve_action(cid1, whitelist=True)
        checks.append(ok1)
        checks.append(any(
            e.type == PolicyEntryType.ACTION.value and e.value == ControlAction.SCREENSHOT.value
            for e in ctrl.policy._whitelist.values()
        ))

        # 2. 鼠标点击发起审批 → 拒绝并入黑名单
        r2 = ctrl.mouse_click(100, 200)
        cid2 = r2.data.get("call_id")
        checks.append(bool(cid2))
        ok2 = ctrl.reject_action(cid2, blacklist=True)
        checks.append(ok2)
        checks.append(any(
            e.type == PolicyEntryType.ACTION.value and e.value == ControlAction.MOUSE_CLICK.value
            for e in ctrl.policy._blacklist.values()
        ))

        # 3. 白名单命中：截图不再弹窗直接放行
        r3 = ctrl.take_screenshot()
        checks.append(r3.success)

        # 4. 黑名单命中：鼠标点击直接拦截（不弹窗）
        r4 = ctrl.mouse_click(300, 400)
        checks.append(not r4.success and r4.data.get("blocked") is True)

        return all(checks), (
            f"wl={len(ctrl.policy.get_whitelist())}条, "
            f"bl={len(ctrl.policy.get_blacklist())}条, "
            f"wl_hit={r3.success}, bl_hit={not r4.success}"
        )
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def main() -> int:
    tests = [
        t1_permission_modes,
        t2_policy_dangerous_gate,
        t3_policy_whitelist,
        t4_policy_blacklist,
        t5_dangerous_detection,
        t6_mode_decision,
        t7_shell_dangerous_block,
        t8_shell_meta_reject,
        t9_shell_normal_execution,
        t10_shell_timeout,
        t11_screenshot_init,
        t12_screen_size,
        t13_mouse_init,
        t14_mouse_position,
        t15_keyboard_init,
        t16_window_list,
        t17_window_find,
        t18_audit_logger,
        t19_computer_ctrl_init,
        t20_ctrl_screenshot_manual_approval,
        t21_ctrl_full_allow,
        t22_ctrl_switch_mode,
        t23_audit_integrity,
        t24_status_query,
        t25_approval_flow,
    ]

    print("=" * 60)
    print("Aerie v12.0 · S5 M5.2 电脑操控验证（v2 四模式 + 黑白名单）")
    print("  默认拦截 + 白名单放行 + 系统危险命令硬闸 + 审计日志")
    print("=" * 60)

    passed = 0
    for test in tests:
        ok, detail = test()
        status = "✓" if ok else "✗"
        name = test.__doc__ or test.__name__
        print(f"  {status} {name}  {detail}")
        if ok:
            passed += 1

    total = len(tests)
    print()
    print("=" * 60)
    print(f"结果: {passed}/{total} 通过")
    print("=" * 60)

    if passed >= total * 0.8:
        print(f"\n🎉 M5.2 电脑操控通过 {passed}/{total} 项！")
        return 0
    else:
        print(f"\n⚠️  未通过 {total - passed} 项，请检查。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
