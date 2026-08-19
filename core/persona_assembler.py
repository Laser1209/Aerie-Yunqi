"""Shared persona prompt assembly for daily chat & proactive push.

Phase 0: thin-delegate façade over ``ContextBuilder`` (the single source of
truth for persona prompt layers), so daily dialogue and the proactive push
generator render persona through the *same* logic — one mouth, one persona,
no prompt drift.

Layers exposed here: L1 identity / L2 relationship / L4 language rules /
L4.5 expression freedom. The push mode additionally strips the L4.5 layers
that only apply to turn-taking dialogue.
"""

from __future__ import annotations

from .context_builder import ContextBuilder

_CB: ContextBuilder | None = None


def _cb() -> ContextBuilder:
    """Shared lightweight ContextBuilder instance (constructor is cheap)."""
    global _CB
    if _CB is None:
        _CB = ContextBuilder()
    return _CB


def build_l1_identity(persona: dict) -> str:
    """L1 · 核心身份层（委托 ContextBuilder，字节一致）。"""
    return _cb()._build_l1_identity(persona)


def build_l2_relationship(persona: dict) -> str:
    """L2 · 关系深度层（委托 ContextBuilder）。"""
    return _cb()._build_l2_relationship(persona)


def build_l4_language(persona: dict) -> str:
    """L4 · 语言铁律层（委托 ContextBuilder）。"""
    return _cb()._build_l4_language(persona)


def build_expression_freedom() -> str:
    """L4.5 · 表达自由（委托 ContextBuilder staticmethod）。"""
    return ContextBuilder._build_expression_freedom()


def build_persona_block(
    persona: dict,
    mode: str = "chat",
    *,
    include_relationship: bool = False,
) -> str:
    """Assemble the shared persona layers for a given mode.

    Args:
        persona: active persona dict from PersonaHub.
        mode: ``"chat"`` (default) keeps the full stack (identity + language
            + expression freedom); ``"push"`` keeps identity + language only.
        include_relationship: include the L2 relationship layer (FULL chat
            mode, and push may opt in for tone grounding).

    Returns:
        Plain-text persona block.
    """
    parts = [build_l1_identity(persona)]
    if include_relationship:
        parts.append(build_l2_relationship(persona))
    parts.append(build_l4_language(persona))
    if mode != "push":
        parts.append(build_expression_freedom())
    return "\n\n".join(parts)