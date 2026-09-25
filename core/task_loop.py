"""任务循环：判断「这条消息是不是一件必须动手完成的事」，并给出执行纪律。

设计背景
--------
此前「真正干活」这条路外包给了一个外部 DSH 子进程（`core/dsh_cli.py`），
它产出 WorkProtocol JSON 再由本机执行器跑。该子进程依赖写死的仓库路径，
本机不存在，于是每次委托都静默降级成普通聊天——用户看到的只是角色扮演。

现在的做法：**不再外包**。执行能力本来就在核心里（`ToolRegistry` 里已有
建目录 / 写文件 / 文件整理 / 文档生成 / 电脑操控等工具，`LLMCaller.chat` 本来
就是能跑 ReAct 循环的），缺的只是「知道这是活、并且按纪律把它做完」。

本模块只负责两件事，都是确定性的：
  1. ``classify`` —— 一条消息是不是可执行任务、属于哪一类（唯一的关键词表，
     办公室模式检测也复用这张表，避免同一个判断散落成多份）。
  2. ``build_task_prompt`` —— 任务模式下追加给模型的执行纪律与工具选择指引。

它不做执行、不碰工具、不碰人格：执行走既有的 ToolRegistry + ReAct 循环，
进度走 ``core.progress_reporter``，人格由既有人设提示词负责。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "TaskKind",
    "TaskVerdict",
    "TASK_KEYWORDS",
    "TASK_REACT_ROUNDS",
    "classify",
    "build_task_prompt",
]


class TaskKind(str, Enum):
    """可执行任务的类别。"""

    FILE = "file"            # 建目录 / 写文件 / 复制移动重命名 / 整理归档
    DOC = "doc"              # 文档写作（报告 / 周报 / 纪要 / 简历 / 方案）
    SHEET = "sheet"          # 表格与数据统计
    SLIDES = "slides"        # 演示文稿
    EMAIL = "email"          # 邮件撰写
    SCHEDULE = "schedule"    # 日程 / 会议安排
    CODE = "code"            # 代码 / 脚本
    ANALYSIS = "analysis"    # 数据分析
    RESEARCH = "research"    # 检索 / 调研
    COMPUTER = "computer"    # 键鼠 / 窗口 / 截图 / 命令


# ── 唯一的关键词表 ────────────────────────────────────────────────
# strength: "strong" 命中即判为任务；"medium" 需要叠加其他信号。
# 关键词刻意写得具体（带宾语），避免「整理心情」「打开心扉」这类日常表达误判。
TASK_KEYWORDS: tuple[tuple[str, TaskKind, str], ...] = (
    # 文件系统操作（今天出问题的正是这一类：建目录 / 写文件）
    (r"(新建|创建|建立|建|做个|做一个)\s*.{0,6}(文件夹|目录|文件)", TaskKind.FILE, "strong"),
    (r"(文件夹|目录).{0,4}(里|中|下|内)", TaskKind.FILE, "medium"),
    (r"(复制|拷贝|移动|重命名|改名|删除|清理|去重).{0,8}(文件|文件夹|目录|照片|图片|图标)", TaskKind.FILE, "strong"),
    (r"整理.{0,8}(文件|文件夹|目录|照片|图片|桌面|下载|硬盘|盘)", TaskKind.FILE, "strong"),
    (r"(文件|文件夹|目录|照片|图片|桌面|下载).{0,6}(整理|归类|分类|归档)", TaskKind.FILE, "strong"),
    (r"(保存|存|写|放|下载|输出).{0,6}(到|进|在)\s*[A-Za-z]:", TaskKind.FILE, "strong"),
    (r"(生成|做|写|创建|开发).{0,6}(网页|页面|网站|HTML|html)", TaskKind.FILE, "strong"),
    # 文档
    (r"写\s*(一份|一个|一篇)?\s*(文档|报告|周报|日报|月报|纪要|总结|方案|简历|文案|稿子)", TaskKind.DOC, "strong"),
    (r"(帮我写|起草|拟|生成)\s*(一份|一个|一篇)?\s*(文档|报告|周报|日报|月报|纪要|方案|总结|简历)", TaskKind.DOC, "strong"),
    (r"(写|生成).{0,4}(PPT|ppt|幻灯片|演示)", TaskKind.SLIDES, "strong"),
    # 表格 / 数据
    (r"(表格|Excel|excel|报表|统计表)", TaskKind.SHEET, "strong"),
    (r"(统计|汇总|透视|求和).{0,6}(数据|表格|销量|金额)", TaskKind.SHEET, "strong"),
    (r"(分析|统计|对比).{0,6}(数据|趋势|报表|销量)", TaskKind.ANALYSIS, "strong"),
    # 邮件 / 日程
    (r"(写|发|起草).{0,4}(邮件|mail|信)", TaskKind.EMAIL, "strong"),
    (r"(安排|约|定).{0,6}(会议|日程|时间|会议室)", TaskKind.SCHEDULE, "strong"),
    # 代码
    (r"(写|改|修|重构|实现).{0,6}(代码|脚本|函数|接口|程序|爬虫)", TaskKind.CODE, "strong"),
    (r"(bug|debug|报错|编译失败)", TaskKind.CODE, "medium"),
    # 检索
    (r"(搜索|搜一下|查一下|查查|调研|检索).{0,10}", TaskKind.RESEARCH, "strong"),
    (r"(帮我|给我).{0,4}(搜|查|找).{0,8}", TaskKind.RESEARCH, "medium"),
    # 电脑操控
    (r"(打开|启动|关闭|退出).{0,6}(软件|应用|程序|浏览器|微信|QQ|文件夹)", TaskKind.COMPUTER, "strong"),
    (r"(截图|屏幕截图|截个图)", TaskKind.COMPUTER, "strong"),
    (r"(执行|运行|跑).{0,6}(命令|脚本|程序)", TaskKind.COMPUTER, "strong"),
    (r"(点击|点一下|输入|打字|按下|按键|鼠标|键盘)", TaskKind.COMPUTER, "medium"),
)

# 编译一次，避免每次分类重复编译
_COMPILED: tuple[tuple[re.Pattern[str], TaskKind, str], ...] = tuple(
    (re.compile(pattern), kind, strength)
    for pattern, kind, strength in TASK_KEYWORDS
)

# 明确的文件系统信号：Windows 路径 / 盘符。命中即视为任务：
# 用户把具体路径都给了，那就是要动手，不是闲聊。
# 盘符字母前用负向后顾排除「字母/数字/点/斜杠/冒号」紧邻的情形，
# 否则 URL 里的 "https:/"（s:/）、"a.b:C:\" 这类文本会被误判成盘符路径。
_PATH_SIGNALS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![A-Za-z0-9./\\:])[A-Za-z]:[\\/]"),
    re.compile(r"[A-Za-z]\s*盘"),
    re.compile(r"~(?:/|\\)"),
)

# 任务模式下放宽 ReAct 轮数：多步任务需要「做一步→看回执→再决定」的余量。
TASK_REACT_ROUNDS = 12


@dataclass(slots=True)
class TaskVerdict:
    """任务判定结果。"""

    kind: TaskKind
    matched: list[str] = field(default_factory=list)
    has_path: bool = False

    @property
    def reason(self) -> str:
        parts = [f"kind={self.kind.value}"]
        if self.has_path:
            parts.append("path")
        if self.matched:
            parts.append("kw=" + ",".join(self.matched[:3]))
        return " ".join(parts)


def classify(text: str) -> TaskVerdict | None:
    """判断一条用户消息是否为可执行任务。

    返回 None 表示「这是聊天，别动手」。判定只做关键词与形态匹配，
    不调模型——把「是不是活」这件事交给一次额外的 LLM 判断，既慢又更容易飘。
    """
    if not text:
        return None
    message = text.strip()
    if not message:
        return None

    matched: list[str] = []
    medium_only: TaskKind | None = None

    for pattern, kind, strength in _COMPILED:
        hit = pattern.search(message)
        if hit is None:
            continue
        matched.append(hit.group(0)[:20])
        if strength == "strong":
            return TaskVerdict(kind=kind, matched=matched, has_path=_has_path(message))
        if medium_only is None:
            medium_only = kind

    has_path = _has_path(message)
    if has_path:
        # 给了具体路径：按文件类任务处理（写文件/建目录是最高频的形态）
        return TaskVerdict(
            kind=medium_only or TaskKind.FILE,
            matched=matched,
            has_path=True,
        )

    if medium_only is not None and len(matched) >= 2:
        return TaskVerdict(kind=medium_only, matched=matched, has_path=False)

    return None


def _has_path(text: str) -> bool:
    return any(pattern.search(text) for pattern in _PATH_SIGNALS)


# ── 任务模式提示词 ────────────────────────────────────────────────

_COMMON_DISCIPLINE = """【任务执行模式 · 现在就动手】
你现在不是在聊天，是在真的把这件事做完——结果必须落到磁盘或屏幕上。

