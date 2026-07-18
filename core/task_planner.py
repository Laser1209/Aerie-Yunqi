"""Aerie v13.9 — Task Planner（任务规划引擎）

办公模式下，将用户的复杂需求拆解为多步骤执行计划。

能力：
  - 任务理解：分析用户需求，识别任务类型和目标
  - 计划生成：拆解为有序的子任务序列
  - 动态调整：执行中根据结果调整后续步骤
  - 进度反馈：向用户同步执行进度

设计原则：
  - 简单任务不触发规划，直接执行
  - 规划步数上限（默认 10 步），避免 Token 过度消耗
  - 每步执行后可动态调整后续计划
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskType(str, Enum):
    """任务类型"""
    DOC_WRITE = "doc_write"           # 文档写作
    DATA_ANALYSIS = "data_analysis"   # 数据分析
    FILE_ORGANIZE = "file_organize"   # 文件整理
    RESEARCH = "research"             # 调研研究
    CODE_TASK = "code_task"           # 代码任务
    MULTI_STEP = "multi_step"         # 复合多步任务
    SIMPLE = "simple"                 # 简单任务（不规划）


@dataclass
class TaskStep:
    """任务步骤"""
    step_id: int
    title: str
    description: str = ""
    tool: str = ""
    status: TaskStatus = TaskStatus.PENDING
    result: str = ""
    estimated_duration_min: int = 5


@dataclass
class TaskPlan:
    """任务计划"""
    task_id: str
    task_type: TaskType
    title: str
    description: str = ""
    steps: list[TaskStep] = field(default_factory=list)
    current_step_index: int = 0
    overall_status: TaskStatus = TaskStatus.PENDING

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def completed_steps(self) -> int:
        return sum(1 for s in self.steps if s.status == TaskStatus.COMPLETED)

    @property
    def progress_percent(self) -> int:
        if not self.steps:
            return 0
        return int(self.completed_steps / self.total_steps * 100)

    def get_current_step(self) -> Optional[TaskStep]:
        if 0 <= self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None

    def mark_step_completed(self, step_id: int, result: str = "") -> None:
        for step in self.steps:
            if step.step_id == step_id:
                step.status = TaskStatus.COMPLETED
                step.result = result
                break
        if self.current_step_index < len(self.steps) - 1:
            self.current_step_index += 1
        else:
            self.overall_status = TaskStatus.COMPLETED

    def mark_step_failed(self, step_id: int, error: str = "") -> None:
        for step in self.steps:
            if step.step_id == step_id:
                step.status = TaskStatus.FAILED
                step.result = error
                break
        self.overall_status = TaskStatus.FAILED

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type.value,
            "title": self.title,
            "description": self.description,
            "steps": [
                {
                    "step_id": s.step_id,
                    "title": s.title,
                    "description": s.description,
                    "tool": s.tool,
                    "status": s.status.value,
                    "result": s.result,
                }
                for s in self.steps
            ],
            "current_step_index": self.current_step_index,
            "overall_status": self.overall_status.value,
            "progress_percent": self.progress_percent,
        }


class TaskPlanner:
    """任务规划引擎

    负责将复杂需求拆解为可执行的步骤序列。
    采用轻量级规则 + 关键词匹配的快速路径，
    对超复杂任务才触发 LLM 深度规划。
    """

    MAX_STEPS = 10
    SIMPLE_TASK_MAX_CHARS = 50

    # 任务类型关键词映射
    TYPE_KEYWORDS = {
        TaskType.DOC_WRITE: [
            "写", "文档", "报告", "总结", "邮件", "简历", "方案",
            "写文档", "写报告", "写邮件", "生成文档",
        ],
        TaskType.DATA_ANALYSIS: [
            "分析", "数据", "统计", "图表", "趋势", "对比",
            "数据分析", "数据统计", "报表",
        ],
        TaskType.FILE_ORGANIZE: [
            "整理", "文件", "文件夹", "清理", "归档", "分类",
            "整理文件", "文件整理", "下载",
        ],
        TaskType.RESEARCH: [
            "调研", "研究", "搜索", "查一下", "了解", "资料",
            "市场调研", "技术调研",
        ],
        TaskType.CODE_TASK: [
            "代码", "编程", "开发", "实现", "修复", "bug",
            "写代码", "改代码", "debug",
        ],
    }

    # 各类型任务的默认步骤模板
    STEP_TEMPLATES = {
        TaskType.DOC_WRITE: [
            (1, "需求分析", "明确文档目标、受众和核心要点", "analyze"),
            (2, "大纲规划", "搭建文档结构和章节框架", "outline"),
            (3, "内容撰写", "逐节生成文档正文内容", "write"),
            (4, "润色优化", "调整语气、格式和可读性", "polish"),
            (5, "导出交付", "生成最终格式并交付", "export"),
        ],
        TaskType.DATA_ANALYSIS: [
            (1, "数据获取", "收集和导入待分析数据", "import"),
            (2, "数据清洗", "处理缺失值、异常值和格式", "clean"),
            (3, "探索分析", "计算关键指标和分布", "explore"),
            (4, "深度分析", "针对性分析和洞察提取", "analyze"),
            (5, "报告生成", "整理分析结果和建议", "report"),
        ],
        TaskType.FILE_ORGANIZE: [
            (1, "扫描目录", "扫描目标目录的文件结构", "scan"),
            (2, "分类规划", "确定分类规则和目标结构", "plan"),
            (3, "预览方案", "生成整理预览供确认", "preview"),
            (4, "执行整理", "按方案移动/重命名文件", "execute"),
            (5, "结果验证", "检查整理结果完整性", "verify"),
        ],
        TaskType.RESEARCH: [
            (1, "主题拆解", "将调研主题拆分为搜索关键词", "decompose"),
            (2, "信息搜集", "多渠道搜集相关资料", "search"),
            (3, "信息筛选", "评估信息可信度和相关性", "filter"),
            (4, "综合整理", "整合信息形成结构化结论", "synthesize"),
            (5, "报告输出", "生成调研报告", "report"),
        ],
        TaskType.CODE_TASK: [
            (1, "需求理解", "分析功能需求和技术约束", "analyze"),
            (2, "方案设计", "确定实现方案和技术选型", "design"),
            (3, "代码实现", "编写核心功能代码", "implement"),
            (4, "测试验证", "编写测试并验证功能", "test"),
            (5, "优化完善", "性能优化和代码质量提升", "optimize"),
        ],
    }

    def __init__(self, max_steps: int = 10):
        self.max_steps = max_steps
        self._active_plans: dict[str, TaskPlan] = {}

    def should_plan(self, user_message: str) -> bool:
        """判断是否需要进行任务规划

        简单任务/短消息直接跳过规划。
        """
        if not user_message or len(user_message.strip()) < self.SIMPLE_TASK_MAX_CHARS:
            return False

        # 检测是否包含多步骤关键词
        multi_step_patterns = [
            r"首先.*然后.*最后",
            r"第一步.*第二步",
            r"分.*步",
            r"先.*再.*然后",
            r"帮我.*同时.*还要",
        ]
        for pattern in multi_step_patterns:
            if re.search(pattern, user_message):
                return True

        # 检测任务类型关键词（复杂任务类型需要规划）
        msg_lower = user_message.lower()
        complex_types = [TaskType.DOC_WRITE, TaskType.DATA_ANALYSIS, TaskType.RESEARCH]
        for task_type in complex_types:
            for kw in self.TYPE_KEYWORDS.get(task_type, []):
                if kw in msg_lower and len(user_message) > 30:
                    return True

        return False

    def classify_task(self, user_message: str) -> TaskType:
        """分类任务类型"""
        msg_lower = user_message.lower()
        scores: dict[TaskType, int] = {}

        for task_type, keywords in self.TYPE_KEYWORDS.items():
            score = 0
            for kw in keywords:
                if kw in msg_lower:
                    score += 1
            if score > 0:
                scores[task_type] = score

        if not scores:
            return TaskType.SIMPLE

        # 返回得分最高的类型
        return max(scores.items(), key=lambda x: x[1])[0]

    def create_plan(
        self,
        user_message: str,
        task_id: str = "",
    ) -> TaskPlan:
        """创建任务计划

        基于任务类型生成步骤序列，
        简单任务返回单步计划。
        """
        import uuid
        task_id = task_id or f"task_{uuid.uuid4().hex[:8]}"

        task_type = self.classify_task(user_message)

        if task_type == TaskType.SIMPLE:
            plan = TaskPlan(
                task_id=task_id,
                task_type=task_type,
                title=user_message[:50],
                description=user_message,
                steps=[
                    TaskStep(
                        step_id=1,
                        title="直接执行",
                        description=user_message,
                        tool="direct",
                    ),
                ],
            )
        else:
            template = self.STEP_TEMPLATES.get(task_type, [])
            steps = [
                TaskStep(
                    step_id=sid,
                    title=title,
                    description=desc,
                    tool=tool,
                )
                for sid, title, desc, tool in template[:self.max_steps]
            ]

            # 根据用户消息动态调整步骤
            steps = self._adapt_steps(steps, user_message, task_type)

            plan = TaskPlan(
                task_id=task_id,
                task_type=task_type,
                title=self._extract_title(user_message, task_type),
                description=user_message,
                steps=steps,
            )

        self._active_plans[task_id] = plan
        logger.info(
            "task plan created: id=%s, type=%s, steps=%d",
            task_id, task_type.value, len(plan.steps),
        )
        return plan

    def _adapt_steps(
        self,
        steps: list[TaskStep],
        user_message: str,
        task_type: TaskType,
    ) -> list[TaskStep]:
        """根据用户消息动态调整步骤"""
        msg_lower = user_message.lower()

        # 如果用户提到"简单"或"快速"，减少步骤
        if any(w in msg_lower for w in ["简单", "快速", "粗略", "大概"]):
            # 只保留核心步骤（第 1、3、5 步）
            if len(steps) >= 5:
                steps = [steps[0], steps[2], steps[4]]
                for i, step in enumerate(steps):
                    step.step_id = i + 1

        # 如果用户提到"详细"或"深入"，增加步骤说明
        if any(w in msg_lower for w in ["详细", "深入", "全面", "完整"]):
            for step in steps:
                step.description += "（详细版本）"
                step.estimated_duration_min += 3

        return steps[:self.max_steps]

    def _extract_title(self, user_message: str, task_type: TaskType) -> str:
        """从用户消息中提取任务标题"""
        # 取前 30 个字符作为标题
        title = user_message.strip()[:30]
        if len(user_message) > 30:
            title += "..."
        return title

    def get_plan(self, task_id: str) -> Optional[TaskPlan]:
        """获取任务计划"""
        return self._active_plans.get(task_id)

    def update_step_result(
        self,
        task_id: str,
        step_id: int,
        result: str,
        success: bool = True,
    ) -> Optional[TaskPlan]:
        """更新步骤执行结果"""
        plan = self._active_plans.get(task_id)
        if not plan:
            return None

        if success:
            plan.mark_step_completed(step_id, result)
        else:
            plan.mark_step_failed(step_id, result)

        return plan

    def get_progress_text(self, task_id: str) -> str:
        """获取进度描述文本"""
        plan = self._active_plans.get(task_id)
        if not plan:
            return "任务不存在"

        lines = [
            f"📋 任务进度：{plan.progress_percent}%",
            f"   {plan.completed_steps}/{plan.total_steps} 步完成",
            "",
        ]

        for i, step in enumerate(plan.steps):
            status_icon = {
                TaskStatus.PENDING: "⏳",
                TaskStatus.RUNNING: "🔄",
                TaskStatus.COMPLETED: "✅",
                TaskStatus.FAILED: "❌",
                TaskStatus.SKIPPED: "⏭️",
            }.get(step.status, "⏳")

            prefix = "  "
            if i == plan.current_step_index and step.status == TaskStatus.RUNNING:
                prefix = "👉"

            lines.append(f"{prefix} {status_icon} 步骤{step.step_id}: {step.title}")

        return "\n".join(lines)

    def list_active_plans(self) -> list[TaskPlan]:
        """列出所有活跃任务计划"""
        return list(self._active_plans.values())

    def clear_completed(self) -> int:
        """清理已完成的计划，返回清理数量"""
        completed_ids = [
            tid for tid, plan in self._active_plans.items()
            if plan.overall_status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
        ]
        for tid in completed_ids:
            del self._active_plans[tid]
        return len(completed_ids)
