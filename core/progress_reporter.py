"""任务进度上报：把工具执行过程翻译成用户看得见的阶段消息。

背景（2026-09-21 建目录事件）：私聊链路此前只在回合结束时推一条最终回复，
中途的工具调用、失败、等待审批只写 trace 与桌面 SSE，QQ / 微信里看不到任何
进展，用户只能反复追问「现在怎么样了」。

上报粒度由 ``settings.yaml`` 的 ``agent.progress.style`` 决定：

  - ``off``        不上报
  - ``start_end``  只在开工与失败时各推一条，收尾交给正常回复
  - ``stage``      （默认）按阶段去重，同一阶段只报一次
  - ``verbose``    每次工具调用都报，受 ``max_messages`` 封顶

本模块只负责「报什么、报几次」，具体投递（落库 / SSE / 发送队列）由调用方
通过 ``emit`` 注入，避免反向依赖。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


class ProgressStyle(str, Enum):
    OFF = "off"
    START_END = "start_end"
    STAGE = "stage"
    VERBOSE = "verbose"


# 工具名 → 阶段描述。stage 模式用它做去重键与文案。
_TOOL_STAGE_LABELS: dict[str, str] = {
    "directory_create": "建目录",
    "file_write": "写入文件",
    "document_create": "生成文档",
    "doc_write": "生成文档",
    "file_copy": "复制文件",
    "file_move": "移动文件",
    "file_rename": "重命名文件",
    "file_search": "查找文件",
    "directory_list": "查看目录",
    "document_read": "读取文档",
    "text_summary": "提炼内容",
    "document_convert": "转换格式",
    "word_generate": "生成文档",
    "csv_generate": "导出表格",
    "chart_generate": "生成图表",
    "shell_execute": "执行命令",
    "shell_cmd": "执行命令",
    "screenshot": "看屏幕",
    "list_windows": "查找窗口",
    "focus_window": "切换窗口",
    "app_open": "打开应用",
    "uia_action": "界面操作",
    "mouse_click": "界面操作",
    "type_text": "输入内容",
    "key_press": "界面操作",
    "web_fetch": "抓取网页",
    "code_search": "查找代码",
}


def stage_label(tool_name: str) -> str:
    """工具名 → 面向用户的阶段描述。"""
    return _TOOL_STAGE_LABELS.get(tool_name) or f"执行 {tool_name}"


@dataclass
class ProgressConfig:
    """进度上报配置（来自 settings.yaml 的 agent.progress）。"""

    style: ProgressStyle = ProgressStyle.STAGE
    max_messages: int = 4

    @classmethod
    def from_settings(cls, settings: Optional[dict]) -> "ProgressConfig":
        agent = (settings or {}).get("agent") or {}
        raw = agent.get("progress") or {}
        if not isinstance(raw, dict):
            raw = {}

        style_raw = str(raw.get("style", ProgressStyle.STAGE.value)).strip().lower()
        try:
            style = ProgressStyle(style_raw)
        except ValueError:
            logger.warning("未知的进度样式 %r，回退 %s", style_raw, ProgressStyle.STAGE.value)
            style = ProgressStyle.STAGE

        try:
            max_messages = max(1, int(raw.get("max_messages", 4)))
        except (TypeError, ValueError):
            max_messages = 4

        return cls(style=style, max_messages=max_messages)

    @property
    def enabled(self) -> bool:
        return self.style != ProgressStyle.OFF


class TaskProgressReporter:
    """把一次工具执行翻译成 0~N 条对外进度消息。

    进度消息**懒触发**：只有真的调用了工具才开口，纯聊天不会冒出「开工」。
    失败永远要报——用户最需要知道的正是「哪一步卡住了」。
    """

    def __init__(
        self,
        config: ProgressConfig,
        emit: Callable[[str], Awaitable[None]],
        *,
        task_hint: str = "",
    ) -> None:
        self._config = config
        self._emit = emit
        self._task_hint = (task_hint or "").strip()
        self._started = False
        self._sent = 0
        self._seen_stages: set[str] = set()
        self._last_tool_at = 0.0

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def sent_count(self) -> int:
        return self._sent

    async def _send(self, text: str) -> None:
        if self._sent >= self._config.max_messages:
            return
        try:
            await self._emit(text)
        except Exception:
            logger.warning("投递进度消息失败: %r", text[:40], exc_info=True)
            return
        self._sent += 1

    def _start_text(self) -> str:
        if self._task_hint:
            hint = self._task_hint[:24].replace("\n", " ")
            return f"好，我先去办「{hint}」，有进展就告诉你。"
        return "好，我先去办，有进展就告诉你。"

    async def report_tool(
        self,
        tool_name: str,
        *,
        success: bool,
        error: str = "",
        arguments: Optional[dict] = None,
        **_ignored,
    ) -> None:
        """记录一次工具执行结果，按配置决定是否对外发一条进度。"""
        if not self._config.enabled:
            return

        if not self._started:
            self._started = True
            await self._send(self._start_text())

        label = stage_label(tool_name)

        if not success:
            reason = (error or "没有给出原因").strip().replace("\n", " ")[:60]
            await self._send(f"「{label}」这一步没成（{reason}），我换个方式再试。")
            return

        style = self._config.style
        if style == ProgressStyle.START_END:
            return

        if style == ProgressStyle.VERBOSE:
            self._last_tool_at = time.monotonic()
            await self._send(f"{label}：完成。")
            return

        # stage：同一阶段只报一次
        if label in self._seen_stages:
            return
        self._seen_stages.add(label)
        await self._send(f"正在{label}…")
