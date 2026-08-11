"""TDD tests for stripping echoed timestamp markers from LLM reply text.

项目约定：必须在输出端剥离所有对话历史时间戳标记（开头/中间、带空格/不带
空格、带年份/带秒），仅保留正文内容——否则模型回显 `[MM-DD HH:MM]` 会漏进
用户可见消息。这里覆盖 pipeline 的 `_HIST_LABEL_RE` 对多种形态的识别。
"""

from __future__ import annotations

from core.pipeline import Pipeline


def _strip(text: str) -> str:
    return Pipeline._strip_leading_timestamp(text)


# ── 行首时间戳（最常被回显）────────────────────────
def test_strips_leading_basic():
    assert _strip("[08-11 21:00] 好的，我看看。") == "好的，我看看。"


def test_strips_leading_with_extra_space():
    assert _strip("[08-11 21:00]   好的。") == "好的。"


# ── 正文中间出现的时间戳（用户报告的核心 bug）────────────────
def test_strips_mid_text():
    assert _strip("我在这儿呢 [08-11 21:00]，刚到家。") == "我在这儿呢 ，刚到家。"
    assert _strip("先等一会 [08-11 21:00] 然后我来。") == "先等一会 然后我来。"


# ── 多种形态：带年份 / 带秒 / 年份+秒 ────────────────
def test_strips_variants():
    assert _strip("[2026-08-11 21:00] 早上好。") == "早上好。"
    assert _strip("看到了 [08-11 21:00:05] 这张图。") == "看到了 这张图。"
    assert _strip("[2026-08-11 21:00:05] 我马上拍。") == "我马上拍。"


# ── 多个时间戳同时出现 ────────────────────────────
def test_strips_multiple():
    assert _strip("[08-11 09:00] 你好 [08-11 21:00] 再见") == "你好 再见"


# ── 不应误伤正文里的合法时间描述 ───────────────────
def test_does_not_strip_plain_text():
    text = "今天傍晚太阳快落山了。"
    assert _strip(text) == text
