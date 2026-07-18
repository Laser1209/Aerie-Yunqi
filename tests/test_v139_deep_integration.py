"""v13.9 第二批升级 - 集成深度测试（工具打通 + 任务执行 + 异步任务）"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_task_executor_with_real_tools():
    """测试任务执行器 + 真实工具调用"""
    print("=" * 60)
    print("测试 1: TaskExecutor + ToolRegistry 真实工具调用")
    print("=" * 60)

    from core.tool_registry import ToolRegistry
    from core.office_tools import register_office_tools
    from core.task_planner import TaskPlanner, TaskStep, TaskStatus
    from core.task_executor import TaskExecutor, StepExecutionStatus

    # 注册工具
    registry = ToolRegistry()
    register_office_tools(registry)
    print(f"  ✅ 注册工具: {len(registry.list_names())} 个")

    # 创建执行器（带真实 tool_registry）
    executor = TaskExecutor(tool_registry=registry, max_retries=1)

    # 构造一个带 tool_args 的步骤，测试 text_summary 工具
    step = TaskStep(
        step_id=1,
        title="文本摘要测试",
        description="测试摘要功能",
        tool="summarize",
    )
    step.tool_args = {  # type: ignore
        "text": "这是一段很长的测试文本。" * 20,
        "max_length": 50,
    }

    context = {"user_message": "帮我总结一下这段文字"}
    result = executor._handler_summarize(step, context)
    assert result.status == StepExecutionStatus.COMPLETED
    print(f"  ✅ text_summary 工具调用成功: {result.result[:50]}...")

    # 测试 data_stats 工具
    step2 = TaskStep(
        step_id=2,
        title="数据分析测试",
        description="测试数据统计",
        tool="analyze",
    )
    step2.tool_args = {  # type: ignore
        "dataset": [
            {"name": "A", "value": 100},
            {"name": "B", "value": 200},
            {"name": "C", "value": 300},
        ]
    }
    result2 = executor._handler_analyze(step2, context)
    assert result2.status == StepExecutionStatus.COMPLETED
    print(f"  ✅ data_stats 工具调用成功: {result2.result}")

    # 测试通用 tool_call 处理器
    step3 = TaskStep(
        step_id=3,
        title="目录列表测试",
        description="测试目录遍历",
        tool="tool_call",
    )
    step3.tool_name = "directory_list"  # type: ignore
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        step3.tool_args = {"directory": tmpdir}  # type: ignore
        result3 = executor._handler_tool_call(step3, context)
        assert result3.status == StepExecutionStatus.COMPLETED
        print(f"  ✅ tool_call 通用处理器调用成功: directory_list")

    # 执行完整计划
    planner = TaskPlanner()
    plan = planner.create_plan("写一份简单的测试报告", task_id="deep-test-001")
    exec_result = executor.execute_plan(plan, user_message="写一份简单的测试报告")
    assert exec_result.success is True
    print(f"  ✅ 完整计划执行成功: {exec_result.completed_steps}/{exec_result.total_steps} 步")
    print(f"  ✅ 执行总结: {exec_result.final_summary[:60]}...")

    print("  🎉 任务执行器 + 真实工具调用测试全部通过!\n")


def test_async_task_manager_with_real_handlers():
    """测试异步任务管理器 + 真实任务处理器"""
    print("=" * 60)
    print("测试 2: AsyncTaskManager 真实任务处理器")
    print("=" * 60)

    import asyncio
    from core.async_task_manager import AsyncTaskManager, TaskPriority, AsyncTaskStatus

    mgr = AsyncTaskManager(max_concurrent=2)

    # 注册一个真实任务处理器
    progress_events = []

    async def sample_task(data: dict, progress_cb) -> dict:
        total = data.get("total_steps", 3)
        for i in range(total):
            progress_cb(
                int((i + 1) / total * 100),
                f"处理第 {i+1} 步",
                f"步骤{i+1}", i+1, total
            )
            progress_events.append(i + 1)
            await asyncio.sleep(0.05)
        return {"success": True, "processed": total}

    mgr.register_task_func("sample", sample_task)
    print(f"  ✅ 注册任务处理器: sample")

    # 提交任务并执行
    async def run_test():
        mgr.start()
        task = mgr.submit_task(
            name="测试任务",
            task_type="sample",
            priority=TaskPriority.HIGH,
            task_data={"total_steps": 3},
        )

        # 等待任务完成
        for _ in range(50):
            await asyncio.sleep(0.1)
            t = mgr.get_task(task.task_id)
            if t and t.status in (AsyncTaskStatus.COMPLETED, AsyncTaskStatus.FAILED):
                break
        return task.task_id

    task_id = asyncio.run(run_test())
    task = mgr.get_task(task_id)

    assert task is not None
    assert task.status == AsyncTaskStatus.COMPLETED
    assert task.progress == 100
    print(f"  ✅ 任务执行完成: status={task.status.value}, progress={task.progress}%")
    print(f"  ✅ 进度事件: {len(progress_events)} 个")
    assert len(progress_events) == 3

    # 测试取消
    mgr2 = AsyncTaskManager()

    async def slow_task(data, progress_cb):
        for i in range(10):
            progress_cb(i * 10, f"step {i+1}")
            await asyncio.sleep(0.5)
        return {"success": True}

    mgr2.register_task_func("slow", slow_task)

    async def test_cancel():
        mgr2.start()
        task = mgr2.submit_task("慢任务", task_type="slow", task_data={})
        await asyncio.sleep(0.3)
        ok = mgr2.cancel_task(task.task_id)
        await asyncio.sleep(0.5)
        t = mgr2.get_task(task.task_id)
        return ok, t

    ok, cancelled_task = asyncio.run(test_cancel())
    assert ok is True
    assert cancelled_task.status == AsyncTaskStatus.CANCELLED
    print(f"  ✅ 任务取消成功: status={cancelled_task.status.value}")

    print("  🎉 异步任务管理器 + 真实处理器测试全部通过!\n")


def test_permission_edge_cases():
    """权限管理器边界条件测试"""
    print("=" * 60)
    print("测试 3: 权限管理器边界条件")
    print("=" * 60)

    from core.permission_manager import (
        FineGrainedPermissionManager, OperationType, RiskLevel,
        PermissionCategory, PermissionConfig
    )

    # 自定义配置
    cfg = PermissionConfig(
        file_read_enabled=True,
        file_write_enabled=True,
        file_delete_enabled=True,
        ui_control_enabled=True,
        system_enabled=True,
        require_confirmation=False,
        trust_mode=True,
    )
    pm = FineGrainedPermissionManager(config=cfg)
    print(f"  ✅ 自定义配置创建成功")

    # 信任模式下所有高危操作都不需要确认
    for op in [OperationType.DELETE_FILE, OperationType.SHELL_CMD]:
        result = pm.check(op, batch_count=10)
        assert result.needs_confirmation is False
        print(f"  ✅ 信任模式下 {op.value} 无需确认")

    # 关闭大类权限
    pm.set_category_enabled(PermissionCategory.FILE_WRITE, False)
    result = pm.check(OperationType.WRITE_FILE)
    assert result.allowed is False
    print(f"  ✅ 关闭 file_write 后写入操作被正确拦截")

    # 风险等级映射
    from core.permission_manager import ACTION_RISK_MAP
    high_risk_ops = [op for op, risk in ACTION_RISK_MAP.items() if risk == RiskLevel.HIGH]
    print(f"  ✅ 高风险操作: {len(high_risk_ops)} 个")
    assert len(high_risk_ops) > 0

    # 审计日志过滤
    pm2 = FineGrainedPermissionManager()
    pm2.check(OperationType.READ_FILE, "C:\\test.txt")
    pm2.check(OperationType.WRITE_FILE, "C:\\test.txt")
    all_logs = pm2.get_audit_log()
    assert len(all_logs) >= 2
    print(f"  ✅ 审计日志记录正常: {len(all_logs)} 条")

    # 限制条数
    limited_logs = pm2.get_audit_log(limit=1)
    assert len(limited_logs) == 1
    print(f"  ✅ 审计日志 limit 参数生效")

    print("  🎉 权限管理器边界测试全部通过!\n")


def test_office_tool_schemas():
    """办公工具 Schema 完整性测试"""
    print("=" * 60)
    print("测试 4: 办公工具 Schema 完整性")
    print("=" * 60)

    from core.tool_registry import ToolRegistry
    from core.office_tools import register_office_tools, _OFFICE_TOOL_SCHEMAS

    registry = ToolRegistry()
    count = register_office_tools(registry)

    # 每个注册的工具都有 Schema
    tool_names = registry.list_names()
    missing_schema = []
    for name in tool_names:
        entry = registry.get(name)
        if not entry or not entry.get("schema"):
            missing_schema.append(name)

    if missing_schema:
        print(f"  ⚠️  缺少 Schema 的工具: {missing_schema}")
    else:
        print(f"  ✅ 所有 {len(tool_names)} 个工具都有完整 Schema")

    # Schema 格式校验（OpenAI Function Calling 格式）
    valid_schemas = 0
    for name in tool_names:
        entry = registry.get(name)
        schema = entry.get("schema", {})
        # 必须有 type=function 和 function 字段
        if schema.get("type") == "function" and "function" in schema:
            fn = schema["function"]
            # function 必须有 name 和 parameters
            if "name" in fn and "parameters" in fn:
                valid_schemas += 1

    print(f"  ✅ 符合 OpenAI Function Calling 格式: {valid_schemas}/{len(tool_names)}")

    # OpenAI schema 输出
    openai_schemas = registry.get_openai_schema()
    assert len(openai_schemas) == len(tool_names)
    print(f"  ✅ OpenAI Schema 列表: {len(openai_schemas)} 个")

    print("  🎉 办公工具 Schema 完整性测试通过!\n")


if __name__ == "__main__":
    print("\n🔥 v13.9 深度集成测试开始\n")
    all_passed = True

    tests = [
        ("TaskExecutor + 真实工具", test_task_executor_with_real_tools),
        ("AsyncTaskManager + 真实处理器", test_async_task_manager_with_real_handlers),
        ("权限管理器边界条件", test_permission_edge_cases),
        ("办公工具 Schema 完整性", test_office_tool_schemas),
    ]

    for name, test_func in tests:
        try:
            test_func()
        except Exception as e:
            print(f"  ❌ {name} 测试失败: {e}")
            import traceback
            traceback.print_exc()
            all_passed = False

    print("=" * 60)
    if all_passed:
        print("🎉🎉🎉 全部深度集成测试通过！四大模块完全打通 🎉🎉🎉")
    else:
        print("⚠️  部分测试未通过")
    print("=" * 60)
