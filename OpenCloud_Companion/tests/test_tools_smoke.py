"""
Tools 烟雾测试 - 逐个调用 14 个 tool 验证基础功能

用法：
    cd e:\Agent_reply\OpenCloud_Companion
    python tests\test_tools_smoke.py [--skip-network]

输出：
    每个工具一行结果：✅ OK / ❌ FAIL / ⚠️ PARTIAL
    最后打印统计 + 失败明细
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

# 添加项目根到 path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 加载 .env
try:
    import dotenv
    dotenv.load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from tools.registry import ToolRegistry
from tools.file_ops import ReadFileTool, WriteFileTool, ListDirTool, SearchFilesTool
from tools.system_ops import OpenAppTool, SystemStatusTool
from tools.web_ops import WebSearchTool, WeatherTool, FetchUrlTool
from tools.todo_manager import TodoCreateTool, TodoListTool, TodoCompleteTool, TodoDeleteTool


# ===== 测试用例 =====

# write_file 用 Desktop 路径（白名单内）
TEST_WRITE_PATH = str(Path.home() / "Desktop" / "opencloud_test_write.txt")
TEST_WRITE_CONTENT = "hello from opencloud companion smoke test"

TOOL_TESTS = [
    # (tool_name, kwargs, expected_success, 描述)
    ("read_file", {"path": str(PROJECT_ROOT / "config" / "settings.yaml"), "max_lines": 5}, True, "读取 settings.yaml"),
    ("write_file", {"path": TEST_WRITE_PATH, "content": TEST_WRITE_CONTENT}, True, "写入 Desktop 测试文件"),
    ("list_dir", {"path": str(PROJECT_ROOT / "tools")}, True, "列出 tools 目录"),
    ("search_files", {"keyword": "tool", "directory": str(PROJECT_ROOT), "max_results": 5}, True, "搜索 'tool' 文件"),
    ("open_app", {"app_name": "记事本"}, True, "打开记事本"),  # 会真打开
    ("system_status", {}, True, "查询系统状态"),
    ("web_search", {"query": "今天AI新闻", "max_results": 3}, None, "DuckDuckGo 搜索（依赖网络）"),
    ("get_weather", {"city": "北京"}, None, "wttr.in 天气查询（依赖网络）"),
    ("fetch_url", {"url": "https://www.baidu.com"}, None, "抓取 baidu.com（依赖网络）"),
    ("todo_create", {"content": "smoke_test_todo"}, True, "创建待办"),
    ("todo_list", {"status": "all"}, True, "列出待办"),
    ("todo_complete", {"todo_id": 1}, None, "完成待办 ID=1（可能不存在）"),
    ("todo_delete", {"todo_id": 1}, None, "删除待办 ID=1（可能不存在）"),
]


async def run_one(registry: ToolRegistry, name: str, kwargs: dict, expected: bool | None, desc: str) -> tuple:
    """运行单个工具测试，返回 (status, name, info)"""
    t0 = time.time()
    try:
        ok, output = await registry.execute(name, **kwargs)
        elapsed = time.time() - t0
        if expected is None:
            # 网络相关，不强求成功
            status = "✅ OK" if ok else "⚠️ NETWORK_FAIL"
        elif expected:
            status = "✅ OK" if ok else f"❌ FAIL: {output[:100]}"
        else:
            status = "✅ OK" if not ok else f"⚠️ UNEXPECTED_OK: {output[:100]}"
        info = f"{status} ({elapsed:.2f}s) {desc}"
        if not ok and expected is None:
            info += f" | {output[:80]}"
        return (status.startswith("✅"), name, info)
    except Exception as e:
        elapsed = time.time() - t0
        return (False, name, f"❌ EXCEPTION ({elapsed:.2f}s) {desc}: {type(e).__name__}: {str(e)[:80]}")


async def main():
    print("=" * 70)
    print("OpenCloud Companion — Tools 烟雾测试")
    print("=" * 70)

    registry = ToolRegistry()
    registry.register_all([
        ReadFileTool(), WriteFileTool(), ListDirTool(), SearchFilesTool(),
        OpenAppTool(), SystemStatusTool(),
        WebSearchTool(), WeatherTool(), FetchUrlTool(),
        TodoCreateTool(), TodoListTool(), TodoCompleteTool(), TodoDeleteTool(),
    ])

    print(f"已注册 {registry.count} 个工具: {', '.join(registry.tool_names)}\n")

    tests = list(TOOL_TESTS)
    if args.skip_network:
        tests = [t for t in tests if t[0] not in ("web_search", "get_weather", "fetch_url")]
        print("[--skip-network] 已跳过网络相关工具\n")
    if args.only:
        wanted = set(args.only.split(","))
        tests = [t for t in tests if t[0] in wanted]
        print(f"[--only] 只跑: {', '.join(wanted)}\n")

    passed, failed, partial = 0, 0, 0
    failures = []

    for name, kwargs, expected, desc in tests:
        ok, _, info = await run_one(registry, name, kwargs, expected, desc)
        # 只输出 INFO/WARNING/ERROR 级别的实际 log（去除 DEBUG 噪音）
        print(info, flush=True)
        if ok:
            passed += 1
        elif "NETWORK_FAIL" in info:
            partial += 1
        else:
            failed += 1
            failures.append(info)

    print("\n" + "=" * 70)
    print(f"统计: ✅ {passed} 通过 | ⚠️ {partial} 网络依赖(可接受) | ❌ {failed} 失败")
    print("=" * 70)

    if failures:
        print("\n失败明细:")
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
        sys.exit(rc)
    except KeyboardInterrupt:
        print("\n已中断")
        sys.exit(130)
