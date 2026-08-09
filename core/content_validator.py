"""Aerie · 云栖 v0.1.0-beta.1 — Content Validator (正文内容强制校验).

Ensures that every LLM response contains meaningful conversational text
after stripping <thought> and <action> tags. If the response is empty
after tag removal, attempts a single regeneration via brain.chat();
if that also fails, falls back to a randomly chosen short reply.

Integration point in Pipeline:
  screen_action_sanitizer → output_self_check → **content_validator** → response_validator

Works for both single-message and batch modes.
"""

from __future__ import annotations

import logging
import random
from typing import Any

from communication.qq_client import strip_thought_action_tags

logger = logging.getLogger(__name__)


FALLBACK_REPLIES: tuple[str, ...] = (
    "嗯？",
    "在听",
    "怎么了？",
    "哦？",
    "继续说",
    "我在呢",
    "嗯嗯",
    "啊？",
)


def has_meaningful_content(text: str) -> bool:
    """Check if text contains non-whitespace content after stripping tags.

    Uses the same tag-stripping logic as qq_client.strip_thought_action_tags
    to ensure consistency between validation and final output filtering.

    Args:
        text: Raw LLM response text (may contain <thought>/<action> tags).

    Returns:
        True if there is actual conversational content after tag removal.
    """
    if not text:
        return False
    stripped = strip_thought_action_tags(text)
    return bool(stripped and stripped.strip())


class ContentValidator:
    """Validates that LLM output contains meaningful conversational text.

    If the response is empty after tag removal, attempts one regeneration
    via brain.chat() with a focused prompt. Falls back to a short reply
    if regeneration also produces no content or fails.
    """

    def __init__(self, brain: Any) -> None:
        """Initialize with a LLMCaller instance for regeneration.

        Args:
            brain: core.llm_caller.LLMCaller instance (or compatible) with chat() method.
        """
        self.brain = brain
        self._metrics = {
            "total": 0,
            "ok": 0,
            "regenerated": 0,
            "fallback_used": 0,
            "brain_errors": 0,
        }

    async def validate_and_fix(
        self,
        content: str,
        context: dict | None = None,
        batch_id: str | None = None,
        sequence_index: int | None = None,
    ) -> tuple[str, bool]:
        """Validate content and fix if it has no meaningful text.

        Args:
            content: Raw LLM response text.
            context: Optional dict with 'history', 'emotion', 'last_user_message', etc.
            batch_id: Optional batch ID for logging in batch mode.
            sequence_index: Optional sequence index for batch mode logging.

        Returns:
            (corrected_content, was_remedied)
            - corrected_content: The validated (or replaced) content.
            - was_remedied: True if regeneration or fallback was used.
        """
        self._metrics["total"] += 1
        ctx = context or {}
        last_user_message = ctx.get("last_user_message", "")

        batch_prefix = ""
        if batch_id is not None:
            seq_part = f" seq={sequence_index}" if sequence_index is not None else ""
            batch_prefix = f"[Batch {batch_id}{seq_part}] "

        if has_meaningful_content(content):
            self._metrics["ok"] += 1
            return content, False

        logger.warning(
            "%sContent has no meaningful text after tag stripping; attempting regeneration",
            batch_prefix,
        )

        regenerated = await self._try_regenerate(last_user_message, batch_prefix)
        if regenerated is not None and has_meaningful_content(regenerated):
            self._metrics["regenerated"] += 1
            logger.warning(
                "%sRegeneration succeeded; using regenerated content",
                batch_prefix,
            )
            return regenerated, True

        fallback = random.choice(FALLBACK_REPLIES)
        self._metrics["fallback_used"] += 1
        logger.warning(
            "%sRegeneration failed or produced empty content; using fallback reply: %r",
            batch_prefix,
            fallback,
        )
        return fallback, True

    async def _try_regenerate(
        self,
        last_user_message: str,
        batch_prefix: str,
    ) -> str | None:
        """Attempt a single lightweight regeneration via brain.chat().

        Args:
            last_user_message: The last message from the user for context.
            batch_prefix: Log prefix for batch identification.

        Returns:
            Regenerated text or None on failure.
        """
        if not self.brain:
            logger.warning("%sNo brain instance available; skipping regeneration", batch_prefix)
            return None

        system_msg = (
            "你是伊塔（Ita），正在通过QQ和用户聊天。"
            "你刚才的回复只包含了动作或心理描写，没有说出实际的对话内容。"
            "请只用自然语言对话正文回复，不要输出<action>或<thought>标签。"
            "直接说你想说的话，保持你的人设语气。"
        )
        user_msg = last_user_message if last_user_message else "（用户刚才没有说话，请简短回应）"

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]

        try:
            from communication.qq_client import strip_thought_action_tags as _strip
            resp = await self.brain.chat(messages)
            text = getattr(resp, "text", "") or ""
            return _strip(text)
        except Exception as e:
            self._metrics["brain_errors"] += 1
            logger.warning(
                "%sRegeneration brain call failed: %s",
                batch_prefix,
                str(e)[:120],
            )
            return None

    def get_metrics(self) -> dict[str, int]:
        """Return current validation metrics snapshot."""
        return dict(self._metrics)

    def reset_metrics(self) -> None:
        """Reset metrics counters."""
        for key in self._metrics:
            self._metrics[key] = 0


_CONTENT_VALIDATOR_SINGLETON: ContentValidator | None = None


def get_content_validator(brain: Any | None = None) -> ContentValidator:
    """Get or create the global ContentValidator singleton.

    Args:
        brain: LLMCaller instance (required on first call; ignored on subsequent calls).

    Returns:
        ContentValidator instance.
    """
    global _CONTENT_VALIDATOR_SINGLETON
    if _CONTENT_VALIDATOR_SINGLETON is None:
        if brain is None:
            raise ValueError("brain instance is required when creating ContentValidator singleton")
        _CONTENT_VALIDATOR_SINGLETON = ContentValidator(brain)
    return _CONTENT_VALIDATOR_SINGLETON
