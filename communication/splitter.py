"""Aerie · 云栖 v0.1.0-beta.1 — Semantic message splitter (atomic-aware, R8.1).

Splits long messages at natural boundaries (sentence ends, line breaks)
so multi-part sends feel human-like. R8.1+ adds atomic-aware splitting:
``<action>...</action>``, ``<thought>...</thought>``, and ``【...】``
spans are treated as **indivisible units** — the splitter NEVER cuts
inside an atomic span, even if it contains sentence terminators (。！？).

Why this matters
----------------
The previous splitter cut at any ``。``, which broke ``<action>``
spans like::

    <action>伊塔把聊天窗口点开...灰蓝色的眼睛弯了一下。
    她靠在椅背上...指尖慢慢敲平。</action>你个表情……

into multiple segments, leaving the first ``<action>`` unclosed at
broadcast time and corrupting the chat UI. Industry practice (gramio,
langflow, langchain RecursiveCharacterTextSplitter) treats atomic
entities as indivisible; we follow the same convention.

Algorithm
---------
1. Use ``_ATOM_RE.finditer`` to locate all atomic spans.
2. Walk the text, emitting text fragments (which may be split at 。！？)
   and atomic spans (kept whole).
3. Merge tiny fragments (< 8 chars) with their neighbors, capped at
   ``max_len``.
"""

from __future__ import annotations
import re

# Atomic units: never split inside these. The two pseudo-tags plus
# full-width brackets (the LLM sometimes emits these instead of <action>).
_ATOM_RE = re.compile(
    r"<action>.*?</action>"
    r"|<thought>.*?</thought>"
    r"|【.*?】",
    re.DOTALL,
)

# Split points in priority order
_SPLIT_PATTERNS = [
    re.compile(r"(?<=[。！？\n])\s*"),
    re.compile(r"(?<=[.!?\n])\s*"),
    re.compile(r"(?<=[，；、\n])\s*"),
    re.compile(r"(?<=[,;\n])\s*"),
]

_DEFAULT_MAX_LEN = 200
_MIN_FRAGMENT_LEN = 8


class SemanticMessageSplitter:
    def __init__(self, max_len: int = _DEFAULT_MAX_LEN) -> None:
        self.max_len = max_len

    def split(self, text: str) -> list[str]:
        """Split text at sentence boundaries, never inside atomic spans.

        R8.1+ atomic-aware algorithm:
        1. Locate atomic spans (<action>, <thought>, 【...】).
        2. Build segments by walking the text and only splitting
           non-atomic fragments at sentence terminators.
        3. Merge tiny fragments (< 8 chars) with their neighbors
           while honoring max_len.
        """
        if not text:
            return [text] if text else []

        # Step 1: locate all atomic spans
        atoms = list(_ATOM_RE.finditer(text))
        if not atoms:
            return self._split_no_atoms(text)

        # Step 2: walk through text, alternating fragments and atoms
        segments: list[str] = []
        cursor = 0
        for atom in atoms:
            # Fragment before this atom (may be empty)
            if atom.start() > cursor:
                fragment = text[cursor:atom.start()]
                segments.extend(self._split_fragment(fragment))
            # Atom itself (always kept whole)
            segments.append(text[atom.start():atom.end()])
            cursor = atom.end()
        # Trailing fragment after the last atom
        if cursor < len(text):
            segments.extend(self._split_fragment(text[cursor:]))

        # Step 3: merge tiny fragments
        return self._merge_tiny(segments)

    def _split_no_atoms(self, text: str) -> list[str]:
        """Original split logic when there are no atomic spans."""
        for pattern in _SPLIT_PATTERNS:
            parts = pattern.split(text)
            if len(parts) > 1:
                merged = []
                for p in parts:
                    p = p.strip()
                    if not p:
                        continue
                    if (
                        merged
                        and (len(p) < _MIN_FRAGMENT_LEN or not _is_sentence_end(p))
                        and len(merged[-1] + p) <= self.max_len
                    ):
                        merged[-1] += p
                    elif (
                        merged
                        and not _is_sentence_end(merged[-1])
                        and len(merged[-1] + p) <= self.max_len
                    ):
                        merged[-1] += p
                    else:
                        merged.append(p)
                if merged:
                    return merged
        return [text]

    def _split_fragment(self, fragment: str) -> list[str]:
        """Split a non-atomic fragment by sentence terminators.

        Falls back to the original split logic but always returns a
        non-empty list (empty fragments short-circuit upstream).
        """
        fragment = fragment.strip()
        if not fragment:
            return []
        return self._split_no_atoms(fragment)

    def _merge_tiny(self, segments: list[str]) -> list[str]:
        """Merge tiny fragments (< 8 chars) with their neighbors."""
        if not segments:
            return []
        merged: list[str] = [segments[0]]
        for seg in segments[1:]:
            if not seg:
                continue
            # If this seg is tiny and the previous is not an atom, glue
            if (
                len(seg) < _MIN_FRAGMENT_LEN
                and merged
                and not _is_atom(merged[-1])
                and len(merged[-1] + seg) <= self.max_len
            ):
                merged[-1] += seg
                continue
            # If the previous seg is mid-sentence and we can fit, glue
            if (
                merged
                and not _is_atom(merged[-1])
                and not _is_sentence_end(merged[-1])
                and len(merged[-1] + seg) <= self.max_len
            ):
                merged[-1] += seg
                continue
            merged.append(seg)
        return merged


def _is_sentence_end(text: str) -> bool:
    """Check if text ends with a sentence terminator."""
    return text and text[-1] in "。！？.!?\n"


def _is_atom(text: str) -> bool:
    """Check if text is an atomic span (must never be split)."""
    return bool(text) and (
        text.startswith("<action>")
        or text.startswith("<thought>")
        or (text.startswith("【") and text.endswith("】"))
    )
