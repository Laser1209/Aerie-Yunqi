"""工具产出归一化契约（core/tool_result.py）。

背景：工具可返回任意 Python 对象（如 ``ControlResult`` 这类 ``@dataclass``），
而下游一律 ``json.dumps(result)``。一旦序列化失败，异常发生在"把 tool 消息
append 进 working_msgs"之前，于是留下孤儿 tool_call，导致本轮**所有**供应商
拒收（OpenAI 兼容接口要求 tool_calls 与 tool 消息逐条配对）。

本测试锁定契约：``normalize_tool_result`` 必然返回可 JSON 序列化的 dict。
"""
from __future__ import annotations

import dataclasses
import datetime
import enum
import json
from pathlib import Path

import pytest

from core.tool_result import (
    CIRCULAR_ERROR,
    NON_SERIALIZABLE_ERROR,
    RECURSION_LIMIT_ERROR,
    normalize_tool_result,
    safe_json_dumps,
)


@dataclasses.dataclass
class _BareDataclass:
    """没有 to_dict 的 dataclass —— 走 asdict 分支。"""

    name: str
    count: int


class _WithToDict:
    """模拟 ControlResult：有 to_dict，且**恒带 error 键**（哪怕是空串）。"""

    def __init__(self) -> None:
        self.success = True
        self.action = "shell_execute"
        self.data = {"stdout": "hi"}
        self.error = ""
        self.timestamp = 1.0

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "action": self.action,
            "data": self.data,
            "error": self.error,
            "timestamp": self.timestamp,
        }


class _Opaque:
    """完全无法转换的对象。"""

    __slots__ = ()


class _Color(enum.Enum):
    RED = "red"


def _roundtrip(value) -> dict:
    """归一化后必须能真正被 json.dumps 编码 —— 这是契约的核心断言。"""
    normalized = normalize_tool_result(value)
    assert isinstance(normalized, dict), "契约要求返回 dict"
    json.dumps(normalized, ensure_ascii=False)  # 不应抛异常
    return normalized


# ── dict 直通（有意为之：不包一层 result，否则破坏既有语义）──────────────


def test_dict_passes_through_unchanged():
    payload = {"success": True, "queued": True, "name": "a.pptx"}
    assert _roundtrip(payload) == payload


def test_dict_keys_are_stringified():
    normalized = _roundtrip({1: "a", (2, 3): "b"})
    assert set(normalized) == {"1", "(2, 3)"}


def test_nested_dict_is_normalized_recursively():
    normalized = _roundtrip({"outer": {"inner": _WithToDict(), "raw": b"ok"}})
    assert normalized["outer"]["inner"]["action"] == "shell_execute"
    assert normalized["outer"]["raw"] == "ok"


def test_error_dict_preserved_for_failure_detection():
    """消费侧靠 ``error`` 键判定失败，归一化不得吞掉它。"""
    normalized = _roundtrip({"error": "boom"})
    assert normalized == {"error": "boom"}


# ── 对象转换 ────────────────────────────────────────────────────────────


def test_object_with_to_dict_prefers_that():
    normalized = _roundtrip(_WithToDict())
    assert normalized["action"] == "shell_execute"
    assert normalized["data"] == {"stdout": "hi"}
    # to_dict 恒带 error 键（空串）—— 这正是必须让消费侧按 success 判定的原因
    assert normalized["error"] == ""


def test_to_dict_result_is_normalized_recursively():
    class _Nested:
        def to_dict(self):
            return {"path": Path("/tmp/x"), "when": datetime.date(2026, 9, 28)}

    normalized = _roundtrip(_Nested())
    assert normalized == {"path": str(Path("/tmp/x")), "when": "2026-09-28"}


def test_bare_dataclass_uses_asdict():
    normalized = _roundtrip(_BareDataclass(name="n", count=2))
    assert normalized == {"name": "n", "count": 2}


def test_dataclass_inside_dict_is_converted():
    normalized = _roundtrip({"item": _BareDataclass(name="x", count=1)})
    assert normalized["item"] == {"name": "x", "count": 1}


def test_control_like_object_is_json_serializable():
    """回归：ControlResult 曾让 json.dumps 抛 TypeError 并毒化整轮上下文。"""
    json.dumps(normalize_tool_result(_WithToDict()), ensure_ascii=False)


