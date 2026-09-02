"""Aerie · world_phase — 世界时间档位单一真源（P1 下沉）.

收拢全库分散维护的 phase 定义，加档位只改本文件一处：
- DEFAULT_WORLD_PHASES：7 档时段（含 location/activity/energy/social）
- TIME_OF_DAY_CN / TIME_OF_DAY_LIGHT_CN：phase → 中文/光线翻译
- PHASE_ZONE：phase → 房间 zone（供 home_space.zone_for_phase 使用）
- phase_for_hour(hour)：小时 → phase（供 companion 生图/上下文取值）

v3.2 收敛结论：档位数量与行为多样性无因果关系，行为多样性由
DailyPlanner 日程生成承担；本模块只解决"氛围/光线细分"与"单一真源"。
"""

from __future__ import annotations

from typing import Any


# ── 7 档时段（跨午夜：night 23:30 – 05:00）─────────────────
DEFAULT_WORLD_PHASES: dict[str, dict[str, Any]] = {
    "dawn": {
        "start": "05:00",
        "end": "07:00",
        "location": "home",
        "activity": "waking_up",
        "energy": 0.45,
        "social": "private",
    },
    "morning": {
        "start": "07:00",
        "end": "12:00",
        "location": "home",
        "activity": "planning",
        "energy": 0.78,
        "social": "private",
    },
    "noon": {
        "start": "12:00",
        "end": "14:00",
        "location": "home",
        "activity": "dining",
        "energy": 0.62,
        "social": "private",
    },
    "afternoon": {
        "start": "14:00",
        "end": "18:00",
        "location": "study",
        "activity": "working",
        "energy": 0.55,
        "social": "focused",
    },
    "evening": {
        "start": "18:00",
        "end": "22:00",
        "location": "home",
        "activity": "relaxing",
        "energy": 0.42,
        "social": "private",
    },
    "late_evening": {
        # 21:30 仍归入 evening，避免边界时刻把晚间关怀过早切换为夜深。
        "start": "22:00",
        "end": "23:30",
        "location": "home",
        "activity": "winding_down",
        "energy": 0.3,
        "social": "private",
    },
    "night": {
        "start": "23:30",
        "end": "05:00",
        "location": "home",
        "activity": "sleeping",
        "energy": 0.22,
        "social": "private",
    },
}


# ── phase → 中文（LLM 中文语境 / 生图上下文）────────────────
TIME_OF_DAY_CN: dict[str, str] = {
    "dawn": "清晨",
    "morning": "上午",
    "noon": "正午",
    "afternoon": "下午",
    "evening": "傍晚",
    "late_evening": "夜深",
    "night": "深夜",
    "unknown": "未知",
}


# ── phase → 光线中文（生图/上下文兜底）─────────────────────
TIME_OF_DAY_LIGHT_CN: dict[str, str] = {
    "dawn": "清晨，天边泛起鱼肚白，室内是柔和冷调的光",
    "morning": "上午，明亮的自然光透过窗户",
    "noon": "正午，明亮的日光从窗户洒进来",
    "afternoon": "下午，柔和的自然光，光影层次分明",
    "evening": "傍晚，黄昏的暖色调光线",
    "late_evening": "夜深，室内一盏暖黄灯，窗外安静",
    "night": "深夜，室内一盏暖黄灯，窗外是安静的夜景",
}


# ── phase → 房间 zone（供 home_space.zone_for_phase 使用）────
PHASE_ZONE: dict[str, str] = {
    "dawn": "master_bedroom",      # 清晨在主卧醒来
    "morning": "living",           # 上午在客厅规划一天
    "noon": "dining",              # 正午在餐区用餐
    "afternoon": "studio",         # 下午在工作室专注工作
    "evening": "living",           # 傍晚在客厅放松
    "late_evening": "master_bedroom",  # 夜深回主卧准备休息
    "night": "master_bedroom",     # 深夜在主卧睡觉
}


def phase_for_hour(hour: int) -> str:
    """小时（0-23）→ phase。跨午夜区间：night 23:30–05:00。"""
    h = int(hour) % 24
    for name, phase in DEFAULT_WORLD_PHASES.items():
        start_h = _hour_of(phase.get("start", "00:00"))
        end_h = _hour_of(phase.get("end", "23:59"))
        if start_h <= end_h:
            if start_h <= h < end_h:
                return name
        else:  # 跨午夜（night）
            if h >= start_h or h < end_h:
                return name
    return "night"


def _hour_of(value: str) -> int:
    try:
        return int(str(value).split(":")[0])
    except (TypeError, ValueError):
        return 0
