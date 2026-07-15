"""Aerie · 云栖 v9.0 — Semantic message splitter.

Splits long OutgoingReply content into multiple short segments to
mimic human chat rhythm. Each segment ends with a sentence-final
punctuation mark.
"""

from __future__ import annotations

import re
from typing import Optional


# Tunable per scene. Per spec R12.
SPLIT_THRESHOLDS = {
    "emotional": 40,
    "daily": 60,
    "proactive": 80,
    "report": 100,
    "urgent": 120,
}

# Sentence-final punctuation. Suffixes if missing.
SENTENCE_END = ("。", "！", "？", "…", ".")
LIST_BULLETS = ("•", "·", "—", "-", "①", "②", "③", "④", "⑤")
TRANSITION_PHRASES = [
    "然后", "于是", "不过", "另外", "还有", "接着",
    "更重要的是", "说实话", "总之", "所以",
]


class SemanticMessageSplitter:
    """Eight segmentation strategies, applied in order."""

    def __init__(self, thresholds: Optional[dict] = None) -> None:
        self.thresholds = {**SPLIT_THRESHOLDS, **(thresholds or {})}

    def _ends_with_punct(self, s: str) -> bool:
        return s.rstrip().endswith(SENTENCE_END)

    def _ensure_period(self, s: str) -> str:
        s = s.rstrip()
        if not s:
            return s
        if self._ends_with_punct(s):
            return s
        if s.endswith(tuple(LIST_BULLETS)):
            return s + "。"
        return s + "。"

    def _split_by_double_newline(self, text: str) -> list[str]:
        parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        return parts

    def _split_by_single_newline(self, text: str) -> list[str]:
        parts = [p.strip() for p in text.split("\n") if p.strip()]
        return parts

    def _split_by_sentence(self, text: str) -> list[str]:
        # Split on 。！？ but keep the punctuation.
        pattern = r"([^。！？!?]+[。！？!?])"
        parts = [p.strip() for p in re.findall(pattern, text)]
        if not parts:
            return [text.strip()]
        return parts

    def _split_by_list_bullet(self, text: str) -> list[str]:
        # Split on bullet markers.
        pattern = r"[•·—\-]|\d+[.、)]"
        parts = re.split(f"({pattern})", text)
        # Re-attach bullet prefix to following text
        out: list[str] = []
        current = ""
        for p in parts:
            if not p:
                continue
            if re.fullmatch(pattern, p):
                current += p
            else:
                current += p
                out.append(current.strip())
                current = ""
        if current.strip():
            out.append(current.strip())
        return out

    def _split_by_transition(self, text: str) -> list[str]:
        for phrase in TRANSITION_PHRASES:
            if phrase in text:
                idx = text.index(phrase)
                if idx > 4:  # Avoid tiny fragments
                    left = text[:idx].rstrip()
                    right = text[idx:].lstrip()
                    return [left, right]
        return []

    def _split_by_quote(self, text: str) -> list[str]:
        if '"' in text:
            parts = text.split('"')
            return [p.strip() for p in parts if p.strip()]
        return []

    def _split_by_semicolon(self, text: str) -> list[str]:
        if "；" in text or "; " in text:
            parts = re.split(r"[；;]\s*", text)
            return [p.strip() for p in parts if p.strip()]
        return []

    def _split_by_comma(self, text: str) -> list[str]:
        if "，" in text:
            parts = re.split(r"，\s*", text)
            return [p.strip() for p in parts if p.strip()]
        return []

    def split(self, text: str, msg_type: str = "daily") -> list[str]:
        """Split text into ≤ threshold-length segments.

        Returns at least 1 segment. Each ends with a final punctuation.
        """
        if not text or not text.strip():
            return []

        threshold = self.thresholds.get(msg_type, 60)
        text = text.strip()

        if len(text) <= threshold:
            return [self._ensure_period(text)]

        segments: list[str] = []
        # Try strategies in order until threshold is met
        for strategy in (
            self._split_by_double_newline,
            self._split_by_single_newline,
            self._split_by_list_bullet,
            self._split_by_quote,
            self._split_by_transition,
            self._split_by_semicolon,
            self._split_by_sentence,
            self._split_by_comma,
        ):
            parts = strategy(text)
            if len(parts) >= 2 and all(len(p) <= threshold * 1.5 for p in parts):
                segments = parts
                break

        if not segments:
            # Force-cut at threshold
            segments = []
            for i in range(0, len(text), threshold):
                segments.append(text[i : i + threshold])

        # If any single segment is still over threshold, force-cut
        refined: list[str] = []
        for seg in segments:
            if len(seg) <= threshold:
                refined.append(seg)
            else:
                for i in range(0, len(seg), threshold):
                    refined.append(seg[i : i + threshold])

        # Ensure punctuation
        refined = [self._ensure_period(s) for s in refined if s.strip()]
        return refined
