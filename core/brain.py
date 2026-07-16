"""Aerie · 云栖 v9.0 — Brain: multi-provider LLM call layer with fallback chain."""

from __future__ import annotations
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from core.token_tracker import get_token_tracker

logger = logging.getLogger(__name__)


@dataclass
class BrainResponse:
    text: str
    provider: str = ""
    model: str = ""
    tokens_prompt: int = 0
    tokens_completion: int = 0
    duration_ms: int = 0
    # Phase 9 Batch 6: ReAct trace (model-emitted or synthesized downstream).
    # Shape: {"thought": str|None, "action": str, "observation": str|None, "react_source": str}
    # react_source in {"model", "synthesized", "model-no-think"}
    react_trace: dict | None = None


class Brain:
    """Multi-provider AI brain with fallback chain.

    Tries providers in order. Falls back to the next on failure.
    Each call is recorded via TokenTracker.
    """

    def __init__(self) -> None:
        self._temperature = float(os.getenv("LLM_TEMPERATURE", "0.7"))
        self._max_tokens = int(os.getenv("LLM_MAX_TOKENS", "2048"))
        self._providers = self._load_providers()

    def _load_providers(self) -> list[dict]:
        """Load provider configs from env vars."""
        providers = []

        # Primary: SiliconFlow
        sf_key = os.getenv("OPENAI_API_KEY", "")
        sf_url = os.getenv("OPENAI_BASE_URL", "https://api.siliconflow.cn/v1")
        sf_model = os.getenv("OPENAI_MODEL", "Qwen/Qwen2.5-7B-Instruct")
        if sf_key:
            providers.append({
                "name": "siliconflow",
                "url": sf_url,
                "key": sf_key,
                "model": sf_model,
            })

        # Fallback: DeepSeek
        ds_key = os.getenv("DEEPSEEK_API_KEY", "")
        ds_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
        ds_model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        if ds_key:
            providers.append({
                "name": "deepseek",
                "url": ds_url,
                "key": ds_key,
                "model": ds_model,
            })

        # Secondary fallback: SiliconFlow free models
        sf_free_model = os.getenv("SILICONFLOW_FREE_MODEL", "")
        if sf_free_model and sf_key:
            providers.append({
                "name": "siliconflow-free",
                "url": sf_url,
                "key": sf_key,
                "model": sf_free_model,
            })

        # Tertiary fallback: Qwen (DashScope)
        qw_key = os.getenv("DASHSCOPE_API_KEY", "")
        if qw_key:
            providers.append({
                "name": "qwen",
                "url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "key": qw_key,
                "model": "qwen-plus",
            })

        if not providers:
            logger.warning("No LLM providers configured! Set OPENAI_API_KEY or DEEPSEEK_API_KEY.")

        return providers

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> BrainResponse:
        """Send chat completion request, try all providers in sequence.

        On failure of all providers, returns a fallback response.
        """
        last_error = ""
        tracker = get_token_tracker()

        for idx, provider in enumerate(self._providers):
            try:
                resp = await self._call_provider(provider, messages, tools)
                if resp.text and not resp.text.startswith("(连接") and not resp.text.startswith("(思考"):
                    # Success — record token usage
                    if tracker._db is not None:
                        tracker.record(
                            provider=resp.provider,
                            model=resp.model,
                            prompt_tokens=resp.tokens_prompt,
                            completion_tokens=resp.tokens_completion,
                            user_id=0,
                        )
                    logger.info(
                        "LLM: %s/%s → %d+%d tokens, %dms",
                        resp.provider, resp.model,
                        resp.tokens_prompt, resp.tokens_completion,
                        resp.duration_ms,
                    )
                    return resp
                else:
                    # Got a fallback response from the provider itself
                    last_error = resp.text
                    logger.warning(
                        "Provider %s returned fallback: %s",
                        provider["name"], last_error[:60],
                    )
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "Provider %s failed (%d/%d): %s",
                    provider["name"], idx + 1, len(self._providers), last_error[:80],
                )

        logger.error("All %d providers failed. Last error: %s", len(self._providers), last_error)
        return BrainResponse(text="(伊塔暂时无法连接大脑，稍后再试...)")

    async def _call_provider(
        self,
        provider: dict,
        messages: list[dict],
        tools: list[dict] | None,
    ) -> BrainResponse:
        """Call a single provider."""
        body: dict[str, Any] = {
            "model": provider["model"],
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {provider['key']}",
            "Content-Type": "application/json",
        }

        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{provider['url']}/chat/completions",
                json=body,
                headers=headers,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")

            data = resp.json()
            choice = data["choices"][0]
            message = choice.get("message", {})

            # Phase 9 Batch 6: detect tool_calls so we can mark the react action
            tool_calls_present = bool(message.get("tool_calls"))

            # Handle tool calls
            if tool_calls_present:
                text = json.dumps(message["tool_calls"], ensure_ascii=False)
            else:
                text = message.get("content", "") or ""

            usage = data.get("usage", {})
            duration = int((time.monotonic() - t0) * 1000)

            # Phase 9 Batch 6: extract <think> block + classify action for react_trace.
            # Tags: "model" = LLM emitted a real <think> block;
            #       "model-no-think" = LLM responded without a <think> block (downstream synthesis).
            react_trace = _build_react_from_text(text, tool_calls_present)

            return BrainResponse(
                text=text.strip(),
                provider=provider["name"],
                model=provider["model"],
                tokens_prompt=usage.get("prompt_tokens", 0),
                tokens_completion=usage.get("completion_tokens", 0),
                duration_ms=duration,
                react_trace=react_trace,
            )

    async def generate_push(
        self,
        template: str,
        mood: str = "neutral",
        **kwargs,
    ) -> str:
        """Generate a proactive push message using a template with mood awareness.

        Sends a lightweight system prompt to the LLM asking it to fill the
        template in a mood-appropriate style. Falls back to raw template
        filling on provider failure.
        """
        system_msg = (
            f"You are writing a short push notification. "
            f"Current mood: {mood}. "
            f"Keep it under 60 characters. Be natural and warm. "
            f"Do NOT add greeting prefixes or explanations. "
            f"Just output the message text directly."
        )
        user_msg = template.format(**kwargs) if kwargs else template

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]

        try:
            resp = await self.chat(messages)
            if resp.text and not resp.text.startswith("(伊塔"):
                return resp.text.strip()
        except Exception:
            pass

        # Fallback: plain template fill
        try:
            return template.format(**kwargs)
        except (KeyError, ValueError):
            return template


