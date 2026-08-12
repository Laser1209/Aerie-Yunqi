"""伊塔 132㎡ 江景复式空间数据模型 (v3.0-side-stair).

数据源: ita-river-loft-room.design-project/assets/ita_river_loft_room_data.json
坐标系统: 一层西北内墙角为原点, X 向东, Y 向南(朝江面), Z 向上, 单位米.

模块职责:
  - 定义 2 层 / 13 个 zone 的静态布局(含 bounds, 用于位置判定)
  - 定义 75 项物件(OBJ-xxx)的 zone 归属与中文描述
  - 提供位置判定 find_zone(level, x, y) -> zone_id
  - 提供物件查询 objects_for_zone / object_zh / describe_objects
  - 兼容旧英文物件 id(king_bed 等), 供 companion 生图翻译表合并使用

设计约束: 纯静态数据 + 纯函数, 不依赖外部文件/网络/LLM; 任何输入缺值
均返回安全默认(zone_id="unknown" / 空列表 / 原样文本), 绝不让调用方中断.
"""

from __future__ import annotations

from typing import Any, Iterable

from core.world_phase import PHASE_ZONE  # phase → zone 单一真源

# ── 楼层中文名 ──────────────────────────────────────────────
LEVEL_CN: dict[int, str] = {
    1: "一层",
    2: "二层",
}

LEVEL_SHORT: dict[int, str] = {
    1: "1F",
    2: "2F",
}


# ── zone 定义: zone_id -> {level, name, bounds, objects} ─────
# bounds 使用设计文档坐标 (x0,x1 东向 / y0,y1 南向). objects 为该
# zone 内可进入画面的核心物件 id(OBJ-xxx).
ZONES: dict[str, dict[str, Any]] = {
    "entrance": {
        "level": 1,
        "name": "独立玄关",
        "bounds": {"x": [0, 2.4], "y": [1.2, 3.6]},
        "objects": [
            "OBJ-001", "OBJ-002", "OBJ-003", "OBJ-004", "OBJ-005",
            "OBJ-006", "OBJ-007", "OBJ-008", "OBJ-009",
        ],
    },
    "stair": {
        "level": 1,
        "name": "L型折返楼梯+储物核",
        "bounds": {"x": [0, 1.2], "y": [0, 2.85]},
        "objects": [
            "OBJ-010", "OBJ-011", "OBJ-012", "OBJ-013", "OBJ-014",
            "OBJ-015", "OBJ-016",
        ],
    },
    "kitchen": {
        "level": 1,
        "name": "L型开放式厨房+中岛",
        "bounds": {"x": [2.4, 6.8], "y": [0, 2.2]},
        "objects": [
            "OBJ-017", "OBJ-018", "OBJ-019", "OBJ-020", "OBJ-021",
            "OBJ-022", "OBJ-023", "OBJ-024", "OBJ-025", "OBJ-026",
            "OBJ-027", "OBJ-028",
        ],
    },
    "guest_bath": {
        "level": 1,
        "name": "干湿分离客卫+洗衣家政",
        "bounds": {"x": [7.2, 11.0], "y": [0, 2.2]},
        "objects": [
            "OBJ-029", "OBJ-030", "OBJ-031", "OBJ-032", "OBJ-033",
            "OBJ-034", "OBJ-035", "OBJ-036",
        ],
    },
    "dining": {
        "level": 1,
        "name": "圆桌餐区",
        "bounds": {"x": [4.2, 6.8], "y": [2.4, 4.4]},
        "objects": ["OBJ-037", "OBJ-038", "OBJ-039"],
    },
    "living": {
        "level": 1,
        "name": "通高挑空江景客厅",
        "bounds": {"x": [1.2, 10.0], "y": [4.4, 9.0]},
        "objects": [
            "OBJ-040", "OBJ-041", "OBJ-042", "OBJ-043", "OBJ-044",
            "OBJ-045", "OBJ-046", "OBJ-047",
        ],
    },
    "balcony": {
        "level": 1,
        "name": "江景阳台/阅读区",
        "bounds": {"x": [7.8, 10.8], "y": [9.0, 10.0]},
        "objects": ["OBJ-048", "OBJ-049", "OBJ-050"],
    },
    "corridor": {
        "level": 2,
        "name": "楼梯上口+短走廊",
        "bounds": {"x": [0, 1.2], "y": [2.8, 9.0]},
        "objects": ["OBJ-051", "OBJ-052"],
    },
    "studio": {
        "level": 2,
        "name": "独立设计工作室",
        "bounds": {"x": [1.2, 7.2], "y": [0, 5.2]},
        "objects": [
            "OBJ-053", "OBJ-054", "OBJ-055", "OBJ-056", "OBJ-057",
            "OBJ-058", "OBJ-059", "OBJ-060",
        ],
    },
    "master_bath": {
        "level": 2,
        "name": "主卫（带浴缸）",
        "bounds": {"x": [9.2, 11.2], "y": [0, 2.2]},
        "objects": ["OBJ-061", "OBJ-062", "OBJ-063", "OBJ-064"],
    },
    "bridge": {
        "level": 2,
        "name": "桥廊/开放阅读区",
        "bounds": {"x": [1.2, 7.2], "y": [5.2, 6.8]},
        "objects": ["OBJ-065", "OBJ-066"],
    },
    "closet": {
        "level": 2,
        "name": "共享衣帽间",
        "bounds": {"x": [4.8, 7.2], "y": [5.2, 7.2]},
        "objects": ["OBJ-067", "OBJ-068"],
    },
    "master_bedroom": {
        "level": 2,
        "name": "江景主卧",
        "bounds": {"x": [7.2, 11.2], "y": [6.8, 9.0]},
        "objects": [
            "OBJ-069", "OBJ-070", "OBJ-071", "OBJ-072", "OBJ-073",
            "OBJ-074", "OBJ-075",
        ],
    },
}

