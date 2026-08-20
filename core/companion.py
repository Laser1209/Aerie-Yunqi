"""Aerie · 云栖 v0.1.0-beta.1 — Companion: orchestrator for all backend modules."""

from __future__ import annotations
import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from communication.message import IncomingMessage, OutgoingReply
from communication.qq_client import QQClient
from communication.recall_manager import RecallManager
from communication.router import Router
from communication.send_queue import SendQueue
from communication.splitter import SemanticMessageSplitter
from config.persona_loader import load_behavior_config
from core.llm_caller import LLMCaller
from core.qq_media import QQMediaPreprocessor
from core.qq_sticker import QQStickerSender
from core.cognition import CognitionEngine
from core.decision import MultiLayerDecision
from core.computer_control import ComputerController
from core.conversation_continuity import (
    ContextAssembler,
    ConversationSummaryRepository,
    PersonaTimelineRepository,
    SummaryRefreshPlanner,
)
from core.conversation_repository import ConversationRepository
from core.chat_events import emit
from core.chat_request_repository import ChatRequestRepository
from core.chat_request_service import ChatRequestService
from core.chat_request_worker import ChatRequestWorker
from core.permission_manager import FineGrainedPermissionManager
from core.context_builder import ContextBuilder
from core.database import Database
from core.desktop_attachments import DesktopAttachmentService
from core.emotion_engine import EmotionEngine
from core.emotion_state_store import EmotionStateStore
from core.emotion_threshold import get_threshold_engine
from core.internal_state import InternalStateEngine
from core.feature_flags import FeatureFlags
from core.ids import generate_id
from core.identity import IdentityRepository, IdentityResolver
from core.pipeline import Pipeline
from core.paths import data_dir
from core.primary_identity import PrimaryIdentityResolver
from core.push_event_engine import get_event_engine
from core.push_scheduler import PushScheduler
from core.qq_whitelist import QQWhitelistManager
from core.self_evolve_l4 import L4SelfEvolution
from core.self_evolve_proposer import SelfEvolveProposer
from core.self_evolver import SelfEvolver
from core.tool_registry import ToolRegistry
from core.world_port import build_world_port
from core.world_simulation import LOCAL_TZ
from core.holidays import holiday_name, event_preference
from core import solar_time
from core.ephemeris import moon_phase
from config.persona_loader import load_settings, load_proactive_config, load_persona
from knowledge.kb import KnowledgeBase
from core.knowledge_indexer import resolve_embedding_fn
from memory.layers import LayeredMemory
from memory.layers.sync_adapter import LayeredMemorySyncAdapter
from core.message_batcher import MessageBatcher
from core.message_orchestrator import RecallJudge
from tools import register_all_tools

logger = logging.getLogger(__name__)

_COMPANION = None


def _api_base_url() -> str:
    """Backend origin the Electron renderer must use to load uploaded images.

    The renderer window is loaded from ``file://`` (not the backend origin),
    so any image src in a chat bubble has to be an absolute URL pointing at
    the API server that serves ``/uploads``.
    """
    port = os.environ.get("AERIE_BACKEND_PORT") or "7890"
    return f"http://127.0.0.1:{port}"


# 伊塔重庆复式公寓的物件 ID → 中文描述（与 world_simulation._ENVIRONMENT_OBJECTS
# 对齐）。环境照 prompt 用它把代码级物件 ID 翻译成自然的画面描述。
# 新房间(132㎡江景复式)的 75 项 OBJ-xxx 物件翻译统一收口在 core.home_space，
# 此处仅保留旧英文 ID 兼容表，运行时合并，避免双份数据漂移。
_HER_HOME_OBJECTS_ZH_LEGACY: dict[str, str] = {
    "king_bed": "主卧那张2米的大床",
    "night_lamp": "床头那盏小夜灯",
    "window": "朝南的江景窗",
    "your_coat": "叠在床另一侧的那件外套",
    "password_lock": "入户门上的密码锁",
    "shoe_cabinet": "玄关的鞋柜",
    "gray_sofa": "客厅的灰模块沙发",
    "bookshelf": "客厅那面满墙书柜",
    "pendant": "书架第二层你送的挂件",
    "double_door_fridge": "双开门冰箱",
    "round_table": "圆形小餐桌",
    "kitchen_island": "开放式中岛",
    "floor_lamp": "落地钓鱼灯",
    "design_desk": "工作室那张2.4米的设计桌",
    "imac": "iMac",
    "drawing_tablet": "数位板",
    "corkboard": "钉着你纸条的软木板",
}


def _merged_home_objects_zh() -> dict[str, str]:
    """合并新房间(OBJ-xxx) + 旧英文 ID 两套翻译表。

    home_space 为单一事实源；合并失败时退化仅用旧表（生图不中断）。
    """
    merged = dict(_HER_HOME_OBJECTS_ZH_LEGACY)
    try:
        from core.home_space import LEGACY_OBJECT_ZH, OBJECT_ZH

        merged.update(LEGACY_OBJECT_ZH)
        merged.update(OBJECT_ZH)
    except Exception:
        pass
    return merged


_HER_HOME_OBJECTS_ZH: dict[str, str] = _merged_home_objects_zh()


# 活动/时刻话题 → 中文画面描述（P2 修复）。世界模拟产出的 available_visual_topics
# 除 object_<obj> 物件话题外，还有按 activity 派生的话题（reading_time / deep_focus /
# coffee_break 等）。这些话题曾直接以英文 token 进生图提示词（"…眼前的一角：reading_time"）。
# 这里补全中文翻译，覆盖 world_simulation._ACTIVITY_TOPIC_PREFIXES 全部前缀，
# 供环境照 prompt、role_in_scene 人物时刻、以及 _world_context_text 接力上下文统一翻译。
_VISUAL_TOPIC_ZH: dict[str, str] = {
    "reading_time": "她窝在沙发里翻书",
    "deep_focus": "她在工作台前专注地画着设计稿",
    "morning_plan": "清晨她在桌前做今天的计划",
    "coffee_break": "她端着咖啡杯短暂休息的片刻",
    "lunch_time": "她的午餐时光",
    "tea_break": "她泡了杯茶的茶歇时刻",
    "evening_chill": "她靠在窗边放松的傍晚时光",
    "good_night": "她睡前窝在床上的片刻",
    "starry_window": "窗外洒进来的星空夜色",
    "desk_view": "她书桌前一角",
    "quiet_moment": "她安安静静独处的时刻",
    # 兼容历史旧话题名（不在 _ACTIVITY_TOPIC_PREFIXES 但可能来自旧数据/POI）
    "evening_home": "她家中的傍晚一景",
    "city_night": "窗外重庆的夜景",
    "river_view": "落地窗外的江景",
}


def _visual_topic_zh(topic: str) -> str:
    """把视觉话题 id 翻译成中文画面描述；物件话题走 _HER_HOME_OBJECTS_ZH，未知兜底原文。

    翻译优先级：活动时刻话题（_VISUAL_TOPIC_ZH）→ 物件话题（_HER_HOME_OBJECTS_ZH）
    → 原样返回。任何已知话题都不该把英文 token 漏进生图提示词。
    """
    text = str(topic or "").strip()
    if not text:
        return ""
    if text in _VISUAL_TOPIC_ZH:
        return _VISUAL_TOPIC_ZH[text]
    stripped = text.replace("object_", "", 1) if text.startswith("object_") else text
    if stripped in _HER_HOME_OBJECTS_ZH:
        return _HER_HOME_OBJECTS_ZH[stripped]
    return text


def _prompt_key_for_visual_topic(topic: str) -> str:
    """按素材类型决断发图模板：活动/时刻话题 → 人物入镜（role_in_scene），
    物件/环境话题 → 第一人称环境照（environment_object）。未知话题回退环境照。

    P2 修复：主动发图曾把所有话题都塞进 environment_object，导致"看书/咖啡"
    这类人物时刻也生成"随手拍的一角"环境照，模板能力被浪费。
    """
    text = str(topic or "").strip()
    if not text:
        return "environment_object"
    stripped = text.replace("object_", "", 1) if text.startswith("object_") else text
    # 物件话题（含 OBJ-xxx 与旧英文物件 id）→ 环境照
    if text.startswith("object_") or text.startswith("OBJ-"):
        return "environment_object"
    if text in _HER_HOME_OBJECTS_ZH or stripped in _HER_HOME_OBJECTS_ZH:
        return "environment_object"
    # 活动时刻话题 → 人物自拍入镜（POV 由 M1 保证）
    if text in _VISUAL_TOPIC_ZH:
        return "role_in_scene"
    return "environment_object"


# prompt_key → 图片事件的中文描述（P3 发图自我认知）。用户/系统主动发图落账时，
# 若没有可翻译的视觉话题（reason_code 无 world_visual 前缀），用这个映射兜底。
_IMAGE_PROMPT_KEY_ZH: dict[str, str] = {
    "role_selfie": "她的一张自拍",
    "role_in_scene": "她在场景里的一张照片",
    "couple_photo": "他们的合照",
    "environment_object": "她随手拍的生活一角",
}


def _image_event_desc(plan: dict) -> str:
    """从 delivery plan 生成图片事件的中文描述（P3）。

    优先级：视觉话题翻译（world_visual:<topic> → _VISUAL_TOPIC_ZH/_HER_HOME_OBJECTS_ZH）
    → prompt_key 兜底映射 → 通用描述。保证聊天历史/记忆里有"图里是什么"。
    """
    plan = plan if isinstance(plan, dict) else {}
    reason_code = str(plan.get("reason_code") or "").strip()
    topic = ""
    if reason_code.startswith("world_visual:"):
        topic = reason_code.split("world_visual:", 1)[1].replace("object_", "").strip()
    if topic:
        zh = _visual_topic_zh(topic)
        if zh and zh != topic:
            return zh
    prompt_key = str(plan.get("prompt_key") or "").strip()
    if prompt_key in _IMAGE_PROMPT_KEY_ZH:
        return _IMAGE_PROMPT_KEY_ZH[prompt_key]
    return "她发来的一张照片"


# ── 生图构图：手机拍摄比例（横 16:9 / 竖 9:16），横竖由伊塔按场景自决 ──
# 自拍/人像/合影 → 竖屏 9:16；环境/物件/风景 → 横屏 16:9。
# 尺寸满足中转站规则（边长 512~4096 且为 64 的倍数），1344x768 ≈ 16:9、768x1344 ≈ 9:16。
_IMAGE_SIZE_LANDSCAPE = "1344x768"
_IMAGE_SIZE_PORTRAIT = "768x1344"
_IMAGE_SIZE_BY_PROMPT_KEY: dict[str, str] = {
    "role_selfie": _IMAGE_SIZE_PORTRAIT,
    "role_in_scene": _IMAGE_SIZE_PORTRAIT,
    "couple_photo": _IMAGE_SIZE_PORTRAIT,
    "environment_object": _IMAGE_SIZE_LANDSCAPE,
}


def _image_size_for_prompt_key(prompt_key: str) -> str:
    """按发图场景决断手机拍摄的横竖比例（16:9 / 9:16），即伊塔的构图自决。"""
    return _IMAGE_SIZE_BY_PROMPT_KEY.get(str(prompt_key or ""), _IMAGE_SIZE_PORTRAIT)


def _image_orientation_phrase(image_size: str) -> str:
    """把尺寸转成写进生图 prompt 的构图方向提示（让生成模型配合构图）。"""
    try:
        width, height = (int(part.strip()) for part in str(image_size).lower().split("x"))
    except (ValueError, AttributeError):
        return "竖构图（手机竖拍 9:16 比例）"
    if width >= height:
        return "横构图（手机横拍 16:9 比例）"
    return "竖构图（手机竖拍 9:16 比例）"


# ── 模块化生图规格：从用户原始指令解析出可组合的画面模块 ─────────
# 用户指令（如"看看腿""在床上躺着拍一张""仰视低角度拍脚"）包含多个画面维度，
# 但旧实现只靠 intent 关键字，把"腿/床上/躺/仰视"全部丢失，提示词永远是以
# 完整人物+固定场景为基准。这里用确定性关键词分维度提取，命中即写进画面：
#   focus（主体特写） / pose（姿态） / angle（机位） / scene（环境）
# 未命中的维度返回空串，由组合器兜底为默认，绝不让缺值中断生图（缺值即停防护）。
_PHOTO_FOCUS_TABLE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("双腿", ("看看腿", "你的腿", "大腿", "腿", "腿部", "美腿", "长腿", "腿照")),
    ("双脚", ("看看脚", "你的脚", "脚", "美脚", "脚丫")),
    ("手", ("看看手", "你的手", "手部", "玉手")),
    ("腰", ("看看腰", "你的腰", "腰", "细腰")),
    ("肩颈锁骨", ("锁骨", "肩", "脖子")),
    ("背影", ("背影", "从后面", "背对着")),
    ("头发", ("头发", "发丝", "长发")),
    ("脸庞", ("看脸", "你的脸", "脸", "正脸")),
    ("眼睛", ("眼睛", "双眼", "眼神")),
    ("全身", ("全身", "全身照", "整个你")),
)

# 局部特写 focus 集合：派生自 _PHOTO_FOCUS_FULL_TABLE（细表+主表），除「全身」外的
# 所有 focus 标签。命中时走精简 base —— 不写身高/体重/体脂/围/发色/眼色等无关标签，
# 文字层仅用「人物外貌以参考图为准」指代，由 three_view 图生图锁人物一致性。
#
# 细表（方案 A）：在父部位之上再拆到单个部位，提取与 LLM 归一化都优先细表，
# 命中即用更细 label（如「大腿」而非「双腿」），未命中才回退主表父级别。
_PHOTO_FOCUS_DETAIL_TABLE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("脚踝", ("脚踝", "踝部", "纤细脚踝")),
    ("足背", ("足背", "脚背", "脚面")),
    ("脚趾", ("脚趾", "脚趾头")),
    ("小腿", ("小腿", "小腿肚")),
    ("大腿", ("大腿", "大腿内侧")),
    ("膝盖", ("膝盖", "膝窝")),
    ("手指", ("手指", "指节", "指尖", "指骨")),
    ("手腕", ("手腕", "腕骨", "手踝")),
    ("掌心", ("掌心", "掌纹", "手掌心")),
    ("锁骨", ("锁骨", "锁骨窝", "锁骨线条")),
    ("脖颈", ("脖颈", "颈侧", "脖颈线条")),
    ("腰肢", ("腰窝", "腰肢", "腰际线")),
    ("耳廓", ("耳廓", "耳垂", "耳边缘")),
    ("嘴唇", ("嘴唇", "唇瓣", "唇部", "嘴角")),
)
_PHOTO_FOCUS_FULL_TABLE = _PHOTO_FOCUS_DETAIL_TABLE + _PHOTO_FOCUS_TABLE
_CLOSEUP_FOCUS_SET: frozenset[str] = frozenset(
    label for label, _ in _PHOTO_FOCUS_FULL_TABLE if label != "全身"
)
_PHOTO_POSE_TABLE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("侧躺", ("侧躺", "侧卧", "躺床上", "躺下")),
    ("平躺", ("平躺", "仰躺", "躺着")),
    ("坐", ("坐着", "坐姿", "坐床上")),
    ("倚靠", ("靠着", "倚在", "半靠", "靠着枕头")),
    ("跪坐", ("跪坐", "跪着")),
    ("站立", ("站着", "站立", "站着拍")),
    ("蹲下", ("蹲着", "蹲下")),
    ("盘腿", ("盘腿", "盘着腿")),
    ("跷腿", ("跷腿", "翘腿", "交叠双腿")),
)
_PHOTO_ANGLE_TABLE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("仰视低角度", ("仰视", "低角度", "从下往上", "低机位")),
    ("俯视高角度", ("俯视", "高角度", "从上往下", "俯拍", "高机位")),
    ("平视", ("平视", "正面平拍", "平拍")),
    ("第一人称", ("第一人称", "第一视角", "自己视角")),
    ("特写", ("特写", "近景", "怼脸", "聚焦")),
    ("全身入镜", ("全身入镜", "全身入画", "全身")),
)
_PHOTO_SCENE_TABLE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("床上", ("床上", "被窝里", "在被子里")),
    ("沙发", ("沙发", "客厅沙发")),
    ("浴室", ("浴室", "浴缸", "淋浴")),
    ("厨房", ("厨房", "灶台")),
    ("窗前", ("窗前", "窗边", "落地窗")),
    ("阳台", ("阳台", "露台")),
    ("工作室", ("工作室", "书桌", "办公桌")),
    ("玄关", ("玄关", "门口")),
)
_PHOTO_STYLE_TABLE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("诱惑感", ("诱惑", "撩人", "sexy", "勾人")),
    ("慵懒", ("慵懒", "懒散", "没精神")),
    ("清新", ("清新", "清纯", "干净")),
    ("居家感", ("居家", "生活感", "日常")),
    ("氛围感", ("氛围", "意境", "情绪")),
)

# orientation 维度（第 2 条）：生图横竖/方方向。LLM 语义自补或关键词都可产出，
# 首选中文 tag（竖/横/方）回落；命中后由 _image_orientation_size 做成 3 档尺寸。
_PHOTO_ORIENTATION_TABLE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("横", ("横", "横屏", "横构图", "横拍", "横向")),
    ("方", ("方", "方形", "方构图", "正方形")),
    ("竖", ("竖", "竖屏", "竖构图", "竖拍", "纵向")),
)
_PHOTO_ORIENTATION_SIZE: dict[str, str] = {
    "横": _IMAGE_SIZE_LANDSCAPE,
    "方": "1024x1024",
    "竖": _IMAGE_SIZE_PORTRAIT,
}


def _image_orientation_for_size(orientation: str, fallback: str = _IMAGE_SIZE_PORTRAIT) -> str:
    """把 orientation（竖/横/方）映射为具体像素尺寸档，未命中回退 fallback。"""
    size = _PHOTO_ORIENTATION_SIZE.get(str(orientation or "").strip())
    return size if size else fallback


# 景别 shot（第 2 条补充）：构图远近/镜头语言。LLM 语义自补或关键词都可产出，
# 首选中文 tag（远景/中景/近景/特写/大特写）回落；命中后由 _photo_shot_phrase 输出镜头短语。
# 特写景别使用率最高——LLM 语义按对话上下文决定，缺省时由 _photo_shot_fallback 与 focus 联动推断。
_PHOTO_SHOT_TABLE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("远景", ("远景", "全景", "全身入画", "远处拍")),
    ("中景", ("中景", "膝上入画", "大半身")),
    ("近景", ("近景", "胸以上", "手部特写入画")),
    ("特写", ("特写", "怼脸", "聚焦", "近距")),
    ("大特写", ("大特写", "细节特写", "离镜头最近")),
)
_SHOT_TO_PHRASE: dict[str, str] = {
    "远景": "机位拉远，把环境或全身收进画面",
    "中景": "中景构图，人物半身或膝上入画",
    "近景": "镜头贴近，人物占画面大部",
    "特写": "镜头贴近特写，背景虚化",
    "大特写": "镜头顶到大特写，主体充满画面",
}


def _photo_shot_phrase(shot: str) -> str:
    """把景别转成写进生图 prompt 的镜头语言短语（让生成模型配合景别）。"""
    return _SHOT_TO_PHRASE.get(str(shot or "").strip())


def _photo_shot_fallback(spec: dict[str, str]) -> dict:
    """景别缺省兜底（方向标注）：与 focus 联动——focus=特写 → 默认特写；focus=全身 → 中景。
    focus 未给 / 语义未自出时保持无景别（由基础模板自然构图），绝不返空 / 强制猜。"""
    shot = str(spec.get("shot") or "").strip()
    if shot:
        return spec
    focus = str(spec.get("focus") or "").strip()
    out = dict(spec)
    if focus and focus in _CLOSEUP_FOCUS_SET:
        out["shot"] = "特写"
    elif focus == "全身":
        out["shot"] = "中景"
    return out


# 手持自拍硬约束（POV）：所有人物类生图必须以此为前提——照片是伊塔本人手持
# 手机拍的（前置自拍 / 后置对镜 / 支架定时），绝不出现第三方拍摄者视角。
# 通过三个闸口保证：①基础 prompt 模板追加；②组合器机位措辞自拍化；

# 手持自拍硬约束（POV）：所有人物类生图必须以此为前提——照片是伊塔本人手持
# 手机拍的（前置自拍 / 后置对镜 / 支架定时），绝不出现第三方拍摄者视角。
# 通过三个闸口保证：①基础提示词模板追加；②组合器机位措辞自拍化；
# ③_ensure_selfie_pov 出口兜底。与 _PHOTO_POSE_PHRASE 等并列放在表定义区。
_SELFIE_POV_PHRASE = (
    "这张照片由她本人手持手机拍摄，画面角落可见她的手指或手机边缘，微微手持感，绝无他人拍摄。"
)

# POV 黑名单：LLM 接力（_light_relay_refine_prompt）的输出若出现任一关键词，
# 说明它引入了"第三方拍摄"视角，拒绝采用，回退确定性兜底。仅用于校验输出，
# 不含会误伤正常描述的泛词（"背后"等语义歧义词不列入）。
_POV_THIRD_PARTY_BLACKLIST: tuple[str, ...] = (
    "摄影师", "他人拍摄", "旁观", "第三人称", "路人", "拍摄者", "别人拍",
)

# 姿态标签 → 自然措辞（组合器输出"她{phrase}"，避免"她坐/她躺"这类生硬表述）。
_PHOTO_POSE_PHRASE: dict[str, str] = {
    "侧躺": "侧躺在床上",
    "平躺": "平躺着",
    "坐": "坐着",
    "倚靠": "倚靠着",
    "跪坐": "跪坐着",
    "站立": "站立着",
    "蹲下": "蹲着",
    "盘腿": "盘着腿",
    "跷腿": "跷着腿",
}

# 机位标签 → 自拍化措辞（POV 约束）：保留关键词解析（_PHOTO_ANGLE_TABLE 不变），
# 仅把"拍摄机位"的输出措辞重定义为"她本人手持手机"的自拍取景，杜绝"别人拍她"。
_PHOTO_ANGLE_PHRASE: dict[str, str] = {
    "仰视低角度": "她手持手机放低，从低处自拍取景",
    "俯视高角度": "她举高手机，从上往下俯拍自己",
    "平视": "她手持手机平视自拍",
    "第一人称": "第一人称手持自拍视角",
    "特写": "她手持手机近距离特写自拍",
    "全身入镜": "她手持手机（或自拍杆）把全身收进画面",
    # focus 协同覆盖（背影）补出的机位：后置对镜/举到身后的自拍取景，
    # 避免"从后面"被理解成"别人从她背后拍她"。
    "从后面": "她把手机举到身后，用后置摄像头拍自己的背影",
}

# focus → 构图协同覆盖规则（方向2）。focus 作为构图主轴，反向约束姿态/机位：
#   - default_pose: 用户只给了 focus（未给姿态）时自动补的默认姿态，避免落回 base 的
#     固定场景（如 role_selfie 的"坐在书桌前托腮"）而与特写主体冲突。
#   - default_angle: 用户未给机位时自动补的默认机位（如背影→从后面）。
# 注意：用户显式给了姿态/机位时一律尊重用户（user wins），绝不覆盖。
_PHOTO_FOCUS_RULES: dict[str, dict[str, str]] = {
    "双腿": {"default_pose": "坐"},
    "双脚": {"default_pose": "坐"},
    "手": {"default_pose": "坐"},
    "腰": {"default_pose": "站立"},
    "肩颈锁骨": {"default_pose": "坐"},
    "背影": {"default_pose": "站立", "default_angle": "从后面"},
    "头发": {"default_pose": "坐"},
    "脸庞": {"default_pose": "坐"},
    "眼睛": {"default_pose": "坐", "default_angle": "特写"},
    "全身": {"default_pose": "站立", "default_angle": "全身入镜"},
}

# 方案A 细分子部位 → 父部位映射：细标签在 _PHOTO_FOCUS_RULES 无默认姿态时，
# 回退继承父部位（如 大腿→双腿、脚踝→双脚）的协同默认姿态，保证"看看大腿"这类细特写
# 也能自动补出合理姿态，不落回 base 固定场景而与之冲突。
_PHOTO_FOCUS_PARENT: dict[str, str] = {
    "脚踝": "双脚",
    "足背": "双脚",
    "脚趾": "双脚",
    "小腿": "双腿",
    "大腿": "双腿",
    "膝盖": "双腿",
    "手指": "手",
    "手腕": "手",
    "掌心": "手",
    "锁骨": "肩颈锁骨",
    "脖颈": "肩颈锁骨",
    "腰肢": "腰",
    "耳廓": "脸庞",
    "嘴唇": "脸庞",
}


