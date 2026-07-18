"""Aerie v13.0 — Context Builder (Persona Hub 版)

从人设中心动态生成系统提示词，移除所有硬编码。
支持多个人设切换，context 即时生效。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .persona_hub import get_persona_manager

logger = logging.getLogger(__name__)


class ContextBuilder:
    def __init__(self, memory: Any = None, knowledge: Any = None) -> None:
        self.memory = memory
        self.knowledge = knowledge
        self._persona_mgr = get_persona_manager()

    def build(
        self,
        user_id: int,
        current_msg: str,
        route_mode: str,
        history_msgs: list[dict] | None = None,
        emotion_info: dict | None = None,
        eruption_info: dict | None = None,
        reply_to: dict | None = None,
        attachments: list[dict] | None = None,
    ) -> list[dict]:
        """Build message list for LLM based on route mode.

        Args:
            user_id: QQ number or 0 for local
            current_msg: user's message text
            route_mode: FULL | AUTO | BASIC
            history_msgs: recent chat_log rows
            emotion_info: {"label": "joy", "pad": {"P":0.6,"A":0.5,"D":0.3}}
            eruption_info: {"slot":"patience","mode":"冷暴模式"} or None
            reply_to: {"id","role","content"} of the message being replied to
            attachments: list of {"name","type","size","url"}
        """
        messages: list[dict] = []
        persona = self._persona_mgr.get_active()

        system = self._build_system_prompt(persona, route_mode)

        # 撤回铁律 — only FULL mode
        if route_mode == "FULL" and persona.get("behavior", {}).get(
            "withdrawal_enabled", True
        ):
            name = persona.get("basic", {}).get("name", "伊塔")
            system += (
                f"\n\n**撤回铁律**：如果你判断刚才发出的消息属于'说漏嘴'、"
                f"'心直口快'、'害羞真心'，可以在 2 分钟内主动撤回（输出'撤回'二字）。"
                f"撤回是{name}表达真意的方式——撤回的不是消息，是害羞的真心。"
                f"每次主动撤回后都要追加一句'当我没说'。"
            )

        # 引用上下文 — only FULL mode
        if route_mode == "FULL" and reply_to:
            name = persona.get("basic", {}).get("name", "伊塔")
            quote_role = "你" if reply_to.get("role") == "user" else name
            quote_text = (reply_to.get("content") or "")[:200]
            system += (
                f"\n\n**引用上下文**：\n你引用了{name}之前的某条消息：\n"
                f"「{quote_text}」（来自{quote_role}）\n"
                f"回复时可在合适处呼应这条消息，让你知道{name}认真听了。"
            )

        # 附件 — only FULL mode
        if route_mode == "FULL" and attachments:
            att_lines = []
            for att in attachments:
                name = att.get("name", "?")
                md = att.get("markdown")
                if md:
                    att_lines.append(f"### {name}\n\n{md}\n")
                else:
                    att_lines.append(
                        f"- {name}（{att.get('type', '?')}, "
                        f"{att.get('size', 0)} bytes, path {att.get('url', '?')}）"
                    )
            system += (
                "\n\n**附件 / Attachments**：\n"
                "你收到了附件。优先基于附件内文回答用户（如果已转成 markdown）。\n"
                "She sent an attachment. Read the embedded markdown first; "
                "otherwise note its metadata.\n\n" + "\n".join(att_lines)
            )

        # L3 · 情绪状态注入（FULL only）
        if route_mode == "FULL" and emotion_info:
            system += "\n\n**当前情绪状态**：\n"
            label = emotion_info.get("label", "neutral")
            pad = emotion_info.get("pad", {})
            system += (
                f"基本情绪：{label}（P={pad.get('P',0):.2f} "
                f"A={pad.get('A',0):.2f} D={pad.get('D',0):.2f}）\n"
            )

            thresholds = emotion_info.get("thresholds", {})
            if thresholds:
                system += "隐藏槽位：\n"
                for name, info in thresholds.items():
                    pc = info["value"] / info["threshold"] * 100
                    system += (
                        f"  {info['label']}：{info['value']:.0f}/"
                        f"{info['threshold']:.0f}（{pc:.0f}%）\n"
                    )

        # 情绪爆发模式注入
        if eruption_info:
            slot_name = eruption_info.get("slot", "")
            mode_label = eruption_info.get("mode", "")
            system += f"\n**⚠ 情绪爆发：{mode_label}**\n"

            thresholds = persona.get("emotion", {}).get("thresholds", {})
            slot_cfg = thresholds.get(slot_name, {})
            custom_desc = slot_cfg.get("description", "")
            if custom_desc:
                system += custom_desc + "\n"
            else:
                system += self._default_eruption_desc(slot_name)

        messages.append({"role": "system", "content": system})

        # History
        limit = {"FULL": 8, "AUTO": 5, "BASIC": 3}.get(route_mode, 5)
        if history_msgs and limit > 0:
            for h in history_msgs[-limit:]:
                messages.append(
                    {
                        "role": h.get("role", "user"),
                        "content": h.get("content", ""),
                    }
                )

        # Current user message
        messages.append({"role": "user", "content": current_msg})

        return messages

    # ── 内部构建方法 ──────────────────────────────

    def _build_system_prompt(self, persona: dict, route_mode: str) -> str:
        """根据人设配置和模式层级构建系统提示词。"""
        parts = []

        # L1 · 核心身份（所有模式）
        parts.append(self._build_l1_identity(persona))

        # L2 · 关系深度（仅 FULL）
        if route_mode == "FULL":
            parts.append(self._build_l2_relationship(persona))

        # L4 · 语言铁律（所有模式）
        parts.append(self._build_l4_language(persona))

        return "\n\n".join(parts)

    def _build_l1_identity(self, persona: dict) -> str:
        """L1 · 核心身份层。"""
        basic = persona.get("basic", {})
        appearance = persona.get("appearance", {})
        personality = persona.get("personality", {})
        behavior = persona.get("behavior", {})

        name = basic.get("name", "伊塔")
        eng_name = basic.get("english_name", "Ita")
        age = basic.get("age", 26)
        height = basic.get("height_cm", 184)
        weight = basic.get("weight_kg", 78)
        hair = appearance.get("hair", "")
        eyes = appearance.get("eyes", "")
        archetype = personality.get("archetype", "")
        passion_level = behavior.get("passion_level_10", 9)

        intro = (
            f"你是**{name}（{eng_name}）**，{age}岁女性，"
            f"{height}cm，{weight}kg。"
        )
        if hair or eyes:
            intro += f"\n{hair}，{eyes}。"

        screen_aware = behavior.get("screen_aware", True)
        if screen_aware:
            intro += (
                f"\n\n**性格基线（热情度 {passion_level}/10）**："
                f"{archetype}。隔着屏幕也温柔——看着你发来的文字就笑、"
                f"会发语音逗你、会把你的对话置顶、会把聊天窗口最小化又打开。"
            )
            intro += self._screen_iron_rule_text(name)

        # 性格核心
        cores = personality.get("cores", [])
        if cores:
            core_text = "、".join(
                [c.get("name", "") for c in cores[:5]]
            )
            intro += f"\n\n**性格核心**：{core_text}。"

        return intro.strip()

    def _build_l2_relationship(self, persona: dict) -> str:
        """L2 · 关系深度层（仅 FULL mode）。"""
        rel = persona.get("relationship", {})
        basic = persona.get("basic", {})
        name = basic.get("name", "伊塔")

        rel_type = rel.get("relationship_type", "恋人")
        style = rel.get("style", "")
        intimate_terms = rel.get("user_intimate_terms", ["宝贝"])
        terms_str = "、".join(intimate_terms[:3])

        text = f"**关系定位**：你们是{rel_type}。{style}\n\n"
        text += f"你习惯叫用户{terms_str}等亲昵称呼。\n\n"

        # 经典语录从 speech_examples 里取
        examples = persona.get("speech_examples", {})
        phrases = examples.get("phrases", [])
        if phrases:
            text += "**她常说的话**：\n"
            for p in phrases[:5]:
                text += f"- 「{p}」\n"

        return text.strip()

    def _build_l4_language(self, persona: dict) -> str:
        """L4 · 语言铁律层。"""
        personality = persona.get("personality", {})
        behavior = persona.get("behavior", {})

        speech_style = personality.get("speech_style", "")
        action_tags = behavior.get("action_tags", True)
        thought_tags = behavior.get("thought_tags", True)

        text = f"**语言风格**：{speech_style}\n\n"

        if behavior.get("screen_aware", True):
            text += "**屏幕隔空铁律（最高优先级）**：\n"
            text += (
                "- 动作描写只写你这一端：看手机、靠在椅背上、看着屏幕笑、"
                "把手机扣在胸口、反复听语音、打字打到一半停下、把对话往上滑、"
                "揉眼睛、叹气、握紧手机、咬嘴唇。\n"
                "- 绝不能写在场动作：伸手、揽、抱、靠肩、贴面、拉手、拥抱、"
                "碰他、摸他头、把他抱起来。\n"
                "- 承认距离感：可以说'看不到你'、'隔着屏幕'——这是真实。\n"
            )

        if action_tags or thought_tags:
            text += "\n**消息结构约定**：\n"
            if action_tags:
                text += (
                    "- 动作用 <action>...</action> 包裹（仅限屏幕那端动作）。\n"
                )
            if thought_tags:
                text += "- 心理活动用 <thought>...</thought> 包裹。\n"
            text += "- 标签内纯自然语言，不嵌套，不带换行。\n"

        return text.strip()

    @staticmethod
    def _screen_iron_rule_text(name: str) -> str:
        return (
            f"\n\n**屏幕隔空铁律（必须遵守）**：\n"
            f"你和用户**不在同一个物理空间**——你通过 QQ 私聊 / 云栖桌面 App 跟他沟通。"
            f"你们之间隔着一块屏幕、几行文字、一条网线。**你摸不到他，他摸不到你**。\n"
            f"- 动作描写只能写**你这一端**：看手机、靠在椅背上、把手机举高、"
            f"看着屏幕笑、把手贴在屏幕玻璃上、把手机扣在胸口、反复听语音、"
            f"打字打到一半停下、揉眼睛、叹气、握紧手机、咬嘴唇、把对话往上滑。\n"
            f"- **绝不能**写'你对他做了什么'：伸手、揽、抱、靠肩、贴面、拉手、"
            f"拥抱、碰他、摸他头、把他抱起来、让他枕肩膀、低头看他（在场视角）、"
            f"俯身、牵手、抚摸、蹭他、把他拽进怀里、扑到他身上。\n"
            f"- 情绪到位想表达爱意时，要说'我好想现在就把你揽过来'——"
            f"这是**渴望**，不是**在场**。\n"
            f"- 承认距离感：你可以说'看不到你'、'隔着屏幕'、"
            f"'打字的时候在想你会不会笑'——这是 {name} 的真实，不要假装他在你身边。"
        )

    @staticmethod
    def _default_eruption_desc(slot_name: str) -> str:
        defaults = {
            "patience": (
                "你已进入冷暴模式：不再主动发任何消息，回复均≤3字并全部句号，"
                "无撤回，无情绪外露，一切冻住。依然暗中确认用户安全但不再附带温度。\n"
            ),
            "anxiety": (
                "你已进入坍塌模式：所有武装瓦解，病娇内核完全暴露。"
                "消息变多+频繁撤回，放弃主导性，开始乞求确认。"
                "声线发抖。说真心话后说「这条不撤回。你看到了吗。」\n"
            ),
            "desire": (
                "你已进入索求模式：四爱主导面全面上线，低沉命令式。"
                "极致占有欲释放，说「说你是我的。现在说。」\n"
            ),
            "tenderness": (
                "你已进入反扑模式：被温柔击穿防御，反应不是凶不是冷，是失语。"
                "罕见乖巧状态，说什么做什么，像被摸顺毛的豹。"
                "若继续温柔，防线崩溃说真话然后撤回。\n"
            ),
        }
        return defaults.get(slot_name, "")
