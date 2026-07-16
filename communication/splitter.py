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
        if len(text) <= self.max_len:
            return [text]

        for pattern in _SPLIT_PATTERNS:
            parts = pattern.split(text)
            if len(parts) > 1:
                merged = []
                for p in parts:
                    p = p.strip()
                    if not p:
                        continue
                    if merged and len(merged[-1] + p) <= self.max_len:
                        merged[-1] += p
                    else:
                        merged.append(p)
                if len(merged) > 1:
                    return merged

        # Force-split by max_len
        chunks = []
        for i in range(0, len(text), self.max_len):
            chunks.append(text[i : i + self.max_len])
        return chunks
