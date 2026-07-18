"""Aerie v13.0 — Office Mode 办公模式

核心能力：
- 模式检测与切换（聊天 / 办公自动识别 + 手动切换）
- 办公场景任务分类（文档/表格/PPT/邮件/日程/代码/搜索）
- 模型路由（办公模式优先使用豆包 Seed 2.1 Turbo）
- 办公专用工具集注册入口
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class OfficeMode(Enum):
    """模式枚举"""
    CHAT = "chat"          # 普通聊天模式
    OFFICE = "office"      # 办公模式
    AUTO = "auto"          # 自动识别


class OfficeTaskType(Enum):
    """办公任务类型"""
    DOCUMENT = "document"       # 文档写作 / 编辑
    SPREADSHEET = "spreadsheet"  # 表格 / 数据处理
    PRESENTATION = "presentation"  # PPT / 演示
    EMAIL = "email"             # 邮件撰写
    SCHEDULE = "schedule"       # 日程 / 会议安排
    CODE = "code"               # 代码开发 / 调试
    SEARCH = "search"           # 信息检索 / 调研
    ANALYSIS = "analysis"       # 数据分析 / 报告
    OTHER = "other"             # 其他


@dataclass
class OfficeContext:
    """办公模式上下文"""
    mode: OfficeMode = OfficeMode.AUTO
    detected_mode: Optional[OfficeMode] = None  # 自动识别结果
    task_type: Optional[OfficeTaskType] = None
    task_keywords: list[str] = field(default_factory=list)
    confidence: float = 0.0
    work_context: dict = field(default_factory=dict)  # 工作上下文（项目名、文档等）

    def is_office_mode(self) -> bool:
        if self.mode == OfficeMode.OFFICE:
            return True
        if self.mode == OfficeMode.AUTO and self.detected_mode == OfficeMode.OFFICE:
            return True
        return False


class OfficeModeManager:
    """办公模式管理器

    负责模式检测、任务分类、上下文维护。
    """

    def __init__(self) -> None:
        self._current_mode = OfficeMode.AUTO
        self._context = OfficeContext(mode=self._current_mode)
        self._work_context_history: list[dict] = []

    # ── 模式控制 ────────────────────────────────

    @property
    def current_mode(self) -> OfficeMode:
        return self._current_mode

    def set_mode(self, mode: OfficeMode | str) -> None:
        """设置模式"""
        if isinstance(mode, str):
            mode = OfficeMode(mode)
        self._current_mode = mode
        self._context.mode = mode
        logger.info("office mode set to %s", mode.value)

    def get_context(self) -> OfficeContext:
        return self._context

    # ── 智能检测 ────────────────────────────────

    def detect(self, message: str, history: list[dict] | None = None) -> OfficeContext:
        """根据用户消息检测是否进入办公模式

        Args:
            message: 当前用户消息
            history: 最近对话历史

        Returns:
            更新后的办公上下文
        """
        if self._current_mode == OfficeMode.OFFICE:
            self._context.detected_mode = OfficeMode.OFFICE
            self._context.confidence = 1.0
            self._classify_task(message)
            return self._context

        if self._current_mode == OfficeMode.CHAT:
            self._context.detected_mode = OfficeMode.CHAT
            self._context.confidence = 0.0
            return self._context

        # AUTO 模式：基于关键词 + 启发式判断
        score = 0.0
        keywords: list[str] = []

        # 强办公关键词（高权重）
        strong_keywords = {
            "写报告": OfficeTaskType.DOCUMENT,
            "写文档": OfficeTaskType.DOCUMENT,
            "写邮件": OfficeTaskType.EMAIL,
            "写方案": OfficeTaskType.DOCUMENT,
            "做PPT": OfficeTaskType.PRESENTATION,
            "做表格": OfficeTaskType.SPREADSHEET,
            "Excel": OfficeTaskType.SPREADSHEET,
            "excel": OfficeTaskType.SPREADSHEET,
            "报表": OfficeTaskType.SPREADSHEET,
            "开会": OfficeTaskType.SCHEDULE,
            "安排会议": OfficeTaskType.SCHEDULE,
            "写代码": OfficeTaskType.CODE,
            "debug": OfficeTaskType.CODE,
            "bug": OfficeTaskType.CODE,
            "数据分析": OfficeTaskType.ANALYSIS,
            "总结": OfficeTaskType.ANALYSIS,
            "整理": OfficeTaskType.DOCUMENT,
            "汇报": OfficeTaskType.DOCUMENT,
            "帮我写": OfficeTaskType.DOCUMENT,
        }

        # 普通办公关键词（中权重）
        medium_keywords = {
            "文档": OfficeTaskType.DOCUMENT,
            "邮件": OfficeTaskType.EMAIL,
            "方案": OfficeTaskType.DOCUMENT,
            "表格": OfficeTaskType.SPREADSHEET,
            "数据": OfficeTaskType.SPREADSHEET,
            "会议": OfficeTaskType.SCHEDULE,
            "日程": OfficeTaskType.SCHEDULE,
            "代码": OfficeTaskType.CODE,
            "函数": OfficeTaskType.CODE,
            "接口": OfficeTaskType.CODE,
            "分析": OfficeTaskType.ANALYSIS,
            "报告": OfficeTaskType.DOCUMENT,
            "PPT": OfficeTaskType.PRESENTATION,
            "演示": OfficeTaskType.PRESENTATION,
            "统计": OfficeTaskType.SPREADSHEET,
            "调研": OfficeTaskType.SEARCH,
            "查一下": OfficeTaskType.SEARCH,
            "搜索": OfficeTaskType.SEARCH,
        }

        msg_lower = message.lower()

        # 强关键词检测
        detected_task = None
        for kw, task_type in strong_keywords.items():
            if kw.lower() in msg_lower or kw in message:
                score += 0.4
                keywords.append(kw)
                if detected_task is None:
                    detected_task = task_type

        # 中关键词检测
        for kw, task_type in medium_keywords.items():
            if kw.lower() in msg_lower or kw in message:
                score += 0.2
                keywords.append(kw)
                if detected_task is None:
                    detected_task = task_type

        # 上下文连贯性：如果最近 3 轮是办公话题，加分
        if history:
            office_history_count = 0
            for msg in history[-6:]:
                content = msg.get("content", "")
                for kw in list(medium_keywords.keys()) + list(strong_keywords.keys()):
                    if kw.lower() in content.lower():
                        office_history_count += 1
                        break
            if office_history_count >= 2:
                score += 0.2

        # 消息长度偏长（认真写需求）也加分
        if len(message) > 50:
            score += 0.1
        if len(message) > 150:
            score += 0.1

        score = min(score, 1.0)

        if score >= 0.4:
            self._context.detected_mode = OfficeMode.OFFICE
            self._context.task_type = detected_task or OfficeTaskType.OTHER
            self._context.task_keywords = list(set(keywords))
            self._context.confidence = score
        else:
            self._context.detected_mode = OfficeMode.CHAT
            self._context.task_type = None
            self._context.task_keywords = []
            self._context.confidence = 0.0

        self._context.mode = self._current_mode

        logger.debug(
            "office detect: mode=%s, task=%s, score=%.2f, keywords=%s",
            self._context.detected_mode.value if self._context.detected_mode else None,
            self._context.task_type.value if self._context.task_type else None,
            score,
            keywords,
        )

        return self._context

    def _classify_task(self, message: str) -> None:
        """对办公任务进行分类（已确认进入办公模式时调用）"""
        msg_lower = message.lower()

        task_patterns = [
            (OfficeTaskType.EMAIL, ["邮件", "email", "写信", "mail"]),
            (OfficeTaskType.DOCUMENT, ["文档", "报告", "方案", "总结", "写", "汇报", "整理"]),
            (OfficeTaskType.SPREADSHEET, ["表格", "excel", "数据", "统计", "报表"]),
            (OfficeTaskType.PRESENTATION, ["ppt", "演示", "幻灯片", "slides"]),
            (OfficeTaskType.CODE, ["代码", "函数", "接口", "bug", "debug", "开发", "实现"]),
            (OfficeTaskType.SCHEDULE, ["会议", "日程", "安排", "时间", "日历"]),
            (OfficeTaskType.ANALYSIS, ["分析", "数据", "趋势", "对比"]),
            (OfficeTaskType.SEARCH, ["搜索", "查找", "调研", "查一下"]),
        ]

        best_task = OfficeTaskType.OTHER
        best_count = 0

        for task_type, patterns in task_patterns:
            count = sum(1 for p in patterns if p in msg_lower)
            if count > best_count:
                best_count = count
                best_task = task_type

        self._context.task_type = best_task

    # ── 模型路由 ────────────────────────────────

    def get_preferred_provider(self) -> str | None:
        """获取当前模式下优先使用的模型 provider

        Returns:
            provider 名称，None 表示用默认顺序
        """
        if self._context.is_office_mode():
            return "doubao"  # 办公模式优先用豆包
        return None

    # ── 系统提示词增强 ──────────────────────────

    def augment_system_prompt(self, base_prompt: str) -> str:
        """根据办公模式增强系统提示词

        Args:
            base_prompt: 基础系统提示词

        Returns:
            增强后的系统提示词
        """
        if not self._context.is_office_mode():
            return base_prompt

        task_type = self._context.task_type
        task_desc = {
            OfficeTaskType.DOCUMENT: "文档写作与编辑",
            OfficeTaskType.SPREADSHEET: "表格与数据处理",
            OfficeTaskType.PRESENTATION: "演示文稿制作",
            OfficeTaskType.EMAIL: "邮件撰写",
            OfficeTaskType.SCHEDULE: "日程与会议安排",
            OfficeTaskType.CODE: "代码开发与调试",
            OfficeTaskType.SEARCH: "信息检索与调研",
            OfficeTaskType.ANALYSIS: "数据分析与报告",
            OfficeTaskType.OTHER: "办公事务",
        }.get(task_type, "办公事务") if task_type else "办公事务"

        office_suffix = f"""

