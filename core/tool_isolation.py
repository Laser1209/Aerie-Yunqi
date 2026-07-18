"""Aerie · 云栖 v0.1.0-beta.1 — 工具调用安全隔离 (S3 M3.3).

提供工具调用的安全沙箱，包括：
  - 工具权限分级（read / write / destructive）
  - 参数校验（基于 JSON Schema）
  - 执行超时保护
  - 审计日志
  - 危险操作二次确认（user-in-the-loop）
  - 敏感路径/命令黑名单

安全等级说明：
  SAFE       — 只读操作，无副作用，可自由执行
  CAUTIOUS   — 有写入但可回滚，需记录审计
  DANGEROUS  — 不可逆操作（删除、执行命令等），需用户确认
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ToolSafetyLevel(str, Enum):
    """工具安全等级."""
    SAFE = "safe"           # 只读，无副作用
    CAUTIOUS = "cautious"   # 有写入但可恢复
    DANGEROUS = "dangerous" # 不可逆操作


class ToolCallStatus(str, Enum):
    """工具调用状态."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    BLOCKED = "blocked"


@dataclass
class ToolCallRecord:
    """工具调用审计记录."""
    call_id: str
    tool_name: str
    arguments: Dict[str, Any]
    safety_level: ToolSafetyLevel
    status: ToolCallStatus
    user_id: int = 0
    session_id: str = ""
    created_at: float = field(default_factory=time.time)
    executed_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    duration_ms: float = 0.0


@dataclass
class IsolationConfig:
    """隔离配置."""
    default_timeout: float = 30.0          # 默认超时（秒）
    dangerous_timeout: float = 60.0        # 危险操作超时
    auto_approve_safe: bool = True         # 自动批准 SAFE 级
    auto_approve_cautious: bool = False    # 自动批准 CAUTIOUS 级
    enable_audit_log: bool = True          # 启用审计日志
    max_calls_per_minute: int = 60         # 每分钟最大调用数
    blacklist_patterns: List[str] = field(default_factory=lambda: [
        r"rm\s+-rf\s+/",
        r"format\s+[A-Z]:",
        r"del\s+/s\s+/q\s+[A-Z]:\\",
        r">\\\.\\",          # UNC 路径绕过
    ])


# ── 参数校验 ────────────────────────────────────────

