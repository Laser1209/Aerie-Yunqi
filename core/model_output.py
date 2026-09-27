"""模型输出净化：把「模型原文」变成「能发给用户的正文」。

这些事在整条链路上必须一致，因此只保留这一个实现，任何出口都调它：

1. 剥 ``thinking`` 推理块
2. 剥 ``<thought>`` / ``<action>`` 标签及其内容
3. 剥模型回显进正文的历史元信息标记：``[MM-DD HH:MM]``、纯时间 ``[00:05]``、
   跨通道来源 ``[QQ]/[桌面]/[本地]/[系统]``、话题前缀 ``[话题：…]``
4. 剥全角括号包裹的动作/神态/心理描写 ``（…）``
5. 剥误写的伪图片 markdown ``[图片](生图提示词)``

调用方：
  - ``core.pipeline``：用户发言触发的正常回合（FULL / BASIC / 批量三条路径）
  - ``core.llm_caller.generate_push``：主动消息（欲望 / 开机问候 / 主动关心）
  - ``communication.qq_client`` / ``core.ilink_gateway``：各通道出站前的最后一道闸

**为什么出口闸必须共用同一实现**：这些标记是喂给模型的「谁在什么时候说的」元信息，
模型会模仿它们并写进自己要说的话里（2026-09-27 实测：主动消息发出
``[00:05] [桌面] 怎么一直没动静…``）。只在一个通道做清洗、或各通道各写一套正则，
就会出现「桌面端正常、QQ/微信端露标记」——同一个 bug 反复复发。
"""

from __future__ import annotations

import re

# ── 1. 全角括号描写 ────────────────────────────────
# 人设提示词从未要求模型用 <action> 标签，模型于是按角色扮演习惯把动作/心理
# 写进全角括号。过滤链此前只认 <action>/<thought> 标签，括号描写因此 100%
# 直达用户。只剥全角括号，不动半角 (…)，避免误伤英文括注与代码片段。
_NARRATION_PAREN_RE = re.compile(r"（[^（）\n]{0,120}?）")

# ── 2/3. 推理块与 thought/action 标签 ────────────────
# 推理块标签用拼接构造：整段标签字面量曾在写入通道里被改写成特殊 token，
# 正则因此静默失效（think 块连块内的 --- 一起漏给用户）。拼接后编译结果
# 与字面量完全一致。
_THINK_OPEN = "<" + "think" + ">"
_THINK_CLOSE = "</" + "think" + ">"
_THINK_RE = re.compile(_THINK_OPEN + ".*?" + _THINK_CLOSE, re.DOTALL)

_THOUGHT_ACTION_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"<thought>.*?</thought>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<action>.*?</action>", re.DOTALL | re.IGNORECASE),
)

# 历史完整标签 ``[MM-DD HH:MM]``：年份可有可无，秒可有可无，日期与时间之间
# 允许 0~1 个空格。这个形状唯一指向注入的元信息，用户正文绝不会这么写。
_DATE_TIME = r"\d{2,4}-\d{2}(?:-\d{2})? ?\d{2}:\d{2}(?::\d{2})?"
_HIST_LABEL_RE = re.compile(rf"\[{_DATE_TIME}\]\s*")

# 内部元信息标记的形状：
#   - 纯时间   ``[00:05]`` / ``[00:05:30]``
#   - 跨通道   ``[QQ]`` ``[桌面]`` ``[本地]`` ``[系统]``（见 core/_hist_utils.channel_short）
#   - 话题前缀 ``[话题：日常]``（见 core/topic_tracker._context_for）
_TIME_ONLY = r"\d{1,2}:\d{2}(?::\d{2})?"
_CHANNEL_WORD = r"(?:QQ|桌面|本地|系统)"
_TOPIC_PREFIX = r"话题[:：][^\[\]]{0,40}"
_METADATA_BODY = rf"(?:{_DATE_TIME}|{_CHANNEL_WORD}|{_TOPIC_PREFIX}|{_TIME_ONLY})"

