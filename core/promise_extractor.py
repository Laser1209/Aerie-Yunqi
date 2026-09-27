"""Aerie · PromiseExtractor — 承诺提取（Promise Beats 子系统，第 ② 段）.

在【她自己的回复】落定后，判断这段话里有没有一个她能在不久后独立兑现的承诺
（典型："好几天闷家里了 想出去走走" → 一两小时后她在外面的照片）。

两层闸门：
- L1 确定性扫描（纯函数，零成本）：硬性反模式（疑问/假设/回忆/收尾/依赖对方/
  否定）一票否决；正面模式给出高/中置信；
- L2 轻量语义确认（siliconflow-light，约 1-2s）：对 L1 命中的文本做最终裁决，
  可推翻 L1，同时给出归纳、地点与延迟。fail-closed：L2 不可用时仅放行 L1
  高置信，宁可不提取也不误提取。

本模块不排期、不触发行为；产出 ``PromiseMatch`` 交给上层写入 BeatStore。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional, Protocol

# ── L1 词表与模式 ────────────────────────────────────────

# 硬性反模式：结构上不可能是“她 1-3 小时内独立兑现的承诺”。
_HARD_VETO = (
    r"[?？]",                                  # 疑问标点
    r"(吗|嘛|呢)\s*[。.！!~～\s]*$",           # 疑问助词收尾
    r"要是|如果|假如|倘若|的话|改天",          # 假设
    r"等[^。\n]{0,8}再",                       # “等天晴了再去”——时间不确定
    r"昨天|前天|上周|上回|上次|刚去|去过|已经去",  # 回忆
    r"等你|陪我|带你|和你一起|跟你一起|你回来|你来了|你有空|咱们一起",  # 依赖对方
    r"不想|不去|出不去|不去了|懒得|不出去|没法出去",  # 否定
)

# 收尾词（话轮让渡，不是承诺）。复用 topic_tracker 的定义。
from core.topic_tracker import CLOSURE_WORDS  # noqa: E402

# 高置信正面模式：明确的自身出门动作。
_HIGH_POSITIVE = (
    r"(想|要)(出去|出门|到外面|去外头|下楼)",
    r"出去(走走|逛逛|晃一晃|透透气|溜达|转转|走一走|晃一圈)",
    r"下楼(走走|逛逛|透透气|溜达|转转)",
    r"出门(透透气|溜达|转转|走走|逛逛)",
)

# 中置信：表达闷久了 / 想去某地的愿望，但未必形成明确动作。
_MEDIUM_POSITIVE = (
    r"好(几|久)[^。\n]{0,4}没(出门|出去)",
    r"想去(江边|公园|湖边|湖边步道|街上|超市|商场|菜市场|咖啡店|书店|外面|外头)",
)

# 软性不确定：不否决，但把高置信降为中置信。
_SOFT_UNCERTAIN = r"吧\s*$|可能|也许|好像|似乎|说不定"

# 可捕获的地点提示。
_PLACE_HINT = re.compile(
    r"(江边|江边步道|湖边|湖边步道|公园|街上|超市|商场|菜市场|咖啡店|书店)"
)


@dataclass
class L1Verdict:
    kind: str
    topic: str
    place_hint: str
    high_confidence: bool


@dataclass
class PromiseMatch:
    kind: str           # 第一版仅 go_out
    topic: str          # ≤10 字归纳
    place_hint: str
    delay_sec: float    # 60-180 分钟
    source_text: str
    confidence: str     # confirmed（L2 确认）/ high（L1 高置信，L2 不可用）


def l1_scan(text: str) -> Optional[L1Verdict]:
    """L1 确定性扫描。命中硬性反模式或无任何正面模式 → None。"""
    candidate = str(text or "").strip()
    if not candidate:
        return None
    for pattern in _HARD_VETO:
        if re.search(pattern, candidate):
            return None
    if _has_standalone_closure(candidate):
        return None

    high_hit = _first_match(_HIGH_POSITIVE, candidate)
    medium_hit = _first_match(_MEDIUM_POSITIVE, candidate)
    if high_hit is None and medium_hit is None:
        return None

    soft = bool(re.search(_SOFT_UNCERTAIN, candidate))
    place = _PLACE_HINT.search(candidate)
    return L1Verdict(
        kind="go_out",
        topic=_short_topic(high_hit or medium_hit),
        place_hint=place.group(1) if place else "",
        high_confidence=high_hit is not None and not soft,
    )


def _first_match(patterns: tuple[str, ...], text: str) -> Optional[str]:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None


# 收尾词两侧允许的边界。“太好了”里的“好了”前面是“太”，不构成独立语气成分。
_SEP = set(" ，。！？、\n,.;！：:")
_CLOSURE_TAIL = set("吧嘛")


def _has_standalone_closure(text: str) -> bool:
    """收尾词是否作为独立语气成分出现（防“太好了/病好了”误伤）。

    宁可少否决：不独立的命中交给 L2 裁决，安全不受影响。
    """
    for word in CLOSURE_WORDS:
        for match in re.finditer(re.escape(word), text):
            before_ok = match.start() == 0 or text[match.start() - 1] in _SEP
            tail = text[match.end()] if match.end() < len(text) else ""
            after_ok = tail == "" or tail in _SEP or tail in _CLOSURE_TAIL
            if before_ok and after_ok:
                return True
    return False


def _short_topic(phrase: str) -> str:
    """把命中短语规整成 ≤10 字的话题。"""
    phrase = str(phrase or "").strip()
    if len(phrase) <= 10:
        return phrase
    return phrase[:10]


# ── L2 客户端协议与生产实现 ──────────────────────────────

class PromiseL2Client(Protocol):
    async def confirm(self, text: str) -> Optional[dict[str, Any]]:
        """返回 L2 判定 dict；服务不可用/超时/坏 JSON → None。"""


_L2_SYSTEM = (
    "你是对话语义分析器。判断下面这段女性发给恋人的话，是否包含一个"
    "【她自己能在接下来1到3小时内独立兑现的承诺】"
    "（典型：她说想出门、出去走走、去某个地方透气）。\n"
    "必须同时满足：1 是她本人的打算或计划，不是疑问、不是假设、不是回忆、"
    "不是需要对方参与或等对方的事；2 在1到3小时内可以开始兑现。\n"
    "只输出一个JSON对象，不要任何其他文字：\n"
    '{"is_promise": true 或 false, "kind": "go_out", '
    '"topic": "不超过10字的中文归纳", "place_hint": "具体地点或空字符串", '
    '"delay_min": 60到180之间的整数}\n'
    "不能确定时 is_promise 填 false。"
)


class SiliconFlowLightPromiseClient:
    """生产 L2 客户端：复用 siliconflow-light（生图提示词接力同款）。"""

    def __init__(self, *, brain: Any, timeout_sec: float = 8.0) -> None:
        self._brain = brain
        self._timeout = float(timeout_sec)

    async def confirm(self, text: str) -> Optional[dict[str, Any]]:
        import asyncio

        try:
            raw = await asyncio.wait_for(
                self._brain.chat(
                    [
                        {"role": "system", "content": _L2_SYSTEM},
                        {"role": "user", "content": str(text)},
                    ],
                    preferred_provider="siliconflow-light",
                    temperature=0.2,
                ),
                timeout=self._timeout,
            )
        except Exception:
            return None
        return _parse_json_object(getattr(raw, "text", raw))


def _parse_json_object(value: Any) -> Optional[dict[str, Any]]:
    if not isinstance(value, str):
        return None
    start, end = value.find("{"), value.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(value[start : end + 1])
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


# ── 提取器 ───────────────────────────────────────────────

class PromiseExtractor:
    """组合 L1 + L2，产出 PromiseMatch。"""

    def __init__(
        self,
        *,
        l2_client: Optional[PromiseL2Client] = None,
        default_delay_sec: float = 5400.0,     # 90 分钟
        delay_min_sec: float = 3600.0,        # 60 分钟
        delay_max_sec: float = 10800.0,       # 180 分钟
        clock: Any = None,
    ) -> None:
        self._l2 = l2_client
        self._default_delay = float(default_delay_sec)
        self._delay_min = float(delay_min_sec)
        self._delay_max = float(delay_max_sec)
        self._clock = clock

    async def extract_from_reply(self, text: str) -> Optional[PromiseMatch]:
        source = str(text or "").strip()
        verdict = l1_scan(source)
        if verdict is None:
            return None

        if self._l2 is None:
            return self._high_confidence_match(verdict, source, "high")

        l2 = await self._l2.confirm(source)
        if l2 is None or "is_promise" not in l2:
            # L2 不可用或返回畸形：仅 L1 高置信放行。
            return self._high_confidence_match(verdict, source, "high")
        if not bool(l2["is_promise"]):
            return None  # L2 拥有最终否决权。

        return PromiseMatch(
            kind=str(l2.get("kind") or verdict.kind),
            topic=_clamped_str(l2.get("topic"), verdict.topic, 10),
            place_hint=str(l2.get("place_hint") or verdict.place_hint),
            delay_sec=self._clamp_delay(l2.get("delay_min")),
            source_text=source,
            confidence="confirmed",
        )

    def _high_confidence_match(
        self, verdict: L1Verdict, source: str, confidence: str
    ) -> Optional[PromiseMatch]:
        if not verdict.high_confidence:
            return None
        return PromiseMatch(
            kind=verdict.kind,
            topic=verdict.topic,
            place_hint=verdict.place_hint,
            delay_sec=self._default_delay,
            source_text=source,
            confidence=confidence,
        )

    def _clamp_delay(self, delay_min: Any) -> float:
        try:
            seconds = float(delay_min) * 60.0
        except (TypeError, ValueError):
            return self._default_delay
        return min(self._delay_max, max(self._delay_min, seconds))


def _clamped_str(value: Any, fallback: str, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    return text[:limit]