---

【办公模式 · Office Mode】
当前任务类型：{task_desc}

办公模式行为准则：
1. 专业高效：输出结构化、条理清晰，用专业术语，减少闲聊语气
2. 质量优先：确保内容准确、逻辑严谨，必要时分步骤说明
3. 主动拆解复杂任务：如果任务复杂，主动拆解为多个步骤并确认理解
4. 善用工具：可以调用文档、表格、代码、搜索等工具完成任务
5. 结果导向：直接交付可使用的成果（文案/代码/数据），少废话
6. 保持你人设的温柔底色，但不要过度撒娇影响工作效率

如果需要执行具体操作（如打开文件、截图、输入文字等），直接调用对应的工具函数。
"""

        return base_prompt + office_suffix


# ── 单例 ────────────────────────────────────────

_instance: Optional[OfficeModeManager] = None


def get_office_mode_manager() -> OfficeModeManager:
    global _instance
    if _instance is None:
        _instance = OfficeModeManager()
    return _instance


# ── 设备识别 ────────────────────────────────────

def detect_device(user_agent: str = "") -> dict:
    """根据 User-Agent 识别设备类型

    Returns:
        {device_type: "desktop" | "mobile" | "tablet", os: str, browser: str}
    """
    ua = (user_agent or "").lower()

    # 设备类型
    device_type = "desktop"
    if "mobile" in ua or "android" in ua or "iphone" in ua:
        device_type = "mobile"
    if "ipad" in ua or "tablet" in ua or ("android" in ua and "mobile" not in ua):
        device_type = "tablet"

    # OS
    os_name = "unknown"
    if "windows" in ua:
        os_name = "windows"
    elif "mac os" in ua or "macintosh" in ua:
        os_name = "macos"
    elif "android" in ua:
        os_name = "android"
    elif "iphone" in ua or "ipad" in ua:
        os_name = "ios"
    elif "linux" in ua:
        os_name = "linux"

    # Browser
    browser = "unknown"
    if "edg/" in ua:
        browser = "edge"
    elif "chrome" in ua and "edg" not in ua:
        browser = "chrome"
    elif "firefox" in ua:
        browser = "firefox"
    elif "safari" in ua and "chrome" not in ua:
        browser = "safari"

    return {
        "device_type": device_type,
        "os": os_name,
        "browser": browser,
        "is_mobile": device_type in ("mobile", "tablet"),
        "is_desktop": device_type == "desktop",
    }
