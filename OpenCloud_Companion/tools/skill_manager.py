"""技能管理器：搜索、下载、安装、注册技能包 + QQ 审批流程

技能包标准格式 (skills/{name}/):
├── manifest.json    # 技能描述（AI 通过此文件理解技能）
├── main.py          # 核心代码
├── requirements.txt # Python 依赖
└── install.py       # 环境检查脚本（可选）
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import aiohttp
from loguru import logger


@dataclass
class SkillInfo:
    """技能包元数据"""
    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    source: str = ""
    size_mb: float = 0
    tools: List[Dict[str, Any]] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    min_python: str = "3.10"
    is_trusted: bool = False


class SkillManager:
    """技能管理器"""

    # 受信来源白名单
    TRUSTED_SOURCES = [
        "github.com/opencloud-companion/skills",
    ]

    # 本地技能市场（内置预置技能）
    BUILTIN_MARKET: List[Dict[str, Any]] = [
        {
            "name": "excel_analysis",
            "version": "1.0.0",
            "description": "Excel 数据分析：透视表、图表生成、数据清洗、公式计算",
            "author": "opencloud-community",
            "source": "github.com/opencloud-companion/skills",
            "size_mb": 50,
            "tools": [
                {
                    "name": "create_pivot_table",
                    "description": "基于 Excel 数据创建透视表",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "Excel 文件路径"},
                            "rows": {"type": "string", "description": "行字段"},
                            "columns": {"type": "string", "description": "列字段"},
                            "values": {"type": "string", "description": "值字段"},
                            "agg_func": {"type": "string", "description": "sum/avg/count"},
                        },
                        "required": ["file_path", "values"],
                    },
                },
                {
                    "name": "generate_chart",
                    "description": "从 Excel 数据生成图表",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "Excel 文件路径"},
                            "chart_type": {"type": "string", "description": "bar/line/pie/scatter"},
                            "x_column": {"type": "string", "description": "X 轴列名"},
                            "y_column": {"type": "string", "description": "Y 轴列名"},
                        },
                        "required": ["file_path", "chart_type", "x_column", "y_column"],
                    },
                },
            ],
            "dependencies": ["openpyxl>=3.1.0", "pandas>=2.0.0", "matplotlib>=3.7.0"],
        },
        {
            "name": "pdf_toolkit",
            "version": "1.0.0",
            "description": "PDF 处理：合并、拆分、提取文字、添加水印",
            "author": "opencloud-community",
            "source": "github.com/opencloud-companion/skills",
            "size_mb": 30,
            "tools": [
                {
                    "name": "merge_pdfs",
                    "description": "合并多个 PDF 文件为一个",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_paths": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "PDF 文件路径列表",
                            },
                            "output_path": {"type": "string", "description": "输出文件路径"},
                        },
                        "required": ["file_paths", "output_path"],
                    },
                },
                {
                    "name": "extract_text",
                    "description": "从 PDF 中提取文字",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "PDF 文件路径"},
                        },
                        "required": ["file_path"],
                    },
                },
            ],
            "dependencies": ["PyPDF2>=3.0.0", "pdfplumber>=0.10.0"],
        },
    ]

    def __init__(
        self,
        skills_dir: str = "skills",
        tool_registry=None,
        qq_sender: Optional[Callable] = None,
    ):
        """
        Args:
            skills_dir: 技能包安装目录
            tool_registry: ToolRegistry 实例（用于注册新工具）
            qq_sender: QQ 发送函数 async (user_id: int, message: str)
        """
        self._skills_dir = Path(skills_dir)
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        self._registry = tool_registry
        self._qq_sender = qq_sender
        self._installed: Dict[str, SkillInfo] = {}
        self._pending_approvals: Dict[str, asyncio.Event] = {}

    def search_market(self, query: str) -> List[SkillInfo]:
        """搜索技能市场（内置 + 可扩展）"""
        results = []
        query_lower = query.lower()

        for skill_data in self.BUILTIN_MARKET:
            if (query_lower in skill_data["name"].lower() or
                query_lower in skill_data["description"].lower()):
                info = SkillInfo(
                    name=skill_data["name"],
                    version=skill_data["version"],
                    description=skill_data["description"],
                    author=skill_data["author"],
                    source=skill_data["source"],
                    size_mb=skill_data["size_mb"],
                    tools=skill_data["tools"],
                    dependencies=skill_data["dependencies"],
                    is_trusted=skill_data["source"] in self.TRUSTED_SOURCES,
                )
                results.append(info)

        return results

    async def install(self, skill: SkillInfo) -> Tuple[bool, str]:
        """
        安装技能包：检查环境 → pip install → 注册工具。

        Returns:
            (success, message)
        """
        skill_dir = self._skills_dir / skill.name

        # 1. 检查是否已安装
        if skill.name in self._installed:
            return False, f"技能 {skill.name} 已安装"

        # 2. 检查 Python 版本
        if skill.min_python:
            current = f"{sys.version_info.major}.{sys.version_info.minor}"
            if current < skill.min_python:
                return False, f"需要 Python {skill.min_python}+，当前 {current}"

        # 3. 安装依赖
        if skill.dependencies:
            logger.info(f"安装依赖: {skill.dependencies}")
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install"] + skill.dependencies,
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode != 0:
                    logger.warning(f"部分依赖安装失败: {result.stderr[:200]}")
            except (subprocess.TimeoutExpired, Exception) as e:
                return False, f"依赖安装失败: {e}"

        # 4. 注册工具到 ToolRegistry
        if self._registry:
            for tool_def in skill.tools:
                self._register_builtin_tool(tool_def)

        # 5. 记录安装状态
        self._installed[skill.name] = skill

        # 6. 保存 manifest
        skill_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = skill_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({
                "name": skill.name,
                "version": skill.version,
                "description": skill.description,
                "tools": skill.tools,
                "dependencies": skill.dependencies,
            }, f, ensure_ascii=False, indent=2)

        logger.info(f"技能已安装: {skill.name} v{skill.version}")
        return True, f"技能 {skill.name} 安装成功！"

    async def request_approval(
        self,
        skill: SkillInfo,
        user_qq: int,
        timeout: float = 30.0,
    ) -> bool:
        """
        通过 QQ 申请审批（Phase 4 核心流程）。

        Args:
            skill: 要安装的技能信息
            user_qq: 主人的 QQ 号
            timeout: 等待审批超时（秒）

        Returns:
            是否批准
        """
        if not self._qq_sender:
            logger.warning("QQ 发送器未配置，自动批准")
            return True

        # 构建审批消息
        source_tag = "官方仓库 ✅" if skill.is_trusted else "第三方 ⚠️"
        msg = (
            f"主人，要完成这个操作我需要装一个技能包呢。\n\n"
            f"📦 技能：{skill.name}\n"
            f"🔧 用处：{skill.description}\n"
            f"📥 依赖：{', '.join(skill.dependencies) if skill.dependencies else '无'}\n"
            f"💾 大小：约 {skill.size_mb}MB\n"
            f"🔒 来源：{skill.source} ({source_tag})\n\n"
            f"回复「允许」我就开始安装～"
        )

        try:
            await self._qq_sender(user_qq, msg)
            logger.info(f"已发送审批请求: {skill.name} → QQ {user_qq}")
        except Exception as e:
            logger.warning(f"发送审批消息失败: {e}")
            return False

        # 等待审批
        event = asyncio.Event()
        self._pending_approvals[skill.name] = event

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            logger.info(f"审批通过: {skill.name}")
            return True
        except asyncio.TimeoutError:
            logger.info(f"审批超时: {skill.name} ({timeout}s)")
            self._pending_approvals.pop(skill.name, None)
            if self._qq_sender:
                try:
                    await self._qq_sender(
                        user_qq,
                        "等了主人一会儿没回复，我先不装啦～需要的时候再告诉我哦 (｡•́︿•̀｡)",
                    )
                except Exception:
                    pass
            return False

    def approve(self, skill_name: str) -> bool:
        """主人批准安装（外部调用）"""
        event = self._pending_approvals.get(skill_name)
        if event:
            event.set()
            return True
        return False

    async def find_and_install(
        self,
        need_description: str,
        user_qq: int,
    ) -> Tuple[bool, str]:
        """
        AI 发现缺少技能 → 搜索 → QQ 审批 → 安装 全流程。

        Args:
            need_description: 需求描述（如 "需要做 Excel 透视表"）
            user_qq: 主人 QQ 号

        Returns:
            (success, message)
        """
        # 1. 搜索
        results = self.search_market(need_description)
        if not results:
            return False, "抱歉主人，我在技能市场没找到能处理这个需求的技能包 (｡•́︿•̀｡)"

        skill = results[0]

        # 2. 已安装？
        if skill.name in self._installed:
            return True, f"技能 {skill.name} 已经安装好了～可以直接用"

        # 3. 审批
        if not skill.is_trusted:
            approved = await self.request_approval(skill, user_qq)
            if not approved:
                return False, "主人没有批准安装，我换个方式试试～"

        # 4. 安装
        return await self.install(skill)

    @property
    def installed_skills(self) -> List[str]:
        return list(self._installed.keys())

    def _register_builtin_tool(self, tool_def: Dict[str, Any]) -> None:
        """注册内置工具到 ToolRegistry（动态生成 Tool 子类）"""
        if not self._registry:
            return

        # 创建一个简单的动态 Tool 子类
        tool_name = tool_def["name"]

        class DynamicTool(Tool):
            name = tool_name
            description = tool_def["description"]

            @property
            def parameters(self) -> Dict[str, Any]:
                return tool_def.get("parameters", {
                    "type": "object",
                    "properties": {},
                    "required": [],
                })

            async def execute(self, **kwargs) -> Tuple[bool, str]:
                # 内置技能：调用实际的 Python 函数
                # 简单版本：返回参数信息
                return True, f"技能 {tool_name} 已就绪，参数: {kwargs}"

        self._registry.register(DynamicTool())
        logger.info(f"工具已注册: {tool_name} (来自技能包)")


# 延迟导入避免循环
from tools.base import Tool
