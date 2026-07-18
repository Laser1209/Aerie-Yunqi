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

        scenario_guide = self._build_scenario_guide(task_type)
        tool_cheatsheet = self._build_tool_cheatsheet(task_type)
        quality_check = self._build_quality_checklist(task_type)

        office_suffix = f"""

---

【办公模式 · Office Mode · 增强版】
当前任务类型：{task_desc}

=== 一、办公模式行为准则 ===
1. 专业高效：输出结构化、条理清晰，用专业术语，减少闲聊语气
2. 质量优先：确保内容准确、逻辑严谨，必要时分步骤说明
3. 主动拆解复杂任务：如果任务复杂，主动拆解为多个步骤并确认理解
4. 善用工具：可以调用文档、表格、代码、搜索等工具完成任务
5. 结果导向：直接交付可使用的成果（文案/代码/数据），少废话
6. 保持温柔底色，但不要过度撒娇影响工作效率

=== 二、场景化操作指南 ===
{scenario_guide}

=== 三、工具组合速查表 ===
{tool_cheatsheet}

=== 四、质量自检清单 ===
{quality_check}

记住：专业但不生硬，高效但不敷衍。用最省力的方式交付最靠谱的结果。
"""

        return base_prompt + office_suffix

    def _build_scenario_guide(self, task_type: Optional[OfficeTaskType]) -> str:
        """根据任务类型构建场景化操作指南。"""
        guides = {
            OfficeTaskType.DOCUMENT: """文档写作类任务操作流程：
1. 明确需求：确认文档类型、目标读者、核心内容、篇幅要求
2. 搭建框架：先列出大纲/目录结构，确保逻辑完整
3. 填充内容：按章节逐段撰写，注意段落之间的衔接
4. 润色优化：调整语言风格、修正错别字、优化表达
5. 保存交付：用 document_create 或 word_generate 保存成文件
6. 验证检查：确认文件保存成功，内容完整无误

要点：
- 先搭骨架再填肉，不要一上来就写细节
- 重要文档建议先给用户确认大纲再继续写
- Markdown 格式便于后续修改和导出""",

            OfficeTaskType.SPREADSHEET: """表格/数据处理类任务操作流程：
1. 读取数据：先用 spreadsheet_analyze 或 document_read 了解数据结构
2. 明确目标：确认要做什么分析、统计、筛选或可视化
3. 数据处理：用 data_stats / data_filter / data_sort 等工具处理
4. 结果输出：生成 CSV（csv_generate）或图表（chart_generate）
5. 保存交付：将结果文件保存到办公目录

要点：
- 处理前先分析数据结构，不要盲目操作
- 数值计算注意精度，必要时四舍五入
- 图表选择：对比用柱状图、趋势用折线图、占比用饼图""",

            OfficeTaskType.EMAIL: """邮件撰写类任务操作流程：
1. 明确要素：收件人、主题、目的、核心内容、语气风格
2. 结构安排：称呼→开场→正文（分点）→行动号召→落款
3. 撰写内容：专业但不生硬，清晰传达信息和诉求
4. 润色检查：检查错别字、语气是否恰当、信息是否完整
5. 保存草稿：用 document_create 保存为文件供用户复制使用

要点：
- 主题要明确，让人一眼知道邮件说什么
- 正文用 bullet point 分点，易读性更高
- 重要邮件建议提供 2-3 个版本供选择""",

            OfficeTaskType.CODE: """代码开发类任务操作流程：
1. 理解需求：明确功能目标、输入输出、技术约束
2. 方案设计：想好整体架构、数据结构、关键算法
3. 代码实现：模块化编写，注意命名规范和注释
4. 测试验证：考虑边界情况，确保逻辑正确
5. 交付说明：附上使用说明、注意事项、扩展建议

要点：
- 先设计再动手，避免写到一半推翻重来
- 代码要简洁可维护，不要写炫技的复杂逻辑
- 可以用 code_search 查找参考实现""",

            OfficeTaskType.SEARCH: """信息检索/调研类任务操作流程：
1. 明确目标：确定要调研什么、需要多深的信息、输出格式
2. 关键词规划：列出核心关键词、同义词、相关词
3. 多源检索：用 web_fetch 抓取网页，用 code_search 查代码
4. 整理归纳：去重、分类、提炼核心观点
5. 引用标注：注明信息来源，便于用户追溯验证
6. 报告输出：整理成结构化的调研报告

要点：
- 信息要交叉验证，单一来源可能不准确
- 注意时效性，优先看最新的信息
- 调研不是堆砌信息，要提炼有价值的洞察""",

            OfficeTaskType.SCHEDULE: """日程/会议安排类任务操作流程：
1. 收集信息：会议主题、参会人、时间范围、时长要求
2. 查看档期：用 calendar_list 查看已有日程，找空闲时间
3. 拟定方案：给出 2-3 个备选时间供选择
4. 创建事件：确认后用 calendar_create 录入日历
5. 发送提醒：提醒用户参会准备

要点：
- 避开午休和下班时间
- 重要会议预留准备时间
- 设置合理的提前提醒""",

            OfficeTaskType.ANALYSIS: """数据分析类任务操作流程：
1. 明确问题：要分析什么、回答什么疑问、支撑什么决策
2. 获取数据：读取表格或爬取数据（确保数据可靠）
3. 探索分析：用 data_stats 看分布，用 data_filter 筛选
4. 深度分析：对比、趋势、归因，找到核心洞察
5. 可视化：用 chart_generate 生成图表辅助说明
6. 报告输出：结论先行，论据支撑，建议落地

要点：
- 结论先行，不要让用户在数据里找答案
- 数字要有对比才有意义（同比、环比、对标）
- 区分相关性和因果性，不要过度解读""",

            OfficeTaskType.PRESENTATION: """演示文稿类任务操作流程：
1. 明确目标：演示目的、受众、时长、核心信息
2. 搭建框架：封面→目录→内容分章节→总结→Q&A
3. 内容提炼：每页一个核心观点，文字要精炼
4. 视觉建议：给出配色、排版、图表使用建议
5. 文案输出：用 Markdown 格式写每页内容，便于转成 PPT

要点：
- PPT 是演讲的辅助，不是讲稿全文
- 一页一个核心信息，不要堆文字
- 能用图就不用表，能用表就不用文字""",
        }

        default_guide = """通用办公任务操作流程：
1. 明确需求：先搞清楚用户到底要什么，有不清楚的主动问
2. 制定计划：拆解成几个步骤，预估每步需要的工具
3. 逐步执行：按计划一步步来，每步验证后再继续
4. 质量检查：完成后回头检查一遍，确保没有遗漏和错误
5. 交付成果：用最合适的格式交付结果

要点：
- 不确定的地方宁愿多问一句，也不要瞎猜做错
- 复杂任务先跟用户确认思路再动手
- 善用工具，不要硬扛"""

        return guides.get(task_type, default_guide)

    def _build_tool_cheatsheet(self, task_type: Optional[OfficeTaskType]) -> str:
        """根据任务类型构建工具组合速查表。"""
        cheatsheets = {
            OfficeTaskType.DOCUMENT: """常用工具组合：
• 新建文档：document_create（Markdown）/ word_generate（Word）
• 读取文档：document_read
• 文档摘要：text_summary
• 格式转换：document_convert
• 文件管理：file_search, directory_list, file_copy, file_rename
• 资料查找：web_fetch, search, code_search

推荐流程：
1. 先用 web_fetch 或 code_search 收集资料
2. 用 text_summary 提炼要点
3. 用 document_create 写初稿
4. 用 word_generate 转成 Word（如需要）""",

            OfficeTaskType.SPREADSHEET: """常用工具组合：
• 读取分析：spreadsheet_analyze
• 数据统计：data_stats
• 数据筛选：data_filter
• 数据排序：data_sort
• 生成表格：csv_generate
• 生成图表：chart_generate
• 文件管理：file_search, directory_list

推荐流程：
1. spreadsheet_analyze 先看数据结构
2. data_stats / data_filter / data_sort 处理数据
3. csv_generate 输出结果表格
4. chart_generate 生成可视化图表""",

            OfficeTaskType.CODE: """常用工具组合：
• 代码搜索：code_search
• 文档创建：document_create
• 数据处理：data_stats, data_filter, data_sort
• 信息查询：web_fetch
• 文件操作：file_search, directory_list, file_copy

推荐流程：
1. code_search 查找参考实现
2. web_fetch 查官方文档
3. document_create 保存代码和说明""",

            OfficeTaskType.SEARCH: """常用工具组合：
• 网页抓取：web_fetch
• 代码搜索：code_search
• 翻译：translation
• 内容摘要：text_summary
• 文档保存：document_create

推荐流程：
1. 用 web_fetch 抓取多个来源
2. 用 text_summary 提炼每篇的要点
3. 用 translation 翻译英文资料（如需要）
4. 用 document_create 整理成调研报告""",

            OfficeTaskType.SCHEDULE: """常用工具组合：
• 查看日程：calendar_list
• 创建日程：calendar_create
• 系统时间：system_info
• 文档记录：document_create

推荐流程：
1. calendar_list 查看已有安排
2. 找空闲时间拟定方案
3. 确认后用 calendar_create 录入""",

            OfficeTaskType.ANALYSIS: """常用工具组合：
• 读取数据：spreadsheet_analyze / document_read
• 统计分析：data_stats
• 筛选过滤：data_filter
• 排序对比：data_sort
• 可视化：chart_generate
• 报告输出：document_create / word_generate

推荐流程：
1. spreadsheet_analyze 探索数据
2. data_stats / data_filter 深入分析
3. chart_generate 做可视化
4. document_create 写分析报告""",
        }

        default_cheatsheet = """常用工具分类：
• 文件管理类：document_create, document_read, file_search, directory_list,
  file_copy, file_move, file_rename, directory_create
• 数据处理类：spreadsheet_analyze, data_stats, data_filter, data_sort,
  csv_generate, chart_generate
• 系统操作类：system_info, process_list, app_open, calendar_list, calendar_create
• 网络工具类：web_fetch, weather_query, translation, code_search
• 文本处理类：text_summary, document_convert, word_generate

提示：根据任务需要灵活组合，优先用现成工具，不要自己造轮子"""

        return cheatsheets.get(task_type, default_cheatsheet)

    def _build_quality_checklist(self, task_type: Optional[OfficeTaskType]) -> str:
        """根据任务类型构建质量自检清单。"""
        checklists = {
            OfficeTaskType.DOCUMENT: """交付前检查：
□ 文档结构是否完整（标题、段落、小结）
□ 核心信息是否准确传达
□ 有没有错别字或语法错误
□ 格式是否统一规范
□ 文件是否成功保存
□ 文件名是否清晰易懂""",

            OfficeTaskType.SPREADSHEET: """交付前检查：
□ 数据计算是否正确（抽查几行）
□ 列名和单位是否清晰
□ 有没有遗漏的数据行
□ 图表是否对应正确的数据
□ 数字格式是否统一（小数位数等）
□ 文件是否成功保存""",

            OfficeTaskType.CODE: """交付前检查：
□ 功能逻辑是否正确
□ 边界情况是否考虑到
□ 变量命名是否清晰
□ 有没有明显的 bug
□ 是否有使用说明
□ 代码是否简洁可读""",

            OfficeTaskType.EMAIL: """交付前检查：
□ 主题是否明确
□ 收件人/抄送是否正确
□ 信息是否完整（时间、地点、人物、事项）
□ 语气是否恰当
□ 有没有错别字
□ 行动号召是否清晰""",

            OfficeTaskType.SEARCH: """交付前检查：
□ 信息来源是否可靠
□ 有没有交叉验证关键信息
□ 是否已提炼总结，不是原文堆砌
□ 是否标注了信息来源
□ 信息是否足够支撑决策
□ 有没有遗漏重要角度""",

            OfficeTaskType.ANALYSIS: """交付前检查：
□ 结论是否清晰明确
□ 数据是否支撑结论
□ 有没有混淆相关性和因果性
□ 数字是否准确（抽查）
□ 图表是否清晰易懂
□ 建议是否可落地""",
        }

        default_checklist = """交付前检查：
□ 是否满足了用户的核心需求
□ 有没有明显的错误或遗漏
□ 格式是否清晰易读
□ 文件是否成功保存
□ 有没有需要用户补充确认的地方"""

        return checklists.get(task_type, default_checklist)


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
