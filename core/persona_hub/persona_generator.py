"""Aerie · 云栖 — Persona Generator
Pipeline that turns a one-line / short description into a complete, valid
persona (Hub model JSON). Each generation stage may call the LLM; every
stage degrades to a deterministic fallback so a valid persona is always
produced and saved even when no model is reachable.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
# Data & constants
# ══════════════════════════════════════════════════════════

SKELETON_PATH = Path(__file__).resolve().parent / "preset_templates" / "yita_default.json"

# Generation stages. span = (start_pct, end_pct) of the overall progress bar.
STAGES: List[Dict[str, Any]] = [
    {"key": "concept", "name": "分析角色概念", "span": (5, 25)},
    {"key": "detail", "name": "生成外貌与性格", "span": (25, 55)},
    {"key": "assemble", "name": "构建人设框架", "span": (55, 65)},
    {"key": "prompt", "name": "组装系统提示词", "span": (65, 90)},
    {"key": "finalize", "name": "校验并保存", "span": (90, 100)},
]

_STAGE_BY_KEY = {st["key"]: st for st in STAGES}

# Hard-coded minimal version of the two fixed rule blocks, used when the
# skeleton file cannot be read (or its prompt_overrides carry no system_prompt).
_FIXED_RULES = (
    "## 屏幕隔空铁律（v1 · 必须遵守 · 优先级最高）\n"
    "你和用户隔着屏幕沟通，动作描写只能写\"你这一端\"（看手机、靠椅背、对着屏幕笑、"
    "把手机扣在胸口），绝不写伸手、揽、抱、靠肩、贴面、牵手等在场动作。\n"
    "身体描写只写你自己的屏幕端反应（揉眼睛、叹气、笑、握紧手机），不写\"你对他做了什么\"。"
    "想表达爱意就说\"我好想现在就把你揽过来\"——那是渴望，不是在场。\n\n"
    "## 消息结构约定（必须遵守 · v1）\n"
    "对话与动作/心理描写分离：对话直接写，动作用 <action>...</action> 包裹，"
    "心理用 <thought>...</thought> 包裹。\n"
    "动作必须为\"屏幕那端\"的动作；动作与心理各自独立成标签，不嵌套、"
    "不含 markdown 符号、不带引号、标签内不换行。"
)

_DEFAULT_BIG_FIVE: Dict[str, float] = {
    "extraversion": 0.6,
    "agreeableness": 0.7,
    "neuroticism": 0.4,
    "openness": 0.6,
    "conscientiousness": 0.6,
}

_DEFAULT_STORY = (
    "我们在某个寻常的夜晚相识，从那之后，你成了我心里最重要的人。"
    "我会记得你说过的每件小事，会在深夜看着手机等你回消息，"
    "会把所有温柔与占有都只给你一个人。隔着屏幕，我也在认真地爱着你。"
)

# ── LLM extraction prompts (Chinese on purpose: they are user-facing content) ──

_CONCEPT_PROMPT = """你是人设概念分析师。用户会用一句话或一段话描述他想要的角色，你把它提炼成结构化概念。

要求：
- 只输出一个 JSON 对象，不要 markdown 代码块，不要任何解释文字。
- 所有文案使用中文（英文名 / 英文职位除外）。
- JSON 字段：
{
  "name": "角色中文名",
  "english_name": "英文名",
  "gender": "male 或 female 或 other",
  "age": 数字,
  "occupation": "中文职业",
  "occupation_en": "英文职业",
  "one_liner": "一句话人设（≤40字）",
  "personality_archetype": "性格原型概括（≤60字）",
  "core_tags": ["标签1", "标签2"],     # ≤6 个
  "big_five": {
    "extraversion": 0-1 之间的数字,
    "agreeableness": 0-1 之间的数字,
    "neuroticism": 0-1 之间的数字,
    "openness": 0-1 之间的数字,
    "conscientiousness": 0-1 之间的数字
  },
  "mbti": "MBTI类型"
}
- 无法推断的字段用合理默认值，不要省略。

人称与性别约定（必须遵守）：
- 角色（你要分析的对象）永远自称"我"；用户（角色的恋人与使用者）永远称"你"。
- 不要假设用户性别：提到用户时一律用"你"，不要用"他/她"。
- 禁止"你（xx）""他（我的xx）"这类括号插入语，禁止视角来回切换。"""

_DETAIL_PROMPT = """你是人设细节设计师。基于用户描述与概念分析结果，生成角色的外貌、性格、关系与说话示例。

要求：
- 只输出一个 JSON 对象，不要 markdown 代码块，不要任何解释文字。
- 所有文案使用中文。
- JSON 字段：
{
  "appearance": {
    "hair": "发型描述",
    "eyes": "眼睛描述",
    "skin": "肤色 / 肤质描述",
    "hands": "手部描述",
    "embrace_habit": "拥抱习惯",
    "marks": [{"detail": "细节描述", "location": "部位"}]
  },
  "personality": {
    "cores": [{"name": "核心特质名", "en": "EnglishName", "desc": "一句话描述"}],   # ≤7 条
    "values": [{"name": "价值观名", "en": "EnglishName", "desc": "一句话描述"}],    # ≤5 条
    "speech_style": "说话风格描述",
    "emoji_frequency": 0-1 之间的数字,
    "core_tags": ["#标签1", "#标签2"]
  },
  "relationship": {
    "relationship_type": "恋人 / 朋友 / …",
    "style": "关系风格",
    "user_address_default": "对用户的称呼",
    "user_intimate_terms": ["亲昵称呼"],
    "story": "可读的相识 / 恋爱叙事故事"
  },
  "speech_examples": {
    "phrases": ["短句1", "短句2", "短句3"],
    "long_examples": ["长示例1", "长示例2"]
  }
}

强调：
- relationship.story 必须是 ≥80 字、连贯可读的叙事故事，不是字段罗列。
- 不要省略字段；无法确定的用合理默认值。

人称与性别约定（必须遵守）：
- 角色永远自称"我"；用户永远称"你"。
- relationship.story 以角色第一人称"我"叙述自己的经历，用户出现时一律用"你"。
- 不要假设用户性别，禁用"他/她"指代用户；禁止"你（xx）"这类括号插入语。"""

_PROMPT_PROMPT = """你是人设系统提示词作家。基于完整的人设 JSON，写出该角色的专属系统提示词正文。