# ── ReAct trace extraction (Phase 9 Batch 6) ─────────────────
import re as _re

_THINK_PATTERN = _re.compile(r"<think>(.*?)</think>", flags=_re.DOTALL)


def _classify_action(thought: str | None, tool_calls_present: bool) -> str:
    """Map a (possibly empty) thought + tool-call presence to a ReAct action."""
    if tool_calls_present:
        return "tool_call"
    if not thought:
        return "reply"
    low = thought.lower()
    if "tool" in low or "调用" in thought:
        return "tool_call"
    if "silent" in low or "沉默" in thought or "不说话" in thought or "撤回" in thought:
        return "silence"
    if "recall" in low or "撤回消息" in thought:
        return "recall"
    return "reply"


def _build_react_from_text(text: str, tool_calls_present: bool) -> dict:
    """Build react_trace dict from raw LLM output.

    Tags:
      - "model"           : LLM emitted a real <think>…</think> block; thought is preserved.
      - "model-no-think"  : LLM responded but did not emit <think>; thought is None.
                            Downstream pipeline will synthesize a thought from stage data.

    Always returns a dict so the brain contract is uniform; no-op reactions
    (e.g. fallback "(伊塔暂时无法连接大脑...)") are tagged with react_source="fallback".
    """
    if not text:
        return {
            "thought": None,
            "action": "silence",
            "observation": "empty_response",
            "react_source": "fallback",
        }
    # Skip react extraction on provider fallback markers — those aren't real model output.
    if text.startswith("(连接") or text.startswith("(思考") or text.startswith("(伊塔暂时"):
        return {
            "thought": None,
            "action": "silence",
            "observation": text[:200],
            "react_source": "fallback",
        }
    m = _THINK_PATTERN.search(text)
    thought = m.group(1).strip() if m else None
    action = _classify_action(thought, tool_calls_present)
    if thought:
        return {
            "thought": thought,
            "action": action,
            "observation": f"text_chars={len(text)}, thought_chars={len(thought)}",
            "react_source": "model",
        }
    return {
        "thought": None,
        "action": action,
        "observation": f"text_chars={len(text)}, no_think_block",
        "react_source": "model-no-think",
    }
