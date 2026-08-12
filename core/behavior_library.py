"""Aerie · behavior_library — 环境行为资源库（P1 行为调度）.

为 13 个 zone 的核心物件绑定交互行为模板；行为由 DailyPlanner
（跨天一次性生成）按"确定性规则 + 加权随机"消费，供伊塔自主选择
当日活动，实现行为模式的自然多变。

- visual_topic 值域契约：必须命中翻译表键（活动话题 _VISUAL_TOPIC_ZH
  14 键 或 OBJ-xxx 物件 id），杜绝英文 token 漏进生图提示词。
- 纯静态数据 + 纯函数，任何缺值安全兜底，绝不中断调用方。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class Behavior:
    """单个交互行为模板。

    obj_id:         行为依托的物件（OBJ-xxx）
    zone_id:        所属区域（home_space.ZONES 键）
    behavior_desc:  中文行为描述（供 LLM 叙事 / 动机句）
    duration_min:   预计时长（分钟）
    energy_delta:   能量变化（正=恢复，负=消耗）
    social:         private | focused | shared（社交状态）
    visual_topic:   生图话题（活动话题键 或 OBJ-xxx，值域契约校验）
    """

    obj_id: str
    zone_id: str
    behavior_desc: str
    duration_min: int
    energy_delta: float
    social: str
    visual_topic: str


# ── 活跃 zone 行为库（起步 6-7 zone × 3-8 条 ≈ 30 条）──────────
BEHAVIORS: tuple[Behavior, ...] = (
    # ── living 客厅 ──────────────────────────────────────
    Behavior("OBJ-040", "living", "窝在灰色模块沙发里翻一本小说", 45, -0.05, "private", "reading_time"),
    Behavior("OBJ-041", "living", "趴在茶几上给设计稿勾线稿", 30, -0.08, "focused", "desk_view"),
    Behavior("OBJ-042", "living", "把钓鱼落地灯拉低，窝在灯下刷手机", 20, -0.02, "private", "quiet_moment"),
    Behavior("OBJ-043", "living", "站在书柜墙前挑一本想看的书", 10, 0.0, "private", "reading_time"),
    Behavior("OBJ-044", "living", "窝在沙发里翻书架上的旧藏书", 40, -0.04, "private", "evening_chill"),
    Behavior("OBJ-046", "living", "光脚踩在地毯上做拉伸", 12, 0.1, "private", "quiet_moment"),
    # ── kitchen 厨房 ──────────────────────────────────────
    Behavior("OBJ-019", "kitchen", "站在白蜡木中岛前准备晚餐", 50, -0.12, "private", "lunch_time"),
    Behavior("OBJ-021", "kitchen", "打开双开门冰箱找食材", 8, 0.0, "private", "coffee_break"),
    Behavior("OBJ-024", "kitchen", "在水槽边洗水果，顺手切一盘", 15, -0.03, "private", "tea_break"),
    Behavior("OBJ-027", "kitchen", "用蒸烤一体机烤一份小蛋糕", 40, -0.06, "private", "tea_break"),
    Behavior("OBJ-020", "kitchen", "坐在吧台凳上喝杯咖啡发呆", 15, 0.05, "private", "coffee_break"),
    # ── studio 工作室 ─────────────────────────────────────
    Behavior("OBJ-053", "studio", "趴在 2.6 米设计长桌前画新方案", 90, -0.15, "focused", "deep_focus"),
    Behavior("OBJ-054", "studio", "对着 iMac 调整渲染参数", 60, -0.12, "focused", "deep_focus"),
    Behavior("OBJ-055", "studio", "坐在人体工学椅上转笔构思创意", 25, -0.04, "focused", "desk_view"),
    Behavior("OBJ-056", "studio", "站在北墙软木板前贴新的灵感便签", 15, 0.02, "private", "desk_view"),
    Behavior("OBJ-057", "studio", "看着你贴的纸条偷偷笑了一下", 10, 0.08, "private", "quiet_moment"),
    Behavior("OBJ-060", "studio", "扭亮黄铜台灯，画到深夜", 60, -0.1, "focused", "starry_window"),
    # ── master_bedroom 主卧 ───────────────────────────────
    Behavior("OBJ-069", "master_bedroom", "蜷进主卧双人床准备睡觉", 20, 0.12, "private", "good_night"),
    Behavior("OBJ-070", "master_bedroom", "把手机放在床头柜上充电", 5, 0.0, "private", "good_night"),
    Behavior("OBJ-071", "master_bedroom", "躺在被子里拨弄床头灯开关", 10, 0.04, "private", "quiet_moment"),
    Behavior("OBJ-073", "master_bedroom", "站在江景窗帘前看窗外夜景", 12, 0.06, "private", "starry_window"),
    Behavior("OBJ-074", "master_bedroom", "把床尾羊毛毯拉上来裹住自己", 8, 0.05, "private", "good_night"),
    # ── master_bath 主卫 ──────────────────────────────────
    Behavior("OBJ-061", "master_bath", "泡在嵌入式浴缸里放空", 40, 0.18, "private", "quiet_moment"),
    Behavior("OBJ-062", "master_bath", "在岩板洗手台前卸妆洗脸", 15, -0.02, "private", "quiet_moment"),
    Behavior("OBJ-063", "master_bath", "拿起台面右侧的手机看一眼有没有你的消息", 5, 0.02, "private", "coffee_break"),
    Behavior("OBJ-064", "master_bath", "洗完澡擦着头发从主卫出来", 10, 0.05, "private", "quiet_moment"),
    # ── balcony 阳台 ──────────────────────────────────────
    Behavior("OBJ-048", "balcony", "窝在阳台休闲单椅里晒太阳", 35, 0.1, "private", "evening_chill"),
    Behavior("OBJ-049", "balcony", "给龟背竹和琴叶榕浇水", 12, 0.0, "private", "morning_plan"),
    Behavior("OBJ-050", "balcony", "把小边几搬到栏杆边放杯花茶", 8, 0.02, "private", "tea_break"),
    # ── dining 餐区 ───────────────────────────────────────
    Behavior("OBJ-037", "dining", "在黑胡桃圆桌边吃午饭", 35, 0.08, "private", "lunch_time"),
    Behavior("OBJ-038", "dining", "坐在藤编餐椅上等水烧开", 8, 0.0, "private", "tea_break"),
    Behavior("OBJ-039", "dining", "抬头看黄铜餐吊灯的光晕发呆", 6, 0.01, "private", "quiet_moment"),
)


# ── 通用 fallback（未绑定的 zone 兜底行为，防空池）────────────
FALLBACK_BEHAVIORS: tuple[Behavior, ...] = (
    Behavior("", "unknown", "在家里慢悠悠地收拾一下", 20, -0.02, "private", "quiet_moment"),
    Behavior("", "unknown", "随手拿起水杯喝口水", 5, 0.01, "private", "coffee_break"),
)


# ── 查询 ───────────────────────────────────────────────────
def behaviors_for_zone(zone_id: str) -> list[Behavior]:
    """返回 zone 内的行为模板列表。"""
    return [b for b in BEHAVIORS if b.zone_id == zone_id]


def behavior_pool(zone_id: str) -> list[Behavior]:
    """zone 行为池；未绑定的 zone 返回通用 fallback（安全兜底）。"""
    items = behaviors_for_zone(str(zone_id or ""))
    return items if items else list(FALLBACK_BEHAVIORS)


def all_behaviors() -> list[Behavior]:
    return list(BEHAVIORS)


def zones_with_behaviors() -> list[str]:
    """有专属行为的 zone 列表（去重保持顺序）。"""
    seen: list[str] = []
    for b in BEHAVIORS:
        if b.zone_id not in seen:
            seen.append(b.zone_id)
    return seen


# ── 值域契约校验（visual_topic 必须命中翻译表键）────────────
# 活动话题键（companion._VISUAL_TOPIC_ZH）—— 此处内联避免反向依赖重型模块；
# 新增活动话题须同步补两处（companion 翻译表 + 本集合）。
_ACTIVITY_TOPIC_KEYS: frozenset[str] = frozenset(
    {
        "reading_time", "deep_focus", "morning_plan", "coffee_break",
        "lunch_time", "tea_break", "evening_chill", "good_night",
        "starry_window", "desk_view", "quiet_moment",
        "evening_home", "city_night", "river_view",
    }
)


def validate_visual_topics(behaviors: Iterable[Behavior] | None = None) -> list[str]:
    """返回违反值域契约的 visual_topic 列表；空列表 = 全部通过。

    合法值：活动话题键 或 OBJ-xxx 物件 id（后者经 _HER_HOME_OBJECTS_ZH
    翻译；前缀 object_ 亦视为合法）。
    """
    bad: list[str] = []
    for b in (behaviors if behaviors is not None else BEHAVIORS):
        topic = str(b.visual_topic or "").strip()
        if topic in _ACTIVITY_TOPIC_KEYS:
            continue
        stripped = topic.replace("object_", "", 1) if topic.startswith("object_") else topic
        if stripped.startswith("OBJ-"):
            continue
        bad.append(topic)
    return bad


def __getattr__(name: str) -> Any:  # pragma: no cover - 防误引用
    raise AttributeError(f"behavior_library has no attribute {name!r}")