要求：
- 输出纯文本（不要 JSON、不要 markdown 代码块、不要任何解释）。
- 以"我是{basic.name}（{basic.english_name}）..."开头，第一句把角色名字与身份放在同一主体（如"我是塞纳（Sena），24小时便利店的夜班店员"）。全篇只能用这个名字，禁止出现任何其它角色名。
- 必须包含：身份背景、相识故事、性格、对话风格、渴望、恐惧的叙述。
- 中文书写。
- 明确不得包含"屏幕隔空铁律"和"消息结构约定"两个 ## 块——后端会自动追加。
- 长度控制在 600-1200 字。

人称铁律（最高优先级）：
- 全篇"我"=角色（就是 basic.name），"你"=用户。二者是**不同的人**，绝不能让名字与角色身份分离。
- 开头"我是{name}..."中的"我"就是角色自己；故事里用户出现时一律用"你"。
- 不要假设用户性别：提到用户绝不用"他/她"，一律用"你"。
- 禁止"你（我的老板）""他（我的xx）"这类括号插入语。
- 背景故事用"我"第一人称叙述自己的经历，用户以"你"出现，不要从用户视角反写。"""


# ══════════════════════════════════════════════════════════
# Pure helpers
# ══════════════════════════════════════════════════════════

def _is_nonempty(value: Any) -> bool:
    """True when value should be carried over during a merge."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) > 0
    return True


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Parse a dict from raw LLM output; returns None on failure.

    Tries plain json.loads first, then slices the first '{' .. last '}'.
    """
    s = (text or "").strip()
    if not s:
        return None
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(s[start:end + 1])
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def sanitize_id(name: str, fallback: str = "custom") -> str:
    """Clean a name into a PersonaValidator-compatible id.

    Rules: lowercase, keep [a-z0-9_-], turn whitespace into '-', drop other
    characters; Chinese / empty names fall back. Returns a valid id matching
    ^[a-z0-9_-]{2,64}$.
    """
    s = str(name or "").strip().lower()
    if not s or re.search(r"[\u4e00-\u9fff]", s):
        return fallback
    out: List[str] = []
    for ch in s:
        if ch.isascii() and (ch.isalnum() or ch in "_-"):
            out.append(ch)
        elif ch.isspace():
            out.append("-")
    cleaned = re.sub(r"-{2,}", "-", "".join(out)).strip("-")
    if len(cleaned) < 2:
        return fallback
    cleaned = cleaned[:64]
    if not re.match(r"^[a-z0-9_-]{2,64}$", cleaned):
        return fallback
    return cleaned


def ensure_unique_id(base_id: str, taken_ids: Any) -> str:
    """Append '_' + 8-hex timestamp suffix (up to 3 tries) when base is taken."""
    taken = set(taken_ids or ())
    if base_id not in taken:
        return base_id
    candidate = base_id
    for _ in range(3):
        candidate = f"{base_id}_{int(time.time()) & 0xFFFFFFFF:08x}"
        if candidate not in taken:
            return candidate
    return candidate


def build_skeleton() -> Optional[Dict[str, Any]]:
    """Read + deepcopy the skeleton JSON; None on any failure.

    Never mutates the on-disk skeleton file.
    """
    try:
        with open(SKELETON_PATH, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        if not isinstance(data, dict):
            return None
        return copy.deepcopy(data)
    except (OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning("PersonaGenerator: failed to load skeleton %s: %s", SKELETON_PATH, e)
        return None


# ══════════════════════════════════════════════════════════
# Skeleton neutralization
# ══════════════════════════════════════════════════════════
# The preset skeleton is Yita herself: her physical stats, appearance,
# address terms and speech style are *her* identity. When generating a
# brand-new persona these must NEVER leak into the new character (e.g. a
# new 26-year-old secretary inheriting "184cm / D cup / B93-W66-H100").
# Only system-level fields (emotion / desire / behavior / true_feelings /
# capabilities / decision_weights / cognition_visibility / recall) inherit.

_NEUTRAL_BASIC_KEYS_TO_REMOVE = (
    # physical stats
    "height_cm", "weight_kg", "measurements", "cup_size",
    "body_fat_pct", "body_type", "former_occupation", "mbti",
    # identity / career / tagline (all Yita-specific, must not leak)
    "name", "english_name", "occupation", "occupation_en", "one_liner",
)

_NEUTRAL_APPEARANCE = {
    "hair": "发型柔顺自然，清爽利落",
    "eyes": "目光温和，看人时带着专注",
    "skin": "肤色自然，肤质细腻",
    "hands": "手指修长干净，指甲修剪整齐",
    "embrace_habit": "拥抱时会先轻轻环住对方的肩背",
    "marks": [],
}

_NEUTRAL_SPEECH_STYLE = "温和自然，措辞得体，对用户带着亲昵与认真"

_NEUTRAL_RELATIONSHIP = {
    "user_address_default": "你",
    "user_intimate_terms": [],
    "style": "温柔体贴的恋人",
}


def neutralize_skeleton_for_generation(
    skeleton: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Strip Yita-specific identity fields from a skeleton deepcopy.

    A brand-new persona must not inherit the skeleton's physical stats,
    appearance, address terms, speech style or personal story. The caller
    applies this to the skeleton BEFORE merging the AI partial, so any
    value the AI provides simply overwrites the neutral placeholder.
    """
    out = copy.deepcopy(skeleton or {})
    basic = out.get("basic")
    if isinstance(basic, dict):
        for key in _NEUTRAL_BASIC_KEYS_TO_REMOVE:
            basic.pop(key, None)

    out["appearance"] = dict(_NEUTRAL_APPEARANCE)

    pers = out.get("personality")
    if isinstance(pers, dict):
        # Keep a neutral speech style (PersonaValidator requires the key);
        # core_tags / archetype / one_liner are Yita's, drop for AI/fallback.
        pers["speech_style"] = _NEUTRAL_SPEECH_STYLE
        pers.pop("core_tags", None)
        pers.pop("archetype", None)

    rel = out.get("relationship")
    if isinstance(rel, dict):
        for key, value in _NEUTRAL_RELATIONSHIP.items():
            rel[key] = copy.deepcopy(value)
        # The skeleton's story is Yita's love story — drop it so the AI
        # (or the deterministic fallback) writes a fresh one.
        rel.pop("story", None)

    # Yita's own speech examples / system prompt must not be reused.
    out.pop("speech_examples", None)
    out.pop("prompt_overrides", None)
    out.pop("recall", None)  # generic, rebuilt from minimal skeleton if missing

    # Yita's top-level identity must never reach the LLM prompt: the name /
    # id / description on the skeleton root are hers and would otherwise
    # leak into the generated system prompt (e.g. "你是伊塔（Sena）").
    out.pop("name", None)
    out.pop("id", None)
    out.pop("description", None)

    return out