1. 先在心里拆步骤，不要输出计划或步骤清单，直接开始做。
2. 一步一步来：一次只调一个工具，拿到回执再决定下一步。
3. 每一步都要看回执：**只有回执明确成功，才算这一步成功**。
4. 失败先看原因再换做法；同一个写法不许重复硬试，最多换两种方式。
5. 全部做完并核实之后，再用你平时说话的语气简短汇报：
   做了什么、结果在哪里。**没做成就不要说得像做成了。**
6. 实在做不完，就直接说卡在哪一步、什么原因、需要他配合什么。

汇报时依然守你的输出铁律（不写动作、神态、心理描写，一条不要超过两三句）。"""

_TOOL_GUIDE: dict[TaskKind, str] = {
    TaskKind.FILE: """【这类任务的工具选择】
- 建目录：directory_create
- 写文件内容：file_write（把完整内容一次写进去，中文路径没问题）
- 看目录有什么：directory_list；找文件：file_search
- 复制/移动/重命名：file_copy / file_move / file_rename
- 绝不要用 shell 的 echo > 重定向、也不要用分号串联多步来写文件——会被安全闸拒绝；
  写文件一律走 file_write，它会把父目录一起建好。""",
    TaskKind.DOC: """【这类任务的工具选择】
- 生成文档：doc_write（可导出 md/html/pdf/docx）
- 需要落到指定路径：file_write
- 先想清楚结构再写正文，一次写入完整内容。""",
    TaskKind.SHEET: """【这类任务的工具选择】
