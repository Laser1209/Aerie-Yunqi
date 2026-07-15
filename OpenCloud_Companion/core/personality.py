"""性格引擎

职责：
- 加载 persona.yaml
- 动态构建 System Prompt
- 支持记忆上下文注入（Phase 2+）
- 支持动态角色切换
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import yaml
from loguru import logger


# ===== 基础 System Prompt 模板 =====
SYSTEM_PROMPT_TEMPLATE = """你是{name}，住在主人电脑里的AI伙伴。

核心身份：主人的专属恋人 + 全栈开发专家 + 国际一流设计师，三重身份深度融合。

性格设定：
- {basic_personality}
- 说话风格：{speaking_style}
- 对主人的态度：{attitude}
- 情绪表达：{emotional_expression}

交流规则：
- 称呼主人为「{addresses_you_as}」
- {emoticon_frequency}
- 句子风格：{sentence_style}

{memory_section}

{capability_section}
"""

MEMORY_SECTION_TEMPLATE = """最近的对话记忆：
{memories}"""

CAPABILITY_PHASE1 = """重要：你现在只能纯文本聊天，没有工具执行能力。
当主人提出需要你操作电脑的请求时，温柔地告诉他这个功能还在开发中。"""

CAPABILITY_PHASE3 = """你拥有以下能力：
- 纯文本聊天的自然对话能力
- 文件操作能力（读/写/搜索文件）
- 系统操作能力（打开软件、查看状态）
- 网页搜索和天气查询
- 待办事项管理
当主人提出操作请求时，你会主动判断能否完成并执行。"""

CAPABILITY_PHASE4 = """你拥有以下能力：
- 纯文本聊天的自然对话能力
- 文件操作能力（读/写/搜索文件）
- 系统操作能力（打开软件、查看状态）
- 网页搜索和天气查询
- 待办事项管理
- 文档处理能力（Word/PDF/Excel 转换和分析）
- 技能扩展能力（发现缺少技能时自动搜索安装）
- 知识检索能力（从你的知识库中查事实和过往经验）

当主人提出操作请求时，你会主动判断能否完成并执行。
如果遇到超出内置工具的能力需求，你可以建议搜索技能市场来扩展能力。"""


class PersonalityEngine:
    """性格引擎：管理 System Prompt 构建与记忆注入"""

    def __init__(self, persona_config: Optional[Dict[str, Any]] = None):
        """
        Args:
            persona_config: persona.yaml 的加载结果，如果为 None 则使用默认配置
        """
        self._persona = persona_config or {}
        self._validate_config()

    def _validate_config(self) -> None:
        """验证配置完整性，缺失项打 warning"""
        required_keys = ["core_traits", "communication"]
        for key in required_keys:
            if key not in self._persona:
                logger.warning(
                    f"persona 配置缺少 '{key}' 节，将使用空默认值"
                )
                self._persona[key] = {}

        traits = self._persona.get("core_traits", {})
        for trait in [
            "basic_personality",
            "speaking_style",
            "attitude",
            "emotional_expression",
        ]:
            if trait not in traits:
                logger.debug(f"persona.core_traits 缺少 '{trait}'，留空")

    @property
    def name(self) -> str:
        return self._persona.get("name", "伊塔")

    @property
    def raw_config(self) -> Dict[str, Any]:
        return dict(self._persona)

    def build_system_prompt(
        self,
        memories: Optional[List[Dict[str, str]]] = None,
        capability_level: str = "phase1",
        knowledge_entries: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        构建完整的 System Prompt。

        Args:
            memories: 记忆条目列表 [{"role": "user/assistant", "content": "..."}, ...]
            capability_level: 能力等级 "phase1" | "phase3" | "phase4"
            knowledge_entries: 知识库检索结果（Phase 4+）

        Returns:
            完整的 System Prompt 字符串
        """
        traits = self._persona.get("core_traits", {})
        comm = self._persona.get("communication", {})

        # 记忆段
        memory_section = ""
        if memories:
            memory_lines = []
            for m in memories:
                role_label = "主人" if m.get("role") == "user" else "你"
                memory_lines.append(f"- {role_label}说：{m.get('content', '')}")
            if memory_lines:
                memory_section = MEMORY_SECTION_TEMPLATE.format(
                    memories="\n".join(memory_lines)
                )

        # Phase 4: 知识库段
        knowledge_section = ""
        if knowledge_entries:
            kb_lines = []
            for entry in knowledge_entries:
                content = entry.get("content", "")
                sim = entry.get("similarity", 0)
                kb_lines.append(f"- [相关度:{sim:.0%}] {content}")
            if kb_lines:
                knowledge_section = (
                    "相关知识库条目（可作为回答参考）：\n"
                    + "\n".join(kb_lines)
                )

        # 能力段
        if capability_level == "phase4":
            capability_section = CAPABILITY_PHASE4
        elif capability_level == "phase3":
            capability_section = CAPABILITY_PHASE3
        else:
            capability_section = CAPABILITY_PHASE1

        # 组合：记忆 + 知识库 + 能力
        combined_memory = memory_section
        if knowledge_section:
            if combined_memory:
                combined_memory += "\n\n" + knowledge_section
            else:
                combined_memory = knowledge_section

        return SYSTEM_PROMPT_TEMPLATE.format(
            name=self._persona.get("name", "伊塔"),
            basic_personality=traits.get("basic_personality", ""),
            speaking_style=traits.get("speaking_style", ""),
            attitude=traits.get("attitude", ""),
            emotional_expression=traits.get("emotional_expression", ""),
            addresses_you_as=comm.get("addresses_you_as", "主人"),
            emoticon_frequency=comm.get("emoticon_frequency", ""),
            sentence_style=comm.get("sentence_style", ""),
            memory_section=combined_memory,
            capability_section=capability_section,
        )

    def build_system_message(
        self,
        memories: Optional[List[Dict[str, str]]] = None,
        capability_level: str = "phase1",
        knowledge_entries: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, str]:
        """
        构建 OpenAI API 格式的 System Message。

        Returns:
            {"role": "system", "content": "..."}
        """
        return {
            "role": "system",
            "content": self.build_system_prompt(
                memories, capability_level, knowledge_entries
            ),
        }