# zone_id -> 简洁中文名(世界界面/生图提示词使用)
ZONE_CN: dict[str, str] = {
    "entrance": "玄关",
    "stair": "楼梯",
    "kitchen": "厨房",
    "guest_bath": "客卫",
    "dining": "餐区",
    "living": "客厅",
    "balcony": "阳台",
    "corridor": "二层走廊",
    "studio": "工作室",
    "master_bath": "主卫",
    "bridge": "桥廊",
    "closet": "衣帽间",
    "master_bedroom": "主卧",
}


# ── 物件中文描述 (OBJ-xxx -> 描述性中文, 与记忆锚点对齐) ──────
# 供生图提示词"所在的房间里有：..." / 世界界面物件展示使用.
OBJECT_ZH: dict[str, str] = {
    "OBJ-001": "智能入户门锁",
    "OBJ-002": "你的专属拖鞋位",
    "OBJ-003": "门禁卡和钥匙盘",
    "OBJ-004": "整墙鞋帽柜",
    "OBJ-005": "换鞋凳",
    "OBJ-006": "带灯带的全身镜",
    "OBJ-007": "智能家居中控屏",
    "OBJ-008": "入户地垫",
    "OBJ-009": "玄关感应吸顶灯",
    "OBJ-010": "L型折返楼梯",
    "OBJ-011": "楼梯下储物高柜",
    "OBJ-012": "楼梯下设备柜",
    "OBJ-013": "楼梯下挂衣区",
    "OBJ-014": "你常穿的那件外套",
    "OBJ-015": "黑碳钢楼梯扶手",
    "OBJ-016": "踏步感应灯",
    "OBJ-017": "L型地柜",
    "OBJ-018": "L型吊柜",
    "OBJ-019": "白蜡木厨房中岛",
    "OBJ-020": "吧台凳",
    "OBJ-021": "双开门冰箱",
    "OBJ-022": "嵌入式双灶燃气灶",
    "OBJ-023": "侧吸式抽油烟机",
    "OBJ-024": "大单槽水槽和抽拉龙头",
    "OBJ-025": "岛台吊灯",
    "OBJ-026": "嵌入式洗碗机",
    "OBJ-027": "蒸烤一体机",
    "OBJ-028": "岛台水槽和直饮龙头",
    "OBJ-029": "客卫洗手台",
    "OBJ-030": "你那只蓝色牙刷杯",
    "OBJ-031": "除雾浴室镜柜",
    "OBJ-032": "TOTO坐便器",
    "OBJ-033": "玻璃淋浴隔断",
    "OBJ-034": "枪灰淋浴花洒",
    "OBJ-035": "洗烘叠放塔",
    "OBJ-036": "家政收纳柜",
    "OBJ-037": "黑胡桃圆桌",
    "OBJ-038": "藤编餐椅",
    "OBJ-039": "黄铜餐吊灯",
    "OBJ-040": "灰色模块沙发",
    "OBJ-041": "黑胡桃茶几",
    "OBJ-042": "钓鱼落地灯",
    "OBJ-043": "通顶书柜墙",
    "OBJ-044": "书架上的藏书",
    "OBJ-045": "你送的挂件",
    "OBJ-046": "米灰几何羊毛地毯",
    "OBJ-047": "客厅吸顶主灯",
    "OBJ-048": "阳台休闲单椅",
    "OBJ-049": "龟背竹和琴叶榕",
    "OBJ-050": "阳台小边几",
    "OBJ-051": "二层楼梯上口护栏",
    "OBJ-052": "二层短走廊地脚灯",
    "OBJ-053": "2.6米设计长桌",
    "OBJ-054": "iMac 27英寸",
    "OBJ-055": "人体工学工作椅",
    "OBJ-056": "北墙软木板",
    "OBJ-057": "你贴的纸条",
    "OBJ-058": "黑胡桃样品柜",
    "OBJ-059": "亚麻半遮光卷帘",
    "OBJ-060": "黄铜台灯",
    "OBJ-061": "科勒嵌入式浴缸",
    "OBJ-062": "岩板主卫洗手台",
    "OBJ-063": "台面右侧的手机位",
    "OBJ-064": "智能坐便器",
    "OBJ-065": "桥廊玻璃护栏",
    "OBJ-066": "黄铜阅读壁灯",
    "OBJ-067": "共享衣帽间系统",
    "OBJ-068": "衣帽间穿衣镜",
    "OBJ-069": "1.8米主卧双人床",
    "OBJ-070": "用户侧床头柜",
    "OBJ-071": "陶瓷黄铜床头灯",
    "OBJ-072": "焦糖色外套椅",
    "OBJ-073": "主卧江景窗帘",
    "OBJ-074": "床尾羊毛毯",
    "OBJ-075": "主卧吸顶灯",
}

