"""TaskProgressReporter 分流测试。

回归 2026-09-25 截图问题：日常问句（「现在是几点了」）调 get_time 时，
旧逻辑无差别播「好，我先去办…」「正在执行 get_time…」工单腔。
聊天模式现在只搭一句自然的话，且不泄露工具名。
"""

import pytest

from core.progress_reporter import (
    ProgressConfig,
    ProgressStyle,
    TaskProgressReporter,
    chat_filler_for,
)


def _make_reporter(chat_mode: bool, style: ProgressStyle = ProgressStyle.STAGE):
    sent: list[str] = []

    async def emit(text: str) -> None:
        sent.append(text)

    reporter = TaskProgressReporter(
        ProgressConfig(style=style, max_messages=4),
        emit=emit,
        chat_mode=chat_mode,
    )
    return reporter, sent


@pytest.mark.asyncio
async def test_chat_mode_time_question_single_natural_filler():
    reporter, sent = _make_reporter(chat_mode=True)

    await reporter.report_tool("get_time", success=True)

    assert sent == ["稍等，我看看。"]


@pytest.mark.asyncio
async def test_chat_mode_silent_after_first_filler():
    reporter, sent = _make_reporter(chat_mode=True)

    await reporter.report_tool("get_time", success=True)
    await reporter.report_tool("get_time", success=True)
    await reporter.report_tool("calendar_list", success=True)

    assert sent == ["稍等，我看看。"]


@pytest.mark.asyncio
async def test_chat_mode_failure_still_reported_without_tool_name():
    reporter, sent = _make_reporter(chat_mode=True)

    await reporter.report_tool("web_fetch", success=False, error="timeout")

    assert len(sent) == 1
    assert "web_fetch" not in sent[0]
    assert "卡住" in sent[0]


@pytest.mark.asyncio
async def test_chat_mode_failure_then_success_no_stage_chatter():
    reporter, sent = _make_reporter(chat_mode=True)

    await reporter.report_tool("web_fetch", success=False, error="timeout")
    await reporter.report_tool("web_fetch", success=True)

    # 失败报过一次即可，重试成功不再啰嗦，等最终回复
    assert len(sent) == 1
    assert "web_fetch" not in sent[0]
    assert "正在" not in sent[0]
    assert "完成" not in sent[0]


@pytest.mark.asyncio
async def test_chat_mode_verbose_style_also_silent_on_success():
    reporter, sent = _make_reporter(
        chat_mode=True, style=ProgressStyle.VERBOSE
    )

    await reporter.report_tool("get_time", success=True)

    assert sent == ["稍等，我看看。"]


@pytest.mark.asyncio
async def test_task_mode_start_text_never_truncates_or_echoes_user():
    """开工语不含用户原话：旧实现 `f"...「{task_hint[:24]}」..."` 把
    "…文件类型是TXT"切成"…时间。文"，还把用户刚说的话原封回灌（§十四 #61）。"""
    reporter, sent = _make_reporter(chat_mode=False)

    await reporter.report_tool("directory_create", success=True)

    assert sent[0] == "好，我先去办，有进展就告诉你。"
    assert "「" not in sent[0]


@pytest.mark.asyncio
async def test_unregistered_tool_never_leaks_english_name():
    """未登记工具不得把英文工具名播给用户（§十四 #62）。"""
    reporter, sent = _make_reporter(chat_mode=False)

    await reporter.report_tool("some_new_tool", success=True)

    assert sent[1] == "正在办这件事…"
    assert "some_new_tool" not in "".join(sent)


def test_chat_failure_text_differs_by_reason():
    """不同失败给不同交代，用户才能分清"一个问题重试两次"与"两个问题"（§十四 #64）。"""
    from core.progress_reporter import chat_failure_text

    not_installed = chat_failure_text("local_txt2img not installed: No module named 'local_txt2img'")
    credential = chat_failure_text("credential_missing: env 'SEEDREAM_KEY' not set")
    timeout = chat_failure_text("ReadTimeout: read timeout")

    assert len({not_installed, credential, timeout}) == 3
    # 通用兜底仍留给"说不清原因"的失败
    assert chat_failure_text("") == "哎呀，这一下没成，我再想想办法。"
    # 一律不得回显英文错误原文
    for text in (not_installed, credential, timeout):
        assert "local_txt2img" not in text
        assert "SEEDREAM_KEY" not in text


@pytest.mark.asyncio
async def test_task_mode_keeps_start_and_stage_report():
    reporter, sent = _make_reporter(chat_mode=False)

    await reporter.report_tool("directory_create", success=True)

    assert sent == ["好，我先去办，有进展就告诉你。", "正在建目录…"]


@pytest.mark.asyncio
async def test_task_mode_stage_dedup_still_works():
    reporter, sent = _make_reporter(chat_mode=False)

    await reporter.report_tool("file_write", success=True)
    await reporter.report_tool("file_write", success=True)

    assert sent.count("正在写入文件…") == 1


@pytest.mark.asyncio
async def test_disabled_config_emits_nothing_in_chat_mode():
    sent: list[str] = []

    async def emit(text: str) -> None:
        sent.append(text)

    reporter = TaskProgressReporter(
        ProgressConfig(style=ProgressStyle.OFF),
        emit=emit,
        chat_mode=True,
    )

    await reporter.report_tool("get_time", success=True)

    assert sent == []


def test_chat_filler_mapping_covers_lightweight_tools():
    assert chat_filler_for("get_time") == "稍等，我看看。"
    assert chat_filler_for("weather_query") == "稍等，我看看。"
    assert chat_filler_for("web_fetch") == "我查一下，稍等。"
    # 未登记的聊天工具也不能把英文名抛给用户
    assert chat_filler_for("some_unknown_tool") == "等我一下。"
