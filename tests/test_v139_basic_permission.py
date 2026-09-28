"""v13.9 快速验证脚本：BASIC 模式 + 权限共享单例"""
import asyncio
import sys
sys.path.insert(0, "e:\\Agent_reply")

from core.computer_control import ControlMode


def test_permission_singleton(monkeypatch, tmp_path):
    """验证办公工具和 companion 共享同一个 ComputerController 实例。"""
    import core.companion as companion
    import core.office_tools as office_tools
    from core.computer_control import ComputerController

    # 构造 Companion 会发布全局实例；测试结束后恢复两个入口并禁止策略落盘。
    monkeypatch.setattr(companion, "_COMPANION", None)
    monkeypatch.setattr(
        companion,
        "ComputerController",
        lambda: ComputerController(persist=False, audit_log_dir=str(tmp_path / "audit")),
    )
    comp = companion.Companion()

    ctrl_tools = office_tools._get_controller()
    assert comp.computer_controller is ctrl_tools
    comp.computer_controller.set_mode(ControlMode.FULL)
    assert ctrl_tools.mode == ControlMode.FULL
    ctrl_tools.set_mode(ControlMode.MANUAL)
    assert comp.computer_controller.mode == ControlMode.MANUAL


def test_basic_mode_context():
    """验证 BASIC 模式的上下文构建。"""
    print("=" * 60)
    print("测试 2: BASIC 模式上下文构建")
    print("=" * 60)

    from core.context_builder import ContextBuilder
    from core.persona_hub import get_persona_manager

    mgr = get_persona_manager()
    persona = mgr.get_active_persona()

    builder = ContextBuilder()

    # FULL 模式
    msgs_full = builder.build(
        user_id=0,
        route_mode="FULL",
        history_msgs=[{"role": "user", "content": "你好"}] * 10,
        current_msg="测试消息",
    )
    print(f"  FULL 模式消息数: {len(msgs_full)}（system + 8 history + user）")

    # BASIC 模式
    msgs_basic = builder.build(
        user_id=0,
        route_mode="BASIC",
        history_msgs=[{"role": "user", "content": "你好"}] * 10,
        current_msg="测试消息",
    )
    print(f"  BASIC 模式消息数: {len(msgs_basic)}（system + user）")

    assert len(msgs_basic) == 2, f"BASIC 应该是 2 条消息，实际 {len(msgs_basic)}"
    print("  ✅ BASIC 模式不携带历史消息")

    print()


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__]))
