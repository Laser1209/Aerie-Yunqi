"""工具产出（Observation）归一化契约。

**为什么需要这个模块**

工具可以返回任意 Python 对象（例如 ``ControlResult`` 这类 ``@dataclass``），
而下游一律假定返回值可 JSON 序列化：

* ``core/llm_caller.py`` 组装 ``role="tool"`` 消息时 ``json.dumps(result)``；
* ``core/pipeline.py`` 写 ``tool_call_log`` 时 ``json.dumps(result)``；
* 工具结果还会进 SSE / trace / 前端。

一旦某个工具返回不可序列化对象，``json.dumps`` 抛 ``TypeError``。更严重的是它
发生在"把 tool 消息 append 进 ``working_msgs``"**之前**，于是历史里留下一条
**只声明了 ``tool_calls`` 却没有配对 ``tool`` 回执的孤儿 assistant 消息**。
而 ``working_msgs`` 是跨供应商复用的 —— 一个工具出错会让本轮**所有**剩余供应商
全部拒收（OpenAI 兼容接口的硬约束：``tool_calls`` 必须逐条配对）。

**契约**

``ToolRegistry.execute`` 的后置条件：返回值**必然可 JSON 序列化**，且**必然为 dict**。

新增工具时不需要关心这件事 —— 归一化在注册表出口**统一收口**，
而不是要求 70 个工具各自保证。
"""

from __future__ import annotations

import base64
import dataclasses
import datetime as _dt
import decimal
import enum
import json
import logging
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 递归深度上限：正常工具结果远达不到；限制它是为了防止病态嵌套把栈打爆。
MAX_DEPTH = 12

# 归一化失败时对模型可见的错误码（绝不静默 —— 静默会让模型失去纠错依据）。
NON_SERIALIZABLE_ERROR = "tool returned non-serializable value"
NORMALIZATION_FAILED_ERROR = "tool_result_normalization_failed"
RECURSION_LIMIT_ERROR = "tool_result_nesting_too_deep"
CIRCULAR_ERROR = "tool_result_contains_circular_reference"

# bytes 转文本时的上限：超长二进制（如图片字节流）截断，避免把上下文冲爆。
_BYTES_TEXT_LIMIT = 512


def _error_payload(code: str, value: Any) -> dict[str, Any]:
    """构造对模型可见的错误回执（保留类型名，便于定位是哪个工具）。"""
    return {"error": code, "type": type(value).__name__}


def _describe_bytes(value: bytes) -> str:
    """bytes → 可读文本；过长或非文本时给一个带长度与 base64 前缀的说明。

    工具返回二进制时，把它当成"可读文本"更有利于模型理解（例如日志片段）；
    真正的二进制（图片等）走 base64 摘要是为了保留可校验的指纹。
    """
    if len(value) <= _BYTES_TEXT_LIMIT:
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            pass
    encoded = base64.b64encode(value[:96]).decode("ascii")
    return f"<binary {len(value)} bytes base64-prefix:{encoded}>"


def normalize_tool_result(value: Any) -> dict[str, Any]:
    """把任意工具返回值归一为可 JSON 序列化的 ``dict``。

    规则（顺序即优先级）：

    1. ``dict`` → 递归归一（键统一转 ``str``）；
    2. ``None`` / ``bool`` / ``int`` / ``float`` / ``str`` → 包成 ``{"result": ...}``
       （契约要求返回 dict；标量不丢，放到 ``result`` 键下）；
    3. ``list`` / ``tuple`` / ``set`` / ``frozenset`` → ``{"result": [...]}``；
    4. 有 ``to_dict()`` → 调它（``ControlResult`` / ``AuditLogEntry`` 都有）；
    5. ``@dataclass`` → ``dataclasses.asdict``；
    6. ``bytes`` → 可读文本；``Path`` → ``str``；时间/``UUID``/``Enum``/``Decimal`` → 其自然表示；
    7. 其余 → ``{"error": ..., "type": ...}``（**对模型可见，绝不静默**）。

    ``dict`` 直通是有意为之：绝大多数工具有意返回 ``{"success": ...}`` 这类结构，
    包一层 ``result`` 会破坏它们的既有语义。
    """
    normalized, _status = _normalize(value, depth=0, seen=set())
    if isinstance(normalized, dict):
        return normalized
    # 顶层非 dict（标量/列表/转换失败）：统一按契约包成 dict。
    return {"result": normalized}


