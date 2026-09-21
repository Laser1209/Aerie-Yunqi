"""模型输出净化：把「模型原文」变成「能发给用户的正文」。

这三件事在整条链路上必须一致，因此只保留这一个实现，任何出口都调它：

1. 剥 `` thinking… response`` 推理块
2. 剥模型回显进正文的历史时间戳 ``[MM-DD HH:MM]``
3. 剥全角括号包裹的动作/神态/心理描写 ``（…）``

调用方：
  - ``core.pipeline``：用户发言触发的正常回合（FULL / BASIC / 批量三条路径）
  - ``core.llm_caller.generate_push``：主动消息（欲望 / 开机问候 / 主动关心）

主动消息同样来自模型，所以不能只保护「用户发言」那一条链路。
"""

from __future__ import annotations

import re

# 全角括号描写：人设提示词从未要求模型用 <action> 标签，模型于是按角色扮演
# 习惯把动作/心理写进全角括号。过滤链此前只认 <action>/<thought> 标签，
# 括号描写因此 100% 直达用户。只剥全角括号，不动半角 (…)，
# 避免误伤英文括注与代码片段。
_NARRATION_PAREN_RE = re.compile(r"（[^（）\n]{0,120}?）")

_THINK_RE = re.compile(r" thinking.*? response", re.DOTALL)

_HIST_LABEL_RE = re.compile(r"\[\d{2,4}-\d{2}(?:-\d{2})? ?\d{2}:\d{2}(?::\d{2})?\]\s*")


def strip_narration(text: str) -> str:
    """剥除全角括号包裹的动作/神态/心理描写。

    整条消息都是描写时返回空串，由调用方决定兜底策略。
    """
    if not text:
        return ""
    cleaned = _NARRATION_PAREN_RE.sub("", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def normalize_model_text(raw: str) -> str:
    """模型原文 → 面向用户的正文本。

    整条消息都是描写时清洗结果会为空，此时回退成剥描写之前的文本——
    宁可多留一句旁白，也不要让这一轮彻底空白。
    """
    if not raw:
        return raw
    cleaned = _THINK_RE.sub("", raw)
    cleaned = _HIST_LABEL_RE.sub("", cleaned).strip()
    return strip_narration(cleaned) or cleaned