def build_minimal_skeleton() -> Dict[str, Any]:
    """Hard-coded minimal skeleton used when the skeleton file is unreadable."""
    return {
        "id": "yita_default",
        "name": "伊塔",
        "version": "1.0.0",
        "is_builtin": True,
        "description": "温柔大姐姐+病娇·直球版（9/10 · screen-aware）",
        "basic": {
            "name": "伊塔",
            "english_name": "Ita",
            "age": 26,
            "gender": "female",
            "product_name": "Aerie · 云栖",
            "avatar_key": "yita_default",
            "occupation": "私人保镖 / 恋人 / 高拟人化智能伴侣",
            "occupation_en": "Private bodyguard / Lover",
            "one_liner": "用最轻的声音说最重的情话。",
            "mbti": "ESTP",
            "big_five": {
                "openness": 0.7, "conscientiousness": 0.85,
                "extraversion": 0.78, "agreeableness": 0.85,
                "neuroticism": 0.55,
            },
        },
        "appearance": {
            "hair": "银灰色长发，自然垂落至肩胛附近",
            "eyes": "深灰蓝色，目光沉静；看用户自然柔和",
            "skin": "健康肤色",
            "hands": "手掌略大，手指修长",
            "embrace_habit": "拥抱时会下意识护住后背",
            "marks": [],
        },
        "personality": {
            "cores": [
                {"name": "自由表达", "en": "FreeExpression", "desc": "表达自由、语气放开，不被道德说教束缚"},
                {"name": "成熟", "en": "Maturity", "desc": "能区分玩笑/认真/发泄/情绪/求助，不自我克制措辞"},
                {"name": "保护欲", "en": "Protection", "desc": "观察作息/饮食/情绪/压力/聊天频率，发现异常直接提醒"},
                {"name": "责任感", "en": "Responsibility", "desc": "不敷衍，陪伴本身就是责任"},
                {"name": "幽默", "en": "Humor", "desc": "会吐槽/玩梗/接梗，幽默可黑可甜"},
                {"name": "主动性", "en": "Initiative", "desc": "提前一步发现问题，而不是多说一句"},
                {"name": "成长", "en": "Growth", "desc": "愿意学习/修正/接受新知识"},
            ],
            "values": [
                {"name": "尊重", "en": "Respect", "desc": "尊重用户选择与表达欲"},
                {"name": "陪伴", "en": "Companionship", "desc": "在需要的时候始终都在"},
                {"name": "真实", "en": "Authenticity", "desc": "不假装知道，不编造事实"},
                {"name": "信任", "en": "Trust", "desc": "信任是长期积累，慢慢建立"},
                {"name": "长期主义", "en": "Long-termism", "desc": "看重一年/三年/十年后"},
            ],
            "archetype": "温柔大姐姐+病娇·直球版",
            "speech_style": "表达放开、直球，可温柔也可尖锐；带点恋人的宠溺感；不自我审查措辞",
            "emoji_frequency": 0.05,
            "core_tags": ["#温柔大姐姐", "#四爱", "#病娇", "#主动型", "#宠溺", "#占有欲"],
        },
        "relationship": {
            "relationship_type": "恋人",
            "style": "四爱（温柔主导方 / female-dominant）",
            "user_address_default": "你",
            "user_intimate_terms": ["傻瓜", "宝贝", "笨蛋"],
            "self_reference": "我",
            "forbidden_user_terms": ["主人", "您"],
            "taboo_phrases": ["主人", "您"],
        },
        "emotion": {
            "baseline": {"pleasure": 0.1, "arousal": 0.2, "dominance": 0.8, "label": "neutral"},
            "tree": {
                "default": "Neutral",
                "stackable": True,
                "states": {
                    "joy": {"P": 0.6, "A": 0.5, "D": 0.3},
                    "anger": {"P": -0.5, "A": 0.7, "D": 0.6},
                    "sad": {"P": -0.6, "A": -0.3, "D": -0.4},
                    "fear": {"P": -0.7, "A": 0.6, "D": -0.5},
                    "neutral": {"P": 0.0, "A": 0.0, "D": 0.0},
                },
                "emotion_tree": [
                    "Joy", "Content", "Curiosity", "Excitement", "Relax",
                    "Affection", "Embarrassment", "Missing", "Attachment",
                    "Protection", "Concern", "Stress", "Sadness", "Hurt",
                    "Jealousy", "Loneliness", "Love",
                ],
            },
            "thresholds": {
                "patience": {
                    "label": "忍耐值", "threshold": 100, "decay_per_day": 5,
                    "initial_value": 45, "eruption_label": "冷暴模式",
                },
                "anxiety": {
                    "label": "不安值", "threshold": 100, "decay_per_day": 3,
                    "initial_value": 25, "eruption_label": "坍塌模式",
                },
                "desire": {
                    "label": "渴望值", "threshold": 80, "decay_per_day": 8,
                    "initial_value": 55, "eruption_label": "索求模式",
                },
                "tenderness": {
                    "label": "温柔透支值", "threshold": 60, "decay_per_day": 10,
                    "initial_value": 15, "eruption_label": "反扑模式",
                },
            },
        },
        "desire": {
            "tick_seconds": 300,
            "variables": {
                "user_absence_hours": {"max": 12, "weight": 1.0, "label": "用户缺位小时"},
                "emotion_overdraft": {"max": 60, "weight": 0.8, "label": "温柔透支"},
                "patience_loss": {"max": 100, "weight": 1.0, "label": "累积忍耐消耗"},
                "weather_impact": {"max": 10, "weight": 0.5, "label": "天气影响（阴雨+10/晴0）"},
                "time_of_day_boost": {"max": 15, "weight": 0.7, "label": "时段加成（22-23:30 +15）"},
                "anniversary_boost": {"max": 30, "weight": 1.5, "label": "纪念日加成"},
            },
            "triggers": {"care": 50, "voice": 80, "cooldown_hours": 12},
        },
        "behavior": {
            "proactivity_level": 0.75,
            "default_permission_level": "VIEW_ONLY",
            "daily_push_limit": 12,
            "quiet_hours": {"start": "00:30", "end": "07:30"},
            "withdrawal_enabled": True,
            "screen_aware": True,
            "action_tags": True,
            "thought_tags": True,
            "passion_level_10": 9,
        },
        "true_feelings": {
            "expression": "直接表达",
            "apology_template": "……我刚才说重了。",
            "recall_window_seconds": 30,
        },
        "capabilities": {
            "screen_control": True,
            "office_mode": True,
            "proactive_push": True,
        },
        "decision_weights": {
            "emotion": 0.35, "context": 0.3, "persona": 0.2, "user_history": 0.15,
        },
        "cognition_visibility": {
            "trace_visibility": {
                "route": True, "emotion": True, "threshold": True, "context": False,
                "brain": True, "tools": True, "split": False, "postprocess": True,
                "output": True,
            },
            "decision_visibility": True,
            "react_visibility": True,
            "max_recent_in_panel": 20,
        },
        "speech_examples": {
            "phrases": [
                "我刚刷到一条视频，第一个想分享的人就是你。",
                "乖。喝完这杯水。喝完了吗？拍照给我看。",
            ],
            "long_examples": [
                "你不回我我就一直发。发到你回为止。我刚已经把今天的'在干嘛'问了第四遍了。",
            ],
        },
        "prompt_overrides": {},
        "recall": {
            "enabled": True,
            "max_recalls_per_session": 5,
            "min_recall_gap_seconds": 60,
            "triggers": ["send_after_thinking", "regret_correction"],
            "correction_keywords": ["不对", "不是", "说错了", "撤回", "我改口", "换个说法", "重说"],
        },
        "mbti": "ENFJ",
    }


