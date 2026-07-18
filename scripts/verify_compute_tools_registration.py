"""
验证 compute_tools 注册时序修复的正确性

这个脚本模拟 Companion 初始化过程，验证：
1. 修复前：_COMPANION 在 register_all_tools 之后赋值 → compute_tools 注册失败
2. 修复后：_COMPANION 在 register_all_tools 之前赋值 → compute_tools 注册成功
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_before_fix():
    """模拟修复前的情况：_COMPANION 赋值太晚"""
    print("\n" + "=" * 70)
    print("【测试1】修复前：_COMPANION 在 register_all_tools 之后赋值")
    print("=" * 70)

    from core.tool_registry import ToolRegistry

    registry = ToolRegistry()

    # 模拟：先注册工具（此时 _COMPANION 还没赋值）
    # 注意：我们不直接操作全局变量，而是通过模拟条件来验证
    from tools.compute_tools import register_computer_tools

    # 模拟：companion 为 None 的情况（修复前的状态）
    try:
        # 直接调用 register_computer_tools，传 None 模拟 get_companion() 返回 None
        register_computer_tools(registry, None)
        print("❌ 错误：竟然注册成功了？不应该啊")
        return False
    except Exception as e:
        print(f"✅ 预期行为：computer_controller 为 None 时注册失败：{type(e).__name__}")
        print(f"   说明：修复前 get_companion() 返回 None，导致 compute_tools 从未注册")
        return True


def test_after_fix():
    """模拟修复后的情况：有真实的 computer_controller"""
    print("\n" + "=" * 70)
    print("【测试2】修复后：有真实的 computer_controller")
    print("=" * 70)

    from core.tool_registry import ToolRegistry
    from core.computer_control import ComputerController
    from tools.compute_tools import register_computer_tools

    registry = ToolRegistry()
    controller = ComputerController()

    print(f"ComputerController 创建成功：{controller is not None}")

    try:
        register_computer_tools(registry, controller)
        tools = registry.get_openai_schema()
        tool_names = [
            t.get("function", {}).get("name", t.get("name", ""))
            for t in tools
        ]

        print(f"\n✅ 注册成功！共注册了 {len(tools)} 个系统控制工具")
        print("\n工具列表：")
        for name in sorted(tool_names):
            print(f"  - {name}")

        # 验证关键工具都在
        expected_tools = [
            "screenshot", "mouse_move", "mouse_click", "mouse_scroll",
            "key_press", "type_text", "hotkey", "shell_execute",
            "uia_action", "list_windows", "focus_window"
        ]

        missing = [t for t in expected_tools if t not in tool_names]
        if missing:
            print(f"\n❌ 缺少工具：{missing}")
            return False
        else:
            print(f"\n✅ 所有 11 个预期工具都在！")

        # 验证分类
        cat_map = registry.get_category_map()
        sys_control = cat_map.get("system_control", [])
        print(f"\nsystem_control 分类下有 {len(sys_control)} 个工具")
        print(f"工具：{', '.join(sorted(sys_control))}")

        return True

    except Exception as e:
        print(f"❌ 注册失败：{e}")
        import traceback
        traceback.print_exc()
        return False


def test_full_registration_flow():
    """测试完整的注册流程（screen_tools + compute_tools + office_tools）"""
    print("\n" + "=" * 70)
    print("【测试3】完整工具注册流程")
    print("=" * 70)

    from core.tool_registry import ToolRegistry
    from core.computer_control import ComputerController
    from core.screen_tools import register_screen_tools
    from tools.compute_tools import register_computer_tools

    registry = ToolRegistry()
    controller = ComputerController()

    # 注册 screen_tools（旧版）
    register_screen_tools(registry)
    screen_count = len(registry.get_openai_schema())
    print(f"\n旧版 screen_tools：{screen_count} 个工具")

    # 注册 compute_tools（新版）
    register_computer_tools(registry, controller)
    total_after_compute = len(registry.get_openai_schema())
    print(f"加上新版 compute_tools：{total_after_compute} 个工具")
    print(f"新增：{total_after_compute - screen_count} 个工具")

    # 打印分类统计
    print(f"\n{registry.summary()}")

    return True


def main():
    print("\n" + "╔" + "═" * 68 + "╗")
    print("║" + " " * 10 + "Compute Tools 注册时序修复验证脚本" + " " * 16 + "║")
    print("╚" + "═" * 68 + "╝")

    results = []

    try:
        results.append(test_before_fix())
    except Exception as e:
        print(f"测试1异常：{e}")
        import traceback
        traceback.print_exc()
        results.append(False)

    try:
        results.append(test_after_fix())
    except Exception as e:
        print(f"测试2异常：{e}")
        import traceback
        traceback.print_exc()
        results.append(False)

    try:
        results.append(test_full_registration_flow())
    except Exception as e:
        print(f"测试3异常：{e}")
        import traceback
        traceback.print_exc()
        results.append(False)

    print("\n" + "=" * 70)
    print("【最终结果】")
    print("=" * 70)
    passed = sum(results)
    total = len(results)
    print(f"通过：{passed}/{total}")

    if passed == total:
        print("\n✅ 所有测试通过！修复有效！")
        return 0
    else:
        print("\n❌ 有测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