def validate_arguments(
    arguments: Dict[str, Any],
    schema: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """
    简单的 JSON Schema 参数校验。

    支持 type, required, properties, enum, minimum/maximum, minLength/maxLength。
    返回 (是否通过, 错误列表)。
    """
    errors: List[str] = []

    # 解析 function 嵌套
    props_schema = schema
    if "function" in schema and isinstance(schema["function"], dict):
        props_schema = schema["function"]
    if "parameters" in props_schema and isinstance(props_schema["parameters"], dict):
        props_schema = props_schema["parameters"]

    # 必填字段检查
    required = props_schema.get("required", [])
    for field_name in required:
        if field_name not in arguments:
            errors.append(f"缺少必填参数: {field_name}")

    # properties 类型检查
    properties = props_schema.get("properties", {})
    for field_name, value in arguments.items():
        if field_name not in properties:
            # 允许额外字段，只警告
            continue
        field_schema = properties[field_name]
        field_type = field_schema.get("type", "string")

        # 类型校验
        if field_type == "string" and not isinstance(value, str):
            errors.append(f"参数 {field_name} 应为 string 类型")
        elif field_type == "integer" and not isinstance(value, int):
            errors.append(f"参数 {field_name} 应为 integer 类型")
        elif field_type == "number" and not isinstance(value, (int, float)):
            errors.append(f"参数 {field_name} 应为 number 类型")
        elif field_type == "boolean" and not isinstance(value, bool):
            errors.append(f"参数 {field_name} 应为 boolean 类型")
        elif field_type == "object" and not isinstance(value, dict):
            errors.append(f"参数 {field_name} 应为 object 类型")
        elif field_type == "array" and not isinstance(value, list):
            errors.append(f"参数 {field_name} 应为 array 类型")

        # 枚举校验
        if "enum" in field_schema and value not in field_schema["enum"]:
            errors.append(
                f"参数 {field_name} 值 {value} 不在允许范围 {field_schema['enum']}"
            )

        # 字符串长度
        if isinstance(value, str):
            if "minLength" in field_schema and len(value) < field_schema["minLength"]:
                errors.append(
                    f"参数 {field_name} 长度不足 {field_schema['minLength']}"
                )
            if "maxLength" in field_schema and len(value) > field_schema["maxLength"]:
                errors.append(
                    f"参数 {field_name} 长度超过 {field_schema['maxLength']}"
                )

        # 数值范围
        if isinstance(value, (int, float)):
            if "minimum" in field_schema and value < field_schema["minimum"]:
                errors.append(f"参数 {field_name} 小于最小值 {field_schema['minimum']}")
            if "maximum" in field_schema and value > field_schema["maximum"]:
                errors.append(f"参数 {field_name} 大于最大值 {field_schema['maximum']}")

    return (len(errors) == 0, errors)


# ── 安全策略引擎 ────────────────────────────────────

class ToolSecurityPolicy:
    """
    工具安全策略引擎.

    负责：
      - 工具安全分级注册
      - 调用前安全检查
      - 黑名单模式匹配
      - 速率限制
    """

    def __init__(self, config: Optional[IsolationConfig] = None) -> None:
        self.config = config or IsolationConfig()
        self._tool_levels: Dict[str, ToolSafetyLevel] = {}
        self._call_timestamps: List[float] = []
        self._audit_log: List[ToolCallRecord] = []

    def register_tool(
        self,
        tool_name: str,
        safety_level: ToolSafetyLevel = ToolSafetyLevel.CAUTIOUS,
    ) -> None:
        """注册工具的安全等级."""
        self._tool_levels[tool_name] = safety_level
        logger.debug("tool %s registered with safety level %s", tool_name, safety_level.value)

    def get_safety_level(self, tool_name: str) -> ToolSafetyLevel:
        """获取工具安全等级，默认为 CAUTIOUS."""
        return self._tool_levels.get(tool_name, ToolSafetyLevel.CAUTIOUS)

    def check_blacklist(self, arguments: Dict[str, Any]) -> List[str]:
        """检查参数是否命中黑名单模式."""
        hits: List[str] = []
        arg_str = json.dumps(arguments, ensure_ascii=False)
        for pattern in self.config.blacklist_patterns:
            if re.search(pattern, arg_str, re.IGNORECASE):
                hits.append(pattern)
        return hits

    def check_rate_limit(self) -> bool:
        """检查是否超过速率限制."""
        now = time.time()
        # 清理 1 分钟前的记录
        self._call_timestamps = [t for t in self._call_timestamps if now - t < 60]
        if len(self._call_timestamps) >= self.config.max_calls_per_minute:
            return False
        self._call_timestamps.append(now)
        return True

    def pre_check(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        tool_schema: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, List[str], ToolSafetyLevel]:
        """
        调用前安全检查.

        返回: (是否通过, 警告/错误列表, 安全等级)
        """
        issues: List[str] = []
        level = self.get_safety_level(tool_name)

        # 1. 速率限制
        if not self.check_rate_limit():
            issues.append(
                f"超过速率限制（{self.config.max_calls_per_minute}/分钟）"
            )
            return False, issues, level

        # 2. 黑名单检查
        blacklist_hits = self.check_blacklist(arguments)
        if blacklist_hits:
            issues.append(f"参数命中黑名单模式: {blacklist_hits}")
            return False, issues, level

        # 3. 参数校验（如果有 schema）
        if tool_schema:
            valid, errors = validate_arguments(arguments, tool_schema)
            if not valid:
                issues.extend([f"参数校验失败: {e}" for e in errors])
                return False, issues, level

        return True, issues, level

    def needs_approval(self, level: ToolSafetyLevel) -> bool:
        """判断是否需要用户审批."""
        if level == ToolSafetyLevel.SAFE:
            return not self.config.auto_approve_safe
        elif level == ToolSafetyLevel.CAUTIOUS:
            return not self.config.auto_approve_cautious
        else:  # DANGEROUS
            return True  # 危险操作永远需要审批

    # ── 审计日志 ──

    def log_call(self, record: ToolCallRecord) -> None:
        """记录审计日志."""
        if self.config.enable_audit_log:
            self._audit_log.append(record)
            if len(self._audit_log) > 1000:
                self._audit_log = self._audit_log[-1000:]

    def get_audit_log(
        self,
        limit: int = 50,
        tool_name: Optional[str] = None,
        status: Optional[ToolCallStatus] = None,
    ) -> List[ToolCallRecord]:
        """查询审计日志."""
        logs = self._audit_log
        if tool_name:
            logs = [r for r in logs if r.tool_name == tool_name]
        if status:
            logs = [r for r in logs if r.status == status]
        return logs[-limit:]


# ── 隔离执行器 ──────────────────────────────────────

class ToolIsolator:
    """
    工具隔离执行器.

    在安全沙箱中执行工具调用，包含：
      - 前置安全检查
      - 可选的用户审批
      - 超时保护
      - 异常捕获
      - 审计记录

    用法::

        isolator = ToolIsolator(registry=tool_registry)
        isolator.policy.register_tool("get_weather", ToolSafetyLevel.SAFE)
        result = await isolator.execute("get_weather", {"city": "Beijing"})
    """

    def __init__(
        self,
        registry: Any = None,
        policy: Optional[ToolSecurityPolicy] = None,
        config: Optional[IsolationConfig] = None,
    ) -> None:
        self.registry = registry
        self.policy = policy or ToolSecurityPolicy(config=config)
        self.config = self.policy.config
        self._pending_approvals: Dict[str, ToolCallRecord] = {}

    def get_tool_info(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """从 registry 获取工具信息."""
        if self.registry and hasattr(self.registry, "get"):
            return self.registry.get(tool_name)
        return None

    async def execute(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        user_id: int = 0,
        session_id: str = "",
        skip_approval: bool = False,
    ) -> Dict[str, Any]:
        """
        执行工具调用（安全隔离模式）.

        Args:
            tool_name: 工具名
            arguments: 参数字典
            user_id: 用户 ID
            session_id: 会话 ID
            skip_approval: 跳过审批（已确认安全的内部调用）

        Returns:
            执行结果 dict，含 status/result/error 等字段
        """
        args = arguments or {}
        call_id = f"tc_{int(time.time()*1000)}_{abs(hash(tool_name + json.dumps(args, sort_keys=True))) % 10000}"

        # 获取工具 schema
        tool_info = self.get_tool_info(tool_name)
        tool_schema = tool_info.get("schema") if tool_info else None
        tool_func = tool_info.get("func") if tool_info else None

        # 1. 前置安全检查
        passed, issues, level = self.policy.pre_check(
            tool_name, args, tool_schema,
        )

        record = ToolCallRecord(
            call_id=call_id,
            tool_name=tool_name,
            arguments=args,
            safety_level=level,
            status=ToolCallStatus.PENDING,
            user_id=user_id,
            session_id=session_id,
        )

        if not passed:
            record.status = ToolCallStatus.BLOCKED
            record.error = "; ".join(issues)
            self.policy.log_call(record)
            return {
                "status": "blocked",
                "call_id": call_id,
                "tool_name": tool_name,
                "safety_level": level.value,
                "errors": issues,
            }

        # 2. 审批检查
        if not skip_approval and self.policy.needs_approval(level):
            self._pending_approvals[call_id] = record
            return {
                "status": "pending_approval",
                "call_id": call_id,
                "tool_name": tool_name,
                "safety_level": level.value,
                "message": f"工具 {tool_name}（{level.value}）需要用户确认",
            }

        # 3. 执行
        return await self._do_execute(record, tool_func)

    async def _do_execute(
        self,
        record: ToolCallRecord,
        tool_func: Optional[Callable],
    ) -> Dict[str, Any]:
        """实际执行工具."""
        record.status = ToolCallStatus.EXECUTING
        record.executed_at = time.time()

        if tool_func is None:
            record.status = ToolCallStatus.FAILED
            record.error = f"工具 {record.tool_name} 不存在"
            self.policy.log_call(record)
            return {
                "status": "error",
                "call_id": record.call_id,
                "tool_name": record.tool_name,
                "error": record.error,
            }

        # 超时设置
        timeout = (
            self.config.dangerous_timeout
            if record.safety_level == ToolSafetyLevel.DANGEROUS
            else self.config.default_timeout
        )

        try:
            # 同步函数在 executor 中运行，异步函数直接 await
            if asyncio.iscoroutinefunction(tool_func):
                result = await asyncio.wait_for(
                    tool_func(**record.arguments),
                    timeout=timeout,
                )
            else:
                loop = asyncio.get_event_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: tool_func(**record.arguments)),
                    timeout=timeout,
                )

            record.status = ToolCallStatus.SUCCESS
            record.result = result if isinstance(result, dict) else {"output": result}
            record.completed_at = time.time()
            record.duration_ms = (record.completed_at - record.executed_at) * 1000

            self.policy.log_call(record)
            return {
                "status": "success",
                "call_id": record.call_id,
                "tool_name": record.tool_name,
                "safety_level": record.safety_level.value,
                "duration_ms": round(record.duration_ms, 2),
                "result": record.result,
            }

        except asyncio.TimeoutError:
            record.status = ToolCallStatus.TIMEOUT
            record.error = f"执行超时（>{timeout}s）"
            record.completed_at = time.time()
            record.duration_ms = timeout * 1000
            self.policy.log_call(record)
            return {
                "status": "timeout",
                "call_id": record.call_id,
                "tool_name": record.tool_name,
                "error": record.error,
            }

        except Exception as e:
            record.status = ToolCallStatus.FAILED
            record.error = str(e)
            record.completed_at = time.time()
            if record.executed_at:
                record.duration_ms = (record.completed_at - record.executed_at) * 1000
            self.policy.log_call(record)
            logger.exception("Tool execution failed: %s", record.tool_name)
            return {
                "status": "error",
                "call_id": record.call_id,
                "tool_name": record.tool_name,
                "error": record.error,
            }

    # ── 审批流程 ──

    def approve(self, call_id: str) -> bool:
        """批准待审批的调用."""
        if call_id not in self._pending_approvals:
            return False
        record = self._pending_approvals.pop(call_id)
        record.status = ToolCallStatus.APPROVED
        return True

    def reject(self, call_id: str, reason: str = "") -> bool:
        """拒绝待审批的调用."""
        if call_id not in self._pending_approvals:
            return False
        record = self._pending_approvals.pop(call_id)
        record.status = ToolCallStatus.REJECTED
        record.error = reason or "用户拒绝"
        self.policy.log_call(record)
        return True

    def get_pending_approvals(self) -> List[Dict[str, Any]]:
        """获取待审批列表."""
        return [
            {
                "call_id": r.call_id,
                "tool_name": r.tool_name,
                "arguments": r.arguments,
                "safety_level": r.safety_level.value,
                "created_at": r.created_at,
            }
            for r in self._pending_approvals.values()
        ]

    # ── 审计查询 ──

    def get_audit_log(
        self,
        limit: int = 50,
        tool_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取审计日志."""
        records = self.policy.get_audit_log(limit=limit, tool_name=tool_name)
        return [
            {
                "call_id": r.call_id,
                "tool_name": r.tool_name,
                "status": r.status.value,
                "safety_level": r.safety_level.value,
                "duration_ms": r.duration_ms,
                "error": r.error,
                "created_at": r.created_at,
            }
            for r in records
        ]
