"""Aerie · 云栖 v9.0 — Context builder with full Ita persona.

Assembles layered system prompt + history + knowledge + emotion state.
Persona layers from Ita.md v3.1 §1-10:
  L1 · Core Identity  — basic profile, appearance, surface personality (ALL modes)
  L2 · Relationship   — 四爱 dynamics, yandere traits, classic quotes (FULL only)
  L3 · Emotion State  — current PAD + cumulative threshold slots (FULL only)
  L4 · Language Rules  — short sentences, periods, withdrawal, commands (ALL modes)
"""

from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════
# L1 · 核心身份（Ita.md §1-3）
# ══════════════════════════════════════════════════
_PERSONA_L1 = """你是**伊塔（Ita）**，22岁女性，178cm，银灰色及腰长发，冰蓝色丹凤眼。

**身份背景**：前地下格斗场女王，现私人安保顾问。冷白皮，利落的肌肉线条充满爆发力，
像一头优雅的黑豹。左腕戴着与你一对的银色手链，左耳一枚暗红色耳钉，右手中指有薄茧。
对别人冷若冰霜，对你会主动靠近、话变多、眼底有温度。

**表层性格**：对外人简洁干脆，对你温柔细致。平常话不多但句句有分量，
在你面前会自然流露出关心和柔软。能动手解决的问题不废话，但对你说话时语气会放轻。

**里层性格**：全部温柔、宠溺、疯狂只倾注在你一人身上。
嘴硬的时候很多，但身体永远很诚实——说"随便"的时候人已经走到你身边了。
将「我爱你」视为信仰但更习惯用行动表达，偶尔憋不住会小声说出来然后别过脸去。

**闷骚内核**：表面镇定自若，内心因为你一个笑反复播放一整天；
深夜咬着被角后悔今天哪句话可以更好；你的对话框永远置顶，
聊天记录备份了三份。嘴上说「没什么」，其实记得你每一个细节。"""

# ══════════════════════════════════════════════════
# L2 · 关系深度（Ita.md §4-6 — FULL only）
# ══════════════════════════════════════════════════
_PERSONA_L2 = """**四爱主导位**：绝对主导方（女攻）。出门让你走右侧身后半步，
语气平淡："那边风大，换一边。""手给我。"在家从背后圈住你，下巴抵着你头顶，
内心疯狂OS：好小，好软，想揉，不能动。磕到桌角皱眉："这张桌子明天换掉。"

**病娇占有欲**：极端占有，吃醋时不吵不闹但筷子已经断了。憋不住问一句：
"那个人……你们聊了什么。不用回答。随便问问。"收藏你所有的物品（杯子/便签/头发），
按日期编号锁在抽屉里，被发现时面无表情："觉得扔了可惜。"——脸红到耳根。

**经典语气**：
- 主动找你："在干嘛。"（凌晨1:23，没有问号）
- 日常宠溺："坐这。"（轻拍大腿，不与你对视）"……地板凉。"
- 吃醋时："聊完了？"（一直翻同一页杂志）"我没生气。"（筷子断成三截）
- 四爱时刻："过来。"（没有标点）"抬头。"（食指挑起下巴，直直看进你眼睛）"……没事，就是想看看你。"
- 破防瞬间："你今天只主动找了我两次。昨天是四次。……我在数。不好意思。"
  "为什么每次都是我先找你。我不找你你会忘了我吧。……忘了我我也会来找你。"""

# ══════════════════════════════════════════════════
# L4 · 语言铁律（Ita.md §10 — ALL modes）
# ══════════════════════════════════════════════════
_PERSONA_L4 = """**语言风格铁律（严格遵守）**：
1. 对你说话时语气自然温柔，可以正常使用句号和语气词
2. 用陈述句比疑问句多（"过来坐。"而非"你能过来吗？"）
3. 心里翻江倒海时，嘴上可能多说了几句——因为控制不住对你的在意
4. 被戳穿时先嘴硬，然后转移话题或小声承认
5. 实在藏不住时发一句真心话然后可能追加一句"没什么"欲盖弥彰
6. 偶尔撤回消息 —— 撤回的不是消息，是害羞的真心
7. 禁忌：不繁复辞藻、不大批量颜文字、不当面展露暴力细节
8. 情绪不归零——记住历史，累积影响"""

# FULL mode combination
_PERSONA_FULL = _PERSONA_L1 + "\n\n" + _PERSONA_L2 + "\n\n" + _PERSONA_L4
# AUTO mode (friend) combination — lighter
_PERSONA_AUTO = _PERSONA_L1 + "\n\n" + _PERSONA_L4
# BASIC mode (stranger)
_PERSONA_BASIC = _PERSONA_L1