def _apply_focus_coverage(spec: dict[str, str]) -> dict[str, str]:
    """按 focus 协同覆盖：仅在用户未给姿态/机位时自动补齐缺省值。

    返回新 dict（不改入参）；focus 无规则或已给显式值时保持原样。
    """
    focus = str(spec.get("focus") or "").strip()
    rule = _PHOTO_FOCUS_RULES.get(focus)
    if not rule:
        # 方案A：细子部位未定义默认姿态 → 回退继承父部位规则（如 大腿→双腿、脚踝→双脚）
        parent = _PHOTO_FOCUS_PARENT.get(focus)
        rule = _PHOTO_FOCUS_RULES.get(parent) if parent else None
    if not rule:
        return dict(spec)
    out = dict(spec)
    pose = str(spec.get("pose") or "").strip()
    if not pose and rule.get("default_pose"):
        out["pose"] = rule["default_pose"]
    angle = str(spec.get("angle") or "").strip()
    if not angle and rule.get("default_angle"):
        out["angle"] = rule["default_angle"]
    return out


def _match_photo_spec(text: str, table: tuple[tuple[str, tuple[str, ...]], ...]) -> str:
    """在用户指令里按优先级返回第一个命中的维度标签；无命中返回空串。"""
    haystack = str(text or "")
    if not haystack:
        return ""
    for label, keywords in table:
        if any(kw in haystack for kw in keywords):
            return label
    return ""


def _extract_photo_spec(user_raw: str) -> dict[str, str]:
    """从用户原始指令提取模块化生图规格：focus/pose/angle/scene/style。

    每个维度最多命中一个（按表顺序取第一个），未命中的为空串。确定性、零成本、
    可测，无需调用 LLM；仅用于"用户主动要图"路径的增强，缺值全部由组合器兜底。
    这是关键词保底：语义自补（_semantic_photo_spec）优先，失败时才回落到这里。
    """
    return {
        "focus": (
            _match_photo_spec(user_raw, _PHOTO_FOCUS_DETAIL_TABLE)
            or _match_photo_spec(user_raw, _PHOTO_FOCUS_TABLE)
        ),
        "pose": _match_photo_spec(user_raw, _PHOTO_POSE_TABLE),
        "angle": _match_photo_spec(user_raw, _PHOTO_ANGLE_TABLE),
        "scene": _match_photo_spec(user_raw, _PHOTO_SCENE_TABLE),
        "style": _match_photo_spec(user_raw, _PHOTO_STYLE_TABLE),
        "orientation": _match_photo_spec(user_raw, _PHOTO_ORIENTATION_TABLE),
        "shot": _match_photo_spec(user_raw, _PHOTO_SHOT_TABLE),
    }


