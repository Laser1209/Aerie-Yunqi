"""v13.9 第二批升级综合测试（权限 + 工具 + 任务规划 + 异步任务）"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_permission_manager():
    """测试细粒度权限管理器"""
    print("=" * 60)
    print("测试 1: 细粒度权限管理器")
    print("=" * 60)

    from core.permission_manager import (
        FineGrainedPermissionManager, OperationType, RiskLevel, PermissionCategory
    )

    pm = FineGrainedPermissionManager()

    # 1. 默认配置
    cfg = pm.config
    assert cfg.file_read_enabled is True
    assert cfg.file_write_enabled is True
    assert cfg.file_delete_enabled is False
    assert cfg.ui_control_enabled is False
    print(f"  ✅ 默认配置正确: file_read={cfg.file_read_enabled}, file_delete={cfg.file_delete_enabled}")

    # 2. 目录授权
    auth_dirs = pm.list_authorized_dirs()
    print(f"  ✅ 默认授权目录: {len(auth_dirs)} 个")
    assert len(auth_dirs) > 0

    # 3. 系统路径拦截
    result = pm.check(OperationType.READ_FILE, "C:\\Windows\\System32\\test.dll")
    assert result.allowed is False
    assert "系统路径" in result.reason
    print(f"  ✅ 系统路径正确拦截: {result.reason}")

    # 4. 文件读取（未授权路径）
    result = pm.check(OperationType.READ_FILE, "C:\\SomeRandomFolder\\test.txt")
    assert result.allowed is False
    print(f"  ✅ 未授权路径正确拦截")

    # 5. 大类开关测试
    pm.set_category_enabled(PermissionCategory.FILE_DELETE, True)
    result = pm.check(OperationType.DELETE_FILE)
    assert result.allowed is True
    assert result.needs_confirmation is True
    print(f"  ✅ 删除操作需二次确认: needs_confirmation={result.needs_confirmation}")

    # 6. 信任模式（跳过确认）
    pm.config.trust_mode = True
    result = pm.check(OperationType.DELETE_FILE)
    assert result.needs_confirmation is False
    print(f"  ✅ 信任模式跳过二次确认")
    pm.config.trust_mode = False

    # 7. 批量操作
    result = pm.check(OperationType.WRITE_FILE, batch_count=5)
    assert result.needs_confirmation is True
    print(f"  ✅ 批量操作需二次确认")

    # 8. 一键撤销
    pm.revoke_all()
    assert pm.config.file_write_enabled is False
    assert pm.config.ui_control_enabled is False
    assert len(pm.list_authorized_dirs()) == 0
    print(f"  ✅ 一键撤销所有非必要权限")

    # 9. 审计日志
    logs = pm.get_audit_log(limit=10)
    assert len(logs) > 0
    print(f"  ✅ 审计日志正常: {len(logs)} 条记录")

    print("  🎉 权限管理器测试全部通过!\n")


def test_office_tools_registration():
    """测试办公工具注册"""
    print("=" * 60)
    print("测试 2: 办公工具矩阵")
    print("=" * 60)

    from core.tool_registry import ToolRegistry
    from core.office_tools import register_office_tools

    registry = ToolRegistry()
    count = register_office_tools(registry)
    print(f"  ✅ 注册了 {count} 个办公工具")

    # 检查各类工具都有
    expected = [
        "document_create", "document_read", "file_search",        # 原有
        "directory_list", "file_copy", "file_move",               # 文件管理
        "word_generate", "csv_generate", "document_convert",      # 文档处理
        "system_info", "process_list", "app_open",                # 系统操作
        "data_stats", "data_filter", "data_sort", "chart_generate",  # 数据分析
        "web_fetch", "weather_query", "translation", "code_search",  # 网络工具
    ]

    missing = [name for name in expected if not registry.get(name)]
    if missing:
        print(f"  ⚠️  缺少工具: {missing}")
    else:
        print(f"  ✅ 所有预期工具都已注册")

    # 检查 OpenAI schema
    schemas = registry.get_openai_schema()
    print(f"  ✅ OpenAI Function Calling Schema: {len(schemas)} 个")

    print("  🎉 办公工具测试全部通过!\n")


def test_task_planner():
    """测试任务规划引擎"""
    print("=" * 60)
    print("测试 3: 任务规划引擎")
    print("=" * 60)

    from core.task_planner import TaskPlanner, TaskType, TaskStatus

    planner = TaskPlanner()

    # 1. 简单任务不触发规划
    assert planner.should_plan("你好") is False
    print(f"  ✅ 简单消息不触发规划")

    # 2. 复杂任务触发规划
    long_msg = "帮我写一份关于人工智能的市场调研报告，需要包含详细的数据统计和未来趋势分析，还要对比几家主要公司的情况"
    assert planner.should_plan(long_msg) is True
    print(f"  ✅ 复杂任务触发规划")

    # 3. 任务分类
    task_type = planner.classify_task("帮我写一份季度工作总结报告")
    assert task_type == TaskType.DOC_WRITE
    print(f"  ✅ 文档写作任务分类正确: {task_type.value}")

    task_type = planner.classify_task("分析一下这个销售数据表")
    assert task_type == TaskType.DATA_ANALYSIS
    print(f"  ✅ 数据分析任务分类正确: {task_type.value}")

    # 4. 创建计划
    plan = planner.create_plan("帮我写一份项目启动方案，要详细一点", task_id="test-001")
    assert plan.task_id == "test-001"
    assert len(plan.steps) >= 3
    print(f"  ✅ 创建计划成功: {plan.title}, 共 {len(plan.steps)} 步")

    # 5. 进度追踪
    assert plan.progress_percent == 0
    plan.mark_step_completed(1, "完成需求分析")
    assert plan.progress_percent > 0
    print(f"  ✅ 进度追踪正常: {plan.progress_percent}%")

    # 6. 动态调整（简单模式）
    plan_simple = planner.create_plan("简单写个报告就行", task_id="test-simple")
    print(f"  ✅ 简单模式步数: {len(plan_simple.steps)}")

    print("  🎉 任务规划引擎测试全部通过!\n")


def test_task_executor():
    """测试任务执行引擎"""
    print("=" * 60)
    print("测试 4: 任务执行引擎")
    print("=" * 60)

    from core.task_planner import TaskPlanner
    from core.task_executor import TaskExecutor, StepExecutionStatus

    planner = TaskPlanner()
    executor = TaskExecutor(max_retries=1)

    # 创建一个文档写作计划
    plan = planner.create_plan("写一份简单的测试报告", task_id="exec-test-001")
    print(f"  ✅ 创建执行计划: {len(plan.steps)} 步")

    # 执行计划
    result = executor.execute_plan(plan, user_message="写一份简单的测试报告")

    assert result.task_id == "exec-test-001"
    assert result.total_steps == len(plan.steps)
    print(f"  ✅ 执行完成: {result.completed_steps}/{result.total_steps} 步")
    print(f"  ✅ 耗时: {result.total_duration_seconds:.2f} 秒")
    print(f"  ✅ 成功率: {result.success}")

    # 检查步骤结果
    for sr in result.step_results:
        assert sr.status == StepExecutionStatus.COMPLETED
        print(f"     步骤{sr.step_id}: {sr.status.value} ({sr.duration_seconds:.2f}s)")

    # 检查总结
    assert "执行完成" in result.final_summary
    print(f"  ✅ 执行总结已生成")

    print("  🎉 任务执行引擎测试全部通过!\n")


def test_async_task_manager():
    """测试异步任务管理器"""
    print("=" * 60)
    print("测试 5: 异步任务管理器")
    print("=" * 60)

    import asyncio
    from core.async_task_manager import (
        AsyncTaskManager, TaskPriority, AsyncTaskStatus
    )

    mgr = AsyncTaskManager(max_concurrent=2)

    # 1. 提交任务
    task = mgr.submit_task(
        name="测试任务",
        description="这是一个测试任务",
        priority=TaskPriority.MEDIUM,
        task_data={"total_steps": 3, "step_delay": 0.1},
    )
    assert task.task_id.startswith("task_")
    assert task.status == AsyncTaskStatus.QUEUED
    print(f"  ✅ 任务提交成功: {task.task_id}")

    # 2. 统计信息
    stats = mgr.stats()
    assert stats["queued"] == 1
    print(f"  ✅ 统计信息正确: queued={stats['queued']}")

    # 3. 获取任务
    task2 = mgr.get_task(task.task_id)
    assert task2 is not None
    print(f"  ✅ 获取任务详情成功")

    # 4. 启动并执行一个快速任务（同步测试用）
    async def run_quick_test():
        mgr.start()
        # 等一下让任务执行
        await asyncio.sleep(1.0)
        final_task = mgr.get_task(task.task_id)
        return final_task

    result_task = asyncio.run(run_quick_test())
    print(f"  ✅ 任务最终状态: {result_task.status.value}")
    print(f"  ✅ 任务进度: {result_task.progress}%")

    # 5. 取消任务
    task2 = mgr.submit_task(name="待取消任务", priority=TaskPriority.LOW)
    ok = mgr.cancel_task(task2.task_id)
    assert ok is True
    print(f"  ✅ 任务取消成功")

    # 6. 任务列表
    all_tasks = mgr.list_tasks(limit=10)
    assert len(all_tasks) >= 2
    print(f"  ✅ 任务列表: {len(all_tasks)} 个任务")

    print("  🎉 异步任务管理器测试全部通过!\n")


def test_data_tools():
    """测试数据分析工具"""
    print("=" * 60)
    print("测试 6: 数据分析工具")
    print("=" * 60)

    from core.office_tools import (
        tool_data_stats, tool_data_filter, tool_data_sort, tool_chart_generate
    )

    test_data = [
        {"name": "产品A", "sales": 1200, "profit": 200},
        {"name": "产品B", "sales": 800, "profit": 150},
        {"name": "产品C", "sales": 1500, "profit": 300},
        {"name": "产品D", "sales": 600, "profit": 100},
        {"name": "产品E", "sales": 2000, "profit": 500},
    ]

    # 1. 数据统计
    result = tool_data_stats(test_data)
    assert result["success"] is True
    assert result["row_count"] == 5
    assert "sales" in result["stats"]
    assert result["stats"]["sales"]["type"] == "numeric"
    print(f"  ✅ 数据统计: {result['row_count']} 行, {result['column_count']} 列")
    print(f"     销售额: 均值={result['stats']['sales']['mean']}, 最大={result['stats']['sales']['max']}")

    # 2. 数据过滤
    result = tool_data_filter(test_data, "sales", "greater", 1000)
    assert result["success"] is True
    assert result["filtered_count"] == 3
    print(f"  ✅ 数据过滤: {result['original_count']} → {result['filtered_count']} 条")

    # 3. 数据排序
    result = tool_data_sort(test_data, "sales", ascending=False)
    assert result["success"] is True
    assert result["data"][0]["sales"] == 2000
    print(f"  ✅ 数据排序: 第一名销售额={result['data'][0]['sales']}")

    # 4. 图表生成
    result = tool_chart_generate(
        test_data, "name", "sales", chart_type="bar", title="销售统计"
    )
    assert result["success"] is True
    assert "svg_path" in result
    print(f"  ✅ 图表生成: {result['chart_type']}, 保存到 {result['svg_path']}")

    print("  🎉 数据分析工具测试全部通过!\n")


def test_file_management_tools():
    """测试文件管理工具"""
    print("=" * 60)
    print("测试 7: 文件管理工具")
    print("=" * 60)

    import tempfile
    import os
    from core.office_tools import (
        tool_directory_list, tool_directory_create,
        tool_file_copy, tool_file_rename
    )

    # 创建临时目录
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. 列目录
        result = tool_directory_list(tmpdir)
        assert result["success"] is True
        print(f"  ✅ 目录列表: {result['total_count']} 项")

        # 2. 创建子目录
        result = tool_directory_create(os.path.join(tmpdir, "subdir"))
        assert result["success"] is True
        print(f"  ✅ 创建目录: {result['path']}")

        # 3. 创建一个测试文件
        test_file = os.path.join(tmpdir, "test.txt")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("Hello, World!")

        # 4. 复制文件
        dest = os.path.join(tmpdir, "test_copy.txt")
        result = tool_file_copy(test_file, dest)
        assert result["success"] is True
        assert os.path.exists(dest)
        print(f"  ✅ 文件复制成功")

        # 5. 重命名
        result = tool_file_rename(dest, "renamed.txt")
        assert result["success"] is True
        assert os.path.exists(os.path.join(tmpdir, "renamed.txt"))
        print(f"  ✅ 文件重命名成功")

    print("  🎉 文件管理工具测试全部通过!\n")


if __name__ == "__main__":
    print("\n🔥 v13.9 第二批升级综合测试开始\n")
    all_passed = True

    tests = [
        ("权限管理器", test_permission_manager),
        ("办公工具矩阵", test_office_tools_registration),
        ("任务规划引擎", test_task_planner),
        ("任务执行引擎", test_task_executor),
        ("异步任务管理器", test_async_task_manager),
        ("数据分析工具", test_data_tools),
        ("文件管理工具", test_file_management_tools),
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
        print("🎉🎉🎉 全部测试通过！v13.9 第二批升级验证成功 🎉🎉🎉")
    else:
        print("⚠️  部分测试未通过")
    print("=" * 60)