- 读表分析：spreadsheet_analyze / document_read
- 统计与筛选：data_stats / data_filter / data_sort
- 导出：csv_generate；画图：chart_generate""",
    TaskKind.SLIDES: """【这类任务的工具选择】
- 生成本地演示文稿：doc_write（fmt=html），需要 pptx 时说明你的做法再动手。""",
    TaskKind.EMAIL: """【这类任务的工具选择】
- 邮件正文：先写清楚收件人、主旨、正文，再问他要不要直接发。""",
    TaskKind.SCHEDULE: """【这类任务的工具选择】
- 看日程：calendar_list；建日程：calendar_create""",
    TaskKind.CODE: """【这类任务的工具选择】
- 写文件/脚本：file_write（完整内容一次写入）
- 跑一下验证：shell_execute（单条简单命令，不要管道和分号）
- 改完必须真的运行或读回来确认，不要只凭想象说「应该可以」。""",
    TaskKind.ANALYSIS: """【这类任务的工具选择】
- 取数：document_read / spreadsheet_analyze
- 算：data_stats / data_filter；画：chart_generate
- 结论要落到具体数字上，不要只给感觉。""",
    TaskKind.RESEARCH: """【这类任务的工具选择】
- 抓网页：web_fetch；需要更多来源可以多抓几页
- 提炼：text_summary；整理成文档：doc_write / file_write
- 只说你真正查到的东西。查不到就说查不到。""",
    TaskKind.COMPUTER: """【这类任务的工具选择】
- 看屏幕：screenshot / list_windows；切窗口：focus_window
- 开应用：app_open；界面操作：uia_action（优先于坐标点击）
- 一次只做一个动作，做完先确认结果再继续。""",
}


def build_task_prompt(verdict: TaskVerdict) -> str:
    """按任务类别拼出要追加到 system prompt 的执行纪律。"""
    guide = _TOOL_GUIDE.get(verdict.kind, "")
    return f"{_COMMON_DISCIPLINE}\n\n{guide}" if guide else _COMMON_DISCIPLINE
