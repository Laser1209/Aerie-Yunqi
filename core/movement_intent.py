"""Aerie · 云栖 — 对话移动意图识别（确定性规则，无 LLM 依赖）。

把用户对话中的"去X / 走到X / 坐到X / 回到X"等祈使指令解析为
home_space 的 zone_id，供 companion 调 MovementManager.move_to()
让伊塔"真的移动"，而不是只在话里答应。

设计：
- 纯规则、零外部依赖，任何输入缺值均安全返回 None，绝不抛异常。
- 别名表覆盖 home_space.ZONES 全部 13 个 zone + 常用物件/口语说法
  （沙发→客厅、床上→主卧、书桌→工作室、窗边→阳台……）。
- 动词与地点允许"了/啦/一下"等口语桥接字；询问类（去哪/在哪/哪儿）
  不视为移动指令，避免"你去哪了"误触发。
"""

from __future__ import annotations

import re
from typing import Optional

from core.home_space import ZONE_CN

# (自然语言别名, zone_id)。长词优先，避免"沙发上"被"沙发"截胡。
_ZONE_ALIASES: list[tuple[str, str]] = [
    ("楼梯间", "stair"),
    ("二楼走廊", "corridor"),
    ("衣帽间里", "closet"),
    ("工作间", "studio"),
    ("洗手间", "guest_bath"),
    ("卫生间", "guest_bath"),
    ("落地窗", "balcony"),
    ("窗前", "balcony"),
    ("沙发上", "living"),
    ("沙发边", "living"),
    ("床边", "master_bedroom"),
    ("大床", "master_bedroom"),
    ("床上", "master_bedroom"),
    ("门厅", "entrance"),
    ("玄关", "entrance"),
    ("门口", "entrance"),
    ("楼梯", "stair"),
    ("厨房", "kitchen"),
    ("中岛", "kitchen"),
    ("岛台", "kitchen"),
    ("客卫", "guest_bath"),
    ("厕所", "guest_bath"),
    ("餐区", "dining"),
    ("餐桌", "dining"),
    ("餐厅", "dining"),
    ("饭桌", "dining"),
    ("客厅", "living"),
    ("沙发", "living"),
    ("茶几", "living"),
    ("书架", "living"),
    ("阳台", "balcony"),
    ("窗边", "balcony"),
    ("飘窗", "balcony"),
    ("走廊", "corridor"),
    ("工作室", "studio"),
    ("书房", "studio"),
    ("书桌", "studio"),
    ("工作台", "studio"),
    ("主卫", "master_bath"),
    ("浴室", "master_bath"),
    ("浴缸", "master_bath"),
    ("桥廊", "bridge"),
    ("阅读区", "bridge"),
    ("衣帽间", "closet"),
    ("主卧", "master_bedroom"),
    ("卧室", "master_bedroom"),
    ("房间", "master_bedroom"),
]

# 移动触发动词（祈使）。按长度降序排列，正则交替时先匹配长动词。
_VERBS = (
    "去一下", "走去", "走到", "去往", "过去", "过来",
    "坐到", "躺到", "躺上", "站到", "回到", "去", "到",
    "回", "进", "上", "来",
)

# 动词与地点之间的口语桥接（可选）。
_BRIDGE = r"(?:了|啦|呀|吧|哦|呢|个|那|一下|边|儿|里|这儿|那儿|那边|这边|去|二楼)?"
# 询问类：不视为移动指令。
_QUERY_RE = re.compile(r"(?:哪儿|哪里|去哪|在哪|哪了)")


def detect_move_intent(text: str) -> Optional[dict]:
    """从消息文本中识别移动指令。

    返回 {"zone": zone_id, "zone_cn": str, "matched": str} 或 None。
    任何异常均返回 None（调用方静默忽略）。
    """
    if not text or not isinstance(text, str):
        return None
    if _QUERY_RE.search(text):
        return None
    verb_alt = "|".join(_VERBS)
    for alias, zone in sorted(_ZONE_ALIASES, key=lambda p: len(p[0]), reverse=True):
        try:
            pattern = re.compile(
                r"(?:" + verb_alt + r")" + _BRIDGE + re.escape(alias)
            )
            if pattern.search(text):
                return {
                    "zone": zone,
                    "zone_cn": ZONE_CN.get(zone, zone),
                    "matched": alias,
                }
        except re.error:
            continue
    return None
