"""Aerie · 云栖 v9.0 — Semantic message splitter.

Splits long messages at natural boundaries (sentence ends, line breaks)
so multi-part sends feel human-like.
"""

from __future__ import annotations
import re

# Split points in priority order
_SPLIT_PATTERNS = [
    re.compile(r"(?<=[。！？\n])\s*"),
    re.compile(r"(?<=[.!?\n])\s*"),
    re.compile(r"(?<=[，；、\n])\s*"),
    re.compile(r"(?<=[,;\n])\s*"),
]

_DEFAULT_MAX_LEN = 200


class SemanticMessageSplitter:
    def __init__(self, max_len: int = _DEFAULT_MAX_LEN) -> None:
        self.max_len = max_len

    def split(self, text: str) -> list[str]:
        """Split text at sentence boundaries for natural multi-message delivery.

        Unlike v9.0 which only split >max_len, v9.1 always splits at
        sentence terminators (。！？ .!?\n) so multi-sentence replies
        arrive as separate messages with natural pacing.
        """
        # Always try sentence-level split
        for pattern in _SPLIT_PATTERNS:
            parts = pattern.split(text)
            if len(parts) > 1:
                merged = []
                for p in parts:
                    p = p.strip()
                    if not p:
                        continue
                    # Merge tiny fragments (< 8 chars) that aren't sentence-complete
                    if merged and (len(p) < 8 or not _is_sentence_end(p)) and len(merged[-1] + p) <= self.max_len:
                        merged[-1] += p
                    elif merged and not _is_sentence_end(merged[-1]) and len(merged[-1] + p) <= self.max_len:
                        merged[-1] += p
                    else:
                        merged.append(p)
                if merged:
                    return merged

        # Fallback: return as-is
        return [text]


def _is_sentence_end(text: str) -> bool:
    """Check if text ends with a sentence terminator."""
    return text and text[-1] in "。！？.!?\n"