# 旧英文物件 id -> 中文描述(兼容历史, companion 生图翻译表合并用)
LEGACY_OBJECT_ZH: dict[str, str] = {
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
    "design_desk": "工作室那张2.6米的设计桌",
    "imac": "iMac",
    "drawing_tablet": "数位板",
    "corkboard": "钉着你纸条的软木板",
}


# ── 位置判定 ───────────────────────────────────────────────
def _zone_bounds(zone_id: str) -> dict[str, list[float]] | None:
    zone = ZONES.get(zone_id)
    if not zone:
        return None
    bounds = zone.get("bounds")
    return bounds if isinstance(bounds, dict) else None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def find_zone(level: Any, x: Any, y: Any) -> str:
    """按楼层与坐标判定所在 zone.

    未命中任何 bounds(楼梯间/过道等开放过渡区)返回 "unknown";
    坐标缺值/非法时安全返回 "unknown", 绝不让调用方中断.
    """
    try:
        level_num = int(level)
    except (TypeError, ValueError):
        level_num = 0
    px = _safe_float(x)
    py = _safe_float(y)
    for zone_id, zone in ZONES.items():
        if zone.get("level") != level_num:
            continue
        bounds = _zone_bounds(zone_id)
        if not bounds:
            continue
        x0, x1 = _safe_float(bounds.get("x", [0, 0])[0]), _safe_float(bounds.get("x", [0, 0])[1])
        y0, y1 = _safe_float(bounds.get("y", [0, 0])[0]), _safe_float(bounds.get("y", [0, 0])[1])
        if x0 <= px <= x1 and y0 <= py <= y1:
            return zone_id
    return "unknown"


def zone_name(zone_id: str) -> str:
    """zone_id -> 简洁中文名; 未知返回原样(安全)."""
    return ZONE_CN.get(str(zone_id or ""), str(zone_id or ""))