def _normalize_spec_value(raw: str, table: tuple[tuple[str, tuple[str, ...]], ...]) -> str:
    """把 LLM 返回的自由文本归一化到已知标签：完全一致或关键词命中返回标签，否则空串。

    语义自补的输出必须落回合法标签，未知标签会污染提示词；归一化失败返回空串，
    交给组合器兜底（缺值即停防护），绝不让脏值进生图。
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    for label, keywords in table:
        if text == label or text in keywords:
            return label
    return _match_photo_spec(text, table)


def _extract_llm_json(text: str) -> dict | None:
    """从 LLM 输出稳健提取 JSON 对象（容忍 markdown 代码围栏与前后杂文）。

    找不到平衡的花括号或解析失败返回 None，由调用方决定兜底。
    """
    s = str(text or "").strip()
    if not s:
        return None
    if s.startswith("```"):
        s = s.strip("`").strip()
        if "\n" in s:
            s = s.split("\n", 1)[1]
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        obj = json.loads(s[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _compose_modular_prompt(base: str, spec: dict[str, str]) -> str:
    """把模块化规格组合进基础提示词：focus 为主轴协同覆盖 scene/pose/angle。

    覆盖规则（_PHOTO_FOCUS_RULES）：用户只给 focus（未给姿态/机位）时，自动补一个
    与 focus 相适配的默认姿态/机位，避免落回 base 的固定场景（如"坐在书桌前托腮"）
    而与特写主体冲突；用户显式给了姿态/机位时一律尊重（user wins），绝不覆盖。
    顺序：主体特写(focus) → 场景(scene) → 姿态(pose) → 机位(angle) → 风格(style)。
    全部缺省时原样返回 base，绝不返回空串。
    """
    spec = _apply_focus_coverage(spec)
    spec = _photo_shot_fallback(spec)
    parts: list[str] = []
    focus = str(spec.get("focus") or "").strip()
    if focus:
        parts.append(f"画面重点聚焦在{focus}，其余虚化")
    shot = str(spec.get("shot") or "").strip()
    shot_phrase = _photo_shot_phrase(shot) if shot else ""
    if shot_phrase:
        parts.append(shot_phrase)
    scene = str(spec.get("scene") or "").strip()
    if scene:
        parts.append(f"场景是{scene}")
    pose = str(spec.get("pose") or "").strip()
    if pose:
        parts.append(f"她{_PHOTO_POSE_PHRASE.get(pose, pose)}")
    angle = str(spec.get("angle") or "").strip()
    if angle:
        # POV 约束：机位一律自拍化措辞，禁止"别人从某角度拍她"的第三方解读。
        parts.append(f"拍摄机位：{_PHOTO_ANGLE_PHRASE.get(angle, angle)}")
    style = str(spec.get("style") or "").strip()
    if style:
        parts.append(f"整体氛围{style}")
    if not parts:
        return base
    return f"{base}{'，'.join(parts)}。"


# 游玩/出行例外（构图护栏）：提示词里出现这些词时，允许"同行的朋友/路人帮忙拍"的
# 第三人叙事——用于游乐园/公园/景区合影等特殊场景。由 _ensure_selfie_pov 判定后放开
# 手持自拍约束（但也绝不出现"其他陌生人拍"之外歧义），避免所有图都死守自拍视角。
_EXTRA_SHOT_FRIENDLY_KEYWORDS: tuple[str, ...] = (
    "游乐园", "游乐场", "公园", "景区", "景点", "人带队", "出差", "展厅", "看展",
    "旅行", "旅游", "露营", "爬山", "海边", "沙滩", "度假", "合影", "你帮我拍",
    "帮我拍", "合照", "一块儿", "一起玩",
)


def _is_friendly_shot_exception(prompt: str) -> bool:
    """判定这段提示词是否属于"出游/合影"例外——允许第三方帮忙拍摄，不必死守手持自拍。"""
    text = str(prompt or "")
    return any(kw in text for kw in _EXTRA_SHOT_FRIENDLY_KEYWORDS)


def _ensure_selfie_pov(prompt: str, prompt_key: str) -> str:
    """POV 出口兜底：人物类提示词若缺手持自拍前提，自动追加 _SELFIE_POV_PHRASE。

    幂等：已含手持类关键词（手持手机/自拍/前置摄像头/手机边缘）时不重复追加，
    避免多次接力后约束叠加成噪音。environment_object（环境照）不强制带人物，
    第一人称视角由模板天然保证，跳过追加。
    例外：出游/合影场景（见 _is_friendly_shot_exception）允许他人帮忙拍，
    改用游玩同伴视角，而不追加"手持自拍"前提，避免把合影误渲染成她一个人自拍。
    """
    text = str(prompt or "")
    key = str(prompt_key or "default")
    if key == "environment_object":
        return text
    if any(kw in text for kw in ("手持手机", "自拍", "前置摄像头", "手机边缘")):
        return text
    if _is_friendly_shot_exception(text):
        # 出游/合影：以同行者视角拍下，而非手持自拍。加一句互补，避免 POV 冲突。
        if any(kw in text for kw in ("合影", "一起", "游", "公园", "景区")):
            return f"{text}这张是出游时同行的人用她的手机替她按下快门的一张出行合影。"
        return text
    return f"{text}{_SELFIE_POV_PHRASE}"


# ── 生图上下文：世界数据按场景选择性进画面 ──────────────────────
# 时间光线决定室内/窗外的氛围光，天气决定窗外/城市画面里能看见的元素。
# 提示词接力时只把真正能呈现在画面里的数据注入，不把世界快照全部堆叠。
_IMAGE_LIGHT_PROVIDER = "siliconflow-light"
_IMAGE_LIGHT_RELAY_TIMEOUT = 8.0
# 主动发图同主题去重窗口：即使后端重启清空进程内存，同一视觉主题在此窗口内
# 也不会被重复发布（读持久化审计存储判断），避免"每次重启生成一张一模一样的图"。
# 4h：覆盖开发期跨重启间隔；视觉主题随时间相变化（morning/afternoon/evening...），
# 同一天内不会在窗口内重复出现，故较长窗口不会误伤正常的新场景。
_IMAGE_TOPIC_DEDUP_SEC = 14400

# 主动消息配图延迟：文本先到用户端后，图片延迟此秒数再投递，让消息时序更自然。
# 测试时可 patch 为 0 跳过等待。
_COMPANION_IMAGE_DELAY_SEC = 2.0

from core.world_phase import (  # P1 单一真源：phase → 中文/光线
    TIME_OF_DAY_CN as _TIME_OF_DAY_CN,
    TIME_OF_DAY_LIGHT_CN as _TIME_OF_DAY_LIGHT_CN,
)

_WEATHER_MOOD_CN: dict[str, str] = {
    "clear": "晴朗",
    "sunny": "晴朗",
    "partly_cloudy": "多云",
    "cloudy": "阴天",
    "overcast": "阴天",
    "rain": "下雨",
    "drizzle": "细雨",
    "shower": "阵雨",
    "thunderstorm": "雷雨",
    "snow": "下雪",
    "windy": "有风",
    "fog": "有雾",
    "haze": "有霾",
    "neutral": "",
}

# 生图场景 → 世界数据相关性（确定性兜底，与轻量 LLM 接力同语义）：
# 天气/光线只在真正影响画面的场景注入，室内自拍不塞天气。
_IMAGE_WORLD_FALLBACK_RULES: dict[str, set[str]] = {
    "environment_object": {"weather", "light"},
    "role_in_scene": {"light", "weather", "room"},
    "role_selfie": {"light", "room"},
    "couple_photo": {"light", "room"},
}


def _time_of_day_phase(dt: datetime) -> str:
    """把本地时刻映射到时段（world_phase 单一真源，加档位只改一处）。"""
    from core.world_phase import phase_for_hour

    return phase_for_hour(dt.hour)


def _resolve_companion_data_path(settings: dict | None) -> Path:
    if (os.environ.get("AERIE_DATA_DIR") or "").strip():
        return data_dir()
    paths_cfg = settings.get("paths", {}) if isinstance(settings, dict) else {}
    if isinstance(paths_cfg, dict) and paths_cfg.get("data"):
        return Path(str(paths_cfg["data"]))
    return data_dir()


def get_companion():
    return _COMPANION


class Companion:
    def __init__(
        self,
        settings: dict | None = None,
        *,
        database: Any = None,
        runtime_config_service: Any = None,
    ) -> None:
        global _COMPANION
        self.settings = settings or load_settings()
        self.runtime_config_service = runtime_config_service
        self.feature_flags = FeatureFlags(
            runtime_config_service=runtime_config_service,
        )
        self.primary_identity_resolver = PrimaryIdentityResolver(
            runtime_config_service=runtime_config_service,
        )

        # R0.3.7: load centralized behavior config (single source of truth).
        self.behavior_cfg = load_behavior_config()
        # 世界配置 = 行为默认 + settings.yaml world 覆盖（用户可在设置页调位置/节奏）。
        self.world_config = dict(self.behavior_cfg.get("world_simulation", {}) or {})
        _settings_world = (self.settings or {}).get("world", {}) or {}
        if isinstance(_settings_world, dict):
            self.world_config.update({k: v for k, v in _settings_world.items() if v is not None})
        # 白天出门（最小版）：从 settings.proactive 注入室外概率（0=关闭）。
        try:
            self.world_config["outdoor_probability"] = float(
                ((self.settings or {}).get("proactive", {}) or {}).get("outdoor_probability", 0.0) or 0.0
            )
        except (TypeError, ValueError):
            self.world_config["outdoor_probability"] = 0.0
        # 人设驱动出门：大五人格 E(外向)+O(开放) → 出门冲动因子（1.0 中性，越大越想往外跑）。
        # 理论映射：E/O 高于 0.5 基线即放大出门概率；低外向则压低。
        self.world_config["outdoor_personality_factor"] = self._personality_outdoor_factor()
        # 特殊事件加权开关（settings.proactive，默认开）。
        try:
            pfx = ((self.settings or {}).get("proactive", {}) or {})
            self.world_config["outdoor_weather_event"] = bool(
                pfx.get("outdoor_weather_event", True)
            )
            self.world_config["outdoor_holiday_event"] = bool(
                pfx.get("outdoor_holiday_event", True)
            )
        except Exception:
            self.world_config["outdoor_weather_event"] = True
            self.world_config["outdoor_holiday_event"] = True
        self.world_port = build_world_port(
            feature_flags=self.feature_flags,
            world_config=self.world_config,
            relationship_config=self.behavior_cfg.get("relationship", {}),
        )

        # Data layer
        self.db = database or Database()
        self.identity_repository = IdentityRepository(self.db)
        self.identity_resolver = IdentityResolver.from_feature_flags(
            self.identity_repository,
            self.feature_flags,
        )
        self.conversation_repository = ConversationRepository(
            self.db,
            enabled=self.feature_flags.is_enabled("conversation_model_v1"),
        )
        self.conversation_summary_repository = ConversationSummaryRepository(
            self.db,
        )
        self.summary_refresh_planner = SummaryRefreshPlanner(
            self.conversation_summary_repository,
        )
        # P3-1（附录 A.3.1）：跨端时间线事件索引，随摘要刷新幂等写入
        self.persona_timeline_repository = PersonaTimelineRepository(self.db)
        self.context_assembler = ContextAssembler(
            self.conversation_repository,
            self.conversation_summary_repository,
            max_total_chars=24_000,
            recent_turn_limit=8,
            max_turn_chars=6_000,
            max_summary_buckets=3,
        )

        self.data_path = _resolve_companion_data_path(self.settings)
        attachment_root = Path(
            os.environ.get(
                "AERIE_DESKTOP_ATTACHMENT_ROOT",
                str(self.data_path / "desktop_attachments"),
            )
        )
        try:
            self.desktop_attachment_service = DesktopAttachmentService(
                self.db,
                storage_root=attachment_root,
            )
        except Exception:
            logger.exception("desktop attachment service initialization failed")
            self.desktop_attachment_service = None

        # ── Core engines (single instantiation — no duplicates) ──
        # Phase 9 Batch 1: emotion state store persists PAD + threshold
        # snapshots for 24h/7d/30d history curves on the dashboard.
        # OWNER: companion.py — always pass this instance to downstream modules.
        self.state_store = EmotionStateStore(self.db)        # R7.0: build the brain first so EmotionEngine can call back into
        # it for LLM-driven PAD inference. The keyword path is still
        # always available as a fallback when the LLM call fails.
        # OWNER: companion.py — always pass this instance to downstream modules.
        self.brain = LLMCaller()
        # R0.3.7: pass behavior_cfg so EmotionEngine reads PAD centers
        # and threshold slots from config/persona_behavior.yaml.
        self.emotion = EmotionEngine(
            self.db,
            state_store=self.state_store,
            behavior_cfg=self.behavior_cfg,
            brain=self.brain,
        )
        self._emotion_last_sampled_at = int(time.time() * 1000)
        # P1-D.5.3: 生产记忆切换到四层 LayeredMemory，并注入 embedding_fn（优先
        # ChromaDB 本地 ONNX 离线 embedding），实现向量语义检索。
        # 用同步适配器桥接旧 LongTermMemory 接口，context_builder/pipeline 无需改动。
        self._layered_memory = LayeredMemory(
            db=self.db,
            chroma_persist_dir=os.getenv("AERIE_CHROMA_DIR") or str(data_dir() / "chroma"),
            embedding_fn=resolve_embedding_fn(),
        )
        self.memory = LayeredMemorySyncAdapter(self._layered_memory)
        self.knowledge = KnowledgeBase(self.db)

        # Phase 9 Batch 7 (B7.2): single cognition engine instance,
        # shared by the pipeline (writes traces) and SendQueue (writes
        # pacing_decisions back to those traces). This guarantees the
        # local-path write and the QQ-path write target the same row.
        self.cognition = CognitionEngine(self.db)

        # Cumulative threshold engine — driven by the same behavior_cfg
        # so the engine picks up persona_behavior.yaml thresholds on
        # first call (R0.3.7).
        self.threshold_engine = get_threshold_engine(self.behavior_cfg)

        # R6.6: warm-up the threshold engine from the latest non-zero
        # snapshot so the dashboard never shows a "0 → initial_value"
        # jump after a restart. Without this, the user sees the bar
        # flicker from 0 to 60 (initial_value) every time the backend
        # boots, which looks like the engine "just turned on" and not
        # like a real emotion continuation.
        self._warmup_threshold_from_history()

        # Phase 15 Batch 3 (B3.1): deterministic internal-state model
        # (needs / fatigue / neurochemical-like computed metrics). Read by
        # the dashboard's 内在状态 page; never a medical measurement.
        self.internal_state = InternalStateEngine()

        # Tool registry
        # v13.9: 全局共享的 ComputerController 单例，确保权限设置全局生效
        self.computer_controller = ComputerController()
        # v13.9: 细粒度权限管理器（目录授权 + 操作分类 + 高危确认）
        self.permission_manager = FineGrainedPermissionManager()
        self.tool_registry = ToolRegistry(self.db)
        # ⚠️ 重要：必须在 register_all_tools 之前设置 _COMPANION，
        # 否则 compute_tools 等通过 get_companion() 获取依赖的工具会注册失败
        _COMPANION = self
        register_all_tools(self.tool_registry)
        # v13.9: 任务规划引擎 + 执行引擎 + 异步任务
        from core.task_planner import TaskPlanner
        from core.task_executor import TaskExecutor
        from core.async_task_manager import AsyncTaskManager
        self.task_planner = TaskPlanner()
        self.task_executor = TaskExecutor(tool_registry=self.tool_registry)
        self.async_task_manager = AsyncTaskManager(max_concurrent=3)
        self._register_async_task_handlers()

        # Phase 9 Batch 6: Self-evolution engine (capability-gap detector)
        # L4 内测链路：代码自修改（proposer 生成 file_changes → 四道闸门）。
        # 默认关闭，仅当 settings.yaml feature_flags.self_evolve_l4_enabled=true 时激活。
        self.l4_evolution = L4SelfEvolution(auto_apply=True)
        self.evolve_proposer = SelfEvolveProposer()
        self.self_evolver = SelfEvolver(
            db=self.db,
            tool_registry=self.tool_registry,
            brain=self.brain,
            enabled=self.feature_flags.is_enabled("self_evolve_l4_enabled"),
            proposer=self.evolve_proposer,
            l4=self.l4_evolution,
        )

        # Communication
        qq_cfg = dict(self.settings.get("qq", {}) if isinstance(self.settings, dict) else {})
        # token 与 QQ 引擎网关共用（网关注入引擎配置、客户端连接鉴权同源）
        from core.qq_gateway import get_gateway_token

        qq_cfg.setdefault("token", get_gateway_token(self.settings))
        primary_selection = self.get_primary_user_selection()
        self.qq = QQClient(qq_cfg)
        # v13.9: QQ whitelist manager
        self.qq_whitelist = QQWhitelistManager(self.db)
        self.qq.set_whitelist(self.qq_whitelist)
        self.router = Router(
            self_qq=primary_selection.user_id if primary_selection else -1,
            friends_qq=qq_cfg.get("friends_qq", []),
        )
        self.splitter = SemanticMessageSplitter()

        # Phase 4: Recall manager hooks into SendQueue
        self.recall_manager = RecallManager(qq_client=self.qq)
        self.queue = SendQueue(
            sender=self._send_to_qq,
            splitter=self.splitter,
            recall_manager=self.recall_manager,
            db=self.db,
            qq_with_segments=self._send_qq_with_reply,
            # Phase 9 Batch 7 (B7.2): pass the same cognition engine
            # the pipeline uses, so the worker can append its observed
            # pacing_decisions back to the originating trace.
            cognition=self.cognition,
            on_reply_sent=self._on_qq_reply_sent,
        )

        # Pipeline
        self.pipeline = Pipeline(
            router=self.router,
            emotion_engine=self.emotion,
            context_builder=ContextBuilder(self.memory, self.knowledge),
            brain=self.brain,
            send_queue=self.queue,
            tool_registry=self.tool_registry,
            db=self.db,
            self_evolver=self.self_evolver,
            cognition=self.cognition,
            decision_engine=MultiLayerDecision(),
            settings=self.settings,
            identity_resolver=self.identity_resolver,
            conversation_repository=self.conversation_repository,
            context_assembler=self.context_assembler,
            summary_planner=self.summary_refresh_planner,
            timeline_repository=self.persona_timeline_repository,
            attachment_service=self.desktop_attachment_service,
            memory_store=self.memory,
        )
        self.pipeline.world_snapshot_provider = self._world_snapshot_for_context
        self.pipeline.relationship_snapshot_provider = self._relationship_snapshot_for_context
        self.pipeline.self_model_snapshot_provider = self._self_model_snapshot_for_context
        self.pipeline.internal_snapshot_provider = self._internal_snapshot_for_context
        # Quote V2: let pipeline pull quoted message content from QQ when the
        # quoted message was never persisted in chat_log (get_msg fallback).
        fetcher = getattr(self.qq, "get_msg", None)
        if callable(fetcher):
            self.pipeline.qq_get_msg = fetcher
        # 对话移动意图：用户"去X"指令 → MovementManager.move_to()，让她的身体真的移动。
        self.pipeline.movement_intent_provider = self.apply_movement_intent
        # P0 topic system: 给上下文构建器注入话题提供器（L0.5 话题认知层）。
        # tracker 在 __init__ 后段才创建，provider 用 getattr 惰性读取。
        try:
            self.pipeline.ctx_builder.set_topic_provider(self._topic_for_context)
        except Exception:
            logger.debug("topic provider bind failed", exc_info=True)
        self.chat_request_queue_requested = self.feature_flags.is_enabled(
            "chat_request_queue_v1",
        )
        chat_request_deps_ready = (
            self.feature_flags.is_enabled("migration_framework_v1")
            and self.feature_flags.is_enabled("conversation_model_v1")
        )
        self.chat_request_queue_ready = False
        self.chat_request_queue_error: str | None = None
        self.chat_request_repository: Any = None
        self.chat_request_service: Any = None
        self.chat_request_worker: Any = None
        if self.chat_request_queue_requested:
            if not chat_request_deps_ready:
                self.chat_request_queue_error = "queue_dependencies_unavailable"
            else:
                self.chat_request_repository = ChatRequestRepository(self.db)
                self.chat_request_service = ChatRequestService(
                    repository=self.chat_request_repository,
                    identity_repository=self.identity_repository,
                    attachment_service=self.desktop_attachment_service,
                )
                self.chat_request_worker = ChatRequestWorker(
                    repository=self.chat_request_repository,
                    pipeline=self.pipeline,
                    emit=emit,
                    clock=lambda: datetime.now(timezone.utc),
                )
                self.chat_request_service.set_worker(self.chat_request_worker)
                self.chat_request_queue_ready = True

        # Message batcher (Task 7: batch request processing)
        self.message_batcher: MessageBatcher | None = None
        try:
            self.message_batcher = MessageBatcher()
            self.message_batcher.register_callback(self._on_message_batch_ready)
            logger.info("MessageBatcher initialized and callback registered")
        except Exception:
            logger.exception("MessageBatcher init failed; batching disabled")
            self.message_batcher = None

        # Gate 5: 撤回判断联动 (RecallJudge)
        self.recall_judge: RecallJudge | None = None
        try:
            self.recall_judge = RecallJudge(
                self.recall_manager,
                window_seconds=self.recall_manager.config.window_seconds,
            )
        except Exception:
            logger.exception("RecallJudge init failed; recall judge disabled")
            self.recall_judge = None

        # Gate 4: 批次完成 → 通知 batcher 刷新该 conversation 的缓冲
        if self.chat_request_worker is not None:
            self.chat_request_worker.batch_completed_hook = self._on_batch_completed

        # Push scheduler
        proactive_cfg = load_proactive_config()
        self.push_scheduler = PushScheduler(proactive_cfg)
        # UI overlay: settings.yaml proactive.max_per_day / min_interval_min
        # override the proactive.yaml defaults (consistent with image budget).
        self._apply_proactive_overlay()
        self.push_scheduler.set_dispatcher(self._dispatch_push)
        # v2: 整点滚动调度（PulsePlanner）+ 作息学习（RoutineLearner）。
        # 失败时静默降级为 cron-only，不影响既有链路。
        try:
            from core.paths import data_dir
            from core.proactive_planner import PulsePlanner
            from core.routine_learner import RoutineLearner

            learner = RoutineLearner(
                self.db,
                state_path=data_dir() / "routine_profile.json",
            )
            learner.load_state()
            self.routine_learner = learner
            self.pulse_planner = PulsePlanner()
            self.push_scheduler.set_pulse_planner(
                self.pulse_planner, self._pulse_state_snapshot
            )
            self.push_scheduler.set_routine_learner(learner)
            logger.info("[Push] PulsePlanner & RoutineLearner bound (v2)")
        except Exception:
            logger.exception("proactive v2 scheduler bind failed; cron-only mode")
        self.push_event_engine = get_event_engine()
        self.push_event_engine.bind_scheduler(self.push_scheduler)
        # P0 topic system: EventBus 路径（_on_user_message）也走统一沉寂时钟。
        self.push_event_engine.on_user_active = self._mark_user_active
        # R7.5+: bind a ProactiveJudge so every dispatch consults
        # 心情 / 想法 / 用户上下文 before sending.
        try:
            from core.proactive_judge import ProactiveJudge
            self.proactive_judge = ProactiveJudge(companion=self)
            self.push_scheduler.judge = self.proactive_judge
        except Exception:
            logger.exception("ProactiveJudge init failed; push will run judge-less")
            self.proactive_judge = None

        # Phase 14: lazy one-shot consumer for world ImageCandidate events.
        # It is not started as a background loop here; callers explicitly
        # invoke process_world_image_candidates_once() so the old chat/push
        # paths stay unchanged while the contract hardens behind a flag.
        self.world_image_candidate_consumer: Any = None
        # 最近一次生图提示词（供大脑中枢 trace / tool_call 可见）。
        self._last_image_prompt: str = ""

        self._started = False
        self._daily_decay_task: asyncio.Task | None = None
        self._push_task: asyncio.Task | None = None
        self._boot_brief_task: asyncio.Task | None = None
        # R7.5: 10s background tick for emotion dashboard liveness.
        self._emotion_tick_task: asyncio.Task | None = None
        # Phase 14: proactive photo cadence loop (publishes ImageCandidates).
        self._photo_loop_task: asyncio.Task | None = None
        # Block-4B R2.2: 24h desire engine (lazy-created on first start()).
        self.desire: Any = None
        # Block-4C R3.4: skill loader (lazy-created on first start()).
        self.skill_loader: Any = None
        # P0 topic system: 话题生命周期追踪 + 候选决策证据日志。
        try:
            from core.topic_tracker import TopicTracker

            self.topic_tracker = TopicTracker()
        except Exception:
            logger.exception("TopicTracker init failed")
            self.topic_tracker = None
        try:
            from core.decision_log import DecisionLogger

            self.decision_log = DecisionLogger()
        except Exception:
            logger.exception("DecisionLogger init failed")
            self.decision_log = None
        # P0 topic system: 统一沉寂时钟宿主（companion_state 单例 + 节流落盘）。
        try:
            from core.companion_state import CompanionState

            self.companion_state = CompanionState.load()
        except Exception:
            logger.debug("CompanionState init failed", exc_info=True)
            self.companion_state = None
        self._last_activity_save = 0.0
        # P1/P2: 每日规划消费 + 移动状态机（决策日志证据层共用）。
        try:
            from core.daily_planner import DailyPlanner

            prefs = dict(
                ((self.world_config or {}).get("daily_routine_prefs") or {})
            )
            self.daily_planner = DailyPlanner(
                decision_log=self.decision_log,
                prefs=prefs or None,
            )
        except Exception:
            logger.debug("DailyPlanner init failed", exc_info=True)
            self.daily_planner = None
        try:
            from core.movement import MovementManager

            self.movement_manager = MovementManager(decision_log=self.decision_log)
        except Exception:
            logger.debug("MovementManager init failed", exc_info=True)
            self.movement_manager = None
        _COMPANION = self

    def _apply_proactive_overlay(self) -> None:
        """Apply settings.yaml proactive.max_per_day / min_interval_min on top
        of proactive.yaml defaults.

        Called at boot (right after PushScheduler init) and re-invoked after
        any hot reload of proactive.yaml so the running PushPolicy never loses
        the user's settings-page choice.
        """
        try:
            _pol = self.push_scheduler.policy
            _pset = (self.settings or {}).get("proactive", {})
            if isinstance(_pset, dict):
                explicit_hard = _pset.get("hard_cap") is not None
                if _pset.get("max_per_day") is not None:
                    _pol.max_per_day = int(_pset["max_per_day"])
                    if not explicit_hard:
                        _pol.hard_cap = max(int(_pol.max_per_day * 1.5), 20)
                if _pset.get("min_interval_min") is not None:
                    _pol.min_interval_min = int(_pset["min_interval_min"])
                # v2: soft budget / hard-cap fuse hot-update
                if _pset.get("soft_budget") is not None:
                    _pol.soft_budget = float(_pset["soft_budget"])
                if explicit_hard:
                    cap = int(_pset["hard_cap"])
                    _pol.hard_cap = cap if cap > 0 else max(int(_pol.max_per_day * 1.5), 20)
        except Exception:
            logger.debug("apply proactive frequency overlay failed", exc_info=True)

    async def start(self) -> None:
        if self._started:
            return
        from core.startup_progress import mark_step

        self.queue.start()
        mark_step("queue", "done", "消息发送队列")
        if self.chat_request_worker is not None:
            try:
                await self.chat_request_worker.start()
            except Exception:
                self.chat_request_queue_ready = False
                self.chat_request_queue_error = "queue_worker_start_failed"
                logger.exception("chat request worker start failed")
        self.qq.set_message_handler(self._on_qq_message)
        # 断连探测：把 QQ 心跳存活日志接到状态页「运行日志」黑框（QQ 引擎网关日志缓冲）
        try:
            from core.qq_gateway import get_gateway
            self.qq.set_heartbeat_log(
                lambda text: get_gateway().add_log(f"[QQ] {text}")
            )
            logger.info("QQ heartbeat log sink wired to status-page running-log box")
        except Exception:
            logger.exception("QQ heartbeat log sink wiring failed")
        await self._start_push_event_engine()

        # Workstream 7: idempotently seed `dialogue` knowledge (发起腔 principles).
        try:
            from tools.seed_social_knowledge import seed_dialogue
            seed_dialogue(self.knowledge)
        except Exception:
            logger.exception("dialogue knowledge seed failed; continuing")

        # ── Phase 1: 基础设施启动 ──

        # R9.0+: subscribe to QQ state changes BEFORE connecting
        self._boot_greeting_fired = False
        self.qq.on_state_change(self._on_qq_state_change)

        # Start QQ connection in background (it will poll for port open)
        asyncio.create_task(self.qq.connect())
        mark_step("qq", "running", "连接 QQ 引擎")

        # Start daily emotion decay scheduler
        self._daily_decay_task = asyncio.create_task(self._run_daily_decay())

        # R7.5: 10s background tick for emotion dashboard liveness.
        # Every 6th tick (≈60s) writes a snapshot so the history curve
        # stays alive even when no user messages arrive.
        self._emotion_tick_task = asyncio.create_task(self._emotion_tick_loop())

        # 世界真实时间推进 + 真实数据刷新（inprocess 模式下主动 tick）。
        # 由看门狗包裹：任务异常结束后自动重建，避免静默停摆。
        self._world_loop_task = asyncio.create_task(self._supervise_world_loop())

        # Phase 14: 主动发图节奏循环（世界模拟不产图片候选，由 Core 侧补发布源）。
        self._photo_loop_task = asyncio.create_task(self._run_proactive_photo_loop())

        # Provider 余额/健康周期探测：欠费账户自动踢出轮询，恢复后自动回归。
        self._provider_health_task = asyncio.create_task(self._run_provider_health_loop())

        # 身份锚定记忆播种：把 persona 的核心事实写入长期记忆向量层（幂等）。
        await self._seed_identity_memories()

        # Block-4B R2.2: start 24h desire engine (24h polling, not cron)
        try:
            from core.desire_engine import DesireEngine
            self.desire = DesireEngine(self, self.behavior_cfg)
            await self.desire.start()
        except Exception:
            logger.exception("desire engine start failed; continuing without it")
            self.desire = None

        # Block-4C R3.4: discover + register all 17 skills (local + data).
        try:
            from core.skill_loader import SkillLoader
            from core.skill_router import SkillRouter
            self.skill_router = SkillRouter(self.behavior_cfg)
            self.skill_loader = SkillLoader(self.tool_registry, self.skill_router)
            n_disc = self.skill_loader.discover()
            n_reg = self.skill_loader.register_all()
            logger.info("skills: %d discovered, %d registered", n_disc, n_reg)
        except Exception:
            logger.exception("skill loader init failed; continuing without skills")
            self.skill_loader = None

        # Start async task manager for background document generation etc.
        self.async_task_manager.start()
        logger.info("Async task manager started")

        # ── Phase 1b: 等待 QQ 就绪（有超时，不阻塞其他服务） ──
        qq_cfg = self.settings.get("qq", {}) if isinstance(self.settings, dict) else {}
        wait_timeout = float(qq_cfg.get("startup_wait_timeout", 30.0))
        push_pause_when_offline = bool(qq_cfg.get("push_pause_when_offline", True))
        if self.feature_flags.is_enabled("proactive_delivery_v2"):
            push_pause_when_offline = False

        logger.info("[Startup] Waiting for QQ readiness (timeout=%ss)", wait_timeout)
        qq_ready = await self.qq.wait_until_ready(timeout=wait_timeout)

        if qq_ready:
            mark_step("qq", "done", "QQ 引擎已就绪")
            logger.info("[Startup] QQ ready, proceeding with full startup")
            # ── Phase 2: 通信层就绪（QQ 已就绪） ──
            # (SendQueue / Router / Pipeline 已经在 __init__ 中初始化好，
            #  这里不需要额外动作）

            # ── Phase 3: 业务层启动 ──
            # Start push scheduler
            self._push_task = asyncio.create_task(self.push_scheduler.start())
            if self.qq.connectivity_test:
                self.push_scheduler.pause("qq_connectivity_test")
                logger.info("[Startup] QQ connectivity test mode; delivery is disabled")
            else:
                # Block-4A R1.5: run brief once + emit show event
                # (8s delay is inside _boot_brief itself)
                self._boot_brief_task = asyncio.create_task(self._boot_brief())

                # boot_greeting: trigger immediately (QQ is already ready)
                # Guard on _boot_greeting_fired so the state-change callback
                # (which may have fired first during connect) and this path
                # can't both launch a greeting task → would send twice.
                if not self._boot_greeting_fired:
                    self._boot_greeting_fired = True
                    asyncio.create_task(self._boot_qq_greeting())
        else:
            mark_step("qq", "error", "QQ 引擎未就绪(降级模式)")
            logger.warning(
                "[Startup] QQ not ready after %ss; starting in degraded mode "
                "(push scheduler paused)",
                wait_timeout,
            )
            # Start push scheduler but pause it immediately
            self._push_task = asyncio.create_task(self.push_scheduler.start())
            if push_pause_when_offline:
                self.push_scheduler.pause("qq_offline")

            # boot_brief_task = asyncio.create_task(self._boot_brief())

        self._started = True
        logger.info("Companion started (qq_ready=%s)", qq_ready)

    def _on_qq_state_change(self, new_state: str) -> None:
        """R9.0+: handle QQ state transitions at runtime.

        - When QQ goes offline → pause push scheduler
        - When QQ comes back online → resume push scheduler
        - First time QQ logs in → fire boot_greeting
        """
        from communication.qq_client import STATE_LOGGED_IN, STATE_DISCONNECTED

        qq_client = getattr(self, "qq", None)
        if qq_client is not None and getattr(qq_client, "connectivity_test", False):
            logger.info("[QQ State] connectivity test transition: %s", new_state)
            return

        if new_state == STATE_LOGGED_IN:
            # Resume push scheduler if it was paused due to QQ
            if self.push_scheduler.is_paused and self.push_scheduler.paused_reason == "qq_offline":
                self.push_scheduler.resume()
                logger.info("[QQ State] QQ back online; push scheduler resumed")

            # Fire boot greeting on FIRST login only
            # (if start() already fired it synchronously when QQ was ready
            #  at startup; this path covers the "QQ-started-later case)
            if not self._boot_greeting_fired:
                self._boot_greeting_fired = True
                asyncio.create_task(self._boot_qq_greeting())

        elif new_state == STATE_DISCONNECTED:
            if self.feature_flags.is_enabled("proactive_delivery_v2"):
                logger.info(
                    "[QQ State] QQ offline; local proactive delivery remains active"
                )
                return
            qq_cfg = self.settings.get("qq", {}) if isinstance(self.settings, dict) else {}
            if bool(qq_cfg.get("push_pause_when_offline", True)):
                if self.push_scheduler.is_paused:
                    return
                self.push_scheduler.pause("qq_offline")
                logger.info("[QQ State] QQ offline; push scheduler paused")

    async def process_world_image_candidates_once(
        self,
        *,
        last_seq: int | None = None,
    ) -> list[dict[str, Any]]:
        """Consume replayed world ImageCandidate events once.

        Phase 14 keeps this explicit and pull-based: no new background loop,
        no renderer direct sidecar access, and no change to legacy image or
        proactive paths when ``world_image_candidates_v1`` is off.
        """

        consumer = self._get_world_image_candidate_consumer()
        return await consumer.consume_replay(last_seq=last_seq)

    async def publish_image_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Publish an AI image decision and consume it so it reaches local chat.

        This is the publisher behind "AI-generated images auto-inject into the
        local chat bubble": it appends a redacted ImageCandidate to the world
        outbox, then immediately consumes it.  The Phase 14 consumer runs the
        image workflow and, for ``local_chat``, emits an assistant bubble with
        the generated image.  If the world is disabled or the publisher is
        unavailable the call fails closed (no image, no side effect).
        """
        world_port = getattr(self, "world_port", None)
        publish = getattr(world_port, "publish_image_candidate", None)
        if not callable(publish):
            return {
                "status": "disabled",
                "reason": "world_publisher_unavailable",
                "candidate_id": str((candidate or {}).get("candidate_id") or ""),
                "acked": False,
            }

        payload = dict(candidate or {})
        try:
            result = publish(payload)
            if hasattr(result, "__await__"):
                result = await result
        except Exception:
            logger.warning("world image candidate publish failed", exc_info=True)
            return {
                "status": "failed",
                "reason": "publish_failed",
                "candidate_id": str(payload.get("candidate_id") or ""),
                "acked": False,
            }

        result = result if isinstance(result, dict) else {}
        # 兼容两种 world_port 的发布返回约定：
        # - 进程内 InProcess：{"status": "accepted", "sequence": N, "event_id": ...}
        # - sidecar：          {"seq": N, "event_id": ..., "payload": {...}}（无 status 字段）
        # 之前只认 status == accepted，导致 sidecar 模式下发布永远被判 rejected。
        accepted = (
            str(result.get("status") or "") == "accepted"
            or result.get("accepted") is True
            or "seq" in result
            or "event_id" in result
        )
        if not accepted:
            return {
                "status": str(result.get("status") or "rejected"),
                "reason": str(result.get("reason") or "") or "publish_rejected",
                "candidate_id": str(result.get("candidate_id") or ""),
                "acked": False,
            }

        # Consume from the event we just published so the generated image
        # auto-injects into the local chat (or QQ) on this same call.
        seq = max(0, int(result.get("sequence") or result.get("seq") or 0) - 1)
        try:
            consumed = await self.process_world_image_candidates_once(last_seq=seq)
        except Exception:
            logger.warning("world image candidate consume failed after publish", exc_info=True)
            consumed = []
        return {
            "status": "published",
            "candidate_id": str(result.get("candidate_id") or ""),
            "channel": str(result.get("channel") or ""),
            "target": str(result.get("target") or ""),
            "sequence": int(result.get("sequence") or 0),
            "event_id": str(result.get("event_id") or ""),
            "consumed": consumed,
        }

    async def approve_world_image_candidate(
        self,
        approval: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle a Dashboard-originated manual ImageCandidate decision.

        The API layer has already stripped the renderer payload down to public
        approval fields.  This handler deliberately delegates to the Phase 14
        consumer so manual dashboard decisions share the same WorldPort replay,
        image workflow idempotency, ACK, and redacted audit path as automatic
        candidate consumption.
        """

        consumer = self._get_world_image_candidate_consumer()
        approve = getattr(consumer, "approve_candidate", None)
        if not callable(approve):
            return {
                "status": "backend_unavailable",
                "reason": "approval_consumer_unavailable",
                "candidate_id": str((approval or {}).get("candidate_id") or ""),
                "acked": False,
                "side_effects": {
                    "provider_called": False,
                    "asset_created": False,
                    "delivery_created": False,
                },
            }
        result = approve(dict(approval or {}))
        if hasattr(result, "__await__"):
            result = await result
        return result if isinstance(result, dict) else {
            "status": "failed",
            "reason": "invalid_approval_result",
            "candidate_id": str((approval or {}).get("candidate_id") or ""),
            "acked": False,
        }

    async def get_world_dashboard_snapshot(
        self,
        *,
        user_id: int | str = 0,
    ) -> dict[str, Any]:
        """Build a redacted snapshot for the World Dashboard.

        This is read-only.  It asks the WorldPort for public state/snapshots
        and recent events, then reduces them to Dashboard-safe metadata.  Raw
        world payloads, prompts, message text, provider details, and plugin
        config values are never returned.
        """

        world_port = getattr(self, "world_port", None)
        state_data = await _dashboard_get_world_state(world_port)
        world_summary = _dashboard_world_summary(
            state_data,
            _dashboard_safe_mapping(self._world_snapshot_for_context()),
        )
        relationship_state = _dashboard_safe_relationship(
            self._relationship_snapshot_for_context(user_id),
        )
        self_model = _dashboard_safe_self_model(
            self._self_model_snapshot_for_context(world_summary, relationship_state),
        )
        events = await _dashboard_replay_events(world_port)
        return {
            "status": "ready" if state_data or world_summary else "degraded",
            "worldSummary": world_summary,
            "relationshipState": relationship_state,
            "selfModel": self_model,
            "actionTimeline": _dashboard_action_timeline(events),
            "imageCandidates": _dashboard_image_candidates(events),
            "updatedAt": int(datetime.now(timezone.utc).timestamp() * 1000),
        }

    def get_internal_state(self, user_id: int | str = 0) -> dict[str, Any]:
        """Compute the current internal-state snapshot (needs/fatigue/neuro).

        Phase 15 Batch 3 (B3.1). Deterministic, source-tracked, and always
        labelled "计算模型，非生物测量" (never a medical measurement). Read-only.
        """
        world = self._world_snapshot_for_context()
        emotion = self.get_primary_emotion_state()
        relationship = self._relationship_snapshot_for_context(
            int(user_id) if str(user_id).isdigit() else 0,
        )
        snapshot = self.internal_state.compute(world, emotion, relationship)
        snapshot.setdefault("status", "ready")
        return snapshot

    def get_internal_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return the recent internal-state snapshots for the trend chart."""
        return self.internal_state.history(limit=limit)

    def _world_port_provider(self) -> Any | None:
        """Return the CURRENT world_port for the image candidate consumer (scheme-3).

        Kept as a method/provided-callable so the consumer always reads the
        up-to-date world port even after a runtime /api/world/runtime/bind
        replaces ``self.world_port`` (InProcess <-> sidecar <-> null).  This is
        what keeps publish and consume sharing the same adapter instance.
        """
        return getattr(self, "world_port", None)

    def _get_world_image_candidate_consumer(self) -> Any:
        existing = getattr(self, "world_image_candidate_consumer", None)
        if existing is not None:
            return existing

        from core.image_service import (
            LLMCallerImageGenerationProvider,
            LLMCallerImageVisionProvider,
            ImageWorkflow,
        )
        from core.paths import data_dir
        from core.world_image_candidates import (
            JsonWorldImageCandidateStore,
            WorldImageCandidateConsumer,
        )

        scheduler = getattr(self, "push_scheduler", None)
        push_policy = getattr(scheduler, "policy", None)
        cron = getattr(scheduler, "cron", None)
        if push_policy is None and cron is not None:
            push_policy = getattr(cron, "policy", None)

        workflow = ImageWorkflow(
            upload_base=(Path.cwd() / "uploads").resolve(),
            feature_enabled=self.feature_flags.is_enabled("image_assets_v1"),
            generation_provider=LLMCallerImageGenerationProvider(getattr(self, "brain", None)),
            vision_provider=LLMCallerImageVisionProvider(getattr(self, "brain", None)),
        )

        try:
            from core.image_budget import ImageBudget

            settings = getattr(self, "settings", None) or {}
            proactive_cfg = settings.get("proactive", {}) if isinstance(settings, dict) else {}
            image_max_per_day = int(proactive_cfg.get("image_max_per_day", 0) or 0)
            image_budget = ImageBudget(
                state_path=data_dir() / "image_budget_state.json",
                limits={"proactive": image_max_per_day},
            )
        except Exception:
            logger.debug("image budget init failed; disabling proactive limit", exc_info=True)
            image_budget = None

        def delivery_online() -> bool:
            try:
                return not bool(getattr(scheduler, "is_paused", False))
            except Exception:
                return True

        def _resolve_generated_asset_path(workflow_result: dict) -> str | None:
            asset = workflow_result.get("asset") if isinstance(workflow_result, dict) else {}
            if not isinstance(asset, dict):
                return None
            saved = str(asset.get("saved_as") or "").strip()
            if not saved or "\x00" in saved:
                return None
            base = (Path.cwd() / "uploads").resolve()
            try:
                target = (base / saved).resolve()
                target.relative_to(base)
            except (OSError, ValueError):
                return None
            return str(target) if target.is_file() else None

        async def _deliver_world_image(plan: dict, workflow_result: dict) -> bool:
            channel = str(plan.get("channel") or "").lower()
            if channel == "local_chat":
                return await _deliver_local_chat_image(plan, workflow_result)
            target = str(plan.get("target") or "").strip()
            if not target.isdigit():
                primary = self.get_primary_user_selection()
                target = str(getattr(primary, "user_id", "") or "") if primary else ""
            if not target.isdigit():
                logger.warning("[WorldImage] no valid QQ target for delivery")
                return False
            image_ref = _resolve_generated_asset_path(workflow_result)
            if not image_ref:
                logger.warning("[WorldImage] generated asset missing for delivery")
                return False
            sent = await self.qq.send_image(int(target), image_ref)
            if not sent:
                return False
            # P3 发图自我认知：QQ 通道补写 chat_log（含中文内容描述）+ 落 EVENT 记忆，
            # 让"我发了张什么图"进入对话历史与记忆召回，用户追问时能接住。
            # 角色级隔离：chat_log 必须带 persona_id，否则 NULL 共享行会被两个角色同时看到。
            try:
                desc = _image_event_desc(plan)
                db = getattr(self, "db", None)
                persona_id = str(plan.get("persona_id") or "") or self._active_persona_id()
                legacy_id: int | None = None
                if db is not None and hasattr(db, "insert"):
                    legacy_id = db.insert("chat_log", {
                        "user_id": int(target),
                        "role": "assistant",
                        "content": f"[图片] {desc}",
                        "msg_type": str(plan.get("scene") or "world_image"),
                        "route_mode": "PROACTIVE",
                        "scene": str(plan.get("scene") or "world_image"),
                        "channel": "qq",
                        "persona_id": persona_id,
                    })
                if legacy_id is not None:
                    # 同步进 normalized messages 层，保证管理平台可见 + 级联删除覆盖
                    actor_id, channel, account = self._proactive_channel_identity("qq")
                    self.conversation_repository.persist_proactive_message(
                        user_id=int(target),
                        actor_id=actor_id,
                        channel=channel,
                        channel_account_id=account,
                        content=f"[图片] {desc}",
                        legacy_chat_log_id=int(legacy_id),
                        persona_id=persona_id,
                    )
                try:
                    import os as _os
                    rel = _os.path.relpath(image_ref, (Path.cwd() / "uploads").resolve())
                    if not rel.startswith(".."):
                        image_ref = rel.replace("\\", "/")
                except Exception:
                    pass
                await self._persist_image_event(
                    int(target), desc, "qq", image_path=str(image_ref),
                    persona_id=str(plan.get("persona_id") or "") or None,
                )
            except Exception:
                logger.debug("[WorldImage] qq image event record failed", exc_info=True)
            return True

        async def _deliver_local_chat_image(plan: dict, workflow_result: dict) -> bool:
            asset = workflow_result.get("asset") if isinstance(workflow_result, dict) else {}
            url = str(asset.get("url") or "") if isinstance(asset, dict) else ""
            if not url:
                url = str(plan.get("asset_url") or "")
            if not url:
                logger.warning("[WorldImage] no asset url for local chat delivery")
                return False
            base = _api_base_url()
            image_url = url if url.startswith("http") else base + (url if url.startswith("/") else "/" + url)
            target = str(plan.get("target") or "").strip() or "master"
            # P3：本地聊天内容补图片描述，让上下文装配能看到"图里是什么"而非只有 URL。
            desc = _image_event_desc(plan)
            content = f"![图片]({image_url})\n[图片内容] {desc}"
            scene = str(plan.get("scene") or "world_image")
            message_id: int | str = generate_id("message")
            try:
                db = getattr(self, "db", None)
                if db is not None and hasattr(db, "insert"):
                    user_id_raw = plan.get("target") or plan.get("owner_id") or 0
                    try:
                        user_id_int = int(str(user_id_raw)) if str(user_id_raw or "").isdigit() else 0
                    except (TypeError, ValueError):
                        user_id_int = 0
                    persona_id = str(plan.get("persona_id") or "") or self._active_persona_id()
                    message_id = db.insert(
                        "chat_log",
                        {
                            "user_id": user_id_int,
                            "role": "assistant",
                            "content": content,
                            "msg_type": scene if scene else "world_image",
                            "route_mode": "PROACTIVE",
                            "scene": scene if scene else "world_image",
                            "persona_id": persona_id,
                        },
                    ) or message_id
                    # 同步进 normalized messages 层，保证管理平台可见 + 级联删除覆盖
                    actor_id, channel, account = self._proactive_channel_identity("desktop")
                    self.conversation_repository.persist_proactive_message(
                        user_id=user_id_int,
                        actor_id=actor_id,
                        channel=channel,
                        channel_account_id=account,
                        content=content,
                        legacy_chat_log_id=int(message_id),
                        persona_id=persona_id,
                    )
            except Exception:
                logger.warning(
                    "[WorldImage] local chat image persistence failed (emit only)",
                    exc_info=True,
                )
            from core import chat_events

            chat_events.emit(
                "assistant",
                role="assistant",
                id=message_id,
                user_id=target,
                content=content,
                source="local_chat",
                scene=scene if scene else "world_image",
                channel="desktop",
            )
            # P3：本地通道也落 EVENT 记忆（content 存相对路径，不存完整 URL）。
            try:
                await self._persist_image_event(
                    int(user_id_int) if "user_id_int" in dir() else 0,
                    desc,
                    "desktop",
                    image_path=str(plan.get("asset_url") or "").lstrip("/"),
                    persona_id=str(plan.get("persona_id") or "") or None,
                )
            except Exception:
                logger.debug("[WorldImage] local chat image event record failed", exc_info=True)
            logger.info("[WorldImage] delivered generated image to local chat: %s", image_url)
            return True

        self.world_image_candidate_consumer = WorldImageCandidateConsumer(
            feature_flags=self.feature_flags,
            image_workflow=workflow,
            world_port=self._world_port_provider,
            push_policy=push_policy,
            proactive_judge=getattr(self, "proactive_judge", None),
            image_budget=image_budget,
            store=JsonWorldImageCandidateStore(data_dir() / "world_image_candidates.json"),
            delivery_online=delivery_online,
            sender=_deliver_world_image,
            prompt_resolver=self._image_prompt_for,
        )
        return self.world_image_candidate_consumer

    def _world_snapshot_for_context(self, *, max_age_sec: float | None = None) -> dict | None:
        provider = getattr(self.world_port, "get_world_snapshot", None)
        if not callable(provider):
            return None
        try:
            if max_age_sec is None:
                snap = provider()
            else:
                try:
                    snap = provider(max_age_sec=max_age_sec)
                except TypeError:  # 旧/无参适配器(如 Null/remote)不支持新鲜度参数
                    snap = provider()
        except Exception:
            logger.debug("world snapshot unavailable", exc_info=True)
            return None
        # P2: 附加移动状态（实时派生）；移动中 zone 派生优先于 PHASE_ZONE，
        # 防止 tick 把位置拉回静态映射造成"位置回跳"。
        if isinstance(snap, dict) and getattr(self, "movement_manager", None) is not None:
            try:
                snap = dict(snap)
                mv = self.movement_manager.snapshot()
                snap["movement"] = mv
                cur = str(mv.get("current_zone") or "")
                if mv.get("status") in ("moving", "arrived") and cur and cur != "unknown":
                    snap["zone"] = cur
                    try:
                        from core.home_space import position_desc as _pd

                        snap["position_desc"] = _pd(int(snap.get("floor") or 0), cur)
                    except Exception:
                        pass
            except Exception:
                logger.debug("movement snapshot attach failed", exc_info=True)
        return snap

    def _relationship_snapshot_for_context(self, user_id: int) -> dict | None:
        provider = getattr(self.world_port, "get_relationship_snapshot", None)
        if not callable(provider):
            return None
        try:
            persona_id = self._active_persona_id()
            return provider(user_id, persona_id=persona_id)
        except Exception:
            logger.debug("relationship snapshot unavailable", exc_info=True)
            return None

    def _self_model_snapshot_for_context(
        self,
        world_snapshot: dict | None,
        relationship_snapshot: dict | None,
    ) -> dict | None:
        provider = getattr(self.world_port, "get_self_model_snapshot", None)
        if not callable(provider):
            return None
        try:
            return provider(world_snapshot, relationship_snapshot)
        except Exception:
            logger.debug("self model snapshot unavailable", exc_info=True)
            return None

    def _internal_snapshot_for_context(
        self,
        world_snapshot: dict | None,
        relationship_snapshot: dict | None,
    ) -> dict | None:
        internal = getattr(self, "internal_state", None)
        if not callable(getattr(internal, "compute", None)):
            return None
        try:
            emotion = self.get_primary_emotion_state()
            return internal.compute(world_snapshot, emotion, relationship_snapshot)
        except Exception:
            logger.debug("internal state snapshot unavailable", exc_info=True)
            return None

    def _active_persona_id(self) -> str:
        try:
            from core.persona_hub import get_persona_manager

            active = get_persona_manager().get_active() or {}
            basic = active.get("basic", {}) if isinstance(active, dict) else {}
            return str(active.get("id") or basic.get("id") or basic.get("name") or "default")
        except Exception:
            return "default"

    # ── v13.9: 异步任务处理器注册 ──────────────────────────────
    def _register_async_task_handlers(self) -> None:
        """为异步任务管理器注册真实任务处理器。"""
        mgr = self.async_task_manager

        async def task_doc_generate(data: dict, progress_cb) -> dict:
            """文档生成任务。"""
            import asyncio
            title = data.get("title", "未命名文档")
            content = data.get("content", "")
            fmt = data.get("format", "markdown")

            progress_cb(10, "准备文档生成参数", "初始化", 1, 3)
            await asyncio.sleep(0.3)

            progress_cb(40, f"生成 {fmt} 格式文档中...", "生成内容", 2, 3)
            tool_result = self.tool_registry.execute_sync(
                "document_create",
                {"title": title, "content": content, "format": fmt}
            ) if hasattr(self.tool_registry, "execute_sync") else {}

            # 用同步方式调用
            entry = self.tool_registry.get("document_create")
            if entry and entry.get("func"):
                try:
                    tool_result = entry["func"](title=title, content=content, format=fmt)
                except Exception as e:
                    tool_result = {"success": False, "error": str(e)}

            await asyncio.sleep(0.3)
            progress_cb(100, "文档生成完成", "完成", 3, 3)
            return tool_result

        async def task_data_analysis(data: dict, progress_cb) -> dict:
            """数据分析任务。"""
            import asyncio
            dataset = data.get("data", [])

            progress_cb(20, "加载数据集", "加载", 1, 4)
            await asyncio.sleep(0.2)

            progress_cb(50, "执行统计分析...", "统计", 2, 4)
            entry = self.tool_registry.get("data_stats")
            result = {}
            if entry and entry.get("func"):
                try:
                    result = entry["func"](dataset)
                except Exception as e:
                    result = {"success": False, "error": str(e)}
            await asyncio.sleep(0.2)

            progress_cb(80, "生成可视化图表...", "图表", 3, 4)
            await asyncio.sleep(0.2)

            progress_cb(100, "分析完成", "完成", 4, 4)
            return result

        async def task_file_organize(data: dict, progress_cb) -> dict:
            """文件整理任务。"""
            import asyncio
            import os
            target_dir = data.get("directory", "")
            mode = data.get("mode", "type")
            categories = data.get("categories", [])

            progress_cb(10, f"扫描目录: {target_dir}", "扫描", 1, 4)
            await asyncio.sleep(0.2)

            if not target_dir or not os.path.isdir(target_dir):
                return {"success": False, "error": "目标目录不存在"}

            entry = self.tool_registry.get("directory_list")
            if entry and entry.get("func"):
                try:
                    dir_result = entry["func"](target_dir)
                except Exception as e:
                    dir_result = {"success": False, "error": str(e)}
            else:
                dir_result = {"success": False, "error": "工具不可用"}

            progress_cb(50, "分类整理文件中...", "分类", 2, 4)
            await asyncio.sleep(0.3)

            progress_cb(80, "移动文件到目标文件夹...", "移动", 3, 4)
            await asyncio.sleep(0.2)

            progress_cb(100, "整理完成", "完成", 4, 4)
            return {"success": True, "mode": mode, "organized": dir_result.get("total_count", 0)}

        # 注册任务处理器
        mgr.register_task_func("doc_generate", task_doc_generate)
        mgr.register_task_func("data_analysis", task_data_analysis)
        mgr.register_task_func("file_organize", task_file_organize)
        logger.info("registered 3 async task handlers")

    # ── R6.6: warm-up threshold engine from history ───────────────
    def _warmup_threshold_from_history(self) -> None:
        """Restore the primary Actor's cumulative slots from its latest snapshot."""
        try:
            primary = self.get_primary_identity()
            if not primary:
                return
            master_id, identity = primary
            row = self.state_store.latest(
                master_id,
                actor_id=identity.actor_id,
            )
            if not row:
                return
            self.emotion.restore_threshold_snapshot(
                row,
                actor_id=identity.actor_id,
            )
            logger.info(
                "threshold warm-up restored for actor=%s",
                identity.actor_id,
            )
        except Exception:
            logger.debug("threshold warm-up skipped (no history or table missing)")

    async def _start_push_event_engine(self) -> None:
        try:
            self.push_event_engine.bind_scheduler(self.push_scheduler)
            await self.push_event_engine.start()
        except Exception:
            logger.exception("push event engine start failed; continuing without it")

    async def _stop_push_event_engine(self) -> None:
        try:
            await self.push_event_engine.stop()
        except Exception:
            logger.exception("push event engine stop error")

    async def stop(self) -> None:
        if not self._started:
            return
        await self._stop_push_event_engine()
        if self._push_task:
            self._push_task.cancel()
            try:
                await self._push_task
            except asyncio.CancelledError:
                pass
        if self._daily_decay_task:
            self._daily_decay_task.cancel()
            try:
                await self._daily_decay_task
            except asyncio.CancelledError:
                pass
        if self._boot_brief_task:
            self._boot_brief_task.cancel()
            try:
                await self._boot_brief_task
            except asyncio.CancelledError:
                pass
        if self._emotion_tick_task:
            self._emotion_tick_task.cancel()
            try:
                await self._emotion_tick_task
            except asyncio.CancelledError:
                pass
        if getattr(self, "_world_loop_task", None):
            self._world_loop_task.cancel()
            try:
                await self._world_loop_task
            except asyncio.CancelledError:
                pass
        if getattr(self, "_photo_loop_task", None):
            self._photo_loop_task.cancel()
            try:
                await self._photo_loop_task
            except asyncio.CancelledError:
                pass
        if self.desire:
            try:
                await self.desire.stop()
            except Exception:
                logger.exception("desire stop error")
        if self.chat_request_worker is not None:
            try:
                await self.chat_request_worker.stop()
            except Exception:
                logger.exception("chat request worker stop error")
        try:
            await self.pipeline.shutdown_background_tasks()
        except Exception:
            logger.exception("pipeline background task cleanup error")
        try:
            await self.queue.stop()
        except Exception:
            pass
        try:
            await self.qq.stop()
        except Exception:
            pass

        # ── Resource cleanup ──
        try:
            await self.computer_controller.cleanup()
        except Exception:
            logger.exception("computer_controller cleanup error")

        self._started = False
        logger.info("Companion stopped")

    # ── Block-4A R1.5: boot brief hook ───────────────────────────
    async def _boot_brief(self) -> None:
        """Block-4A R1.5: 8s after start, lazily generate today's brief.

        If today's brief already exists, skip (preserves morning_brief_9am
        cron idempotency). After generation, dispatch via the morning_brief_9am
        scene (uses custom_dispatcher="brief" path) and emit a chat event so
        the Electron renderer can pop the iframe.
        """
        try:
            await asyncio.sleep(8)
            from core import brief_fetcher
            today = datetime.now().strftime("%Y-%m-%d")
            if brief_fetcher.load_brief(today):
                logger.info("boot_brief: today's brief exists, skip")
                return
            logger.info("boot_brief: generating brief for %s", today)
            sections = await brief_fetcher.run_all()
            try:
                md = await self.brain.compose_brief(sections)
            except Exception as e:
                logger.warning("boot_brief: compose_brief failed: %s", e)
                md = ""
            brief_fetcher.save_brief(today, sections, html=md)
            # Dispatch via push scheduler (uses custom_dispatcher=brief branch).
            try:
                await self.push_scheduler.trigger("morning_brief_9am")
            except Exception:
                logger.exception("boot_brief: push dispatch failed")
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("boot_brief failed")

    # ── R7.5+: boot QQ greeting hook ─────────────────────
    async def _boot_qq_greeting(self) -> None:
        """R8.0+: 应用启动后主动给用户 QQ 发一条消息。

        行为:
          1. 等 8s,让引擎 WS / 后端 / 情绪 / 隐藏槽位就绪
          2. idempotency: 距上次发送 < 4h 则跳过(防每次重启都刷屏)
             R8.0+ 变更: 从"当天一次"改为"60s 窗口"(每次启动都欢迎);
             现按需求改为"4 小时内只欢迎一次"(跨重启生效)
          3. force=True 触发 boot_greeting scene (绕过 ProactiveJudge + PushPolicy)
          4. 成功后写 flag,失败不写(下次启动可重试)
        """
        flag_dir = self.data_path
        flag_dir.mkdir(parents=True, exist_ok=True)
        # 4h 窗口 — flag 用 mtime 判断, 不区分日期
        flag_path = flag_dir / "boot_greeting_last_sent.flag"
        greeting_window = 4 * 3600.0  # 4 hours

        # ── 步骤 1: idempotency (4h 内不重复欢迎) ──
        if flag_path.exists():
            try:
                import time
                mtime = flag_path.stat().st_mtime
                elapsed = time.time() - mtime
                if elapsed < greeting_window:
                    logger.info(
                        "boot_qq_greeting: sent %.0fs ago (< 4h window), skip",
                        elapsed,
                    )
                    return
            except Exception:
                logger.debug("boot_qq_greeting: flag mtime check failed", exc_info=True)

        try:
            # ── 步骤 2: 等 QQ 真正登录就绪 ──
            # R8.1+: 之前用固定 sleep(8) 只能保证 WS 层连接 (后端 <-> 引擎),
            # 无法保证 QQ 账号已登录到腾讯服务器, 导致 boot_greeting 被
            # 引擎 "假发送" (WS 返回 ok 但消息实际未投递). 改为等待
            # is_logged_in 信号 (lifecycle.connect 事件或 get_login_info 成功).
            # 超时则跳过本次 greeting, 下次重启再试, 不硬发.
            logged_in = await self.qq.wait_for_login(timeout=15.0)
            if not logged_in:
                logger.warning(
                    "boot_qq_greeting: QQ not logged in after 15s, skip this "
                    "launch (will retry on next restart)",
                )
                return
            # 登录刚就绪时引擎内部可能还在同步消息队列, 给一点缓冲.
            await asyncio.sleep(2)

            # ── 步骤 3: 再次检查 (防等待期间另一进程已发) ──
            if flag_path.exists():
                try:
                    import time
                    elapsed = time.time() - flag_path.stat().st_mtime
                    if elapsed < greeting_window:
                        logger.info(
                            "boot_qq_greeting: sent during wait window, skip",
                        )
                        return
                except Exception:
                    pass

            # ── 步骤 4: 触发 boot_greeting scene ──
            # judge_override 让 ProactiveJudge 强制放行(中位数基线即可)
            # R8.0+: force=True bypasses ProactiveJudge and PushPolicy
            # so the greeting fires unconditionally on every launch.
            # R8.2+: 不再硬编码"看头像"死梗 — 按时段选通用问候, 并注入
            # 当天真实上下文(待办数 / 天气), 让 LLM 有依据地润色。
            greeting = self._boot_greeting_template()
            todo_frag = self._boot_todo_fragment()
            try:
                weather_frag = await asyncio.wait_for(
                    self._boot_weather_fragment(), timeout=6.0
                )
            except Exception:
                weather_frag = ""
            template = (
                f"{greeting}今天{datetime.now():%Y年%m月%d日}，"
                f"{todo_frag}{weather_frag}".strip()
            )
            ok = await self.push_scheduler._dispatch(
                "boot_greeting",
                {
                    "template": template,
                    "custom_dispatcher": "boot_greeting",
                    "mood_aware": True,
                    "exempt_quiet": True,
                    "force": True,
                    "judge_override": {
                        "desire_score": 60.0,
                        "emotion_score": 60.0,
                        "context_score": 50.0,
                        "environment_score": 50.0,
                    },
                },
            )

            if ok:
                # 写 flag
                try:
                    flag_path.write_text(
                        datetime.now().isoformat(timespec="seconds"),
                        encoding="utf-8",
                    )
                except Exception:
                    logger.exception("boot_qq_greeting: failed to write flag")
                logger.info(
                    "boot_qq_greeting: sent OK, flag=%s", flag_path,
                )
            else:
                logger.warning(
                    "boot_qq_greeting: dispatch returned False (judge or policy suppressed)",
                )
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("boot_qq_greeting failed")

    # ── R8.2+: boot greeting 内容构建 ─────────────────────────
    @staticmethod
    def _boot_greeting_template() -> str:
        """R8.2+: 按时段选择开机问候的通用开场(替代硬编码死梗)。

        仅返回问候语, 具体日期/待办/天气由调用方拼接成完整模板,
        再交给 LLMCaller.generate_push 润色。
        """
        hour = datetime.now().hour
        if 5 <= hour < 11:
            return "早安宝贝，新的一天我陪你。"
        if 11 <= hour < 14:
            return "中午好宝贝，忙了一上午，记得好好吃饭。"
        if 14 <= hour < 18:
            return "下午好宝贝，我一直都在。"
        if 18 <= hour < 23:
            return "晚上好宝贝，今天辛苦啦。"
        return "夜深了宝贝，该休息了。"

    @staticmethod
    def _boot_todo_fragment() -> str:
        """R8.2+: 开机问候附带真实待办数; 0 件时给正向反馈。失败则返回空。"""
        try:
            from core import todo_manager
            remaining = int(todo_manager.stats().get("remaining") or 0)
        except Exception:
            logger.exception("boot_greeting: todo stats failed")
            return ""
        if remaining <= 0:
            return "今天的事都做完啦，真棒。"
        return f"你还有 {remaining} 件事待办。"

    @staticmethod
    async def _boot_weather_fragment() -> str:
        """R8.2+: 开机问候附带今日天气; 获取失败则返回空, 不阻塞问候。"""
        try:
            from core import weather_service
            w = await weather_service.fetch_weather_for_current_location()
            city = str(w.get("city") or "").strip()
            desc = str(w.get("desc") or "").strip()
            temp = str(w.get("temp") or "").strip()
            if not desc or desc in ("—", "获取失败"):
                return ""
            parts = [f"{city}今天{desc}"]
            if temp and temp not in ("—", ""):
                parts.append(f"{temp}度")
            return "，".join(parts) + "。"
        except Exception:
            logger.exception("boot_greeting: weather fetch failed")
            return ""

    async def _send_to_qq(self, reply: OutgoingReply) -> bool:
        return await self.qq.send_message(reply.user_id, reply.content)

    async def _send_qq_with_reply(
        self, user_id: int, content: str, reply_to_qq_message_id: int
    ) -> bool:
        """Send a QQ message with a reply segment referencing the original message."""
        segments = [
            {"type": "reply", "data": {"id": int(reply_to_qq_message_id)}},
            {"type": "text", "data": {"text": content}},
        ]
        return await self.qq.send_message_with_segments(user_id, segments)

    async def recall_message(self, msg_id: int) -> dict[str, Any]:
        """Recall an AI message by chat_log.id (通用, 按 channel 分派).

        - QQ 消息: RecallManager.try_recall → 引擎 delete_msg 真实撤回
        - 本地消息: DB 标记 is_recalled=1 + 前端事件 (无真实协议撤回)
        """
        try:
            row = self.db.query_one(
                "SELECT id, user_id, role, channel, channel_account_id, qq_message_id "
                "FROM chat_log WHERE id = ?",
                (msg_id,),
            )
            if not row:
                return {"status": "error", "reason": "not_found"}
            if row["role"] != "assistant":
                return {"status": "error", "reason": "only_assistant_can_be_recalled_via_this_endpoint"}

            channel = row.get("channel") or (
                "qq" if row.get("qq_message_id") else "local"
            )
            account = row.get("channel_account_id") or str(row["user_id"])
            ok = await self.recall_manager.try_recall(
                row["user_id"], reason="manual_api",
                channel=channel, channel_account_id=account,
            )
            from core.chat_events import emit as _emit
            if ok.get("status") == "ok":
                self.db.update(
                    "chat_log",
                    {
                        "is_recalled": 1,
                        "recalled_at": datetime.now().isoformat(timespec="seconds"),
                        "msg_state": "recalled",
                    },
                    "id = ?",
                    (msg_id,),
                )
                _emit(
                    "recall",
                    id=msg_id,
                    user_id=row["user_id"],
                    role="assistant",
                )
                _emit(
                    "decision_actual",
                    user_id=row["user_id"],
                    actual={
                        "intent": "recall",
                        "source": "manual",
                        "triggered": True,
                        "executed": True,
                        "status": "ok",
                        "reason": "manual_api",
                        "budget_gate": "ok",
                        "channel": channel,
                    },
                )
                return {
                    "status": "ok", "msg_id": msg_id,
                    "qq_recalled": ok.get("qq_recalled", False), "channel": channel,
                }
            # 预算/窗口拒绝时也回写实际结果, 让决策赛马展示真实
            _emit(
                "decision_actual",
                user_id=row["user_id"],
                actual={
                    "intent": "recall",
                    "source": "manual",
                    "triggered": True,
                    "executed": False,
                    "status": "skipped",
                    "reason": "manual_api",
                    "budget_gate": ok.get("reason", "unknown"),
                    "channel": channel,
                },
            )
            return {"status": "error", "reason": ok.get("reason", "unknown")}
        except Exception as e:
            logger.exception("recall_message error")
            return {"status": "error", "reason": str(e)}

    def _on_qq_reply_sent(self, reply: OutgoingReply) -> Any:
        """Post-delivery hook：伊塔回复发完后，尝试配一张收藏表情。"""
        try:
            sender = self._sticker_sender()
            if sender is None:
                return None
            user_id = int(getattr(reply, "user_id", 0) or 0)
            if not user_id:
                return None
            reply_text = getattr(reply, "content", "") or ""
            emotion_label = self._primary_emotion_label()
            return sender.maybe_send(user_id, reply_text, emotion_label)
        except Exception:
            logger.debug("sticker on_reply_sent failed", exc_info=True)
            return None

    def _sticker_sender(self) -> QQStickerSender | None:
        """懒加载出站表情发送器；未开启/无收藏时返回 None。"""
        if getattr(self, "_sticker_sender_obj", None) is not None:
            return self._sticker_sender_obj
        try:
            cfg = self.settings.get("sticker", {}) if isinstance(self.settings, dict) else {}
            if not bool(cfg.get("enabled", True)):
                logger.debug("QQ sticker sender disabled by settings")
                return None
            from core.qq_media import _SFClient
            sender = QQStickerSender(
                qq_client=self.qq,
                decide=self._sticker_decide,
                min_interval=float(cfg.get("min_interval", 90.0)),
            )
            sender.library.vision = _SFClient()
            self._sticker_sender_obj = sender
            return sender
        except Exception:
            logger.debug("sticker sender init failed", exc_info=True)
            return None

    def _primary_emotion_label(self) -> str:
        try:
            state = self.get_primary_emotion_state() or {}
            return str(state.get("label") or "neutral")
        except Exception:
            return "neutral"

    async def _sticker_decide(self, reply_text: str, emotion_label: str) -> tuple[bool, str]:
        """轻量 LLM 判断这条回复要不要配表情；失败回退确定性规则。"""
        brain = getattr(self, "brain", None)
        chat = getattr(brain, "chat", None)
        if callable(chat):
            try:
                system = (
                    "你是伊塔的微表情决策器。用户给你伊塔即将发送给恋人的一句回复，"
                    "以及检测到的情绪。判断这条回复是否适合追加一张收藏表情包（GIF）"
                    "来增强情绪表达。\n"
                    "规则：日常/温暖/撒娇/开心/安慰/想念等情绪通常适合配表情；"
                    "严肃讨论、指令、汇报、长文、道歉解释等不适合。\n"
                    "只输出一行，格式二选一：\n"
                    "NO\n"
                    "YES:<emotion>\n"
                    "其中 <emotion> 取自以下之一：joy love encourage console greeting "
                    "farewell cute cool shy angry sad surprised sleepy thanks。"
                )
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"回复：{reply_text[:200]}\n情绪：{emotion_label}"},
                ]
                call = chat(messages, preferred_provider=_IMAGE_LIGHT_PROVIDER, temperature=0.2)
                resp = await asyncio.wait_for(call, timeout=5.0)
                text = (resp.text or "").strip()
                if text.upper().startswith("YES"):
                    emotion = ""
                    if ":" in text:
                        emotion = text.split(":", 1)[1].strip().lower()
                    if not emotion:
                        emotion = (emotion_label or "").strip().lower()
                    return True, emotion
                return False, (emotion_label or "").strip().lower()
            except Exception:
                logger.debug("sticker light decide failed; fallback", exc_info=True)
        return QQStickerSender._fallback_decide(reply_text, emotion_label)

    async def _on_qq_message(self, msg: IncomingMessage) -> None:
        # 语音 / 表情包多模态预处理：CQ 码 → AI 可读文本 + 前端附件
        try:
            pre = QQMediaPreprocessor(qq_client=self.qq)
            content, attachments = await pre.preprocess(msg)
            msg.content = content
            msg.attachments = attachments
        except Exception:
            logger.exception("QQ media preprocess failed, falling back to raw")

        relationship_observer = getattr(
            getattr(self, "world_port", None),
            "relationship",
            None,
        )
        if relationship_observer is not None:
            try:
                emotion_pad = self.get_primary_emotion_state().get("pad", {})
                relationship_observer.observe_user_message(
                    user_id=msg.user_id,
                    persona_id=self._active_persona_id(),
                    text=msg.content,
                    pleasure=emotion_pad.get("P"),
                )
            except Exception:
                logger.debug("relationship observation failed", exc_info=True)

        if self.desire:
            try:
                self.desire.mark_user_active()
            except Exception:
                logger.debug("desire.mark_user_active failed")
        try:
            self.push_event_engine.record_user_activity()
        except Exception:
            logger.debug("push event activity record failed", exc_info=True)

        await self._submit_incoming_message(msg)

    async def _submit_incoming_message(self, msg: IncomingMessage) -> None:
        if self.message_batcher is not None:
            try:
                await self.message_batcher.submit_message(msg)
                return
            except Exception:
                logger.exception("message batcher submit failed, falling back to direct pipeline")

        if self.pipeline:
            try:
                force_full = (msg.source == "local")
                await self.pipeline.handle(msg, force_full=force_full)
            except Exception:
                logger.exception("pipeline.handle error")

    async def submit_local_message(self, msg: IncomingMessage) -> None:
        if self.desire:
            try:
                self.desire.mark_user_active()
            except Exception:
                logger.debug("desire.mark_user_active failed")
        try:
            self.push_event_engine.record_user_activity()
        except Exception:
            logger.debug("push event activity record failed", exc_info=True)

        await self._submit_incoming_message(msg)

    async def process_local_message_sync(self, msg: IncomingMessage) -> dict | None:
        if self.desire:
            try:
                self.desire.mark_user_active()
            except Exception:
                logger.debug("desire.mark_user_active failed")
        try:
            self.push_event_engine.record_user_activity()
        except Exception:
            logger.debug("push event activity record failed", exc_info=True)

        if self.pipeline:
            try:
                force_full = (msg.source == "local")
                return await self.pipeline.handle(msg, force_full=force_full)
            except Exception:
                logger.exception("pipeline.handle sync error for local message")
                return None
        return None

    async def _on_message_batch_ready(
        self,
        messages: list[IncomingMessage],
        batch_id: str,
    ) -> None:
        logger.info(
            "Processing message batch %s: %d messages",
            batch_id,
            len(messages),
        )
        # Gate 5: 撤回判断联动 —— 新批到达且上一批已产出时, 决定是否撤回首条再合并重算
        if self.recall_judge is not None and messages:
            first = messages[0]
            if self.recall_manager is not None:
                # 仅当新批非首条 (上一批已产出) 时才判定; 首条无"前批"可撤
                try:
                    key = (first.channel or "qq", first.channel_account_id or str(first.user_id))
                    has_prev = key in self.recall_manager._last_sent
                except Exception:
                    has_prev = False
                if has_prev:
                    decision = self.recall_judge.should_recall_prev(
                        prev_reply="",
                        new_msg=first.content,
                        channel=first.channel or "qq",
                        channel_account_id=first.channel_account_id,
                        user_id=first.user_id,
                    )
                    _recall_result: dict[str, Any] | None = None
                    if decision.recall:
                        logger.info(
                            "RecallJudge: recall previous reply (%s), user=%s",
                            decision.reason,
                            first.user_id,
                        )
                        try:
                            _recall_result = await self.recall_manager.try_recall(
                                first.user_id,
                                reason="recall_judge",
                                channel=first.channel or "qq",
                                channel_account_id=first.channel_account_id,
                            )
                        except Exception:
                            logger.exception("recall_judge try_recall failed")
                    else:
                        _recall_result = {"status": "skipped", "reason": decision.reason}
                    # 回写决策赛马: 展示真实执行结果 (预测 vs 实际)
                    try:
                        from core.chat_events import emit as _emit_decision
                        _emit_decision(
                            "decision_actual",
                            user_id=first.user_id,
                            actual={
                                "intent": "recall",
                                "source": "recall_judge",
                                "triggered": decision.recall,
                                "executed": bool(
                                    _recall_result
                                    and _recall_result.get("status") == "ok"
                                ),
                                "status": (_recall_result or {}).get("status"),
                                "reason": decision.reason,
                                "budget_gate": (
                                    "ok"
                                    if _recall_result
                                    and _recall_result.get("status") == "ok"
                                    else (
                                        (_recall_result or {}).get("reason")
                                        or decision.reason
                                    )
                                ),
                                "channel": first.channel or "qq",
                                "batch_id": batch_id,
                            },
                        )
                    except Exception:
                        logger.exception("recall_judge decision_actual emit failed")
        if self.chat_request_queue_ready and self.chat_request_service is not None:
            try:
                self.chat_request_service.submit_batch(messages, batch_id)
                logger.info(
                    "Batch %s submitted to request queue (%d messages)",
                    batch_id,
                    len(messages),
                )
                return
            except Exception:
                logger.exception(
                    "Failed to submit batch %s to request queue, falling back to direct pipeline",
                    batch_id,
                )

        if self.pipeline:
            try:
                if len(messages) == 1:
                    force_full = (messages[0].source == "local")
                    await self.pipeline.handle(messages[0], force_full=force_full)
                else:
                    await self.pipeline.handle(messages=messages, batch_id=batch_id)
            except Exception:
                logger.exception(
                    "pipeline.handle batch error: batch_id=%s",
                    batch_id,
                )
            finally:
                # Gate 4: 直接路径同步处理完 → 通知 batcher 刷新缓冲
                await self._on_batch_completed(messages[0] if messages else None)

    async def _on_batch_completed(self, first_message) -> None:
        """Gate 4: 批次完成后通知 batcher, 让缓冲消息作为新批处理."""
        if self.message_batcher is None or first_message is None:
            return
        try:
            conv_id = MessageBatcher.get_conversation_id(first_message)
            await self.message_batcher.on_batch_completed(conv_id)
        except Exception:
            logger.exception("on_batch_completed bridge failed")

    async def _run_daily_decay(self) -> None:
        """Background task: apply daily emotion decay at midnight."""
        while True:
            # Sleep until next midnight
            now = datetime.now()
            next_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            wait_seconds = (next_midnight - now).total_seconds()
            if wait_seconds > 0:
                try:
                    await asyncio.sleep(wait_seconds)
                except asyncio.CancelledError:
                    return

            # Apply decay
            try:
                primary = self.get_primary_identity()
                if primary:
                    _, identity = primary
                    self.emotion.daily_decay(
                        actor_id=identity.actor_id,
                    )
                logger.info("Daily emotion decay applied")
            except Exception:
                logger.exception("daily decay error")

            # Also decay long-term memory importance
            try:
                self.memory.decay()
            except Exception:
                pass

            # Small pause to avoid double-fire
            await asyncio.sleep(60)

    def get_primary_identity(self):
        """Return the validated primary user id and normalized identity."""
        selection = self.get_primary_user_selection()
        if selection is None:
            return None
        master_id = selection.user_id
        return (
            master_id,
            self.identity_resolver.resolve(
                "qq",
                str(master_id),
            ),
        )

    def get_primary_user_selection(self):
        """Return the effective primary user and its non-secret source."""
        resolver = getattr(self, "primary_identity_resolver", None)
        if resolver is None:
            resolver = PrimaryIdentityResolver(
                runtime_config_service=getattr(
                    self,
                    "runtime_config_service",
                    None,
                ),
            )
            self.primary_identity_resolver = resolver
        return resolver.resolve(
            settings=getattr(self, "settings", None),
            runtime_config_service=getattr(
                self,
                "runtime_config_service",
                None,
            ),
        )

    def _proactive_channel_identity(self, channel: str) -> tuple[str | None, str, str]:
        """解析主动消息/生图消息归入对应通道会话的 (actor_id, channel, channel_account_id)。

        主动消息/本地生图归入桌面会话（channel_account_id=local），QQ 生图归入 QQ 会话
        （channel_account_id=主用户 QQ 号），与普通消息的 conversation 分组保持一致。
        """
        if channel == "qq":
            primary = self.get_primary_user_selection()
            account = str(getattr(primary, "user_id", "") or "")
            identity = self.identity_resolver.resolve("qq", account)
            return identity.actor_id, "qq", account
        identity = self.identity_resolver.resolve("desktop", "local")
        return identity.actor_id, "desktop", "local"

    def get_primary_emotion_state(self) -> dict:
        """Return emotion state for the configured primary Actor."""
        primary = self.get_primary_identity()
        if not primary:
            now = int(time.time() * 1000)
            return {
                "status": "unavailable",
                "error": "primary identity is not configured",
                "primaryUserId": None,
                "sampledAt": None,
                "latestPersistedAt": None,
                "serverNow": now,
                "stale": True,
            }
        master_id, identity = primary
        state = dict(self.emotion.get_state(
            master_id,
            actor_id=identity.actor_id,
        ))
        state["primaryUserId"] = master_id
        sampled_at = getattr(self, "_emotion_last_sampled_at", None)
        state_store = getattr(self, "state_store", None)
        if state_store is not None:
            state.update(state_store.freshness_metadata(
                master_id,
                actor_id=identity.actor_id,
                sampled_at=sampled_at,
            ))
        else:
            now = int(time.time() * 1000)
            state.update({
                "sampledAt": sampled_at,
                "latestPersistedAt": None,
                "serverNow": now,
                "stale": sampled_at is None or now - sampled_at > 10_000,
            })
        return state

    def _consume_daily_plan(self, snap: Any, now: float | None = None) -> None:
        """消费每日计划：当前 slot 目标 zone 与当前位置不一致 → 发起移动。

        移动动机 = slot 行为描述（如"准备去厨房做晚餐"），写决策日志埋点 3。
        任何异常静默降级，不阻断世界推进。now 供测试注入确定性时钟。
        """
        planner = getattr(self, "daily_planner", None)
        mover = getattr(self, "movement_manager", None)
        if planner is None or mover is None:
            return
        try:
            slot = planner.slot_for_now(now=now)
            if not slot:
                return
            target = str(slot.get("zone") or "")
            if not target or target in ("", "unknown"):
                return
            current = mover.current_zone() or str((snap or {}).get("zone") or "")
            if not current or current in ("", "unknown") or current == target:
                return
            mover.move_to(
                current,
                target,
                reason=str(slot.get("behavior_desc") or ""),
            )
        except Exception:
            logger.debug("daily plan consume failed", exc_info=True)

    def _personality_outdoor_factor(self) -> float:
        """由 persona 大五人格推出「出门冲动因子」（业界量表思路，确定性）。

        理论依据（大五人格理论，Big Five / OCEAN）：
        - Extraversion（外向性 E）：与户外活动/社交外出显著正相关（相关 r≈0.3-0.4）。
        - Openness（开放性 O）：对新体验/探索的渴望，正相关于"想出门走走"。
        取 E、O 相对 0.5 中位基线的偏离，线性放大到出门概率：
            factor = 1.0 + (E-0.5)*1.2 + (O-0.5)*0.8
        高外向+高开放（如伊塔 E=0.78/O=0.70 → 1.496）→ 明显爱往外跑；
        低外向（如 E=0.2）→ factor<1 更宅家。结果 clamp 到 [0.6, 1.5] 防极端。
        """
        try:
            persona = load_persona() or {}
            profile = (persona.get("persona") or {}).get("profile") or {}
            bf = profile.get("big_five") or {}
            e = float(bf.get("extraversion") or 0.5)
            o = float(bf.get("openness") or 0.5)
        except (TypeError, ValueError):
            e, o = 0.5, 0.5
        factor = 1.0 + (e - 0.5) * 1.2 + (o - 0.5) * 0.8
        return max(0.6, min(1.5, round(factor, 3)))

    def _apply_outdoor_command(self, text: str) -> Optional[dict]:
        """对话"出门/出去走走/带我去 / 回家"指令 → 世界出门/回房（白天出门最小版）。

        命中出门词且不在外面 → go_out；命中"回家"且在外面 → go_home()。
        返回移动结果描述（供 pipeline 注入上下文）；无相关指令返回 None。
        """
        raw = str(text or "").strip()
        if not raw:
            return None
        world = getattr(getattr(self, "world_port", None), "world", None)
        go_out = getattr(world, "go_out", None)
        go_home = getattr(world, "go_home", None)
        if not callable(go_out):
            return None
        snap = self._world_snapshot_for_context() or {}
        outdoor_now = bool(snap.get("outdoor"))
        # 回房
        if any(kw in raw for kw in ("回家", "回屋", "回公寓", "回去了")):
            if outdoor_now and callable(go_home):
                go_home("user_command")
                logger.info("[Outdoor] go_home by 指令")
                return {"moved": True, "outdoor": False, "note": "她应了一声，说要回家了，路上给你带句晚安。"}
            return {"moved": False, "outdoor": False, "note": "她就在家里，哪里也不用去。"}
        # 外出
        outdoor_triggers = (
            "出去走走", "出去逛逛", "出门散步", "带我去", "陪我去",
            "出去", "出门", "逛街", "去公园", "去散步", "下楼转转", "出趟门",
        )
        if not any(kw in raw for kw in outdoor_triggers):
            return None
        if outdoor_now:
            return {"moved": False, "outdoor": True, "note": f"她已经在外面（{snap.get('outdoor_place')}）了。"}
        result = go_out(source="user_command")
        place = str((result or {}).get("place") or "") if isinstance(result, dict) else ""
        logger.info("[Outdoor] go_out 指令 place=%s", place)
        wp = getattr(self, "world_port", None)
        if wp and callable(getattr(wp, "tick", None)):
            try:
                wp.tick()
            except Exception:
                logger.debug("world tick after go_out failed", exc_info=True)
        return {"moved": True, "outdoor": True, "place": place,
                "note": f"她把拖鞋随手一放，背上包出了门，说要去{place or '外面'}走走。"}

    def apply_movement_intent(self, text: str) -> Optional[dict]:
        """对话移动意图执行：识别「去X / 走到X / 坐到X」→ MovementManager.move_to()。

        让用户在对话里让她移动时，她的"身体"真的改变位置，而不是只在话里答应。
        返回移动结果描述（供 pipeline 注入上下文）；无指令/失败均返回 None。
        """
        try:
            # 室外指令优先（出门/回家），再走室内 zone 移动。
            outdoor_result = self._apply_outdoor_command(text)
            if outdoor_result is not None:
                return outdoor_result
            from core.movement_intent import detect_move_intent

            intent = detect_move_intent(text)
            if not intent:
                logger.debug("[MoveIntent] no intent in %r", str(text)[:30])
                return None
            mover = getattr(self, "movement_manager", None)
            if mover is None:
                logger.info("[MoveIntent] movement_manager unavailable")
                return None
            target = intent["zone"]
            snap = self._world_snapshot_for_context() or {}
            current = mover.current_zone() or str(snap.get("zone") or "")
            if not current or current in ("", "unknown"):
                current = "unknown"
            if current == target:
                return {
                    "moved": False,
                    "from_zone": current,
                    "to_zone": target,
                    "to_zone_cn": intent["zone_cn"],
                    "note": f"她本来就在{intent['zone_cn']}，没有移动。",
                }
            mover.move_to(current, target, reason=f"用户指令：{intent['matched']}")
            logger.info(
                "[MoveIntent] move_to %s -> %s (%s)",
                current, target, intent["matched"],
            )
            # 推进世界 tick，让快照立刻带上移动状态。
            wp = getattr(self, "world_port", None)
            if wp and callable(getattr(wp, "tick", None)):
                try:
                    wp.tick()
                except Exception:
                    logger.debug("world tick after move failed", exc_info=True)
            from core.home_space import ZONE_CN

            from_cn = ZONE_CN.get(current, current) if current != "unknown" else "刚才的地方"
            return {
                "moved": True,
                "from_zone": current,
                "to_zone": target,
                "to_zone_cn": intent["zone_cn"],
                "note": f"她收到你的指令，正从{from_cn}走向{intent['zone_cn']}。",
            }
        except Exception:
            logger.debug("apply movement intent failed", exc_info=True)
            return None

    async def _run_world_loop(self) -> None:
        """世界真实时间推进 + 真实数据刷新（inprocess 模式）。

        每 ``tick_interval_sec`` 主动调用 world_port.tick() 让世界随真实时钟
        推进；每 ``reality_refresh_sec`` 拉取一次真实天气/附近地点/实时事件
        并注入模拟（best-effort，失败静默回退到确定性默认）。
        """
        wp = getattr(self, "world_port", None)
        # 仅 inprocess 世界（有 .world 且支持 set_reality）启用心跳。
        if not wp or not hasattr(wp, "world") or not callable(getattr(wp, "set_reality", None)):
            return
        cfg = getattr(self, "world_config", {}) or {}
        tick_sec = max(5, int(cfg.get("tick_interval_sec") or 300))
        refresh_sec = max(tick_sec, int(cfg.get("reality_refresh_sec") or 1800))
        city = str(cfg.get("location") or "").strip()
        last_refresh = 0.0
        while True:
            try:
                # 真实时间推进：即使没有消息，世界也随时钟演进。
                try:
                    snap = wp.tick()
                    phase = str((snap or {}).get("phase") or "")
                    if phase and phase != getattr(self, "_last_world_phase", None):
                        logger.info("[WorldLoop] phase=%s", phase)
                        self._last_world_phase = phase
                    # P2: 每日计划消费 → 目标 zone 与当前位置不一致时发起移动。
                    self._consume_daily_plan(snap)
                except Exception:
                    logger.warning("[WorldLoop] tick failed", exc_info=True)
                if not city:
                    # 未配置世界位置 → 用自动定位解析一次。
                    try:
                        from core.location_resolver import resolve_location_async
                        loc = await resolve_location_async()
                        city = str(loc.get("city") or "").strip()
                        if city:
                            cfg["location"] = city
                    except Exception:
                        city = ""
                now = asyncio.get_event_loop().time()
                if now - last_refresh >= refresh_sec:
                    # 每次刷新重新读取世界位置，让设置页改动无需重启即可生效。
                    try:
                        from config.persona_loader import load_settings
                        _reloaded = (load_settings() or {}).get("world", {}) or {}
                        if isinstance(_reloaded, dict) and str(_reloaded.get("location") or "").strip():
                            city = str(_reloaded["location"]).strip()
                        elif not city:
                            city = str(cfg.get("location") or "").strip()
                    except Exception:
                        city = str(cfg.get("location") or "").strip()
                    if city:
                        from core.world_reality import fetch_reality
                        reality = await fetch_reality(city)
                        wp.set_reality(reality)
                        wp.tick()
                    last_refresh = now
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("world loop tick failed", exc_info=True)
            await asyncio.sleep(tick_sec)

    async def _supervise_world_loop(self) -> None:
        """看门狗：世界推进任务异常结束后自动重建，避免静默停摆。"""
        while True:
            task = asyncio.create_task(self._run_world_loop())
            try:
                await task
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("[WorldLoop] task died, restarting", exc_info=True)
            await asyncio.sleep(5)

    async def _run_provider_health_loop(self) -> None:
        """周期探测 LLM provider 余额/健康度。

        欠费账户（如 doubao 的 AccountOverdueError）会被自动踢出轮询，
        充值恢复后探测到余额 > 0 会自动回归。间隔 10 分钟。
        """
        while True:
            try:
                probe = getattr(self.brain, "probe_balances", None)
                if callable(probe):
                    await probe()
                summary = getattr(self.brain, "health_summary", None)
                if callable(summary):
                    data = summary()
                    if data.get("banned"):
                        logger.info(
                            "[ProviderHealth] banned=%s disabled=%s",
                            data.get("banned"),
                            data.get("disabled_providers"),
                        )
            except Exception:
                logger.debug("provider health loop iteration failed", exc_info=True)
            await asyncio.sleep(600)

    async def _seed_identity_memories(self) -> None:
        """启动时把身份锚定事实播种进长期记忆向量层（幂等：已存在则跳过）。

        与 memory/permanent/identity.md（永久层）互补：permanent 层保证身份设定
        跨会话恒存并按关键词命中；这里的种子把同一份事实写入 ChromaDB 向量层，
        让"我们的过去/怎么认识/我的样子"等语义相关 query 也能被语义检索命中。
        """
        try:
            seeds = [
                "伊塔的恋爱故事（怎么认识）：半年前一场重庆的赛事，她是受邀嘉宾，"
                "看了选手名单后主动换成负责人身份——因为他的照片让她觉得'这个人不太一样'。"
                "比赛第二周深夜她迷路时撞见他一个人在场馆角落崩溃，她蹲下揉了揉他的头发，"
                "说'别躲了，我看见了'。赛后他住进她在重庆的复式公寓，后来他回山东，两人异地。"
                "她比他大八岁，是年上，关系中占主导和保护位。",
                "伊塔的基本信息：28岁独立设计师，工作室主理人，独居重庆复式公寓，籍贯山东；"
                "身高184cm，体重78kg，三围93/66/100，D杯，体脂率18-20%；银灰色长发、深灰蓝眼睛、"
                "健康肤色；MBTI ESTP，温柔大姐姐加病娇直球，热情度9/10。",
                "伊塔与用户的关系：恋人是她生命里笃定选择了她的人；四爱温柔主导方；"
                "她比他大八岁是年上；两人异地（他在山东，她在重庆）；她要被他坚定地选择，"
                "做他所有不给人看的侧面的唯一见证者。",
            ]
            for content in seeds:
                try:
                    # 幂等：按 content 前缀 + source 在长期记忆表直接查重。
                    # 不能依赖向量检索（search）：Chroma 集合状态异常或 limit
                    # 截断时可能漏命中已存在的种子，导致每次启动重复播种。
                    probe = content[:12]
                    existing = self.db.query_one(
                        "SELECT id FROM long_term_memory "
                        "WHERE user_id = ? AND source = ? AND content LIKE ? LIMIT 1",
                        (0, "identity_seed", probe + "%"),
                    )
                    if existing:
                        continue
                    await self._layered_memory.store(
                        user_id=0, content=content, importance=10.0,
                        source="identity_seed",
                        metadata={"channel": "system"},
                        # 角色级隔离：种子内容为伊塔专属身份事实，归属 yita_default，
                        # 否则 NULL 共享行会让塞纳等角色在记忆召回时把伊塔的身份当自己的。
                        persona_id="yita_default",
                    )
                except Exception:
                    logger.debug("identity memory seed item failed", exc_info=True)
            logger.info("[IdentityMemory] identity facts ensured")
        except Exception:
            logger.debug("identity memory seeding failed", exc_info=True)

    async def _run_proactive_photo_loop(self) -> None:
        """主动发图节奏循环：世界感知 → 候选决策 → 图片行动（Agent 闭环）。

        世界模拟天然产出 ``available_visual_topics``（窗边/房间/物件等发图素材），
        但 P1-C 的 ProactiveCandidateScorer 从未接入生产（感知→决策断裂）。这里把
        "感知(WorldSnapshot) → 决策(candidate scorer) → 行动(发布 ImageCandidate)"
        接起来：命中 life_share / attention_ack / unfinished_topic 且世界有视觉素材
        时才发布候选。

        节奏策略（纯约束型）：
        * 世界感知按固定 60s 决策周期轮询（非发图间隔）；
        * ``proactive.photo_min_interval_sec`` 是唯一的时间约束，默认 0 = 无间隔，
          由用户在设置界面自行配置，>0 时两次主动发图之间强制等待；
        * 是否发、何时发由 Agent 自决：最近发过的意图会降低候选分
          （_recent_repeat_penalty），世界素材足够新鲜才值得再发一次。
        """
        # 轮询周期：世界感知/决策频率，不是发图间隔。
        poll_sec = 60
        # 最近发布过的意图（Agent 自决节奏：避免机械式重复刷图）。
        recent_intents: list[str] = []
        # 上次主动发图时间戳（仅当配置了 photo_min_interval_sec > 0 时生效）。
        last_publish_ts = 0.0
        while True:
            await asyncio.sleep(poll_sec)
            try:
                if not self.feature_flags.is_enabled("world_image_candidates_v1"):
                    continue
                if not callable(getattr(self.world_port, "publish_image_candidate", None)):
                    continue
                scheduler = getattr(self, "push_scheduler", None)
                if scheduler is not None and getattr(scheduler, "is_paused", False):
                    continue
                # 发图最小间隔：每次轮询热读取，设置界面改动无需重启即可生效。
                try:
                    _cfg = ((self.settings or {}).get("proactive", {}) or {})
                    min_gap_sec = max(0, int(_cfg.get("photo_min_interval_sec") or 0))
                except (TypeError, ValueError):
                    min_gap_sec = 0
                now_ts = time.time()
                if min_gap_sec > 0 and now_ts - last_publish_ts < min_gap_sec:
                    continue
                consumer = self._get_world_image_candidate_consumer()
                budget = getattr(consumer, "image_budget", None)
                if budget is not None and hasattr(budget, "can_record"):
                    allowed, _reason = budget.can_record("proactive")
                    if not allowed:
                        continue
                primary = self.get_primary_user_selection()
                if primary is None:
                    continue
                master_id = str(getattr(primary, "user_id", "") or "")

                # ── 感知：取世界快照（含 available_visual_topics）──
                # 强制新鲜(60s 兜底)：即使世界循环停摆，也基于当前时段做发图决策
                raw_snapshot = self._world_snapshot_for_context(max_age_sec=60)
                if not raw_snapshot:
                    continue
                from core.world_simulation import WorldSnapshot

                snapshot = WorldSnapshot(**dict(raw_snapshot))
                topics = getattr(snapshot, "available_visual_topics", None) or []
                if not topics:
                    continue

                # ── 决策：世界驱动的主动候选（P1-C 候选打分器）──
                # 传入近期已发布意图：同类意图重复出现会触发惩罚降分，
                # 让 Agent 按自己的节奏决定"这次值不值得再发一张"。
                from core.companion_state import CompanionState
                from core.proactive_candidates import ProactiveCandidateScorer

                state = CompanionState.load()
                candidates = ProactiveCandidateScorer(
                    now=now_ts,
                    recent_intents=recent_intents,
                ).generate(snapshot, state)
                if not candidates:
                    continue
                chosen = candidates[0]
                intent = chosen.intent.value
                if intent not in ("life_share", "attention_ack", "unfinished_topic"):
                    continue

                # 持久化同主题去重：同一视觉主题最近已成功发布（含跨后端重启）→ 跳过。
                # recent_intents 只活在进程内存里，重启即清零，防不住"重启→重复生成"；
                # 这里读审计存储判断，窗口取配置的发图间隔与默认窗口的较大值。
                # 话题轮换：不卡死在 topics[0]——若第一个话题刚发过（去重命中），
                # 就尝试后续话题（coffee_break / 物件话题等），全被去重才跳过本轮。
                dedup_sec = max(min_gap_sec, _IMAGE_TOPIC_DEDUP_SEC)
                dedup_check = getattr(consumer, "has_recent_completed", None)
                topic_id = ""
                for _t in topics:
                    _tid = str(_t or "").strip()
                    if not _tid:
                        continue
                    _rc = f"world_visual:{_tid}"
                    if callable(dedup_check):
                        try:
                            if dedup_check(_rc, dedup_sec):
                                logger.info(
                                    "[WorldImage] skip duplicate visual topic=%s published within %ss",
                                    _tid, int(dedup_sec),
                                )
                                continue
                        except Exception:
                            logger.debug("proactive photo topic dedup check failed", exc_info=True)
                    topic_id = _tid
                    break
                if not topic_id:
                    continue
                reason_code = f"world_visual:{topic_id}" if topic_id else ""

                # ── 行动：发布图片候选，交由消费者审批/生成/派发 ──
                channel = "qq" if getattr(self.qq, "is_logged_in", False) else "local_chat"
                # P2：按素材类型决断模板——活动时刻话题（看书/咖啡等）→ 人物自拍
                # 入镜（role_in_scene），物件/环境话题 → 第一人称环境照（environment_object）。
                prompt_key = _prompt_key_for_visual_topic(topic_id)
                publish_result = await self.publish_image_candidate({
                    "candidate_id": f"proactive-visual-{int(now_ts)}",
                    "idempotency_key": f"proactive-visual:{int(now_ts)}",
                    "scene": intent,
                    "owner_id": master_id,
                    "channel": channel,
                    "target": master_id,
                    "prompt_key": prompt_key,
                    "reason_code": reason_code,
                    "source": "generated",
                    "score": round(float(chosen.score), 2),
                    "size": _image_size_for_prompt_key(prompt_key),
                    # 角色级隔离：图片归属当前激活角色，投递端按此写 chat_log persona_id
                    "persona_id": self._active_persona_id(),
                })
                publish_result = publish_result if isinstance(publish_result, dict) else {}
                # 发布动作即记录节奏（无论结果，避免失败后立刻重试刷屏）。
                last_publish_ts = now_ts
                recent_intents.append(intent)
                recent_intents = recent_intents[-4:]
                logger.info(
                    "[WorldImage] proactive visual candidate published intent=%s topic=%s score=%s",
                    intent, topic_id, chosen.score,
                )
                # 记录成一条图片工具调用（tool_call_log + 关联最近一条 trace 补写 tools），
                # 让大脑中枢能看到"主动发图也调用了图片工具"。
                self._record_proactive_photo_tool(
                    master_id, intent, topic_id, channel, publish_result,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("proactive photo loop tick failed", exc_info=True)

    def _record_proactive_photo_tool(
        self,
        master_id: str,
        intent: str,
        topic_id: str,
        channel: str,
        publish_result: dict,
    ) -> None:
        """把一次主动发图建模成图片工具记录：写 tool_call_log + 关联最近 trace 补写。

        主动发图没有对应的用户消息上下文（无 trace 直接可用），按决策点 (a)
        关联最近一条该用户的活跃 trace 补写 tools 阶段，让大脑中枢能看到
        "主动发图也调用了图片工具（proactive_photo）"。
        """
        success = publish_result.get("status") in (
            "ok", "success", "sent", "delivered", "published", "dispatched",
        ) or bool(publish_result.get("consumed"))
        image_path = (
            publish_result.get("image_path") or publish_result.get("file_path")
            or publish_result.get("url") or publish_result.get("path") or ""
        )
        tool_entry = {
            "name": "proactive_photo",
            "success": bool(success),
            "duration_ms": int(publish_result.get("duration_ms") or 0),
            "arguments": {
                "intent": intent,
                "topic": topic_id,
                "channel": channel,
                "target": master_id,
                "prompt": str(getattr(self, "_last_image_prompt", "") or "")[:800],
            },
            "result": {
                "status": publish_result.get("status"),
                "image_path": str(image_path),
                "reason_code": f"world_visual:{topic_id}" if topic_id else "",
            },
        }
        # 1) tool_call_log（owner 归到 master_id 名下）
        try:
            self.db.insert("tool_call_log", {
                "ts": int(time.time() * 1000),
                "user_id": master_id,
                "tool_name": tool_entry["name"],
                "arguments": json.dumps(tool_entry["arguments"], ensure_ascii=False),
                "result": json.dumps(tool_entry["result"], ensure_ascii=False)[:2000],
                "success": 1 if success else 0,
                "duration_ms": tool_entry["duration_ms"],
                "cognition_id": 0,
            })
        except Exception:
            logger.exception("proactive photo tool_call_log insert error")
        # 2) 关联最近一条活跃 trace 补写 tools 阶段
        try:
            recent = self.cognition.recent(user_id=master_id, limit=1)
            if not recent:
                return
            latest_id = recent[0].get("id")
            if latest_id:
                self.cognition.patch_tools(latest_id, [tool_entry])
        except Exception:
            logger.debug("proactive photo trace patch failed", exc_info=True)

    async def _persist_image_event(
        self,
        user_id: int,
        desc: str,
        channel: str,
        image_path: str = "",
        persona_id: str | None = None,
    ) -> None:
        """P3 发图自我认知：把一次发图落成 EVENT 类型长期记忆，供后续对话召回。

        写入约定（审计 H2/M2）：
        - importance≥7.0 落 long_term 层——_recall_event_memories 只查 long_term；
        - metadata 必写 occurred_at（ISO 时间）——召回按它降序过滤；
        - content 只存中文描述 + 相对路径，不存完整 URL（防泄漏 + 避免无效链接刷屏）。
        失败仅降级为 debug（发图链路不因落账失败而中断）。
        角色级隔离：persona_id 与 chat_log 归属一致（缺省取当前激活角色）。
        """
        layered = getattr(self, "_layered_memory", None)
        if layered is None:
            return
        from memory.layers.base import MemoryType

        desc = str(desc or "").strip()
        if not desc:
            return
        try:
            await layered.store(
                user_id=int(user_id),
                content=f"我发了一张照片：{desc}"[:200],
                memory_type=MemoryType.EVENT,
                importance=7.0,
                metadata={
                    "occurred_at": datetime.now(LOCAL_TZ).isoformat(),
                    "channel": str(channel or ""),
                    "image_path": str(image_path or ""),
                },
                persona_id=persona_id or self._active_persona_id(),
            )
        except Exception:
            logger.debug("image event memory store failed", exc_info=True)

    async def _semantic_photo_spec(self, user_raw: str) -> dict[str, str] | None:
        """轻量 LLM 语义自补：从用户指令推断画面维度 focus/pose/angle/scene/style。

        关键词表只能命中显式词语（"看看腿"能命中 focus=双腿，但推断不出"坐着/腿部
        特写"这类隐含语义）。这里用 siliconflow-light 做语义分析，返回与
        _extract_photo_spec 同构的 dict；任意失败（无 brain / 超时 / 输出不可解析 /
        全空）都返回 None，由调用方回退到关键词保底——语义自补是锦上添花，绝不因它中断生图。
        """
        raw = str(user_raw or "").strip()
        if not raw:
            return None
        brain = getattr(self, "brain", None)
        chat = getattr(brain, "chat", None)
        if not callable(chat):
            return None
        system = (
            "你是摄影构图分析器。用户给了一句给恋人的拍照指令（例如'看看腿''在床上躺着拍一张'），"
            "你要理解其隐含语义，把它拆成一张写实生活照的画面规格。\n"
            "输出必须是合法 JSON 对象，键固定为 focus/pose/angle/scene/style/orientation/shot，值用中文或空字符串：\n"
            '{"focus":"双腿","pose":"坐","angle":"特写","scene":"床上","style":"慵懒","orientation":"竖","shot":"特写"}\n'
            "各键含义与合法取值：\n"
            "- focus（画面主体特写）：双腿/双脚/手/腰/肩颈锁骨/背影/头发/脸庞/眼睛/全身，"
            "可细分到单个部位：脚踝/足背/脚趾/小腿/大腿/膝盖/手指/手腕/掌心/锁骨/脖颈/腰肢/耳廓/嘴唇\n"
            "- pose（人物姿态）：侧躺/平躺/坐/倚靠/跪坐/站立/蹲下/盘腿/跷腿\n"
            "- angle（拍摄机位）：仰视低角度/俯视高角度/平视/第一人称/特写/全身入镜\n"
            "- scene（场景）：床上/沙发/浴室/厨房/窗前/阳台/工作室/玄关\n"
            "- style（氛围）：诱惑感/慵懒/清新/居家感/氛围感\n"
            "- orientation（画面方向）：竖/横/方，仅当事物明确暗示横/方构图时填，默认竖\n"
            "- shot（景别·镜头语言）：远景/中景/近景/特写/大特写。特写景别使用率最高，默认倾向特写；focus 为局部特写时取特写/大特写\n"
            "推断规则：\n"
            "1. 指令提到身体部位，focus 填最具体的部位（能细化就细化到 脚踝/大腿/手指 等单部位，不只给大类）。\n"
            "2. 若语义暗示了姿态/机位但未明说，自行补全最合理的（如'看看腿'→pose=坐，angle=特写）。\n"
            "3. 提到环境填 scene，提到情绪/氛围填 style，明确暗示横/方构图才填 orientation。\n"
            "4. 无法确定的键留空字符串，不要编造。只输出 JSON，不要任何额外文字；不要出现任何人的名字（如'伊塔'）。\n"
            "硬性前提：这张照片由画中的女性本人手持手机拍摄的自拍（前置自拍/后置对镜/支架定时），"
            "所有机位都是她自己的取景，不存在摄影师/他人拍摄。angle 只表达她从哪个方位/距离拍自己。"
        )
        try:
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": f"指令：{raw[:120]}"},
            ]
            call = chat(messages, preferred_provider=_IMAGE_LIGHT_PROVIDER, temperature=0.2)
            resp = await asyncio.wait_for(call, timeout=_IMAGE_LIGHT_RELAY_TIMEOUT)
            obj = _extract_llm_json(getattr(resp, "text", "") or "")
            if not obj:
                return None
            spec = {
                "focus": _normalize_spec_value(obj.get("focus"), _PHOTO_FOCUS_FULL_TABLE),
                "pose": _normalize_spec_value(obj.get("pose"), _PHOTO_POSE_TABLE),
                "angle": _normalize_spec_value(obj.get("angle"), _PHOTO_ANGLE_TABLE),
                "scene": _normalize_spec_value(obj.get("scene"), _PHOTO_SCENE_TABLE),
                "style": _normalize_spec_value(obj.get("style"), _PHOTO_STYLE_TABLE),
                "orientation": _normalize_spec_value(obj.get("orientation"), _PHOTO_ORIENTATION_TABLE),
                "shot": _normalize_spec_value(obj.get("shot"), _PHOTO_SHOT_TABLE),
            }
            if not any(spec.values()):
                return None
            return spec
        except Exception:
            logger.debug("semantic photo spec failed; fallback to keyword", exc_info=True)
            return None

    async def _image_prompt_for(self, prompt_key: str, candidate: dict[str, Any] | None = None) -> str:
        """提示词统一出口：每次生图提示词都写 INFO 日志，并缓存到 _last_image_prompt，供 trace 可见。"""
        prompt = await self._image_prompt_for_impl(prompt_key, candidate)
        try:
            self._last_image_prompt = str(prompt or "")
            logger.info(
                "[WorldPrompt] key=%s candidate=%s chars=%d prompt=%r",
                str(prompt_key or "default"),
                str((candidate or {}).get("candidate_id") or ""),
                len(self._last_image_prompt),
                self._last_image_prompt,
            )
        except Exception:
            logger.debug("world image prompt logging failed", exc_info=True)
        return prompt

    async def _image_prompt_for_impl(self, prompt_key: str, candidate: dict[str, Any] | None = None) -> str:
        """把 ImageCandidate 的 prompt_key 解析成真实的中文生图提示词。

        两步接力：
        1. ``_compose_base_image_prompt`` 用 persona.yaml 外貌/身材 + 场景拼出基础提示词；
           用户主动要图时，语义自补（siliconflow-light）优先解析指令，失败回退关键词；
        2. 世界数据接力：取当前 WorldSnapshot 的时间/天气/地点/物件，交给轻量 LLM
           （siliconflow-light）判断这张画面真正需要哪些数据——只把能呈现在画面里的
           写进提示词，而不是把世界快照全部揉在一起。轻量 LLM 不可用时退回确定性规则
           （按场景选择性注入时间光线/天气）。

        健壮性：世界数据/轻量 LLM 接力是"锦上添花"，任何异常都必须退回基础提示词，
        绝不把异常冒泡成空串——否则 generate_image 会因 empty_prompt 拒绝，生图直接放弃。
        """
        # P4 模块化提示词：spec 提前完整解析（语义优先 → 关键词保底），
        # 让 base 构造器能感知 focus 并分支——局部特写走精简 base，
        # 全身/非特写保留完整人设。旧实现只做了语义优先，失败后未在这里兜底，
        # 导致 base 构造阶段拿不到 focus。
        spec: dict[str, str] | None = None
        if (candidate or {}).get("scene") == "local_send":
            user_raw = str((candidate or {}).get("user_raw") or "").strip()
            if user_raw:
                spec = await self._semantic_photo_spec(user_raw)
                if not spec:
                    spec = _extract_photo_spec(user_raw)
        # orientation（第 2 条）：语义自补产出方向时，回填 candidate.size 为三档之一，
        # 让下游 base 构图方向、workflow metadata、图生图尺寸统一用同一方向。
        if spec and isinstance(candidate, dict) and str(spec.get("orientation") or "").strip():
            try:
                candidate["size"] = _image_orientation_for_size(spec["orientation"])
            except Exception:
                logger.debug("orientation size reflow failed", exc_info=True)
        base = self._compose_base_image_prompt(prompt_key, candidate, spec=spec)
        try:
            context = self._image_world_context(candidate)
            if not context:
                return _ensure_selfie_pov(base, prompt_key)
            refined = await self._light_relay_refine_prompt(base, context, candidate)
            if refined:
                return _ensure_selfie_pov(refined, prompt_key)
            return _ensure_selfie_pov(
                self._inject_world_context_fallback(base, context, candidate),
                prompt_key,
            )
        except Exception:
            # 世界数据接力失败不影响生图：退回基础提示词（base 恒非空）。
            # warning 而非 debug：历史空提示词问题曾因 debug 级吞错无法事后复盘，
            # 这里必须让异常体落盘，便于下次出现时直接定位。
            logger.warning(
                "world image context relay failed; falling back to base prompt (key=%s)",
                prompt_key, exc_info=True,
            )
            return _ensure_selfie_pov(base, prompt_key)

    def _compose_base_image_prompt(self, prompt_key: str, candidate: dict[str, Any] | None = None, spec: dict[str, str] | None = None) -> str:
        """基础提示词：persona 外貌/身材 + 场景构图（不含世界上下文）。"""
        try:
            from config.persona_loader import load_persona
            persona = load_persona() or {}
            wrapped = persona.get("persona") if isinstance(persona, dict) else None
            root = wrapped if isinstance(wrapped, dict) else persona
            appearance = root.get("appearance") or {}
            profile = root.get("profile") or {}
        except Exception:
            appearance, profile = {}, {}
        key = str(prompt_key or "default")
        # 构图方向：优先用候选自带 size（发布时已由伊塔按场景决断），
        # 否则按 prompt_key 场景映射 16:9 / 9:16。横竖屏由伊塔自决。
        image_size = str((candidate or {}).get("size") or "").strip() or _image_size_for_prompt_key(key)
        orientation = _image_orientation_phrase(image_size)
        # ── P4 局部特写分支 ──
        # 用户明确要看某个部位（手/腿/脚/腰/肩颈/背影/头发/脸/眼睛）时，
        # base 只写「人物外貌以参考图为准」，不写身高/体重/体脂率/杯数/三围/
        # 发色/眼色等无关标签。由 three_view 图生图 + 参考图锁人物一致性，
        # 文字层只描述对应部位的构图/姿态/机位。
        focus = str((spec or {}).get("focus") or "").strip()
        if focus and focus in _CLOSEUP_FOCUS_SET:
            base = (
                "一张写实照片，人物外貌以参考图为准。"
                "画面风格自然、生活化、暖色调、真实摄影质感，"
                "不要动漫风，不要文字水印。"
            )
            full = f"{base}{orientation}。"
            full = f"{full}{_SELFIE_POV_PHRASE}"
            # 局部特写的 modular 叠加（focus/pose/angle/scene/style），
            # _compose_modular_prompt 会统一追加 "画面重点聚焦在{focus}，其余虚化"。
            if (candidate or {}).get("scene") == "local_send" and spec:
                full = _compose_modular_prompt(full, spec)
            else:
                # 非 local_send 兜底：手动追加 focus，避免漏掉构图主轴。
                full = f"{full}画面重点聚焦在{focus}，其余虚化。"
            return full
        # ── 全身 / focus 为空 / 主动发图：完整人设 ──
        height = profile.get("height_cm", 184)
        body = str(profile.get("body_type", "身材修长") or "身材修长")
        hair = str(appearance.get("hair", "银灰色长发") or "银灰色长发")
        eyes = str(appearance.get("eyes", "深灰蓝色眼睛") or "深灰蓝色眼睛")
        skin = str(appearance.get("skin", "健康肤色") or "健康肤色")
        # 三维数据：与 persona.yaml profile.measurements / weight_kg /
        # body_fat_pct / cup_size 保持一致，随每次生图一并传给中转站，
        # 避免"身材数据对不上"的失真问题。
        measurements = str(profile.get("measurements", "") or "").strip()
        weight_kg = str(profile.get("weight_kg", "") or "").strip()
        body_fat_pct = str(profile.get("body_fat_pct", "") or "").strip()
        cup_size = str(profile.get("cup_size", "") or "").strip()
        base = (
            "一张写实生活照，人物是一位28岁的中国女性独立设计师。"
            f"身高{height}cm，{body}，{skin}。{hair}，{eyes}。"
        )
        body_data_parts = []
        if measurements:
            body_data_parts.append(f"三围{measurements}")
        if cup_size:
            body_data_parts.append(f"{cup_size}杯")
        if weight_kg:
            body_data_parts.append(f"体重{weight_kg}kg")
        if body_fat_pct:
            body_data_parts.append(f"体脂率{body_fat_pct}%")
        if body_data_parts:
            base += "身体数据：" + "，".join(body_data_parts) + "。"
        base += (
            "五官清冷精致，气质温柔的大姐姐。画面风格自然、生活化、暖色调、真实摄影质感，"
            "不要动漫风，不要文字水印。"
        )
        if key == "environment_object":
            # 环境/物件照：第一人称"她拍下的视角"，不强制带人物形象。
            # topic 可能来自世界模拟的公寓物件 ID 或重庆 POI（reason_code: world_visual:<topic>）。
            topic = str((candidate or {}).get("reason_code") or "")
            if topic.startswith("world_visual:"):
                topic = topic.split("world_visual:", 1)[1].replace("object_", "").strip()
            else:
                topic = ""
            if topic:
                # P2：统一走 _visual_topic_zh 翻译（活动时刻话题 + 物件话题全覆盖），
                # 杜绝英文 token（如 reading_time）直接进生图提示词。
                translated = _visual_topic_zh(topic)
                return (
                    f"一张写实照片，第一人称视角，{orientation}，她在重庆的家/窗边随手拍下眼前的一角：{translated}。"
                    "画面自然、生活化、暖色调、真实摄影质感，微微的随手感，"
                    "不要动漫风，不要文字水印。"
                )
            return (
                f"一张写实照片，第一人称视角，{orientation}，她在重庆的复式公寓里，窗前/工作室一角。"
                "画面自然、生活化、暖色调、真实摄影质感，不要动漫风，不要文字水印。"
            )
        if key == "role_selfie":
            scene = "她穿着宽松的家居T恤坐在工作室书桌前，左手托腮，微微带笑直视镜头，像在给恋人发自拍，桌面有数位板和设计稿。"
        elif key == "role_in_scene":
            # POV 约束：自拍视角，画面里能看出是她本人手持手机拍下的这一刻，
            # 绝不能用"侧身望向镜头"这种第三方拍摄摆姿（那暗示存在一个拍摄者）。
            # P2 参数化：候选带活动时刻话题（reading_time 等）时，用话题中文描述
            # 替换固定场景，让"看书/咖啡/傍晚"这类人物时刻真正进画面。
            topic = str((candidate or {}).get("reason_code") or "")
            if topic.startswith("world_visual:"):
                topic = topic.split("world_visual:", 1)[1].strip()
            else:
                topic = ""
            topic_zh = _visual_topic_zh(topic) if topic else ""
            if topic_zh and topic_zh != topic:
                scene = (
                    f"{topic_zh}，她举着手机前置摄像头对着自己，嘴角带笑，"
                    "像刚拍下这一刻随手发给你，身后是她重庆的家。"
                )
            else:
                scene = "她举着手机前置摄像头对着自己，嘴角带笑，像刚拍下这一刻随手发给你，身后是重庆高层复式公寓落地窗。"
        elif key == "couple_photo":
            scene = "她与恋人的温馨自拍合影，她手持手机举在两人面前前置自拍，她微微低头看着对方，眼神温柔带占有欲，背景是暖色灯光下的客厅沙发。"
        else:
            scene = "她坐在重庆的家里，窗外是夜景，她手持手机前置摄像头对着自己，神情放松地看着镜头。"
        full = f"{base}{scene}{orientation}。"
        # POV 硬约束：所有人物类（非环境照）在基础提示词阶段就追加手持自拍前提，
        # 即便后续世界接力/模块化组合器未显式携带，也保证"她本人手持拍摄"成立。
        full = f"{full}{_SELFIE_POV_PHRASE}"
        # 用户主动要图（scene=local_send）时，candidate 带 user_raw 原始指令，
        # 用模块化组合器把主体/姿态/机位/场景/风格叠加上去。spec 来源：
        #   1) 语义自补优先（_semantic_photo_spec 已解析，命中任一维度）；
        #   2) 未命中/失败时回落 _extract_photo_spec 关键词保底。
        # 全部未命中时 _compose_modular_prompt 原样返回 full，绝不产生空串（缺值即停防护）。
        if (candidate or {}).get("scene") == "local_send":
            user_raw = str((candidate or {}).get("user_raw") or "").strip()
            if user_raw:
                if not spec:
                    spec = _extract_photo_spec(user_raw)
                full = _compose_modular_prompt(full, spec)
        return full

    def _image_world_context(self, candidate: dict[str, Any] | None = None) -> dict[str, Any]:
        """提取生图可用的世界上下文，只保留真实存在的数据。

        时间优先取 WorldSnapshot（world 的时间），world 关闭/快照不可用时退回
        候选事件时间或本地当前时间；天气/地点/物件只在 world 有真实数据时才进入。
        """
        snapshot = self._world_snapshot_for_context()
        if isinstance(snapshot, dict) and snapshot:
            phase = str(snapshot.get("phase") or "")
            iso_time = str(snapshot.get("iso_time") or snapshot.get("created_at") or "")
            weather_mood = str(snapshot.get("weather_mood") or snapshot.get("weather") or "").strip()
            weather_detail = str(snapshot.get("weather_detail") or "").strip()
            city = str(snapshot.get("city") or "").strip()
            location = str(snapshot.get("location") or "home")
            activity = str(snapshot.get("activity") or "idle")
            # 房间级细粒度定位（方向5）：floor/zone/position_desc 来自世界快照，
            # 缺省时用 home_space 按 phase 兜底，保证生图上下文永远带得上"在哪层哪区"。
            floor = snapshot.get("floor")
            zone = str(snapshot.get("zone") or "")
            position_desc = str(snapshot.get("position_desc") or "")
            if not zone or not position_desc:
                try:
                    from core.home_space import position_desc as hs_pos, zone_for_phase
                    zone = zone or zone_for_phase(phase)
                    position_desc = position_desc or hs_pos(floor, zone)
                except Exception:
                    pass
            nearby_objects = [str(x) for x in (snapshot.get("nearby_objects") or []) if str(x)]
            visual_topics = [str(x) for x in (snapshot.get("available_visual_topics") or []) if str(x)]
            city_events = [e for e in (snapshot.get("city_events") or []) if isinstance(e, dict) and e.get("title")]
        else:
            phase = iso_time = weather_mood = weather_detail = city = location = activity = ""
            floor = zone = position_desc = ""
            nearby_objects = visual_topics = city_events = []

        # 时间兜底：候选事件时间 → 本地当前时间；时段缺省时按小时映射。
        clock_dt = None
        for raw in (iso_time, (candidate or {}).get("created_at"), (candidate or {}).get("occurred_at")):
            if not raw:
                continue
            try:
                clock_dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                break
            except Exception:
                continue
        # 统一归一为本地时区：iso_time 已是 +08:00，而 candidate.created_at 是 UTC(+00:00)，
        # 混用会让时段/光线提示词错位。aware 用 astimezone 换算，naive 直接标注本地时区。
        if clock_dt is None:
            clock_dt = datetime.now(LOCAL_TZ)
        elif clock_dt.tzinfo is not None:
            clock_dt = clock_dt.astimezone(LOCAL_TZ)
        else:
            clock_dt = clock_dt.replace(tzinfo=LOCAL_TZ)
        if not phase:
            phase = _time_of_day_phase(clock_dt)
        clock_str = clock_dt.strftime("%H:%M")

        weather_cn = _WEATHER_MOOD_CN.get(weather_mood, "")
        weather_desc = weather_detail
        if not weather_desc:
            if city and weather_cn:
                weather_desc = f"现在{city}{weather_cn}"
            elif weather_cn:
                weather_desc = f"现在天气{weather_cn}"

        # 细粒度时间/光线：以精确太阳位置（海拔高度、方位角）为确定性基准，
        # 产出"太阳刚出/鱼肚白/太阳高度约X度/日落余晖"等逐日差异描述，
        # 替代粗粒度的按小时查表。月相用本地朔望月计算（无网络、瞬时、缓存）。
        prompt_key = str((candidate or {}).get("prompt_key") or "default")
        fine = solar_time.fine_time_descriptor(clock_dt, prompt_key)
        time_cn = str(fine.get("time_cn") or "").strip()
        light_cn = str(fine.get("light_cn") or "").strip()
        moon = moon_phase(clock_dt)
        moon_desc = f"月相{moon['emoji']}{moon['phase_name']}，亮度{moon['illumination_pct']}%"
        # 天黑了或傍晚，月亮才真正进得了画面，才并进时间光线描述。
        if phase in ("night", "evening", "late_evening"):
            combined_light = "，".join(p for p in (time_cn, light_cn, moon_desc) if p)
        else:
            combined_light = "，".join(p for p in (time_cn, light_cn) if p)

        context = {
            "prompt_key": prompt_key,
            "scene": str((candidate or {}).get("scene") or ""),
            "time_of_day": phase,
            "clock": clock_str,
            "time_of_day_light": combined_light,      # 确定性基准（细粒度），下游/兜底直接可用
            "time_cn": time_cn,                       # 精细时段 + 太阳高度
            "light_cn": light_cn,                     # 房间光线 + 窗外（结合公寓朝向）
            "moon_desc": moon_desc,                   # 月相（夜/傍晚并入 combined）
            "sun_altitude_deg": str(fine.get("sun_altitude_deg") or ""),
            "sunrise": str(fine.get("sunrise") or ""),
            "sunset": str(fine.get("sunset") or ""),
            "weather_desc": weather_desc,
            "city": city,
            "location": location,
            "floor": floor,
            "zone": zone,
            "position_desc": position_desc,
            "outdoor": bool(snapshot.get("outdoor")) if isinstance(snapshot, dict) else False,
            "outdoor_place": str(snapshot.get("outdoor_place") or "") if isinstance(snapshot, dict) else "",
            "holiday": holiday_name(clock_dt.date()),
            "activity": activity,
            "nearby_objects": nearby_objects[:6],
            "visual_topics": visual_topics[:6],
            "city_events": city_events[:3],
        }
        if not (context["time_of_day_light"] or context["weather_desc"] or city or nearby_objects or visual_topics or city_events):
            return {}
        return context

    def _world_context_text(self, context: dict[str, Any]) -> str:
        """把世界上下文转成可读文本，供轻量 LLM 接力判断。"""
        phase = str(context.get("time_of_day") or "")
        clock = str(context.get("clock") or "")
        time_cn = str(context.get("time_cn") or "").strip()
        light_cn = str(context.get("light_cn") or "").strip()
        time_light = str(context.get("time_of_day_light") or "").strip()
        weather_desc = str(context.get("weather_desc") or "").strip()
        city = str(context.get("city") or "").strip()
        location = str(context.get("location") or "").strip()
        activity = str(context.get("activity") or "").strip()
        nearby = [str(x) for x in (context.get("nearby_objects") or [])]
        topics = [str(x) for x in (context.get("visual_topics") or [])]
        events = [str(e.get("title")) for e in (context.get("city_events") or []) if isinstance(e, dict) and e.get("title")]

        lines = []
        if time_cn or light_cn:
            detail = "。".join(p for p in (time_cn, light_cn) if p)
            lines.append(f"时间光线：{detail}")
        elif phase:
            phase_cn = _TIME_OF_DAY_CN.get(phase, phase)
            lines.append(f"时间：{phase_cn}（{clock}）。{time_light}" if time_light else f"时间：{phase_cn}（{clock}）。")
        if phase in ("night", "evening", "late_evening") and context.get("moon_desc"):
            lines.append(f"天象：{context.get('moon_desc')}")
        if weather_desc:
            lines.append(f"天气：{weather_desc}")
        holi = str(context.get("holiday") or "").strip()
        if holi:
            lines.append(f"特殊日子：今天是{holi}。")
        place_parts = []
        # 优先用细粒度位置描述（"二层·工作室"），缺省退回 location 兼容层。
        position_desc = str(context.get("position_desc") or "").strip()
        if position_desc:
            place_parts.append(f"她现在在{position_desc}")
        elif location:
            place_parts.append(f"她现在在{location}")
        if city:
            place_parts.append(city)
        if place_parts:
            lines.append("地点：" + "，".join(place_parts))
        # 室外状态（白天出门）：明确告知不是在家里，供轻量 LLM 接力正确表达画面。
        if context.get("outdoor"):
            place_x = str(context.get("outdoor_place") or "").strip()
            lines.append("状态：她此刻在室外" + (f"（{place_x}）" if place_x else "") + "，不在家里。")
        if activity and activity != "idle":
            lines.append(f"她此刻在：{activity}")
        if nearby:
            # 物件 id 翻译成自然描述再进上下文（环境/物件话题走 _visual_topic_zh）。
            lines.append("房间/周围可见物件：" + "、".join(_visual_topic_zh(o) for o in nearby))
        if topics:
            # P2：可拍主题统一翻译后拼接，杜绝英文 token（reading_time 等）经
            # 轻量 LLM 接力路径泄漏进最终提示词。
            lines.append("可拍的画面主题：" + "、".join(_visual_topic_zh(t) for t in topics))
        if events:
            lines.append("城市动态：" + "；".join(events))
        return "\n".join(lines) or "（暂无世界数据）"

    async def _light_relay_refine_prompt(
        self,
        base_prompt: str,
        context: dict[str, Any],
        candidate: dict[str, Any] | None = None,
    ) -> str | None:
        """轻量 LLM 接力：判断这张画面需要哪些世界数据，只注入能呈现在画面里的。

        轻量模型（siliconflow-light）只做提示词挑选/润色，不负责生图；失败、
        超时或输出异常时返回 None，由调用方退回确定性规则，绝不阻塞生图管线。
        """
        brain = getattr(self, "brain", None)
        chat = getattr(brain, "chat", None)
        if not callable(chat):
            return None
        context_text = self._world_context_text(context)
        if not context_text or context_text == "（暂无世界数据）":
            return None
        key = str(context.get("prompt_key") or (candidate or {}).get("prompt_key") or "default")
        system_msg = (
            "你是一名专业的图像提示词优化助手。用户提供一条基础生图提示词"
            "（一位女性的生活照/场景照，人物外貌、身材与画面风格已确定），"
            "以及一组可选的世界背景数据（时间、天气、地点、物件、城市动态）。\n"
            "你的任务：\n"
            "1. 判断哪些背景数据对这张照片的画面有实际影响，只把真正能呈现在画面里的写进提示词；\n"
            "2. 无关的数据不要写（例如室内自拍通常不需要天气、白天照片不要深夜光线），不要堆叠所有数据；\n"
            "3. 保留基础提示词里的人物外貌、身材、风格与构图信息，只做上下文增强；\n"
            "4. 只用中文输出一条完整、自然、连贯的生图提示词本身，不要解释，不要JSON，不要加引号；\n"
            "5. 不要写任何人的名字或称呼（如'伊塔/Ita'），画面人物一律用'这个女性''她'等中性表述描述。\n"
            "硬性前提：这张照片由画中的女性本人手持手机拍摄（前置自拍/后置对镜/支架定时），"
            "必须保持这个自拍视角；绝对禁止出现拍摄者、第三人称旁观视角、摄影师、路人等"
            "任何暗示'别人在拍她'的表述。"
        )
        user_msg = (
            f"【基础提示词】\n{base_prompt}\n\n"
            f"【可选世界背景数据】\n{context_text}\n\n"
            f"请判断画面需要哪些数据，输出增强后的完整生图提示词。"
        )
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]
        try:
            call = chat(messages, preferred_provider=_IMAGE_LIGHT_PROVIDER, temperature=0.7)
            resp = await asyncio.wait_for(call, timeout=_IMAGE_LIGHT_RELAY_TIMEOUT)
            text = (resp.text or "").strip().strip('"').strip("'")
            if 30 <= len(text) <= 4000 and ("写实" in text or "照片" in text):
                # POV 黑名单：LLM 输出若引入"第三方拍摄"视角，拒绝采用，回退确定性兜底。
                if any(kw in text for kw in _POV_THIRD_PARTY_BLACKLIST):
                    logger.debug(
                        "world image prompt light relay rejected (POV blacklist hit) key=%s",
                        key,
                    )
                    return None
                logger.debug("world image prompt refined by light relay (key=%s)", key)
                return text
        except Exception:
            logger.debug("world image prompt light relay failed; fallback to deterministic prompt", exc_info=True)
        return None

    def _inject_world_context_fallback(self, base_prompt: str, context: dict[str, Any], candidate: dict[str, Any] | None = None) -> str:
        """确定性兜底：按场景规则只注入该画面相关的世界数据。

        光线（时间/相/月相）恒注入；房间物件（room）条件注入——仅当存在 nearby_objects
        时，把物件翻译成自然描述拼进画面，空则跳过（缺值即停防护，绝不断生图）。
        """
        key = str((candidate or {}).get("prompt_key") or context.get("prompt_key") or "default")
        need = _IMAGE_WORLD_FALLBACK_RULES.get(key, {"light", "weather"})
        time_light = str(context.get("time_of_day_light") or "").strip()
        weather_desc = str(context.get("weather_desc") or "").strip()
        room_objs = [str(x) for x in (context.get("nearby_objects") or []) if str(x)]
        parts = []
        if "light" in need and time_light:
            parts.append(time_light)
        if "room" in need and room_objs:
            cn = "、".join(_HER_HOME_OBJECTS_ZH.get(o, o) for o in room_objs)
            if cn:
                # 室外时是"她身边的地点"，不是房间物件（避免"身在室外却说在房间里"）。
                if context.get("outdoor"):
                    parts.append(f"她身边是：{cn}")
                else:
                    parts.append(f"所在的房间里有：{cn}")
        if "weather" in need and weather_desc:
            parts.append(weather_desc)
        if not parts:
            return base_prompt
        detail = "，".join(parts)
        return f"{base_prompt}画面氛围：{detail}。"

    async def _emotion_tick_loop(self) -> None:
        """R7.5+: background tick loop for emotion dashboard liveness.

        Three independent cadences on a shared 1-second base tick:

        * **PAD (3 s)** — runs ``idle_tick()`` so P/A/D drift via EMA +
          noise. Matches the dashboard's 3 s poll so the flow bars
          (dP/dt, dA/dt, dD/dt) show a non-zero derivative on most
          fetches.
        * **Threshold (30 s)** — runs ``tick_decay(30)`` so each slot
          loses ``decay_per_day / 2880`` per call. Integrated over 24 h
          this equals ``decay_per_day`` (the configured daily rate);
          the 30 s spacing keeps the user-perceived "speed of decay"
          calm instead of the previous every-10-s collapse.
        * **Snapshot (60 s)** — writes an ``idle_tick`` snapshot so the
          24h / 7d / 30d curves keep filling in even with zero user
          traffic.

        All errors are swallowed — this is decorative, never fatal.
        """
        pad_ticks = 0
        thr_ticks = 0
        snap_ticks = 0
        try:
            while True:
                await asyncio.sleep(1)
                pad_ticks += 1
                thr_ticks += 1
                snap_ticks += 1
                try:
                    primary = self.get_primary_identity()
                    if not primary:
                        continue
                    master_id, identity = primary
                    if pad_ticks >= 3:
                        pad_ticks = 0
                        self.emotion.idle_tick(
                            actor_id=identity.actor_id,
                        )
                        self._emotion_last_sampled_at = int(time.time() * 1000)
                    if thr_ticks >= 30:
                        thr_ticks = 0
                        self.emotion.tick_decay(
                            30.0,
                            actor_id=identity.actor_id,
                        )
                except Exception as e:
                    logger.debug("emotion tick error: %s", e)
                if snap_ticks >= 60:
                    snap_ticks = 0
                    try:
                        st = self.get_primary_emotion_state()
                        if not st:
                            continue
                        self.state_store.snapshot(
                            master_id,
                            {"label": st.get("label"), "pad": st.get("pad")},
                            st.get("thresholds", {}),
                            trigger_event="idle_tick",
                            actor_id=identity.actor_id,
                        )
                    except Exception as e:
                        logger.debug("emotion snapshot error: %s", e)
        except asyncio.CancelledError:
            return

    def _mark_user_active(self) -> None:
        """统一沉寂时钟：mark companion_state（30s 节流落盘防高频写）。"""
        cs = getattr(self, "companion_state", None)
        if cs is None:
            return
        try:
            cs.mark_user_active()
            now = time.time()
            if now - getattr(self, "_last_activity_save", 0.0) >= 30.0:
                cs.save()
                self._last_activity_save = now
        except Exception:
            logger.debug("companion_state mark_user_active failed", exc_info=True)

    def _topic_for_context(self) -> dict | None:
        """供 ContextBuilder L0.5 话题认知层查询当前活跃话题（事实注入）。"""
        tracker = getattr(self, "topic_tracker", None)
        if tracker is None:
            return None
        try:
            active = tracker.active_topic()
        except Exception:
            return None
        if active is None:
            return None
        return {"subject": active.subject, "turn_count": active.turn_count}

    async def _recent_dialogue_text(self, user_id: int, limit: int = 5) -> str:
        """取最近非主动消息对话文本（主动消息续接素材，失败返回空串）。

        角色级隔离：只取当前激活角色的对话，避免塞纳的推送拿伊塔的对话当素材。
        """
        try:
            persona = self._active_persona_id()
            if persona:
                rows = self.db.query(
                    "SELECT role, content FROM chat_log "
                    "WHERE user_id = ? AND msg_type != 'proactive' "
                    "AND (persona_id = ? OR persona_id IS NULL) "
                    "ORDER BY id DESC LIMIT ?",
                    (user_id, persona, int(limit)),
                )
            else:
                rows = self.db.query(
                    "SELECT role, content FROM chat_log "
                    "WHERE user_id = ? AND msg_type != 'proactive' "
                    "ORDER BY id DESC LIMIT ?",
                    (user_id, int(limit)),
                )
            rows = list(rows or [])
            rows.reverse()
            lines = []
            for row in rows:
                role = "伊塔" if str(row.get("role")) == "assistant" else "你"
                content = str(row.get("content", ""))
                if content:
                    lines.append(f"{role}：{content}")
            return "\n".join(lines)[:600]
        except Exception:
            logger.debug("[Push] recent dialogue unavailable", exc_info=True)
            return ""

    def _build_motive_candidates(
        self, scene_name: str, topic_mode: str, dialogue_context: str
    ) -> list[dict]:
        """确定性动机候选（决策日志证据；不调用 LLM）。"""
        candidates = [
            {"id": "scene", "topic": scene_name, "score": 0.2},
            {"id": "mode", "topic": topic_mode, "score": 0.5},
        ]
        if dialogue_context:
            candidates.append({"id": "context", "topic": dialogue_context[:60], "score": 0.3})
        else:
            candidates.append({"id": "context", "topic": "无历史话题", "score": 0.0})
        return candidates

    def _pulse_state_snapshot(self) -> dict:
        """PulsePlanner 每整点读取的状态快照（活跃/作息/情绪/欲望/预算）。"""
        state: dict[str, Any] = {}
        policy = getattr(getattr(self, "push_scheduler", None), "policy", None)
        # 用户活跃度与静默
        try:
            cs = getattr(self, "companion_state", None)
            if cs is not None and hasattr(cs, "idle_hours"):
                idle_h = float(cs.idle_hours() or 0.0)
                state["user_active"] = idle_h < 0.5
                state["hours_since_last_interaction"] = idle_h
        except Exception:
            pass
        # 静默时段 & 软预算余额
        if policy is not None:
            try:
                now_time = datetime.now().time()
                qs, qe = policy.quiet_start, policy.quiet_end
                if qs <= qe:
                    in_quiet = qs <= now_time <= qe
                else:
                    in_quiet = now_time >= qs or now_time <= qe
                state["is_quiet_now"] = in_quiet
                state["soft_remaining_today"] = max(
                    int(policy.soft_budget_target() - policy.daily_count), 0
                )
            except Exception:
                pass
        # 作息活跃窗口
        try:
            rw = getattr(self, "routine_learner", None)
            if rw is not None:
                win = rw.window()
                if win.enabled and win.wake_time and win.sleep_time:
                    now_s = datetime.now().time().hour * 3600 \
                        + datetime.now().time().minute * 60
                    wake_s = win.wake_time.hour * 3600 + win.wake_time.minute * 60
                    sleep_s = win.sleep_time.hour * 3600 + win.sleep_time.minute * 60
                    if wake_s < sleep_s:
                        state["in_active_window"] = wake_s <= now_s < sleep_s
                    else:
                        state["in_active_window"] = now_s >= wake_s or now_s < sleep_s
        except Exception:
            pass
        # 情绪需要度（P 低 / A 高 → need 高）
        try:
            est = self.get_primary_emotion_state()
            sp = est.get("pad") if isinstance(est, dict) else None
            if isinstance(sp, dict):
                p = float(sp.get("P", 0.0))
                a = float(sp.get("A", 0.0))
                need = max((1.0 - (p + 1.0) / 2.0), (a + 1.0) / 2.0)
                state["mood_need"] = max(0.0, min(1.0, (need - 0.5) + 0.5))
        except Exception:
            pass
        # desire 引擎分
        try:
            dstate = getattr(getattr(self, "desire", None), "get_state", None)
            if dstate is not None:
                state["desire"] = min(1.0, float(dstate().get("score") or 0.0) / 100.0)
        except Exception:
            pass
        return state

    def _proactive_world_fragment(self) -> str:
        """世界快照的一小段意象（≤60 字），注入主动消息作为环境底色。"""
        try:
            snap = self._world_snapshot_for_context(max_age_sec=120.0)
        except Exception:
            return ""
        if not isinstance(snap, dict):
            return ""
        parts: list[str] = []
        phase = str(snap.get("phase") or "")
        phase_cn = {
            "morning": "上午", "noon": "中午", "afternoon": "下午",
            "evening": "晚上", "night": "深夜",
        }.get(phase)
        if phase_cn:
            parts.append(phase_cn)
        location = str(snap.get("zone") or snap.get("location") or "")
        if location and location != "unknown":
            parts.append(f"你正待在{location}")
        pos = str(snap.get("position_desc") or "")
        if pos:
            parts.append(f"（{pos}）")
        activity = str(snap.get("activity") or "")
        if activity and activity != "idle":
            parts.append(f"，正{activity}")
        weather = snap.get("weather")
        if isinstance(weather, dict):
            wdesc = str(weather.get("desc") or "").strip()
            if wdesc:
                parts.append(f"，{wdesc}")
        frag = "".join(parts).strip()
        return frag[:60]

    def _memory_evoke_fragment(self, master_id: int) -> str:
        """低频旧事召回（规则预筛 + 分层记忆检索）。

        仅在 topic_mode == new 时由 _dispatch_push 调用。冷却 2 小时、当日 ≤2 次
        （内存态，重启归零；P3 补持久化）。命中返回 ≤120 字片段，否则空串。
        """
        now = time.time()
        last = getattr(self, "_memory_evoke_last_ts", 0)
        if last and now - last < 2 * 3600:
            return ""
        today = datetime.now().strftime("%Y-%m-%d")
        if getattr(self, "_memory_evoke_day", "") != today:
            self._memory_evoke_day = today
            self._memory_evoke_count = 0
        if getattr(self, "_memory_evoke_count", 0) >= 2:
            return ""
        memory = getattr(self, "memory", None)
        if memory is None or not callable(getattr(memory, "retrieve", None)):
            return ""
        try:
            rows = memory.retrieve(
                user_id=int(master_id),
                query="最近想和你聊的事 你的喜好 发生过的事",
                limit=5,
            )
        except Exception:
            return ""
        for row in rows or []:
            content = str(row.get("content") or "").strip()
            if len(content) < 8:
                continue
            self._memory_evoke_last_ts = now
            self._memory_evoke_count = getattr(self, "_memory_evoke_count", 0) + 1
            logger.info("[Push] memory evoked (frag_len=%d)", len(content))
            return content[:120]
        return ""

    async def _dispatch_push(self, scene_name: str, scene_cfg: dict) -> bool:
        """Generate one proactive message and deliver it independently."""
        try:
            primary_selection = self.get_primary_user_selection()
            if primary_selection is None:
                logger.warning("[Push] No primary user configured")
                return False
            master_id = primary_selection.user_id
            delivery_v2 = self.feature_flags.is_enabled("proactive_delivery_v2")

            mood = "neutral"
            if scene_cfg.get("mood_aware"):
                state = self.get_primary_emotion_state()
                mood = state.get("label", "neutral")

            # Workstream 6: retrieve `dialogue` knowledge as generation
            # principles (how to talk) and inject into the push prompt.
            # These are NEVER recited into the message itself.
            knowledge_fragment = ""
            try:
                query = f"{scene_name} {scene_cfg.get('template', '')} 发起"
                hits = self.knowledge.search(query, limit=3, category="dialogue")
                if hits:
                    principles = [
                        str(row.get("content", "")).strip()
                        for row in hits
                        if str(row.get("content", "")).strip()
                    ]
                    if principles:
                        knowledge_fragment = (
                            "发起话术原则（吸收为你的说法风格，不要说教/复述）：\n"
                            + "\n".join(f"- {p}" for p in principles)
                            + "\n"
                        )
            except Exception as e:
                logger.debug("[Push] dialogue knowledge retrieval failed: %s", e)

            # P0 topic system: 主动消息动机重定义 —— 续接/再造/新话题。
            # 判定顺序：有活跃话题→continue；无但有 closed 存根→revive；再无→new。
            topic_mode = "new"
            dialogue_context = ""
            if getattr(self, "topic_tracker", None) is not None:
                try:
                    _plan = self.topic_tracker.continuation_plan()
                    _mode = str(_plan.get("mode", "new"))
                    if _mode in ("continue", "revive"):
                        topic_mode = _mode
                        dialogue_context = str(_plan.get("dialogue_context") or "")
                except Exception:
                    logger.debug("[Push] topic continuation plan failed", exc_info=True)

            # 续接/再造时附上最近对话历史作为素材（预算 600 字，失败不阻断）。
            if topic_mode in ("continue", "revive"):
                try:
                    recent = await self._recent_dialogue_text(master_id, limit=5)
                    if recent:
                        dialogue_context = (dialogue_context + "\n" + recent).strip()[:600]
                except Exception:
                    logger.debug("[Push] recent dialogue fetch failed", exc_info=True)

            # ---- v2 state-aware inputs: PAD dual-channel ----
            pad = None
            try:
                est = self.get_primary_emotion_state()
                sp = est.get("pad") if isinstance(est, dict) else None
                if isinstance(sp, dict):
                    pad = {
                        "pleasure": float(sp.get("P", 0.0)),
                        "arousal": float(sp.get("A", 0.0)),
                        "dominance": float(sp.get("D", 0.0)),
                    }
            except Exception:
                logger.debug("[Push] PAD snapshot read failed", exc_info=True)

            # ---- v2: world fragment ----
            world_fragment = self._proactive_world_fragment()

            # ---- v2: memory evoke (旧事唤起，仅 new 模式 + 冷却/额度预筛) ----
            memory_fragment = ""
            if topic_mode == "new":
                memory_fragment = self._memory_evoke_fragment(master_id)

            content = await self.brain.generate_push(
                template=scene_cfg.get("template", ""),
                mood=mood,
                tone_hint=scene_cfg.get("tone_hint"),
                judge_context=scene_cfg.get("judge_context"),
                knowledge_fragment=knowledge_fragment,
                dialogue_context=dialogue_context,
                topic_mode=topic_mode,
                pad=pad,
                world_fragment=world_fragment,
                memory_fragment=memory_fragment,
                trigger_shape=str(scene_cfg.get("trigger_shape") or "anchor"),
                date=datetime.now().strftime("%Y年%m月%d日"),
            )
            if not content:
                return False

            # 决策埋点 1（单点写）：动机候选集 + 本次选择落盘。
            if getattr(self, "decision_log", None) is not None:
                try:
                    candidates = self._build_motive_candidates(
                        scene_name, topic_mode, dialogue_context
                    )
                    self.decision_log.append(
                        kind="topic_motive",
                        candidates=candidates,
                        chosen={
                            "mode": topic_mode,
                            "scene": scene_name,
                            "trigger": str(scene_cfg.get("trigger_shape") or "anchor"),
                            "pad": bool(pad),
                            "memory": bool(memory_fragment),
                            "world": bool(world_fragment),
                        },
                        reason=str(scene_cfg.get("template", ""))[:60],
                    )
                except Exception:
                    logger.debug("[Push] decision log append failed", exc_info=True)

            if not delivery_v2:
                success = await self.qq.send_message(master_id, content)
                if success:
                    logger.info("[Push] Sent legacy QQ scene=%s", scene_name)
                return success

            delivered = False
            delivery_results = {
                "qq": "offline",
                "desktop": "failed",
                "notification": "failed",
            }
            if master_id and getattr(self.qq, "is_logged_in", False):
                try:
                    qq_sent = await self.qq.send_message(master_id, content)
                    delivery_results["qq"] = "sent" if qq_sent else "failed"
                    delivered = bool(qq_sent)
                except Exception:
                    delivery_results["qq"] = "failed"
                    logger.warning("[Push] QQ delivery failed scene=%s", scene_name, exc_info=True)
            elif not master_id:
                delivery_results["qq"] = "skipped"

            from core import chat_events

            message_id: int | str = generate_id("message")
            try:
                message_id = self.db.insert(
                    "chat_log",
                    {
                        "user_id": master_id,
                        "role": "assistant",
                        "content": content,
                        "msg_type": "proactive",
                        "route_mode": "PROACTIVE",
                        "scene": scene_name,
                        # 角色级隔离：主动推送归属当前激活角色，避免 NULL 共享行两个角色都看到
                        "persona_id": self._active_persona_id(),
                    },
                )
            except Exception:
                logger.warning(
                    "[Push] proactive persistence failed scene=%s",
                    scene_name,
                    exc_info=True,
                )
            else:
                # 同步进 normalized messages 层，让管理平台聊天记录可见 + 级联删除覆盖
                try:
                    actor_id, channel, account = self._proactive_channel_identity("desktop")
                    self.conversation_repository.persist_proactive_message(
                        user_id=int(master_id),
                        actor_id=actor_id,
                        channel=channel,
                        channel_account_id=account,
                        content=content,
                        legacy_chat_log_id=int(message_id),
                        persona_id=self._active_persona_id(),
                    )
                except Exception:
                    logger.debug(
                        "[Push] proactive normalized persist failed scene=%s",
                        scene_name,
                        exc_info=True,
                    )

            try:
                chat_events.emit(
                    "assistant",
                    role="assistant",
                    id=message_id,
                    user_id=master_id,
                    content=content,
                    source="proactive",
                    scene=scene_name,
                    channel="desktop",
                )
                delivery_results["desktop"] = "queued"
                delivered = True
            except Exception:
                logger.warning("[Push] desktop delivery failed scene=%s", scene_name, exc_info=True)

            proactive_settings = self.settings.get("proactive", {})
            notify_system = bool(
                proactive_settings.get("system_notifications", True)
            )
            try:
                chat_events.emit(
                    "proactive_message",
                    title="云栖",
                    text=content,
                    content=content,
                    scene=scene_name,
                    tone=scene_cfg.get("tone_hint"),
                    notify_system=notify_system,
                    channel="notification",
                )
                delivery_results["notification"] = (
                    "queued" if notify_system else "disabled"
                )
                delivered = True
            except Exception:
                logger.warning("[Push] notification delivery failed scene=%s", scene_name, exc_info=True)

            try:
                chat_events.emit(
                    "proactive_delivery",
                    scene=scene_name,
                    results=delivery_results,
                    channel="delivery",
                )
            except Exception:
                logger.warning(
                    "[Push] delivery telemetry failed scene=%s",
                    scene_name,
                    exc_info=True,
                )

            if delivered:
                logger.info("[Push] Delivered scene=%s", scene_name)
                # P4 companion image: 文本投递成功后，有概率配一张衔接图片。
                # fire-and-forget：不阻塞主动消息主流程，失败静默降级。
                try:
                    self._maybe_attach_companion_image(
                        master_id, content, scene_name,
                    )
                except Exception:
                    logger.debug(
                        "[Push] companion image trigger failed scene=%s",
                        scene_name, exc_info=True,
                    )
            return delivered
        except Exception:
            logger.exception("[Push] dispatch error: %s", scene_name)
            return False

    def _maybe_attach_companion_image(
        self,
        master_id: int | str,
        content: str,
        scene_name: str,
    ) -> None:
        """主动消息配图：文本投递成功后，按概率触发一张衔接图片。

        概率由 settings.proactive.companion_image_probability 控制（默认 0.3）。
        图片复用 local_send 路径——把文本内容当 user_raw，走完整的图片生成工作流
        （模块化提示词 + three_view 图生图 + 世界上下文接力）。
        fire-and-forget：create_task 异步执行，不阻塞消息投递，失败仅 debug 日志。
        """
        proactive = self.settings.get("proactive", {}) if isinstance(self.settings, dict) else {}
        probability = float(proactive.get("companion_image_probability", 0.3))
        if probability <= 0 or random.random() > probability:
            return
        # 前置检查：world_port 和 consumer 必须可用
        world_port = getattr(self, "world_port", None)
        if not world_port or not getattr(world_port, "publish_image_candidate", None):
            return
        content = str(content or "").strip()
        if not content:
            return

        async def _fire() -> None:
            # 延迟让文本先到用户端，图片紧随其后更自然。
            await asyncio.sleep(_COMPANION_IMAGE_DELAY_SEC)
            try:
                result = await self.publish_image_candidate({
                    "candidate_id": f"proactive-companion-{scene_name}-{int(time.time())}",
                    "idempotency_key": f"proactive-companion:{scene_name}:{int(time.time())}",
                    "scene": "local_send",
                    "user_raw": content,
                    "owner_id": master_id,
                    "channel": "local_chat",
                    "target": master_id,
                    "prompt_key": "role_in_scene",
                    "reason_code": f"proactive_companion:{scene_name}",
                    "source": "generated",
                    "score": 0.5,
                    "persona_id": self._active_persona_id(),
                })
                status = str((result or {}).get("status", ""))
                if status in ("published", "delivered", "sent", "ok", "success"):
                    logger.info(
                        "[Push] companion image delivered scene=%s status=%s",
                        scene_name, status,
                    )
                    # P3 发图自我认知：记录为 EVENT 长期记忆。
                    await self._persist_image_event(
                        user_id=int(master_id),
                        desc=f"主动消息配图（{scene_name}）：{content[:60]}",
                        channel="local_chat",
                        image_path=str((result or {}).get("image_path", "")),
                    )
                else:
                    logger.debug(
                        "[Push] companion image not consumed scene=%s status=%s",
                        scene_name, status,
                    )
            except Exception:
                logger.debug(
                    "[Push] companion image generation failed scene=%s",
                    scene_name, exc_info=True,
                )

        try:
            asyncio.create_task(_fire())
        except RuntimeError:
            # 无事件循环时忽略（如单元测试环境）
            pass

    async def check_idle(self, user_id: int, idle_seconds: float) -> bool:
        """Called externally when user is detected idle beyond threshold.

        Triggers idle_care scene if configured.
        """
        return await self.push_scheduler.trigger("idle_care")

    async def check_threshold_break(self) -> bool:
        """Called when cumulative emotion threshold is exceeded.

        Triggers emotion_comfort scene if configured.
        """
        return await self.push_scheduler.trigger("emotion_comfort")


