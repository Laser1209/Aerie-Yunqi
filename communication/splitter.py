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

Intent-first splitting (模型自报条数)
---------------------------------
切点由谁决定，决定了「像不像人」。旧逻辑里模型只写一整段，切点全靠
标点猜；现在系统提示词（``core.context_builder.OUTPUT_IRON_RULE``）
要求模型用「单独一行 ``---``」自己划出消息边界，``split()`` 优先按它
分条，模型没照做时再回退到标点切分：条数和每条说什么由模型决定，
程序只负责兜底。

Algorithm
---------
1. 先找模型自报的边界（``_INTENT_SEP_RE``；落在围栏代码块或原子段内的
   分隔符不算——它们分别是代码内容与原子段内容，绝不是消息边界）；
   命中 ≥2 条就按它分，超长单条再按下面的原子感知逻辑切。
2. 没命中时回退标点切分：用 ``_ATOM_RE.finditer`` 定位所有原子 span。
3. Walk the text, emitting text fragments (which may be split at 。！？)
   and atomic spans (kept whole).
4. Merge tiny fragments (< 8 chars) with their neighbors, capped at
   ``max_len``.

``split()`` 返回空列表 = 没有可外发内容（空文本 / 纯空白 / 去掉分隔符后
什么都不剩）。调用方不得把空结果回退成原文，否则用户会看到裸 ``---``。
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

# 模型自报的消息边界：单独一行写 3 个以上连字符（Markdown 分隔线）。
# 选它的理由：模型对 Markdown 分隔线极熟（遵循率高）、单行零成本、中文正文
# 里不会自然出现（比空行/编号更不容易误判），且万一解析漏了也只是多一行横线，
# 不会像自定义标签那样把怪标记漏给用户。
_INTENT_SEP_RE = re.compile(r"^[^\S\n]*-{3,}[^\S\n]*$", re.MULTILINE)
# 围栏代码块：块内的 ---（YAML front matter / 正文分隔线）是代码内容，不是消息边界。
# 末尾用 (?:```|\Z) 而非要求成对：未闭合围栏里的 --- 同样是代码内容，
# 一旦按「没闭合就当普通文本」处理，就会把用户贴的代码从中间切开。
_FENCE_RE = re.compile(r"```.*?(?:```|\Z)", re.DOTALL)


class SemanticMessageSplitter:
    def __init__(self, max_len: int = _DEFAULT_MAX_LEN, max_segments: int = 0) -> None:
        self.max_len = max_len
        # >0 时限制单次外发条数：相邻段落就近并成 N 条，不丢内容、也不攒成一大段。
        # 0 = 不限制（保持既有行为）。
        self.max_segments = max(0, int(max_segments))

    def split(self, text: str) -> list[str]:
        """Split text into outbound messages, never inside atomic spans.

        模型自报条数优先（见模块 docstring）：命中单独一行的 ``---`` 就按它
        分条（分隔符落在原子段/围栏代码块内时忽略，绝不切开它们），条数超过
        ``max_segments`` 时由 ``_cap_segments`` 就近平摊收敛。没有可用分隔符时
        回退到既有的原子感知标点切分——缺分隔符绝不丢内容。

        返回空列表 = 没有可外发内容。调用方必须照此「不发」，不得回退成原文。
        """
        if not text or not text.strip():
            return []
        intended = self._split_by_intent(text)
        if intended is not None:
            if len(intended) >= 2:
                return self._cap_segments(self._expand_overlong(intended))
            # 只切出一条（或分隔符之外没有内容）：分隔符本身不是内容，剔除后走默认逻辑
            if not intended:
                return []
            text = intended[0]
        return self._cap_segments(self._split_uncapped(text))

    def _split_by_intent(self, text: str) -> list[str] | None:
        """按模型自报的边界（单独一行 ``---``）分条。

        返回 None = 模型没按约定输出（或分隔符只出现在围栏代码块 / 原子段里）
        ——调用方必须回退到标点切分。空片段（如描写被净化后剩下的空行）会被
        丢弃，不留空气泡。

        分隔符优先级高，但不得切开原子单位（``<action>`` / ``<thought>`` /
        ``【】``）与围栏代码块：落在它们内部的 ``---`` 只是内容。
        """
        if not text:
            return None
        protected = [m.span() for m in _FENCE_RE.finditer(text)]
        protected += [m.span() for m in _ATOM_RE.finditer(text)]
        separators = [
            m for m in _INTENT_SEP_RE.finditer(text)
            if not any(start <= m.start() < end for start, end in protected)
        ]
        if not separators:
            return None
        parts: list[str] = []
        cursor = 0
        for sep in separators:
            parts.append(text[cursor:sep.start()])
            cursor = sep.end()
        parts.append(text[cursor:])
        return [part.strip() for part in parts if part.strip()]

    def _expand_overlong(self, parts: list[str]) -> list[str]:
        """模型自报的单条超过 ``max_len`` 时按原子感知逻辑再切。

        气泡边界归模型，但单条仍不得变回「文字墙」；切分不丢内容。
        """
        expanded: list[str] = []
        for part in parts:
            if len(part) > self.max_len:
                expanded.extend(self._split_uncapped(part) or [part])
            else:
                expanded.append(part)
        return expanded

    def _split_uncapped(self, text: str) -> list[str]:
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

    def _cap_segments(self, segments: list[str]) -> list[str]:
        """把段落数压到 ``max_segments`` 以内，且不让任何一条变成一大段。

        做法：按字符数把相邻段落就近收进 N 个桶（目标 = 总长度 / N），
        而不是把溢出全部塞进最后一条——后者会产出一面文字墙，等于把
        「分段发送」又退回成「一条长文」，正好是本次要修掉的反模式。
        """
        if self.max_segments <= 0 or len(segments) <= self.max_segments:
            return segments

        total = sum(len(seg) for seg in segments)
        target = max(1, -(-total // self.max_segments))  # ceil，尽量均分
        buckets: list[str] = []
        current = ""
        for seg in segments:
            if current and len(current) >= target and len(buckets) < self.max_segments - 1:
                buckets.append(current)
                current = ""
            current += seg
        if current:
            buckets.append(current)
        return buckets

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
