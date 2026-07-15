"""Aerie · 云栖 v9.0 — Context builder.

Assembles the LLM message list by combining:
- System prompt (persona + emotion + rules)
- Long-term memory top-K
- Knowledge base top-K
- Recent chat history
"""

from __future__ import annotations

from typing import Any, Optional

from communication.message import IncomingMessage, RouteMode
from config.persona_loader import load_persona


class ContextBuilder:
    """Builds the LLM context for a given user message."""

    def __init__(self, memory_store=None, knowledge_base=None) -> None:
        self.memory_store = memory_store
        self.knowledge_base = knowledge_base
        self.persona = load_persona()

    def _system_prompt(self, route_mode: RouteMode, mood: str = "neutral", pad: dict | None = None) -> str:
        base = self.persona.get("system_prompt", "")
        speech = self.persona.get("speech", {})
        taboo = speech.get("taboo_phrases", [])
        taboo_line = "、".join(taboo) if taboo else ""
        pad_line = ""
        if pad:
            pad_line = (
                f"\n\n[当前情绪状态] PAD: "
                f"P={pad.get('pleasure', 0):.2f} "
                f"A={pad.get('arousal', 0):.2f} "
                f"D={pad.get('dominance', 0):.2f} "
                f"label={mood}"
            )
        mode_line = f"\n\n[路由模式] {route_mode.value}"
        taboo_block = f"\n\n[禁止] 不得使用这些称谓：{taboo_line}" if taboo_line else ""
        return base + pad_line + mode_line + taboo_block

    def _memory_block(self, user_id: int, query: str, top_k: int = 5) -> str:
        if not self.memory_store:
            return ""
        try:
            mems = self.memory_store.search(user_id, query, top_k=top_k) or []
        except Exception:
            mems = []
        if not mems:
            return ""
        lines = ["[记忆]"]
        for m in mems:
            content = m.get("content", "") if isinstance(m, dict) else str(m)
            lines.append(f"- {content}")
        return "\n".join(lines)

    def _kb_block(self, query: str, top_k: int = 3) -> str:
        if not self.knowledge_base:
            return ""
        try:
            hits = self.knowledge_base.search(query, top_k=top_k) or []
        except Exception:
            hits = []
        if not hits:
            return ""
        lines = ["[知识库]"]
        for h in hits:
            title = h.get("title", "") if isinstance(h, dict) else ""
            content = h.get("content", "") if isinstance(h, dict) else str(h)
            lines.append(f"- {title}: {content}")
        return "\n".join(lines)

    def _history_block(self, history: list[dict]) -> str:
        if not history:
            return ""
        lines = ["[最近对话]"]
        for h in history[-8:]:
            role = h.get("role", "user")
            content = h.get("content", "")
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def build(
        self,
        user_id: int,
        user_msg: IncomingMessage | str,
        route_mode: RouteMode = RouteMode.FULL,
        history: Optional[list[dict]] = None,
        mood: str = "neutral",
        pad: Optional[dict] = None,
    ) -> list[dict]:
        """Build the full messages list for LLM."""
        if isinstance(user_msg, IncomingMessage):
            content = user_msg.content
        else:
            content = str(user_msg)

        system = self._system_prompt(route_mode, mood=mood, pad=pad)
        memory = self._memory_block(user_id, content, top_k=5)
        kb = self._kb_block(content, top_k=3)
        hist = self._history_block(history or [])

        # System message can be enriched with the meta blocks
        enriched_system = system
        for block in (memory, kb, hist):
            if block:
                enriched_system += "\n\n" + block

        messages = [
            {"role": "system", "content": enriched_system},
            {"role": "user", "content": content},
        ]
        return messages
