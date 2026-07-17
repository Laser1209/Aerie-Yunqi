"""Aerie · 云栖 v11.2 — S3 M3.3 工具调用隔离验证.

验证工具安全分级、参数校验、超时保护、审计日志、审批流程等。
用法: python e2e_s3_tool_isolation_verify.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _check(label: str, ok: bool, detail: str = "") -> None:
    sym = "✓" if ok else "✗"
    print(f"  {sym} {label}  {detail}")


# ─────────────────────────────────────────────────────
# T1 · 安全分级
# ─────────────────────────────────────────────────────

async def test_t1_safety_levels() -> bool:
    """验证工具安全分级."""
    print("\n[T1] 工具安全分级")
    all_ok = True

    from core.tool_isolation import (
        ToolSecurityPolicy, ToolSafetyLevel, ToolIsolator, IsolationConfig,
    )

    policy = ToolSecurityPolicy()

    # 1.1 注册不同等级的工具
    policy.register_tool("get_weather", ToolSafetyLevel.SAFE)
    policy.register_tool("save_note", ToolSafetyLevel.CAUTIOUS)
    policy.register_tool("delete_file", ToolSafetyLevel.DANGEROUS)

    # 1.2 获取等级
    ok = policy.get_safety_level("get_weather") == ToolSafetyLevel.SAFE
    _check("1.1 get_weather = SAFE", ok)
    if not ok:
        all_ok = False

    ok = policy.get_safety_level("save_note") == ToolSafetyLevel.CAUTIOUS
    _check("1.2 save_note = CAUTIOUS", ok)
    if not ok:
        all_ok = False

    ok = policy.get_safety_level("delete_file") == ToolSafetyLevel.DANGEROUS
    _check("1.3 delete_file = DANGEROUS", ok)
    if not ok:
        all_ok = False

    # 1.4 未注册的工具默认为 CAUTIOUS
    ok = policy.get_safety_level("unknown_tool") == ToolSafetyLevel.CAUTIOUS
    _check("1.4 未注册工具默认 CAUTIOUS", ok)
    if not ok:
        all_ok = False

    # 1.5 审批需求
    config = IsolationConfig(auto_approve_safe=True, auto_approve_cautious=False)
    policy2 = ToolSecurityPolicy(config=config)
    ok = policy2.needs_approval(ToolSafetyLevel.SAFE) is False
    _check("1.5a SAFE 无需审批", ok)
    if not ok:
        all_ok = False

    ok = policy2.needs_approval(ToolSafetyLevel.CAUTIOUS) is True
    _check("1.5b CAUTIOUS 需要审批", ok)
    if not ok:
        all_ok = False

    ok = policy2.needs_approval(ToolSafetyLevel.DANGEROUS) is True
    _check("1.5c DANGEROUS 必须审批", ok)
    if not ok:
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# T2 · 参数校验
# ─────────────────────────────────────────────────────

async def test_t2_param_validation() -> bool:
    """验证参数校验."""
    print("\n[T2] 参数校验")
    all_ok = True

    from core.tool_isolation import validate_arguments

    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 1, "maxLength": 50},
            "age": {"type": "integer", "minimum": 0, "maximum": 150},
            "role": {"type": "string", "enum": ["admin", "user", "guest"]},
            "tags": {"type": "array"},
        },
        "required": ["name", "age"],
    }

    # 2.1 合法参数
    valid, errors = validate_arguments(
        {"name": "Alice", "age": 25, "role": "user"},
        {"parameters": schema},
    )
    ok = valid and len(errors) == 0
    _check("2.1 合法参数通过校验", ok, f"errors={errors}")
    if not ok:
        all_ok = False

    # 2.2 缺少必填字段
    valid, errors = validate_arguments({"name": "Alice"}, {"parameters": schema})
    ok = not valid and any("age" in e for e in errors)
    _check("2.2 缺少必填字段被拦截", ok, f"errors={errors}")
    if not ok:
        all_ok = False

    # 2.3 类型错误
    valid, errors = validate_arguments(
        {"name": "Alice", "age": "不是数字"},
        {"parameters": schema},
    )
    ok = not valid and any("age" in e and "integer" in e for e in errors)
    _check("2.3 类型错误被拦截", ok, f"errors={errors}")
    if not ok:
        all_ok = False

    # 2.4 枚举越界
    valid, errors = validate_arguments(
        {"name": "Alice", "age": 25, "role": "superadmin"},
        {"parameters": schema},
    )
    ok = not valid and any("role" in e and "允许范围" in e for e in errors)
    _check("2.4 枚举越界被拦截", ok, f"errors={errors}")
    if not ok:
        all_ok = False

    # 2.5 数值范围
    valid, errors = validate_arguments(
        {"name": "Alice", "age": 200},
        {"parameters": schema},
    )
    ok = not valid and any("最大值" in e for e in errors)
    _check("2.5 数值越界被拦截", ok, f"errors={errors}")
    if not ok:
        all_ok = False

    # 2.6 字符串长度
    valid, errors = validate_arguments(
        {"name": "", "age": 25},
        {"parameters": schema},
    )
    ok = not valid and any("长度不足" in e for e in errors)
    _check("2.6 字符串太短被拦截", ok, f"errors={errors}")
    if not ok:
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# T3 · 黑名单拦截
# ─────────────────────────────────────────────────────

async def test_t3_blacklist() -> bool:
    """验证黑名单模式拦截."""
    print("\n[T3] 黑名单拦截")
    all_ok = True

    from core.tool_isolation import ToolSecurityPolicy, IsolationConfig

    config = IsolationConfig()
    policy = ToolSecurityPolicy(config=config)

    # 3.1 危险命令被拦截
    hits = policy.check_blacklist({"command": "rm -rf /"})
    ok = len(hits) > 0
    _check("3.1 rm -rf / 被拦截", ok, f"hits={hits}")
    if not ok:
        all_ok = False

    # 3.2 正常命令不被拦截
    hits = policy.check_blacklist({"command": "ls -la"})
    ok = len(hits) == 0
    _check("3.2 ls -la 不被拦截", ok)
    if not ok:
        all_ok = False

    # 3.3 pre_check 集成黑名单
    passed, issues, level = policy.pre_check(
        "exec_cmd", {"command": "rm -rf /important"},
    )
    ok = not passed and any("黑名单" in i for i in issues)
    _check("3.3 pre_check 集成黑名单拦截", ok, f"passed={passed}, issues={issues}")
    if not ok:
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# T4 · 工具执行 + 超时
# ─────────────────────────────────────────────────────

async def test_t4_execution() -> bool:
    """验证工具执行和超时保护."""
    print("\n[T4] 工具执行 + 超时")
    all_ok = True

    from core.tool_isolation import (
        ToolIsolator, ToolSafetyLevel, ToolSecurityPolicy, IsolationConfig,
    )

    # 模拟 registry
    class MockRegistry:
        def __init__(self) -> None:
            self._tools = {}

        def register(self, name, func, schema=None):
            self._tools[name] = {"func": func, "schema": schema or {}}

        def get(self, name):
            return self._tools.get(name)

    registry = MockRegistry()

    # 正常同步工具
    def add(a: int, b: int) -> dict:
        return {"result": a + b}

    # 正常异步工具
    async def async_greet(name: str) -> dict:
        await asyncio.sleep(0.01)
        return {"greeting": f"Hello, {name}!"}

    # 超时工具
    def slow_func() -> dict:
        time.sleep(5)
        return {"done": True}

    registry.register("add", add, {
        "parameters": {
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
        }
    })
    registry.register("async_greet", async_greet)
    registry.register("slow_func", slow_func)

    config = IsolationConfig(default_timeout=1.0, auto_approve_safe=True)
    policy = ToolSecurityPolicy(config=config)
    policy.register_tool("add", ToolSafetyLevel.SAFE)
    policy.register_tool("async_greet", ToolSafetyLevel.SAFE)
    policy.register_tool("slow_func", ToolSafetyLevel.CAUTIOUS)

    isolator = ToolIsolator(registry=registry, policy=policy)

    # 4.1 同步工具正常执行
    result = await isolator.execute("add", {"a": 3, "b": 4}, skip_approval=True)
    ok = result["status"] == "success" and result["result"]["result"] == 7
    _check("4.1 同步工具正常执行", ok,
           f"status={result['status']}, result={result.get('result')}")
    if not ok:
        all_ok = False

    # 4.2 异步工具正常执行
    result = await isolator.execute("async_greet", {"name": "Etta"}, skip_approval=True)
    ok = result["status"] == "success" and "Hello, Etta!" in result["result"]["greeting"]
    _check("4.2 异步工具正常执行", ok,
           f"status={result['status']}, result={result.get('result')}")
    if not ok:
        all_ok = False

    # 4.3 超时保护
    result = await isolator.execute("slow_func", {}, skip_approval=True)
    ok = result["status"] == "timeout"
    _check("4.3 超时保护生效", ok,
           f"status={result['status']}, error={result.get('error')}")
    if not ok:
        all_ok = False

    # 4.4 不存在的工具
    result = await isolator.execute("nonexistent", {}, skip_approval=True)
    ok = result["status"] == "error" and "不存在" in result["error"]
    _check("4.4 不存在的工具报错", ok,
           f"status={result['status']}, error={result.get('error')}")
    if not ok:
        all_ok = False

    # 4.5 执行时长记录
    result_ok = await isolator.execute("add", {"a": 1, "b": 2}, skip_approval=True)
    ok = "duration_ms" in result_ok and result_ok["duration_ms"] >= 0
    _check("4.5 执行时长记录", ok, f"duration_ms={result_ok.get('duration_ms')}")
    if not ok:
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# T5 · 审批流程
# ─────────────────────────────────────────────────────

async def test_t5_approval() -> bool:
    """验证审批流程."""
    print("\n[T5] 审批流程")
    all_ok = True

    from core.tool_isolation import (
        ToolIsolator, ToolSafetyLevel, ToolSecurityPolicy, IsolationConfig,
    )

    class MockRegistry:
        def __init__(self) -> None:
            self._tools = {}
        def register(self, name, func, schema=None):
            self._tools[name] = {"func": func, "schema": schema or {}}
        def get(self, name):
            return self._tools.get(name)

    def save_file(content: str) -> dict:
        return {"saved": True, "length": len(content)}

    def delete_file(path: str) -> dict:
        return {"deleted": True, "path": path}

    registry = MockRegistry()
    registry.register("save_file", save_file)
    registry.register("delete_file", delete_file)

    config = IsolationConfig(auto_approve_safe=True, auto_approve_cautious=False)
    policy = ToolSecurityPolicy(config=config)
    policy.register_tool("save_file", ToolSafetyLevel.CAUTIOUS)
    policy.register_tool("delete_file", ToolSafetyLevel.DANGEROUS)

    isolator = ToolIsolator(registry=registry, policy=policy)

    # 5.1 CAUTIOUS 需要审批
    result = await isolator.execute("save_file", {"content": "hello"})
    ok = result["status"] == "pending_approval"
    _check("5.1 CAUTIOUS 需审批", ok, f"status={result['status']}")
    if not ok:
        all_ok = False

    call_id = result["call_id"]

    # 5.2 待审批列表
    pending = isolator.get_pending_approvals()
    ok = len(pending) == 1 and pending[0]["tool_name"] == "save_file"
    _check("5.2 待审批列表正确", ok, f"count={len(pending)}")
    if not ok:
        all_ok = False

    # 5.3 拒绝审批
    ok = isolator.reject(call_id, reason="不需要保存")
    _check("5.3 拒绝审批成功", ok)
    if not ok:
        all_ok = False

    pending_after = isolator.get_pending_approvals()
    ok = len(pending_after) == 0
    _check("5.4 拒绝后待审批清空", ok)
    if not ok:
        all_ok = False

    # 5.5 DANGEROUS 也需要审批
    result2 = await isolator.execute("delete_file", {"path": "/tmp/test"})
    ok = result2["status"] == "pending_approval"
    _check("5.5 DANGEROUS 需审批", ok, f"status={result2['status']}")
    if not ok:
        all_ok = False

    # 5.6 skip_approval 跳过审批
    result3 = await isolator.execute("save_file", {"content": "x"}, skip_approval=True)
    ok = result3["status"] == "success"
    _check("5.6 skip_approval 跳过审批直接执行", ok,
           f"status={result3['status']}")
    if not ok:
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# T6 · 审计日志
# ─────────────────────────────────────────────────────

async def test_t6_audit_log() -> bool:
    """验证审计日志."""
    print("\n[T6] 审计日志")
    all_ok = True

    from core.tool_isolation import (
        ToolIsolator, ToolSafetyLevel, ToolSecurityPolicy, IsolationConfig,
    )

    class MockRegistry:
        def __init__(self) -> None:
            self._tools = {}
        def register(self, name, func, schema=None):
            self._tools[name] = {"func": func, "schema": schema or {}}
        def get(self, name):
            return self._tools.get(name)

    def echo(msg: str) -> dict:
        return {"echo": msg}

    registry = MockRegistry()
    registry.register("echo", echo)

    config = IsolationConfig(enable_audit_log=True, auto_approve_safe=True)
    policy = ToolSecurityPolicy(config=config)
    policy.register_tool("echo", ToolSafetyLevel.SAFE)

    isolator = ToolIsolator(registry=registry, policy=policy)

    # 执行几次
    await isolator.execute("echo", {"msg": "hello"})
    await isolator.execute("echo", {"msg": "world"})
    await isolator.execute("echo", {"msg": "test"})

    # 6.1 审计日志记录
    logs = isolator.get_audit_log()
    ok = len(logs) >= 3
    _check("6.1 审计日志记录调用", ok, f"count={len(logs)}")
    if not ok:
        all_ok = False

    # 6.2 日志状态正确
    ok = all(log["status"] == "success" for log in logs)
    _check("6.2 日志状态均为 success", ok)
    if not ok:
        all_ok = False

    # 6.3 按工具名过滤
    echo_logs = isolator.get_audit_log(tool_name="echo")
    ok = len(echo_logs) >= 3
    _check("6.3 按工具名过滤", ok, f"count={len(echo_logs)}")
    if not ok:
        all_ok = False

    # 6.4 日志含安全等级
    ok = all("safety_level" in log for log in logs)
    _check("6.4 日志包含安全等级", ok)
    if not ok:
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────

async def main() -> int:
    print("=" * 60)
    print("Aerie v11.2 · S3 M3.3 工具调用隔离验证")
    print("=" * 60)

    results: list[tuple[str, bool]] = []

    results.append(("T1 安全分级", await test_t1_safety_levels()))
    results.append(("T2 参数校验", await test_t2_param_validation()))
    results.append(("T3 黑名单拦截", await test_t3_blacklist()))
    results.append(("T4 执行+超时", await test_t4_execution()))
    results.append(("T5 审批流程", await test_t5_approval()))
    results.append(("T6 审计日志", await test_t6_audit_log()))

    print("\n" + "=" * 60)
    print("汇总")
    print("=" * 60)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        sym = "✓ PASS" if ok else "✗ FAIL"
        print(f"  {sym}  {name}")

    print(f"\n结果: {passed}/{total} 通过")

    if passed == total:
        print("\n🎉 M3.3 工具调用隔离全部通过！")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 项未通过，请检查。")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