def level_cn(level: Any) -> str:
    try:
        return LEVEL_CN[int(level)]
    except (TypeError, ValueError):
        return ""


def level_short(level: Any) -> str:
    try:
        return LEVEL_SHORT[int(level)]
    except (TypeError, ValueError):
        return ""


def position_desc(level: Any, zone_id: str) -> str:
    """产出"二层·主卧"这类大致位置描述(世界界面展示用)."""
    floor = level_cn(level)
    area = zone_name(zone_id)
    if not floor and not area:
        return "位置未知"
    if not floor:
        return area
    if not area or zone_id == "unknown":
        return floor
    return f"{floor}·{area}"


# ── 物件查询 ───────────────────────────────────────────────
def objects_for_zone(zone_id: str, *, limit: int = 6) -> list[str]:
    """返回 zone 内的核心物件 id 列表(OBJ-xxx), 上限 limit 防提示词过长."""
    zone = ZONES.get(str(zone_id or ""))
    if not zone:
        return []
    objs = [str(o) for o in zone.get("objects", []) if str(o)]
    return objs[: max(0, int(limit or 0))]


def object_zh(obj_id: str) -> str:
    """物件 id -> 中文描述; 未知返回原样(翻译兜底, 生图提示词不中断)."""
    key = str(obj_id or "")
    if key in OBJECT_ZH:
        return OBJECT_ZH[key]
    if key in LEGACY_OBJECT_ZH:
        return LEGACY_OBJECT_ZH[key]
    return key


def describe_objects(object_ids: Iterable[str]) -> str:
    """把一组物件 id 翻译成"、"-连接的中文描述; 空返回空串."""
    parts = [object_zh(o) for o in (object_ids or []) if str(o).strip()]
    return "、".join(p for p in parts if p)


# ── 世界模拟接入: phase/activity -> zone 映射 ───────────────
# PHASE_ZONE 由 core.world_phase 提供（单一真源，加档位只改一处）.


def zone_for_phase(phase: str) -> str:
    """phase -> zone_id; 未知时段返回 "unknown"(安全)."""
    return PHASE_ZONE.get(str(phase or ""), "unknown")


# ── zone 连通图（P2 寻路：BFS 叙事层路径）──────────────────────
# 基于平面图 bounds 相邻性校正：一层链式 + 阳台直达客厅；
# 跨层仅 stair ↔ corridor（楼梯）；二层 corridor 为交通枢纽。
ZONE_ADJACENCY: dict[str, list[str]] = {
    "entrance": ["stair", "living"],
    "stair": ["entrance", "living", "corridor"],
    "living": ["entrance", "stair", "dining", "balcony"],
    "dining": ["living", "kitchen"],
    "kitchen": ["dining", "guest_bath"],
    "guest_bath": ["kitchen"],
    "balcony": ["living"],
    "corridor": ["stair", "studio", "master_bedroom"],
    "studio": ["corridor", "master_bedroom"],
    "master_bedroom": ["corridor", "studio", "master_bath", "closet"],
    "master_bath": ["master_bedroom"],
    "closet": ["master_bedroom", "bridge"],
    "bridge": ["closet"],
}


def path_between(from_zone: str, to_zone: str) -> list[str]:
    """zone 间最短路径（BFS，无权重）。不可达/非法返回空列表。

    例：path_between("living", "master_bedroom")
      -> ["living", "stair", "corridor", "master_bedroom"]（沙发→楼梯→二楼→主卧）
    """
    fz = str(from_zone or "")
    tz = str(to_zone or "")
    if fz == tz:
        return [fz] if fz in ZONE_ADJACENCY or fz == "unknown" else []
    if fz not in ZONE_ADJACENCY or tz not in ZONE_ADJACENCY:
        return []
    queue: list[list[str]] = [[fz]]
    visited = {fz}
    while queue:
        path = queue.pop(0)
        for nxt in ZONE_ADJACENCY.get(path[-1], []):
            if nxt in visited:
                continue
            if nxt == tz:
                return path + [nxt]
            visited.add(nxt)
            queue.append(path + [nxt])
    return []