# 行首的连续标记串：历史前缀形如 ``[09-27 00:05] [桌面] ``，
# 而模型回显时常常**砍掉日期**只留时间，于是变成 ``[00:05] [桌面] ``。
# 关键：两者贴在同一行，所以不能只认"行首第一个 [..]"，必须吃掉整串。
# 原实现用 ``^\[(?:QQ|桌面…)\]`` 且依赖前一个时间戳先被剥掉，
# 时间戳一变形状（少了日期）整条链就全失效——本 bug 正是如此。
_LEADING_MARKER_RUN_RE = re.compile(
    rf"^(?:[ \t]*\[{_METADATA_BODY}\])+[ \t]*",
    re.MULTILINE,
)

# 跨通道来源标记在正文中间出现时同样剥除（``[QQ]`` 这类形状不可能是正文）。
_INLINE_CHANNEL_RE = re.compile(rf"\[{_CHANNEL_WORD}\]\s*")

# ── 4. 伪图片 markdown ──────────────────────────────
# LLM 偶发把"生图提示词"写进回复文本，形如 ``[图片](一张局部特写。昏暗的光线下…)``
# 或 ``![图片](描述)``。这些是给后台生图系统的输入，不该出现在用户可见文本里。
# 正则只剥 ``[图片](...)`` / ``![图片](...)`` 且括号内**不是合法 http(s) URL**
# 的片段——真实图片消息 ``![图片](http://127.0.0.1:7890/...)`` 是附件渲染语法，
# 不受影响。
_FAKE_IMAGE_MARKDOWN_RE = re.compile(
    r"!?\[图片\]\((?!https?://)(?![^)]*https?://)[^)]*\)"
)


def _collapse_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text)


def strip_narration(text: str) -> str:
    """剥除全角括号包裹的动作/神态/心理描写。

    整条消息都是描写时返回空串，由调用方决定兜底策略。
    """
    if not text:
        return ""
    cleaned = _NARRATION_PAREN_RE.sub("", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def strip_thought_action_tags(text: str) -> str:
    """移除 <thought> / <action> 标签及其内容，只留纯对话文本。"""
    if not text:
        return text
    cleaned = text
    for pattern in _THOUGHT_ACTION_RES:
        cleaned = pattern.sub("", cleaned)
    return _collapse_blank_lines(cleaned).strip()


def strip_internal_markers(text: str) -> str:
    """剥除模型回显的内部元信息标记。

    两层处理：
      1. 行首的**连续标记串**整体剥除（``[00:05] [桌面] `` 一起走）；
      2. 正文中出现的完整时间戳 / 跨通道标记单独剥除。

    纯时间只在行首位置剥除：正文中 ``[00:05]`` 有可能是正当内容（倒计时等），
    而模型模仿历史前缀时总是写在行首。
    """
    if not text:
        return text
    cleaned = _LEADING_MARKER_RUN_RE.sub("", text)
    cleaned = _HIST_LABEL_RE.sub("", cleaned)
    cleaned = _INLINE_CHANNEL_RE.sub("", cleaned)
    return _collapse_blank_lines(cleaned).strip()


def strip_fake_image_markdown(text: str) -> str:
    """剥除 LLM 误写的伪图片 markdown（`[图片](描述)` / `![图片](描述)`）。

    仅匹配完整语法形态（含括号与"图片"字样），不误伤裸词"图片"；
    括号内含 http(s) URL 的真实图片语法被负向前瞻排除，保留不动。
    """
    if not text:
        return text
    cleaned = _FAKE_IMAGE_MARKDOWN_RE.sub("", text)
    return _collapse_blank_lines(cleaned).strip()


def sanitize_outbound_text(text: str) -> str:
    """出站唯一闸门：任何通道把文本发给用户之前都必须过这里。

    顺序有意义——标签先剥（可能腾出新的行首），再剥元信息标记，最后处理
    伪图片语法。缺任何一步都会让某类标记直达用户。
    """
    if not text:
        return text
    cleaned = strip_thought_action_tags(text)
    cleaned = strip_internal_markers(cleaned)
    cleaned = strip_fake_image_markdown(cleaned)
    return cleaned.strip()


def normalize_model_text(raw: str) -> str:
    """模型原文 → 面向用户的正文本。

    整条消息都是描写时清洗结果会为空，此时回退成剥描写之前的文本——
    宁可多留一句旁白，也不要让这一轮彻底空白。
    """
    if not raw:
        return raw
    cleaned = _THINK_RE.sub("", raw)
    cleaned = strip_internal_markers(cleaned)
    return strip_narration(cleaned) or cleaned
