"""任务循环：判定「这条消息是不是一件必须动手完成的事」。

回归背景（2026-09-21）：用户说「帮我在D盘建立一个文件夹…生成一个网页」，
当时三套关键词表（work_mode_router / office_mode / task_planner）全都没命中，
任务被当成闲聊，只回了一轮角色扮演。这里锁住「任务必被认出」与
「日常聊天不能被误判成任务」两侧。
"""

from __future__ import annotations

import pytest

from core.task_loop import (
    TASK_REACT_ROUNDS,
    TaskKind,
    build_task_prompt,
    classify,
)

# ── 必须认出是任务 ──────────────────────────────────────────────

TASK_CASES = [
    # 原始事故原话
    ("帮我在D盘建立一个文件夹，名字是想你的夜，然后在里面使用下面的提示词去生成一个网页", TaskKind.FILE),
    ("用这个提示词去生成一个网页", TaskKind.FILE),
    (r"把这份文件保存到 D:\想你的夜", TaskKind.FILE),
    ("把下载目录里的照片整理一下", TaskKind.FILE),
    ("帮我新建一个文件夹", TaskKind.FILE),
    ("帮我写一份周报", TaskKind.DOC),
    ("生成一份简历", TaskKind.DOC),
    ("统计一下这个月的销量", TaskKind.SHEET),
    ("写个脚本把文件重命名", TaskKind.CODE),
    ("搜一下这个库怎么用", TaskKind.RESEARCH),
    ("打开一下微信", TaskKind.COMPUTER),
    ("帮我截个图", TaskKind.COMPUTER),
]

# ── 绝不能被当成任务（日常聊天） ────────────────────────────────

CHAT_CASES = [
    "我今天好累",
    "想你了",
    "在干嘛",
    "晚上吃什么好呢",
    "这个电影好看吗",
    "我好无聊啊",
    "晚安",
    "你还记得我们第一次见面吗",
]


@pytest.mark.parametrize("text,expected", TASK_CASES)
def test_task_is_recognized(text: str, expected: TaskKind) -> None:
    verdict = classify(text)
    assert verdict is not None, f"任务未被识别: {text!r}"
    assert verdict.kind is expected, f"{text!r} → {verdict.kind}（期望 {expected}）"


@pytest.mark.parametrize("text", CHAT_CASES)
def test_chat_is_not_a_task(text: str) -> None:
    assert classify(text) is None, f"日常聊天被误判成任务: {text!r}"


def test_empty_and_whitespace() -> None:
    assert classify("") is None
    assert classify("   ") is None
    assert classify(None) is None


def test_react_rounds_allow_multi_step() -> None:
    """任务模式必须比默认 6 轮宽，否则多步任务做不完。"""
    assert TASK_REACT_ROUNDS > 6


def test_prompt_forbids_writing_descriptions_and_false_success() -> None:
    """执行纪律必须包含：不写描写、只认成功的回执、没做成就别说得像做成了。"""
    prompt = build_task_prompt(classify("帮我在D盘建立一个文件夹"))
    assert "不要写动作" in prompt or "不写动作" in prompt
    assert "回执" in prompt
    assert "没做成就不要说得像做成了" in prompt


def test_prompt_prefers_dedicated_tools_over_shell() -> None:
    """文件类任务必须明确指引用 directory_create / file_write，而不是 shell 拼写。"""
    prompt = build_task_prompt(classify(r"把文件写到 D:\x\y.html"))
    assert "directory_create" in prompt
    assert "file_write" in prompt


def test_office_mode_shares_the_single_keyword_table() -> None:
    """办公模式的任务判定必须复用同一张表，不能各写一份（曾经三份）。"""
    from core.office_mode import OfficeModeManager, OfficeTaskType

    manager = OfficeModeManager()
    ctx = manager.detect("帮我写一份周报")
    assert ctx.is_office_mode()
    assert ctx.task_type is OfficeTaskType.DOCUMENT

    # 日常聊天不进入办公模式
    chat_ctx = OfficeModeManager().detect("我今天好累")
    assert not chat_ctx.is_office_mode()