def _normalize(value: Any, *, depth: int, seen: set[int]) -> tuple[Any, str]:
    """递归归一；返回 ``(归一化后的值, 状态)``，状态用于上层判断是否降级。"""
    if depth > MAX_DEPTH:
        return {"error": RECURSION_LIMIT_ERROR, "depth": depth}, "error"

    # 1) JSON 原生标量：直接通过。
    if value is None or isinstance(value, (bool, int, float, str)):
        return value, "ok"

    # 2) 容器：先查环，再递归。
    if isinstance(value, dict):
        if id(value) in seen:
            return {"error": CIRCULAR_ERROR}, "error"
        seen.add(id(value))
        try:
            out: dict[str, Any] = {}
            for key, item in value.items():
                key_text = key if isinstance(key, str) else str(key)
                out[key_text], _ = _normalize(item, depth=depth + 1, seen=seen)
            return out, "ok"
        finally:
            seen.discard(id(value))

    if isinstance(value, (list, tuple, set, frozenset)):
        if id(value) in seen:
            return {"error": CIRCULAR_ERROR}, "error"
        # set 无序：排序保证同样的输入产出同样的结果，便于测试与去重。
        items = sorted(value, key=repr) if isinstance(value, (set, frozenset)) else value
        seen.add(id(value))
        try:
            normalized_items = [
                _normalize(item, depth=depth + 1, seen=seen)[0] for item in items
            ]
            return normalized_items, "ok"
        finally:
            seen.discard(id(value))

    # 3) 显式提供了转换入口的对象：优先用它（语义最准确）。
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            converted = to_dict()
        except Exception:
            logger.debug("to_dict() failed for %s", type(value).__name__, exc_info=True)
        else:
            return _normalize(converted, depth=depth + 1, seen=seen)

    # 4) dataclass：标准库转换（不依赖工具自己实现 to_dict）。
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        try:
            return _normalize(dataclasses.asdict(value), depth=depth + 1, seen=seen)
        except Exception:
            logger.debug("asdict() failed for %s", type(value).__name__, exc_info=True)

    # 5) 常见叶子类型：转成自然表示。
    if isinstance(value, bytes):
        return _describe_bytes(value), "ok"
    if isinstance(value, (bytearray, memoryview)):
        return _describe_bytes(bytes(value)), "ok"
    if isinstance(value, Path):
        return str(value), "ok"
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat(), "ok"
    if isinstance(value, uuid.UUID):
        return str(value), "ok"
    if isinstance(value, decimal.Decimal):
        return str(value), "ok"
    if isinstance(value, enum.Enum):
        return _normalize(value.value, depth=depth + 1, seen=seen)

    # 6) 兜底：能否直接被 JSON 编码？能就用它的自然结构，不能就如实报错。
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return _error_payload(NON_SERIALIZABLE_ERROR, value), "error"
    return value, "ok"


def tool_result_success(result: Any) -> bool:
    """判定工具结果是否成功。

    优先读显式的 ``success`` 布尔（``ControlResult.to_dict()`` 会带），否则按
    "有无 ``error``" 判断。

    为什么不能继续用 ``"error" in result``：归一化后 ``ControlResult`` 会变成
    dict，而它的 ``to_dict()`` **恒带 ``error`` 键**（成功时为空串）。若仍按
    "存在 error 键"判定，**每一次成功的系统操控都会被误判为失败**。
    """
    if not isinstance(result, dict):
        return True
    explicit = result.get("success")
    if isinstance(explicit, bool):
        return explicit
    return not result.get("error")


def safe_json_dumps(value: Any) -> str:
    """``json.dumps`` 的安全版本 —— 消费侧的最后一道防线。

    即使上游漏做了归一化，这里也**绝不抛异常**：保证
    ``role="tool"`` 消息一定拼得出来、pairing 一定完整。
    """
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        logger.warning(
            "tool result not JSON-serializable (%s); falling back to error payload",
            type(value).__name__,
        )
    try:
        return json.dumps(normalize_tool_result(value), ensure_ascii=False)
    except Exception:
        logger.exception("tool result normalization failed in safe_json_dumps")
        return json.dumps(
            {"error": NORMALIZATION_FAILED_ERROR, "type": type(value).__name__},
            ensure_ascii=False,
        )
