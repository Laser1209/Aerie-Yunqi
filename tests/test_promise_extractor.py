"""Unit tests: PromiseExtractor (L1 scan + L2 gating)."""
from __future__ import annotations

import pytest

from core.promise_extractor import L1Verdict, PromiseExtractor, l1_scan


# ── L1 正例：高置信 ─────────────────────────────────────

@pytest.mark.parametrize(
    "text,expected_topic",
    [
        ("好几天闷在家里了 我想出去走走", "想出去"),
        ("我想出门透透气", "想出门"),
        ("想出去逛逛", "想出去"),
        ("今天光太好了 下楼走走", "下楼走走"),
        ("太好了 下楼走走", "下楼走走"),
        ("出去溜达一圈", "出去溜达"),
    ],
)
def test_l1_high_confidence_promises(text, expected_topic):
    verdict = l1_scan(text)
    assert verdict is not None
    assert verdict.kind == "go_out"
    assert verdict.high_confidence is True
    assert expected_topic in verdict.topic


# ── L1 正例：中置信 ─────────────────────────────────────

def test_l1_medium_stuck_at_home():
    verdict = l1_scan("好几天没出门了 人都快废了")
    assert verdict is not None
    assert verdict.high_confidence is False


def test_l1_medium_place_wish_with_hint():
    verdict = l1_scan("想去江边坐会儿")
    assert verdict is not None
    assert verdict.high_confidence is False
    assert verdict.place_hint == "江边"


# ── L1 软不确定：高降中 ─────────────────────────────────

def test_l1_soft_ba_lowers_confidence():
    verdict = l1_scan("想出去走走吧")
    assert verdict is not None
    assert verdict.high_confidence is False


# ── L1 反例：一票否决 ───────────────────────────────────

@pytest.mark.parametrize(
    "text",
    [
        "你说我要不要出去呢",
        "我要不要出去？",
        "出去吗",
        "要是明天不下雨就出去",
        "等天晴了再去",
        "明天再说吧 我先睡了",
        "先这样 我忙去了",
        "昨天去了趟江边",
        "上周出门逛了一圈",
        "不想动 今天算了",
        "出不去 楼下在修路",
        "等你回来我们一起去",
        "想陪我去就直说",
        "刚吃完饭",
        "好的",
    ],
)
def test_l1_hard_veto_and_no_signal(text):
    assert l1_scan(text) is None


# ── L2 行为 ─────────────────────────────────────────────

class FakeL2:
    def __init__(self, result):
        self._result = result
        self.calls = 0

    async def confirm(self, text):
        self.calls += 1
        return self._result


@pytest.mark.asyncio
async def test_l2_confirms_and_fields_win():
    fake = FakeL2({
        "is_promise": True, "kind": "go_out", "topic": "江边走走",
        "place_hint": "江边步道", "delay_min": 120,
    })
    extractor = PromiseExtractor(l2_client=fake)
    match = await extractor.extract_from_reply("我想出去透透气")
    assert match is not None
    assert match.confidence == "confirmed"
    assert match.topic == "江边走走"
    assert match.place_hint == "江边步道"
    assert match.delay_sec == 7200.0


@pytest.mark.asyncio
async def test_l2_delay_is_clamped():
    fake = FakeL2({"is_promise": True, "delay_min": 5})
    match = await PromiseExtractor(l2_client=fake).extract_from_reply("想出门")
    assert match.delay_sec == 3600.0
    fake2 = FakeL2({"is_promise": True, "delay_min": 999})
    match2 = await PromiseExtractor(l2_client=fake2).extract_from_reply("想出门")
    assert match2.delay_sec == 10800.0


@pytest.mark.asyncio
async def test_l2_veto_overrides_l1():
    fake = FakeL2({"is_promise": False})
    match = await PromiseExtractor(l2_client=fake).extract_from_reply("我想出去走走")
    assert match is None


@pytest.mark.asyncio
async def test_l2_unavailable_high_confidence_passes():
    fake = FakeL2(None)
    match = await PromiseExtractor(l2_client=fake).extract_from_reply(
        "好几天闷家里了 想出去走走"
    )
    assert match is not None
    assert match.confidence == "high"
    assert match.delay_sec == 5400.0


@pytest.mark.asyncio
async def test_l2_unavailable_medium_confidence_dropped():
    fake = FakeL2(None)
    match = await PromiseExtractor(l2_client=fake).extract_from_reply("好几天没出门了")
    assert match is None


@pytest.mark.asyncio
async def test_l2_malformed_treated_as_unavailable():
    fake = FakeL2({"unexpected": "shape"})  # 缺 is_promise
    match = await PromiseExtractor(l2_client=fake).extract_from_reply("想出去走走")
    assert match is not None
    assert match.confidence == "high"


@pytest.mark.asyncio
async def test_no_l2_client_medium_confidence_dropped():
    match = await PromiseExtractor(l2_client=None).extract_from_reply("想去江边坐会儿")
    assert match is None


@pytest.mark.asyncio
async def test_l2_not_called_when_l1_empty():
    fake = FakeL2({"is_promise": True})
    match = await PromiseExtractor(l2_client=fake).extract_from_reply("刚吃完饭")
    assert match is None
    assert fake.calls == 0


@pytest.mark.asyncio
async def test_empty_and_blank_reply():
    fake = FakeL2({"is_promise": True})
    assert await PromiseExtractor(l2_client=fake).extract_from_reply("") is None
    assert await PromiseExtractor(l2_client=fake).extract_from_reply("   ") is None