# ── 叶子类型 ────────────────────────────────────────────────────────────


def test_bytes_decoded_as_text_when_printable():
    assert _roundtrip(b"hello") == {"result": "hello"}


def test_binary_bytes_keep_length_and_prefix():
    value = bytes(range(256)) * 4
    normalized = _roundtrip(value)
    assert "binary" in normalized["result"]
    assert str(len(value)) in normalized["result"]


def test_path_datetime_uuid_enum_decimal():
    import decimal
    import uuid

    stamp = datetime.datetime(2026, 9, 28, 15, 30)
    assert _roundtrip(stamp) == {"result": "2026-09-28T15:30:00"}
    assert _roundtrip(Path("/a/b")) == {"result": str(Path("/a/b"))}
    token = uuid.uuid4()
    assert _roundtrip(token) == {"result": str(token)}
    assert _roundtrip(_Color.RED) == {"result": "red"}
    assert _roundtrip(decimal.Decimal("1.5")) == {"result": "1.5"}


# ── 标量与容器 ──────────────────────────────────────────────────────────


def test_scalars_wrapped_under_result():
    assert _roundtrip(None) == {"result": None}
    assert _roundtrip(True) == {"result": True}
    assert _roundtrip(7) == {"result": 7}
    assert _roundtrip("text") == {"result": "text"}


def test_sequences_wrapped_as_list():
    assert _roundtrip([1, "a"]) == {"result": [1, "a"]}
    assert _roundtrip((1, 2)) == {"result": [1, 2]}


def test_set_is_sorted_for_determinism():
    """set 无序：排序保证同样输入产出同样结果（便于测试与去重）。"""
    assert _roundtrip({"b", "a", "c"}) == {"result": ["a", "b", "c"]}


# ── 边界与防御 ──────────────────────────────────────────────────────────


def test_circular_reference_does_not_crash():
    payload: dict = {"name": "root"}
    payload["self"] = payload
    normalized = _roundtrip(payload)
    assert normalized["self"] == {"error": CIRCULAR_ERROR}


def test_deep_nesting_is_bounded():
    node: dict = {}
    cursor = node
    for _ in range(40):
        cursor["next"] = {}
        cursor = cursor["next"]
    json.dumps(normalize_tool_result(node), ensure_ascii=False)  # 不抛栈溢出


def test_opaque_object_reports_type_visibly():
    """不可序列化必须**对模型可见**（静默会让模型失去纠错依据）。"""
    normalized = _roundtrip(_Opaque())
    assert normalized["error"] == NON_SERIALIZABLE_ERROR
    assert normalized["type"] == "_Opaque"


def test_raising_to_dict_falls_back_to_asdict_or_error():
    class _Broken:
        def to_dict(self):
            raise RuntimeError("nope")

    normalized = _roundtrip(_Broken())
    assert normalized["error"] == NON_SERIALIZABLE_ERROR


def test_circular_list_does_not_crash():
    items: list = []
    items.append(items)
    normalized = _roundtrip({"items": items})
    assert normalized["items"] == [{"error": CIRCULAR_ERROR}]


# ── safe_json_dumps：消费侧最后一道防线 ─────────────────────────────────


def test_safe_json_dumps_never_raises_on_opaque():
    text = safe_json_dumps(_Opaque())
    assert NON_SERIALIZABLE_ERROR in text


def test_safe_json_dumps_handles_circular():
    payload: dict = {}
    payload["self"] = payload
    json.loads(safe_json_dumps(payload))  # 必须能解析


def test_safe_json_dumps_matches_json_for_plain_payload():
    payload = {"a": [1, 2], "b": "中文"}
    assert json.loads(safe_json_dumps(payload)) == payload


@pytest.mark.parametrize(
    "value",
    [_WithToDict(), _BareDataclass("n", 1), Path("/x"), b"raw", _Opaque(), {1, 2}],
)
def test_every_shape_is_round_trippable(value):
    """统一不变量：任何形状都能过 JSON 编解码一次且不抛异常。"""
    json.loads(safe_json_dumps(normalize_tool_result(value)))