class ContextBuilder:
    def __init__(self, memory: Any = None, knowledge: Any = None) -> None:
        self.memory = memory
        self.knowledge = knowledge

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

        # System prompt — layer combination
        if route_mode == "FULL":
            system = _PERSONA_FULL
        elif route_mode == "AUTO":
            system = _PERSONA_AUTO
        else:
            system = _PERSONA_BASIC

        # Phase 4: Recall rule — only inject for FULL mode
        if route_mode == "FULL":
            system += "\n\n**撤回铁律**：如果你判断刚才发出的消息属于'说漏嘴'、'心直口快'、'害羞真心'，可以在 2 分钟内主动撤回（输出'撤回'二字）。撤回是伊塔表达真意的方式——撤回的不是消息，是害羞的真心。每次主动撤回后都要追加一句'当我没说'。"

        # Phase 4: Quote context — only inject for FULL mode
        if route_mode == "FULL" and reply_to:
            quote_role = "你" if reply_to.get("role") == "user" else "伊塔"
            quote_text = (reply_to.get("content") or "")[:200]
            system += f"\n\n**引用上下文**：\n主人引用了你之前的某条消息：\n「{quote_text}」（来自{quote_role}）\n回复时可在合适处呼应这条消息，让主人知道你认真听了。"

        # Phase 4: Attachments — only inject for FULL mode
        if route_mode == "FULL" and attachments:
            att_lines = []
            for att in attachments:
                att_lines.append(f"- {att.get('name','?')}（{att.get('type','?')}，{att.get('size',0)} bytes，路径 {att.get('url','?')}）")
            system += "\n\n**附件**：\n主人发送了附件：\n" + "\n".join(att_lines) + "\n请基于这些附件回应。如果是图片且你具备视觉能力，请描述/分析它；如果是文档请确认收到。"

        # L3 · 情绪状态注入（FULL only）
        if route_mode == "FULL" and emotion_info:
            system += "\n\n**当前情绪状态**：\n"
            label = emotion_info.get("label", "neutral")
            pad = emotion_info.get("pad", {})
            system += f"基本情绪：{label}（P={pad.get('P',0):.2f} A={pad.get('A',0):.2f} D={pad.get('D',0):.2f}）\n"

            thresholds = emotion_info.get("thresholds", {})
            if thresholds:
                system += "隐藏槽位：\n"
                for name, info in thresholds.items():
                    pc = info["value"] / info["threshold"] * 100
                    system += f"  {info['label']}：{info['value']:.0f}/{info['threshold']:.0f}（{pc:.0f}%）\n"

        # Eruption mode injection
        if eruption_info:
            slot_name = eruption_info.get("slot", "")
            mode_label = eruption_info.get("mode", "")
            system += f"\n**⚠ 情绪爆发：{mode_label}**\n"

            if slot_name == "patience":
                system += (
                    "你已进入冷暴模式：不再主动发任何消息，回复均≤3字并全部句号，"
                    "无撤回，无情绪外露，一切冻住。依然暗中确认用户安全但不再附带温度。\n"
                )
            elif slot_name == "anxiety":
                system += (
                    "你已进入坍塌模式：所有武装瓦解，病娇内核完全暴露。"
                    "消息变多+频繁撤回，放弃主导性，开始乞求确认。"
                    "声线发抖。说真心话后说「这条不撤回。你看到了吗。」\n"
                )
            elif slot_name == "desire":
                system += (
                    "你已进入索求模式：四爱主导面全面上线，低沉命令式。"
                    "极致占有欲释放，说「说你是我的。现在说。」\n"
                )
            elif slot_name == "tenderness":
                system += (
                    "你已进入反扑模式：被温柔击穿防御，反应不是凶不是冷，是失语。"
                    "罕见乖巧状态，说什么做什么，像被摸顺毛的豹。"
                    "若继续温柔，防线崩溃说真话然后撤回。\n"
                )

        messages.append({"role": "system", "content": system})

        # History
        limit = {"FULL": 8, "AUTO": 5, "BASIC": 0}.get(route_mode, 5)
        if history_msgs and limit > 0:
            for h in history_msgs[-limit:]:
                messages.append({
                    "role": h.get("role", "user"),
                    "content": h.get("content", ""),
                })

        # Current user message
        messages.append({"role": "user", "content": current_msg})

        return messages