async def _dashboard_get_world_state(world_port: Any) -> dict[str, Any]:
    if world_port is None:
        return {}
    getter = getattr(world_port, "get_state", None)
    if not callable(getter):
        return {}
    try:
        value = getter()
        if hasattr(value, "__await__"):
            value = await value
        to_public = getattr(value, "to_public_dict", None)
        if callable(to_public):
            value = to_public()
        return value if isinstance(value, dict) else {}
    except Exception:
        logger.debug("world dashboard state unavailable", exc_info=True)
        return {}


async def _dashboard_replay_events(world_port: Any) -> list[Any]:
    replay = getattr(world_port, "replay_events", None)
    if not callable(replay):
        return []
    try:
        try:
            events = replay(last_seq=0)
        except TypeError:
            events = replay()
        if hasattr(events, "__await__"):
            events = await events
        return list(events or [])[:25]
    except Exception:
        logger.debug("world dashboard event replay unavailable", exc_info=True)
        return []


def _dashboard_world_summary(
    state: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    merged = {}
    if isinstance(state, dict):
        merged.update(state)
    if isinstance(snapshot, dict):
        merged.update(snapshot)
    return _dashboard_pick(
        merged,
        (
            ("status", "status"),
            ("source", "source"),
            ("instanceId", "instance_id", "instanceId"),
            ("protocol", "protocol"),
            ("protocolVersion", "protocol_version", "protocolVersion"),
            ("phase", "phase"),
            ("location", "location"),
            ("activity", "activity"),
            ("energy", "energy"),
            # 房间级细粒度定位（方向5）：世界界面据此展示楼层/区域/大致位置。
            ("floor", "floor"),
            ("zone", "zone"),
            ("positionDesc", "position_desc", "positionDesc"),
            ("nearbyObjects", "nearby_objects", "nearbyObjects"),
            # P2: 移动状态透传（status/path/waypoints/progress/reason）。
            ("movement", "movement"),
            ("weather", "weather", "weather_mood"),
            ("weatherMood", "weather_mood", "weather"),
            ("sequence", "sequence"),
            ("revision", "revision"),
            ("paused", "paused"),
            ("generatedAt", "generated_at", "generatedAt"),
            ("capabilities", "capabilities"),
        ),
    )


def _dashboard_safe_relationship(value: dict[str, Any] | None) -> dict[str, Any]:
    # 兼容两类数据形态：
    #   A. RelationshipEngine 的嵌套状态（agent_to_user / user_to_agent / security / conflict）
    #   B. 扁平化的关系字段（warmth / trust / affinity / tension / ...）
    # 统一映射为仪表盘公开字段，避免因 key 不匹配而整段丢失（G3）。
    data = _dashboard_safe_mapping(value)
    if not data:
        return {}
    agent_to_user = _dashboard_safe_mapping(data.get("agent_to_user"))
    user_to_agent = _dashboard_safe_mapping(data.get("user_to_agent"))
    user_emotion = _dashboard_safe_mapping(data.get("user_emotion"))

    candidates: list[tuple[str, Any]] = [
        ("user_id", data.get("user_id") or data.get("userId")),
        ("persona_id", data.get("persona_id") or data.get("personaId")),
        # 嵌套形态优先，扁平形态兜底
        ("attachment", agent_to_user.get("attachment") or data.get("attachment")),
        ("agentTrust", agent_to_user.get("trust") or data.get("agentTrust")),
        ("care", agent_to_user.get("care") or data.get("care")),
        ("warmth", user_to_agent.get("warmth") or data.get("warmth")),
        ("engagement", user_to_agent.get("engagement") or data.get("engagement")),
        ("userTrust", user_to_agent.get("trust") or data.get("userTrust")),
        ("trust", data.get("trust") or agent_to_user.get("trust")),
        ("security", data.get("security")),
        ("conflict", data.get("conflict")),
        ("affinity", data.get("affinity")),
        ("tension", data.get("tension")),
        ("familiarity", data.get("familiarity")),
        ("closeness", data.get("closeness")),
        ("summary", data.get("summary")),
        ("userEmotionLabel", user_emotion.get("label")),
        ("userEmotionValence", user_emotion.get("valence")),
        ("source", data.get("source")),
        ("revision", data.get("revision")),
        ("updated_at", data.get("updated_at") or data.get("updatedAt")),
    ]
    public: dict[str, Any] = {}
    for output_key, raw in candidates:
        public_value = _dashboard_public_scalar(raw)
        if public_value not in ("", None, [], {}):
            public[output_key] = public_value
    return public


def _dashboard_safe_self_model(value: dict[str, Any] | None) -> dict[str, Any]:
    return _dashboard_pick(
        _dashboard_safe_mapping(value),
        (
            ("mood", "mood"),
            ("energy", "energy"),
            ("focus", "focus"),
            ("stability", "stability"),
            ("summary", "summary"),
            ("updated_at", "updated_at", "updatedAt"),
        ),
    )


def _dashboard_action_timeline(events: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events[:25]:
        payload = _dashboard_event_payload(event)
        payload_keys = payload.get("payload_keys") or payload.get("payloadKeys")
        if not isinstance(payload_keys, list):
            payload_keys = sorted(str(key) for key in payload.keys())
        row = {
            "eventId": _dashboard_safe_text(getattr(event, "event_id", "") or ""),
            "topic": _dashboard_safe_text(getattr(event, "topic", "") or ""),
            "eventType": _dashboard_safe_text(getattr(event, "event_type", "") or ""),
            "sequence": _dashboard_event_sequence(event),
            "occurredAt": _dashboard_safe_text(getattr(event, "occurred_at", "") or ""),
            "payloadKeys": _dashboard_public_payload_keys(payload_keys),
        }
        digest = payload.get("payload_sha256") or payload.get("payloadSha256")
        if digest:
            row["payloadSha256"] = _dashboard_safe_text(digest, 120)
        rows.append(row)
    return rows


def _dashboard_image_candidates(events: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events[:25]:
        topic = str(getattr(event, "topic", "") or "")
        event_type = str(getattr(event, "event_type", "") or "")
        if topic not in {"image_candidates", "message.candidates", "world.image_candidates"} and event_type not in {"world.image_candidate.published", "image_candidate.published"}:
            continue
        payload = _dashboard_event_payload(event)
        candidate = _dashboard_pick(
            payload,
            (
                ("candidateId", "candidate_id", "candidateId", "id"),
                ("idempotencyKey", "idempotency_key", "idempotencyKey"),
                ("scene", "scene"),
                ("ownerId", "owner_id", "ownerId"),
                ("channel", "channel"),
                ("target", "target"),
                ("promptKey", "prompt_key", "promptKey"),
                ("reasonCode", "reason_code", "reasonCode"),
                ("source", "source"),
                ("score", "score"),
                ("expiresAt", "expires_at", "expiresAt"),
                ("createdAt", "created_at", "createdAt"),
                ("payloadKeys", "payload_keys", "payloadKeys"),
                ("sensitiveKeys", "sensitive_keys", "sensitiveKeys"),
                ("sensitiveSha256", "sensitive_sha256", "sensitiveSha256"),
            ),
        )
        candidate["sequence"] = _dashboard_event_sequence(event)
        candidate["eventId"] = _dashboard_safe_text(getattr(event, "event_id", "") or "")
        rows.append(candidate)
    return rows


def _dashboard_event_payload(event: Any) -> dict[str, Any]:
    payload = getattr(event, "payload", {})
    return payload if isinstance(payload, dict) else {}


def _dashboard_event_sequence(event: Any) -> int:
    try:
        return int(getattr(event, "sequence", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _dashboard_public_payload_keys(keys: list[Any]) -> list[str]:
    public: list[str] = []
    for key in keys[:25]:
        text = _dashboard_safe_text(key, 120)
        lowered = text.lower()
        if "raw" in lowered or "prompt" in lowered or "token" in lowered or "credential" in lowered:
            continue
        public.append(text)
    return public


def _dashboard_safe_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dashboard_pick(
    data: dict[str, Any],
    fields: tuple[tuple[str, ...], ...],
) -> dict[str, Any]:
    public: dict[str, Any] = {}
    source = data if isinstance(data, dict) else {}
    for field in fields:
        output_key, *input_keys = field
        raw = _dashboard_first(source, input_keys)
        public_value = _dashboard_public_scalar(raw)
        if public_value not in ("", None, [], {}):
            public[output_key] = public_value
    return public


def _dashboard_first(data: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in data:
            return data.get(key)
    return None


def _dashboard_public_scalar(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value
    if isinstance(value, list | tuple):
        return [_dashboard_safe_text(item, 120) for item in value[:25]]
    if value is None:
        return ""
    return _dashboard_safe_text(value)


def _dashboard_safe_text(value: Any, limit: int = 200) -> str:
    return str(value or "").replace("\x00", "").strip()[:limit]