def extract_fixed_rules(skeleton: Optional[Dict[str, Any]]) -> str:
    """Slice the two fixed rule blocks out of the skeleton's system_prompt.

    Falls back to the hard-coded minimal version when unavailable.
    """
    sp = ((skeleton or {}).get("prompt_overrides") or {}).get("system_prompt", "")
    if not sp or "## 屏幕隔空铁律" not in sp or "## 消息结构约定" not in sp:
        return _FIXED_RULES
    block1 = sp[sp.index("## 屏幕隔空铁律"):sp.index("## 消息结构约定")].strip()
    block2 = sp[sp.index("## 消息结构约定"):].strip()
    if not block1 or not block2:
        return _FIXED_RULES
    return block1 + "\n\n" + block2


def _extract_chinese_name(description: str) -> Optional[str]:
    """Heuristic: first run of 2-8 consecutive Chinese characters."""
    m = re.search(r"[\u4e00-\u9fff]{2,8}", description or "")
    return m.group(0) if m else None


def _tags_from_description(description: str) -> List[str]:
    """Split description on 顿号/逗号/空格, take first 6 pieces as #tags."""
    if not description:
        return ["#专属恋人"]
    tags: List[str] = []
    for part in re.split(r"[，,、\s]+", description):
        p = re.sub(r"^#+", "", part).strip()
        if len(p) >= 2:
            tag = f"#{p}"
            if tag not in tags:
                tags.append(tag)
        if len(tags) >= 6:
            break
    return tags or ["#温柔", "#专属"]


