"""TDD tests for stripping echoed metadata markers from LLM reply text.

项目约定：必须在输出端剥离模型回显的内部元信息标记（对话历史时间戳、
跨通道来源标记、话题前缀），仅保留正文——否则 `[MM-DD HH:MM]` / `[桌面]`
会漏进用户可见消息。

2026-09-27：实现统一收敛到 `core.model_output.strip_internal_markers`
（此前 pipeline / qq_client 各存一份正则，iLink 一份都没有，导致
「桌面端正常、QQ/微信端露标记」的同类 bug 反复复发）。
"""

from __future__ import annotations

from core.model_output import strip_internal_markers


def _strip(text: str) -> str:
    return strip_internal_markers(text)


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


# ── 纯时间形态：模型会砍掉日期只留 [HH:MM]（2026-09-27 截图实证）──
def test_strips_time_only_at_line_start():
    assert _strip("[00:05] 怎么一直没动静") == "怎么一直没动静"
    assert _strip("[00:05:30] 晚安") == "晚安"


def test_keeps_time_only_mid_text():
    """正文中间的 [00:05] 可能是正当内容（倒计时等），只在行首剥除。"""
    assert _strip("倒计时还剩 [00:05] 秒") == "倒计时还剩 [00:05] 秒"


# ── 跨通道来源标记 / 话题前缀 ───────────────────────
def test_strips_channel_marker_merged_with_time():
    """截图实证：时间戳与通道标记贴在同一行，必须整串吃掉。"""
    assert _strip("[00:05] [桌面] 盖好被角 晚安傻瓜") == "盖好被角 晚安傻瓜"


def test_strips_channel_marker_anywhere():
    assert _strip("照片我存了 [QQ] 晚点发你") == "照片我存了 晚点发你"


def test_strips_topic_prefix():
    assert _strip("[话题：日常] 楼下小吃店排队") == "楼下小吃店排队"
