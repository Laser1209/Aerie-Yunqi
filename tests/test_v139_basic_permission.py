"""v13.9 快速验证脚本：BASIC 模式 + 权限共享单例"""
import asyncio
import sys
sys.path.insert(0, "e:\\Agent_reply")

from core.computer_control import PermissionLevel


def test_permission_singleton():
    """验证 screen_tools 和 companion 共享同一个 ComputerController 实例。"""
    print("=" * 60)
    print("测试 1: 权限共享单例验证")
    print("=" * 60)

    from core.companion import Companion
    comp = Companion()

    from core.screen_tools import get_controller
    ctrl_tools = get_controller()

    print(f"  companion.computer_controller id: {id(comp.computer_controller)}")
    print(f"  screen_tools.get_controller() id: {id(ctrl_tools)}")

    assert comp.computer_controller is ctrl_tools, "两个实例不相同！"
    print("  ✅ screen_tools 和 companion 共享同一实例")

    # 测试权限设置是否双向同步
    comp.computer_controller.set_permission(PermissionLevel.FULL)
    assert ctrl_tools.permission_level == PermissionLevel.FULL
    print("  ✅ companion 设置 FULL → screen_tools 同步生效")

    ctrl_tools.set_permission(PermissionLevel.VIEW_ONLY)
    assert comp.computer_controller.permission_level == PermissionLevel.VIEW_ONLY
    print("  ✅ screen_tools 设置 VIEW_ONLY → companion 同步生效")

    print()


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
    try:
        test_permission_singleton()
        test_basic_mode_context()
        print("=" * 60)
        print("🎉 所有测试通过！")
        print("=" * 60)
    except AssertionError as e:
        print(f"❌ 测试失败: {e}")
        sys.exit(1)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"❌ 测试异常: {e}")
        sys.exit(1)