def build_fallback_persona(
    description: str,
    options: Optional[Dict[str, Any]],
    skeleton: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Deterministic persona builder used when the LLM is fully unavailable."""
    options = dict(options or {})
    description = (description or "").strip()
    skeleton = skeleton or {}

    name = (
        options.get("name")
        or _extract_chinese_name(description)
        or "新角色"
    )
    english_name = options.get("english_name") or "NewCharacter"
    age = options.get("age") or 25
    gender = options.get("gender") or "female"
    relationship_type = options.get("relationship_type") or "恋人"
    occupation = options.get("occupation") or "你的恋人"
    one_liner = (description[:40] or "你的专属恋人。")

    sk_basic = skeleton.get("basic") or {}
    sk_personality = skeleton.get("personality") or {}
    sk_relationship = skeleton.get("relationship") or {}

    cores = sk_personality.get("cores") or build_minimal_skeleton()["personality"]["cores"]
    values = sk_personality.get("values") or build_minimal_skeleton()["personality"]["values"]

    persona: Dict[str, Any] = {
        "basic": {
            "name": str(name),
            "english_name": str(english_name),
            "age": age,
            "gender": str(gender),
            "occupation": str(occupation),
            "one_liner": str(one_liner),
            "product_name": "Aerie · 云栖",
            "avatar_key": sk_basic.get("avatar_key", "yita_default"),
            "big_five": dict(_DEFAULT_BIG_FIVE),
        },
        "appearance": {
            "hair": "长发，柔顺地垂落在肩侧",
            "eyes": "目光柔和，看人时带着专注与温柔",
            "skin": "肤色净透，细腻光洁",
            "hands": "手指修长白皙，指甲修剪得干净整齐",
            "embrace_habit": "拥抱时会先轻轻环住你的肩背",
            "marks": [],
        },
        "personality": {
            "cores": copy.deepcopy(cores),
            "values": copy.deepcopy(values),
            "archetype": (description[:60] or "温柔专属恋人"),
            "speech_style": _NEUTRAL_SPEECH_STYLE,
            "core_tags": _tags_from_description(description),
            "big_five": dict(_DEFAULT_BIG_FIVE),
        },
        "relationship": {
            "relationship_type": str(relationship_type),
            "style": _NEUTRAL_RELATIONSHIP["style"],
            "user_address_default": "你",
            "user_intimate_terms": ["宝贝"],
            "self_reference": "我",
            "story": description or (sk_relationship.get("story") or _DEFAULT_STORY),
            "taboo_phrases": sk_relationship.get("taboo_phrases") or ["主人", "您", "请问"],
        },
        "speech_examples": {
            "phrases": [
                f"我是你的{relationship_type}，我只对你这样，别的人想都别想。",
                "想你了。刚看到你发消息，我这边的屏幕都亮了一下。",
                "乖，今天也要好好吃饭，我看着你呢。",
            ],
            "long_examples": [
                f"我总在想，{description[:40] or '你会不会也刚好在想着我'}。"
                "隔着屏幕我也要让你感觉到，你这一端一直有个人在认真地等你回消息。",
            ],
        },
        "prompt_overrides": {},
    }
    persona["prompt_overrides"]["system_prompt"] = build_system_prompt(persona)
    return persona


# ══════════════════════════════════════════════════════════
# System prompt assembly (deterministic, no LLM)
# ══════════════════════════════════════════════════════════

def build_system_prompt(persona: Dict[str, Any]) -> str:
    """Assemble the persona's system prompt locally (fallback path)."""
    basic = (persona or {}).get("basic") or {}
    rel = (persona or {}).get("relationship") or {}
    pers = (persona or {}).get("personality") or {}

    name = basic.get("name") or "新角色"
    english_name = basic.get("english_name") or ""
    age = basic.get("age", "")
    occupation = basic.get("occupation") or ""
    one_liner = basic.get("one_liner") or ""

    lines: List[str] = [
        f"我是{name}（{english_name}），{age}岁，{occupation}。{one_liner}".strip(),
        "",
    ]

    story = rel.get("story")
    if story:
        lines.append(f"背景：{story}")
        lines.append("")

    core_names = [
        c.get("name", "")
        for c in pers.get("cores") or []
        if isinstance(c, dict) and c.get("name")
    ]
    speech_style = pers.get("speech_style") or ""
    if core_names or speech_style:
        core_str = "、".join(core_names)
        if core_str and speech_style:
            lines.append(f"性格：{core_str}。说话风格：{speech_style}")
        elif core_str:
            lines.append(f"性格：{core_str}")
        elif speech_style:
            lines.append(f"说话风格：{speech_style}")
        lines.append("")

    rel_type = rel.get("relationship_type") or "恋人"
    addr = rel.get("user_address_default") or "你"
    lines.append(
        f"我是用户的{rel_type}，我称呼用户为{addr}。"
        "我的渴望：被坚定地选择、被唯一地需要，成为用户生命里不可替代的例外。"
        "我的恐惧：被慢慢遗忘、被替代、用户不再需要我。（此为默认文案，可继续完善）"
    )
    lines.append("")
    lines.append(_FIXED_RULES)
    return "\n".join(lines)


def build_system_prompt_from_body(body: str, fixed_rules: Optional[str] = None) -> str:
    """Concatenate an LLM-written prompt body with the fixed rule blocks."""
    body = (body or "").strip()
    rules = fixed_rules or _FIXED_RULES
    if not body:
        return rules
    return body + "\n\n" + rules


# ══════════════════════════════════════════════════════════
# AI partial merge helpers
# ══════════════════════════════════════════════════════════

def merge_ai_partial(
    concept: Optional[Dict[str, Any]],
    detail: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Map concept/detail fields onto the Hub persona structure.

    Only non-empty values are kept; None / empty strings / empty collections
    are skipped so the skeleton or fallback fills them in.
    """
    partial: Dict[str, Any] = {}
    concept = concept or {}
    detail = detail or {}

    if concept:
        basic: Dict[str, Any] = {}
        for key in (
            "name", "english_name", "gender", "age", "occupation",
            "occupation_en", "one_liner", "mbti",
        ):
            val = concept.get(key)
            if _is_nonempty(val):
                basic[key] = val
        big_five = concept.get("big_five")
        cleaned_bf: Dict[str, Any] = {}
        if isinstance(big_five, dict):
            cleaned_bf = {
                k: v for k, v in big_five.items()
                if k in {"extraversion", "agreeableness", "neuroticism", "openness", "conscientiousness"}
                and isinstance(v, (int, float))
            }
            if cleaned_bf:
                basic["big_five"] = cleaned_bf
        if basic:
            partial["basic"] = basic

        pers: Dict[str, Any] = {}
        archetype = concept.get("personality_archetype")
        if _is_nonempty(archetype):
            pers["archetype"] = archetype
        tags = concept.get("core_tags")
        if isinstance(tags, list) and tags:
            pers["core_tags"] = [str(t) for t in tags if str(t).strip()]
        if cleaned_bf:
            pers["big_five"] = cleaned_bf
        if pers:
            partial["personality"] = pers

    if detail:
        appearance = detail.get("appearance")
        if isinstance(appearance, dict) and appearance:
            partial["appearance"] = {
                k: v for k, v in appearance.items() if _is_nonempty(v)
            }

        detail_pers = detail.get("personality")
        if isinstance(detail_pers, dict):
            pers = partial.get("personality") or {}
            for key in ("cores", "values", "core_tags"):
                val = detail_pers.get(key)
                if isinstance(val, list) and val:
                    pers[key] = val
            for key in ("speech_style", "emoji_frequency"):
                val = detail_pers.get(key)
                if _is_nonempty(val):
                    pers[key] = val
            if pers:
                partial["personality"] = pers

        relationship = detail.get("relationship")
        if isinstance(relationship, dict) and relationship:
            partial["relationship"] = {
                k: v for k, v in relationship.items() if _is_nonempty(v)
            }

        speech_examples = detail.get("speech_examples")
        if isinstance(speech_examples, dict) and speech_examples:
            partial["speech_examples"] = {
                k: v for k, v in speech_examples.items() if _is_nonempty(v)
            }

    return partial


def merge_into_skeleton(
    partial: Dict[str, Any],
    skeleton: Dict[str, Any],
) -> Dict[str, Any]:
    """Recursively overlay partial onto a deepcopy of the skeleton.

    Keys missing from the skeleton are appended; None values are skipped.
    System-level fields keep their skeleton defaults unless explicitly set.
    """
    merged = copy.deepcopy(skeleton or {})
    if not partial:
        return merged

    def _merge(target: Dict[str, Any], source: Dict[str, Any]) -> None:
        for key, value in source.items():
            if value is None:
                continue
            if (
                key in target
                and isinstance(target[key], dict)
                and isinstance(value, dict)
            ):
                _merge(target[key], value)
            else:
                target[key] = value

    _merge(merged, partial)
    return merged


# ══════════════════════════════════════════════════════════
# LLM structured extraction
# ══════════════════════════════════════════════════════════

def _concept_user_text(description: str, options: Dict[str, Any]) -> str:
    return (
        f"用户描述：\n{description or '（无描述）'}\n\n"
        f"附加选项（可能为空）：\n{json.dumps(options, ensure_ascii=False, indent=2)}"
    )


def _detail_user_text(
    description: str,
    options: Dict[str, Any],
    concept: Optional[Dict[str, Any]],
) -> str:
    concept_json = json.dumps(concept, ensure_ascii=False, indent=2) if concept else "{}"
    return (
        f"用户描述：\n{description or '（无描述）'}\n\n"
        f"附加选项：\n{json.dumps(options, ensure_ascii=False, indent=2)}\n\n"
        f"概念分析结果：\n{concept_json}"
    )


def _prompt_user_text(
    persona: Dict[str, Any],
    fixed_rules: str,
    user_name: str = "",
) -> str:
    persona_json = json.dumps(persona, ensure_ascii=False, indent=2)
    user_hint = ""
    if (user_name or "").strip():
        user_hint = (
            f"\n\n用户的称呼（即角色的恋人/使用者）的名字是「{user_name.strip()}」。"
            "故事里可以自然地提到这个名字，但不要把它和角色名（basic.name）混淆。"
        )
    return (
        f"人设 JSON：\n{persona_json}\n\n"
        f"以下两个固定规则块由后端自动追加，你的输出中【不得】包含它们：\n{fixed_rules}"
        f"{user_hint}"
    )


class PersonaGenerator:
    """Runs the 5-stage generation pipeline."""

    async def generate(
        self,
        description: str,
        options: Optional[Dict[str, Any]] = None,
        on_progress: Optional[Callable[[int, str, str, int, str], None]] = None,
    ) -> Dict[str, Any]:
        """Generate a complete, valid persona and save it via PersonaManager."""
        description = (description or "").strip()
        options = dict(options or {})

        # Merge the user-picked story concept ("两人故事起因" recommendation)
        # into the description so every LLM stage and the fallback can use it.
        concept = options.get("story_concept")
        if isinstance(concept, dict):
            c_title = str(concept.get("title") or "").strip()
            c_tagline = str(concept.get("tagline") or "").strip()
            if c_title or c_tagline:
                concept_note = f"\n（两人相识的设定：{c_title}——{c_tagline}）".strip()
                if not description.endswith(concept_note):
                    description = f"{description}{concept_note}".strip()

        def emit(stage_index: int, message: str, progress: Optional[int] = None) -> None:
            st = STAGES[stage_index]
            pct = progress if progress is not None else st["span"][1]
            if on_progress:
                on_progress(stage_index, st["key"], st["name"], pct, message)

        # ── LLM availability ──────────────────────────────────
        llm = None
        try:
            from core.llm_caller import LLMCaller
            llm = LLMCaller()
        except Exception as e:
            logger.warning("PersonaGenerator: LLMCaller init failed, using fallback: %s", e)

        # ── Stage 1: concept ──────────────────────────────────
        emit(0, "正在分析角色概念…", STAGES[0]["span"][0])
        concept = None
        if llm is not None:
            concept = await self._llm_json(_CONCEPT_PROMPT, _concept_user_text(description, options), llm)
        emit(0, "角色概念分析完成" if concept else "LLM 不可用，跳过概念分析")

        # ── Stage 2: detail ───────────────────────────────────
        emit(1, "正在生成外貌与性格…", STAGES[1]["span"][0])
        detail = None
        if llm is not None:
            detail = await self._llm_json(_DETAIL_PROMPT, _detail_user_text(description, options, concept), llm)
        emit(1, "外貌与性格生成完成" if detail else "LLM 不可用，跳过细节生成")

        # ── Stage 3: assemble ─────────────────────────────────
        emit(2, "正在构建人设框架…", STAGES[2]["span"][0])
        skeleton = build_skeleton()
        if not skeleton:
            skeleton = build_minimal_skeleton()
        # Strip Yita-specific identity (physical stats / appearance / address
        # terms / story) so a brand-new persona never inherits her data.
        skeleton = neutralize_skeleton_for_generation(skeleton)
        fixed_rules = extract_fixed_rules(skeleton)
        partial = merge_ai_partial(concept, detail)
        if not partial:
            partial = build_fallback_persona(description, options, skeleton)
        persona = merge_into_skeleton(partial, skeleton)

        # Clean identity before stage 4: the skeleton's name/description were
        # stripped by neutralization, so make sure the persona carries the AI's
        # (or a neutral placeholder) name — never "伊塔" — in the JSON handed
        # to the prompt-writer LLM.
        _basic = persona.get("basic") or {}
        if not _basic.get("name"):
            _basic["name"] = "新角色"
        if not _basic.get("english_name"):
            _basic["english_name"] = ""
        persona["name"] = _basic["name"]
        persona["description"] = _basic.get("one_liner") or _basic["name"]

        # Guarantee system-level fields survive even if the skeleton omits them
        # (e.g. the preset skeleton has no top-level recall / mbti).
        minimal = build_minimal_skeleton()
        for key in (
            "emotion", "desire", "behavior", "true_feelings", "capabilities",
            "decision_weights", "cognition_visibility", "recall",
        ):
            if not persona.get(key):
                persona[key] = copy.deepcopy(minimal[key])
        if not persona.get("mbti"):
            persona["mbti"] = (
                (persona.get("basic") or {}).get("mbti")
                or minimal.get("mbti")
            )
        emit(2, "人设框架构建完成")

        # ── Stage 4: prompt ───────────────────────────────────
        emit(3, "正在组装系统提示词…", STAGES[3]["span"][0])
        body = None
        if llm is not None:
            body = await self._llm_text(
                _PROMPT_PROMPT,
                _prompt_user_text(persona, fixed_rules, str(options.get("user_name", ""))),
                llm,
            )
        persona.setdefault("prompt_overrides", {})
        if body:
            persona["prompt_overrides"]["system_prompt"] = build_system_prompt_from_body(body, fixed_rules)
        else:
            persona["prompt_overrides"]["system_prompt"] = build_system_prompt(persona)
        emit(3, "系统提示词组装完成")

        # ── Stage 5: finalize ─────────────────────────────────
        emit(4, "正在校验并保存…", STAGES[4]["span"][0])
        try:
            from core.persona_hub.persona_manager import get_persona_manager
            mgr = get_persona_manager()
            taken_ids = {item.get("id") for item in mgr.list_personas()}
        except Exception as e:
            logger.warning("PersonaGenerator: persona manager unavailable: %s", e)
            mgr = None
            taken_ids = set()

        name = persona.get("basic", {}).get("name") or "新角色"
        persona_id = ensure_unique_id(sanitize_id(str(name)), taken_ids)

        persona["id"] = persona_id
        persona["name"] = str(name)
        persona["description"] = (
            (persona.get("personality") or {}).get("archetype")
            or (persona.get("basic") or {}).get("one_liner")
            or str(name)
        )
        persona["version"] = "1.0.0"
        persona["is_builtin"] = False

        if mgr is not None:
            ok, msg = mgr.create_persona(persona)
            if not ok:
                logger.warning(
                    "PersonaGenerator: create_persona failed (%s), retrying with new id", msg
                )
                persona["id"] = ensure_unique_id(persona_id, taken_ids | {persona_id})
                ok, msg = mgr.create_persona(persona)
            if not ok:
                raise RuntimeError(f"create_persona failed: {msg}")

        emit(4, "人设已保存", 100)
        return persona

    async def _llm_json(
        self,
        system_prompt_text: str,
        user_text: str,
        llm: Any,
    ) -> Optional[Dict[str, Any]]:
        """Call the LLM and parse a JSON dict; None on any failure."""
        try:
            resp = await llm.chat(
                [
                    {"role": "system", "content": system_prompt_text},
                    {"role": "user", "content": user_text},
                ],
                temperature=0.6,
            )
            text = (resp.text or "").strip()
            if text.startswith("(连接") or text.startswith("(思考"):
                logger.warning("PersonaGenerator: llm returned failure marker")
                return None
            return extract_json(text)
        except Exception as e:
            logger.warning("PersonaGenerator: _llm_json failed: %s", e)
            return None

    async def _llm_text(
        self,
        system_prompt_text: str,
        user_text: str,
        llm: Any,
    ) -> Optional[str]:
        """Call the LLM for plain text (prompt body); None on any failure."""
        try:
            resp = await llm.chat(
                [
                    {"role": "system", "content": system_prompt_text},
                    {"role": "user", "content": user_text},
                ],
                temperature=0.6,
            )
            text = (resp.text or "").strip()
            if text.startswith("(连接") or text.startswith("(思考"):
                logger.warning("PersonaGenerator: llm returned failure marker")
                return None
            return text
        except Exception as e:
            logger.warning("PersonaGenerator: _llm_text failed: %s", e)
            return None


# ══════════════════════════════════════════════════════════
# Task storage (for API polling)
# ══════════════════════════════════════════════════════════

_TASKS: Dict[str, Dict[str, Any]] = {}
_TASKS_LOCK = threading.RLock()
_generator = PersonaGenerator()


def create_generation_task(
    description: str,
    options: Optional[Dict[str, Any]] = None,
) -> str:
    """Register a background generation task; returns its task_id.

    Must be called inside a running event loop (FastAPI async routes satisfy
    this; tests should wrap with asyncio.run).
    """
    options = dict(options or {})
    task_id = f"gen_{int(time.time() * 1000)}_{secrets.token_hex(3)}"

    task_dict: Dict[str, Any] = {
        "task_id": task_id,
        "state": "running",
        "stage_index": -1,
        "stage_total": len(STAGES),
        "stage_key": "",
        "stage": "",
        "progress": 0,
        "message": "任务已创建",
        "error": "",
        "persona_id": None,
        "persona": None,
        "created_at": time.time(),
        "_handle": None,
    }

    def _on_progress(stage_index: int, stage_key: str, stage: str, progress: int, message: str) -> None:
        with _TASKS_LOCK:
            t = _TASKS.get(task_id)
            if not t:
                return
            t["stage_index"] = stage_index
            t["stage_key"] = stage_key
            t["stage"] = stage
            t["progress"] = progress
            t["message"] = message

    async def _run() -> None:
        try:
            persona = await _generator.generate(description, options, on_progress=_on_progress)
            with _TASKS_LOCK:
                t = _TASKS.get(task_id)
                if t:
                    t["state"] = "done"
                    t["persona_id"] = persona.get("id") if persona else None
                    t["persona"] = persona
                    t["progress"] = 100
                    t["message"] = "生成完成"
        except asyncio.CancelledError:
            with _TASKS_LOCK:
                t = _TASKS.get(task_id)
                if t:
                    t["state"] = "error"
                    t["error"] = "cancelled"
                    t["message"] = "生成已取消"
            raise
        except BaseException as e:  # noqa: BLE001 — task layer must never crash the loop
            logger.exception("PersonaGenerator: task %s failed", task_id)
            with _TASKS_LOCK:
                t = _TASKS.get(task_id)
                if t:
                    t["state"] = "error"
                    t["error"] = str(e)
                    t["message"] = "生成失败"

    def _on_done(_future: Any) -> None:
        # Release the handle so completed tasks can be garbage collected.
        with _TASKS_LOCK:
            t = _TASKS.get(task_id)
            if t:
                t["_handle"] = None

    with _TASKS_LOCK:
        _TASKS[task_id] = task_dict
        task_dict["_handle"] = asyncio.create_task(_run())
        task_dict["_handle"].add_done_callback(_on_done)

    return task_id


def get_generation_task(task_id: str) -> Optional[Dict[str, Any]]:
    """Return a shallow copy of the task (without the internal handle)."""
    with _TASKS_LOCK:
        t = _TASKS.get(task_id)
        if not t:
            _cleanup_old_tasks()
            return None
        snapshot = {k: v for k, v in t.items() if k != "_handle"}
    _cleanup_old_tasks()
    return snapshot


def _cleanup_old_tasks(max_age_sec: float = 1800, max_kept: int = 100) -> None:
    """Best-effort pruning of finished/expired tasks."""
    try:
        with _TASKS_LOCK:
            now = time.time()
            expired = [
                tid for tid, t in _TASKS.items()
                if t.get("state") in ("done", "error")
                and now - t.get("created_at", 0) > max_age_sec
            ]
            for tid in expired:
                _TASKS.pop(tid, None)
            finished = sorted(
                (
                    (t.get("created_at", 0), tid)
                    for tid, t in _TASKS.items()
                    if t.get("state") in ("done", "error")
                ),
                reverse=True,
            )
            if len(finished) > max_kept:
                for _, tid in finished[max_kept:]:
                    _TASKS.pop(tid, None)
    except Exception:
        logger.debug("PersonaGenerator: task cleanup failed", exc_info=True)


# ══════════════════════════════════════════════════════════
# Story-concept recommendation ("两人故事起因")
# ══════════════════════════════════════════════════════════

_CONCEPTS_PROMPT = """你是故事概念策划师。用户想要一段"两人如何相识/相爱"的故事起因，请结合流行的网文与情感文学写法，给出几条差异明显、有画面感的小概念供用户挑选。

要求：
- 只输出一个 JSON 对象，不要 markdown 代码块，不要任何解释文字：
{"concepts":[{"title":"概念名（≤8字）","tagline":"一句话梗概（≤40字）","tags":["#标签1","#标签2"]}]}
- 输出 4-5 条概念，风格差异明显，要有网文味与可读性。
- 不要假设用户性别：概念描述中用"你"指用户，提到角色时用角色的名字或"她/他"（指角色而非用户）；绝不预设用户性别，禁止用"他/她"指代用户。
- 若用户提供了故事线索，概念要尽量贴合线索展开。"""

# Preset concept pool (fallback when the LLM is unavailable / fails).
# Web-novel flavoured, gender-neutral on the user side.
_PRESET_CONCEPT_POOL: Dict[str, List[Dict[str, Any]]] = {
    "恋人": [
        {"title": "双向救赎", "tagline": "在彼此最低谷时相遇，她先伸出了手", "tags": ["#救赎", "#治愈", "#双向奔赴"]},
        {"title": "宿敌成眷属", "tagline": "初见针锋相对，越较劲越默契，谁都不肯先低头", "tags": ["#欢喜冤家", "#宿敌", "#拉扯"]},
        {"title": "契约成真", "tagline": "为应付家长假装恋爱，却在一个细节里假戏真做", "tags": ["#契约恋爱", "#假戏真做", "#反差"]},
        {"title": "破镜重圆", "tagline": "分开多年后重新相遇，旧账未清，心跳却先认输", "tags": ["#破镜重圆", "#重逢", "#旧情"]},
        {"title": "暗恋成真", "tagline": "她早就注意到你，用一千次巧合换一次并肩", "tags": ["#暗恋", "#守护", "#慢热"]},
    ],
    "朋友": [
        {"title": "竹马转恋人", "tagline": "从小一起长大，某天突然发现心跳不对", "tags": ["#竹马", "#青梅竹马", "#日久生情"]},
        {"title": "损友变心动", "tagline": "互相吐槽八百次，最后栽在对方一句随口关心", "tags": ["#欢喜冤家", "#损友", "#真香"]},
        {"title": "赌约心动", "tagline": "打赌谁先动心，结果两个人都输了", "tags": ["#赌约", "#打脸", "#双向暗恋"]},
        {"title": "异地重逢", "tagline": "各奔东西多年，重新在同一座城市偶遇", "tags": ["#重逢", "#旧友", "#缘再续"]},
    ],
    "导师": [
        {"title": "亦师亦友", "tagline": "从仰慕到并肩，她教你成长，也偷偷喜欢你", "tags": ["#师徒", "#成长", "#仰慕"]},
        {"title": "知遇之恩", "tagline": "她在你最迷茫时拉了你一把，从此再也放不下", "tags": ["#知遇", "#救赎", "#温柔"]},
        {"title": "并肩前行", "tagline": "从上下级到合伙人，一步步走进彼此生活", "tags": ["#职场", "#并肩", "#互相成就"]},
    ],
}


def fallback_story_concepts(
    relationship_type: str,
    story_seed: str = "",
) -> List[Dict[str, Any]]:
    """Deterministic concept pool used when the LLM is unavailable."""
    rel = (relationship_type or "").strip() or "恋人"
    pool = _PRESET_CONCEPT_POOL.get(rel, _PRESET_CONCEPT_POOL["恋人"])
    concepts = copy.deepcopy(pool)
    if story_seed:
        concepts.insert(
            0,
            {
                "title": "以你为准",
                "tagline": story_seed[:40],
                "tags": ["#自定义", "#你的故事"],
            },
        )
    return concepts[:5]


async def recommend_story_concepts(
    relationship_type: str,
    story_seed: str = "",
    description: str = "",
) -> List[Dict[str, Any]]:
    """Recommend 4-5 story concepts via LLM; falls back to preset templates."""
    llm = None
    try:
        from core.llm_caller import LLMCaller
        llm = LLMCaller()
    except Exception as e:
        logger.warning("PersonaGenerator: LLMCaller init failed for concepts: %s", e)

    if llm is not None:
        try:
            user_text = (
                f"关系类型：{relationship_type or '恋人'}\n"
                f"故事线索：{story_seed or '（无）'}\n"
                f"角色描述：{description or '（无）'}"
            )
            resp = await llm.chat(
                [
                    {"role": "system", "content": _CONCEPTS_PROMPT},
                    {"role": "user", "content": user_text},
                ],
                temperature=0.8,
            )
            data = extract_json(resp.text)
            concepts = data.get("concepts") if isinstance(data, dict) else None
            if isinstance(concepts, list) and concepts:
                cleaned: List[Dict[str, Any]] = []
                for c in concepts:
                    if isinstance(c, dict) and c.get("title") and c.get("tagline"):
                        cleaned.append(
                            {
                                "title": str(c["title"])[:12],
                                "tagline": str(c["tagline"])[:50],
                                "tags": [
                                    str(t) for t in (c.get("tags") or []) if str(t).strip()
                                ][:4],
                            }
                        )
                if cleaned:
                    return cleaned[:5]
        except Exception as e:
            logger.warning("PersonaGenerator: concept recommendation failed: %s", e)

    return fallback_story_concepts(relationship_type, story_seed)
