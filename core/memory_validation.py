"""Aerie · P2 写入校验门（ConsistencyGate）PoC（§3.7-2 / §4 #17）。

对 importance ≥ 7 的关键记忆/知识，写入前用轻量 LLM（siliconflow-light）
快速判断「该事实是否由用户明确表达」：模糊/推断内容降级为 low_confidence，
不直接提升为事实，防止记忆污染。

默认由 feature flag ``memory_write_validation_v1`` 控制（商业测试版本默认开启）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

IMPORTANCE_THRESHOLD = 7

_SYSTEM_PROMPT = (
    "你是记忆一致性检查器。判断下面这条「待写入的记忆」是否由用户在本轮对话中"
    "**明确表达**（用户亲口说出/明确指定），而不是 AI 自己的推断、猜测、脑补或"
    "对过去信息的模糊联想。\n"
    "只输出一个 JSON 对象，不要其他文字：\n"
    "{\"explicit\": true 或 false, \"reason\": \"一句话理由\"}\n"
    "判定标准：用户明确说出的事实（地址/电话/喜好/约定/身份等）→ explicit=true；"
    "AI 推断、推测、假设、或内容含糊 → explicit=false。"
)

_DEFAULT_LLM_FACTORY: Callable[[], Any] | None = None


def set_default_llm_factory(factory: Callable[[], Any]) -> None:
    """注入默认 LLM caller 工厂（测试或容器组装用）。"""
    global _DEFAULT_LLM_FACTORY
    _DEFAULT_LLM_FACTORY = factory


def get_default_llm() -> Any:
    if _DEFAULT_LLM_FACTORY is not None:
        return _DEFAULT_LLM_FACTORY()
    from core.llm_caller import LLMCaller

    return LLMCaller()


class MemoryFactValidator:
    """轻量写入校验门：显式事实 → confirmed，推断/模糊 → low_confidence。"""

    def __init__(
        self,
        llm: Any | None = None,
        *,
        enabled: bool = True,
        timeout: float = 8.0,
        max_retries: int = 1,
    ) -> None:
        self.llm = llm
        self.enabled = enabled
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))

    def _build_messages(self, text: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"待写入记忆：\n{text}",
            },
        ]

    @staticmethod
    def _parse_response(raw: str) -> dict[str, Any]:
        text = (raw or "").strip()
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                explicit = bool(parsed.get("explicit"))
                reason = str(parsed.get("reason") or "").strip()
                return {"explicit": explicit, "reason": reason}
        except Exception:
            pass
        lowered = text.lower()
        if '"explicit": true' in lowered or 'explicit":true' in lowered:
            return {"explicit": True, "reason": "parsed from raw json"}
        if '"explicit": false' in lowered or 'explicit":false' in lowered:
            return {"explicit": False, "reason": "parsed from raw json"}
        if text.startswith("true") or text.startswith("yes") or text.startswith("是"):
            return {"explicit": True, "reason": "parsed from raw text"}
        if text.startswith("false") or text.startswith("no") or text.startswith("否"):
            return {"explicit": False, "reason": "parsed from raw text"}
        return {"explicit": None, "reason": text[:120]}

    async def validate(
        self,
        *,
        text: str,
        channel: str | None = None,
        source: str | None = None,
        importance: float = 5.0,
    ) -> dict[str, Any]:
        """校验一条待写入记忆。返回结构化结果（不抛异常）。"""
        started = time.monotonic()
        try:
            importance = float(importance)
        except (TypeError, ValueError):
            importance = 5.0
        base: dict[str, Any] = {
            "status": "unchecked",
            "importance": importance,
            "channel": channel or "unknown",
            "source": source or "unknown",
            "duration_ms": 0,
            "reason": "",
        }
        if importance < IMPORTANCE_THRESHOLD:
            base["status"] = "skip"
            base["reason"] = "low_importance"
            base["duration_ms"] = round((time.monotonic() - started) * 1000, 2)
            return base
        if not self.enabled:
            base["status"] = "unchecked"
            base["reason"] = "validation_disabled"
            base["duration_ms"] = round((time.monotonic() - started) * 1000, 2)
            return base
        try:
            llm = self.llm or get_default_llm()
            messages = self._build_messages(text)
            last_error: Exception | None = None
            for attempt in range(self.max_retries + 1):
                try:
                    resp = await asyncio.wait_for(
                        llm.chat(
                            messages,
                            preferred_provider="siliconflow-light",
                            temperature=0.0,
                        ),
                        timeout=self.timeout,
                    )
                    parsed = self._parse_response(getattr(resp, "text", ""))
                    if parsed.get("explicit") is None:
                        last_error = ValueError(f"unparsable response: {parsed['reason'][:80]}")
                        continue
                    return {
                        "status": (
                            "confirmed" if parsed["explicit"] else "low_confidence"
                        ),
                        "importance": importance,
                        "channel": channel or "unknown",
                        "source": source or "unknown",
                        "reason": parsed.get("reason") or "",
                        "provider": getattr(resp, "provider", ""),
                        "model": getattr(resp, "model", ""),
                        "tokens_prompt": int(getattr(resp, "tokens_prompt", 0)),
                        "tokens_completion": int(getattr(resp, "tokens_completion", 0)),
                        "duration_ms": round((time.monotonic() - started) * 1000, 2),
                    }
                except asyncio.TimeoutError:
                    last_error = TimeoutError("light LLM timeout")
                    break
                except Exception as exc:  # noqa: BLE001 - fail-open path
                    last_error = exc
                    logger.debug(
                        "memory validation attempt %d failed: %s", attempt, exc
                    )
            # fail-open：LLM 不可用时标记 unavailable，不阻塞写入
            return {
                "status": "unavailable",
                "importance": importance,
                "channel": channel or "unknown",
                "source": source or "unknown",
                "reason": f"llm_unavailable: {last_error}" if last_error else "",
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
            }
        except Exception as exc:  # noqa: BLE001 - fail-open path
            logger.warning("memory validation failed: %s", exc)
            return {
                "status": "unavailable",
                "importance": importance,
                "channel": channel or "unknown",
                "source": source or "unknown",
                "reason": f"validation_error: {exc}",
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
            }


async def validate_fact(
    text: str,
    *,
    channel: str | None = None,
    source: str | None = None,
    importance: float = 5.0,
    enabled: bool = True,
    timeout: float = 8.0,
) -> dict[str, Any]:
    """便捷 async 入口。"""
    validator = MemoryFactValidator(enabled=enabled, timeout=timeout)
    return await validator.validate(
        text=text,
        channel=channel,
        source=source,
        importance=importance,
    )


def validation_enabled() -> bool:
    """读取 feature flag memory_write_validation_v1（商业测试版本默认开启）。"""
    try:
        from core.feature_flags import FeatureFlags

        return bool(FeatureFlags().is_enabled("memory_write_validation_v1"))
    except Exception:
        return False
