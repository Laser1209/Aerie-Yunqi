"""Aerie · image_shooting — 拍摄手法语料（已内化，运行时不读任何文件）.

本模块把 `documents/生图加强/*.md` 的语料**提炼内化**成结构化表：镜头 / 机位 /
取景 / 景深 / 质感，按画面类型（氛围风格、画面用途、景别）配套成组的拍摄手法，
而不是把零星关键词硬拼进提示词。硬组合只适用于"场景与周围景观"（由场景池负责），
"怎么拍"交给这里。

两条铁律：
1. **画面中不出现任何拍摄设备**：手机、相机、三脚架、自拍杆、握持设备的手都不允许
   入镜。拍摄手法用"用 iPhone 前置/后置摄像头拍摄"这类*说明性*语言表达视角与构图，
   由负面约束兜底排除设备本体（见 DEVICE_EXCLUSION_CLAUSE）。
2. **与当前状态同步**：按她此刻的时段（phase）与精力（energy）微调手法颗粒度，
   让"此刻"真的落在画面上，而不是每张图都一样。

改动本文件的表即改动全库拍摄手法，无需触碰 companion。语料与代码同源，随代码回溯。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ── 出口措辞：无一例外的横切约束 ────────────────────────────────
# 第一人称自拍视角：照片是她自己的视角，用设备说明拍摄方式，但设备本体绝不出现在画面里。
SELFIE_POV_PHRASE = (
    "这张照片是她本人的第一人称自拍视角，用 iPhone 前置摄像头拍摄，"
    "画面中不出现手机、相机、三脚架、自拍杆或任何拍摄设备，也不出现握持设备的手。"
)

# 出游/合影例外：允许同行者视角，但同样不得让设备入镜。
TOGETHER_SHOT_PHRASE = (
    "同行的人用她的手机替她按下快门，画面中不出现手机、相机或任何拍摄设备。"
)

# 负面约束追加项：明确把设备本体排除在画面之外。
DEVICE_EXCLUSION_CLAUSE = "手机、相机、三脚架、自拍杆等任何拍摄设备及其握持的手。"


# ── 设备词清洗（出口护栏）──────────────────────────────────────
# 提示词会经轻量 LLM 接力重写，历史措辞或模型自由发挥都可能把"手持手机"带回画面。
# 出口统一清洗：先按整句替换成语义等价的无设备措辞，再清掉残留的设备词与重复标点，
# 保证"不出现设备元素"这条约束在最终提示词里成立（而不是只靠上游自觉）。
_PHRASE_REWRITES: tuple[tuple[str, str], ...] = (
    ("她手持手机（或自拍杆）把全身收进画面", "机位拉远，把全身收进画面"),
    ("她把手机举到身后，用后置摄像头拍自己的背影", "机位在她身后，从背后取景"),
    ("她手持手机放低，从低处自拍取景", "低机位仰拍，从低处取景"),
    ("她举高手机，从上往下俯拍自己", "高机位俯拍，从上往下取景"),
    ("她手持手机平视自拍", "眼平机位平视取景"),
    ("她手持手机近距离特写自拍", "近距离特写机位"),
    ("第一人称手持自拍视角", "第一人称视角"),
    ("她举着手机前置摄像头对着自己", "以前置摄像头视角对着镜头"),
    ("她举起手机前置摄像头对着自己", "以前置摄像头视角对着镜头"),
    ("她手持手机前置摄像头对着自己", "以前置摄像头视角对着镜头"),
    ("她手持手机举在两人面前前置自拍", "以广角前置机位把两人收进画面"),
    ("这张照片由她画中的女性本人手持手机拍摄", "这张照片是她本人的第一人称自拍视角"),
    ("这张照片由她本人手持手机拍摄", "这张照片是她本人的第一人称自拍视角"),
)
_DEVICE_TOKEN_REWRITES: tuple[tuple[str, str], ...] = (
    ("手机前置摄像头", "前置摄像头"),
    ("手机后置摄像头", "后置摄像头"),
    ("用手机拍摄", "拍摄"),
    # 清洗后残留的"举着设备"类动词短语（LLM 接力常见泄漏）→ 语义等价的无设备表述。
    ("举在胸前自拍", "以第一人称自拍"),
    ("举在胸前", "胸前"),
    ("举着自拍", "自拍"),
    ("举高自拍", "自拍"),
    ("手持手机", ""),
    ("举着手机", ""),
    ("举高手机", ""),
    ("手机边缘", ""),
    ("自拍杆", ""),
    ("的手机", "的"),
    ("手机", ""),
)
_TIDY_RE = re.compile(r"[，,]{2,}|。。|，。|。，|；，|，；")
_LEADING_PUNCT_RE = re.compile(r"^[，,。；;、]+")


def strip_device_props(text: str) -> str:
    """清洗提示词里的拍摄设备元素，返回无设备措辞的文本（幂等）。

    自身横切措辞（POV / 同行者 / 负面约束）本就含"手机/相机"字样（"不出现手机…"），
    必须原样保护——它们是在**排除**设备，不能被当成待清洗的设备描述删掉。
    """
    out = str(text or "")
    if not out:
        return out
    # 先给受保护措辞打占位符（即"排除设备"的约束本身），清洗完再还原。
    protected: dict[str, str] = {}
    for idx, clause in enumerate((SELFIE_POV_PHRASE, TOGETHER_SHOT_PHRASE, DEVICE_EXCLUSION_CLAUSE)):
        if clause and clause in out:
            token = f"\x00SHOOT{idx}\x00"
            out = out.replace(clause, token)
            protected[token] = clause
    for src, dst in _PHRASE_REWRITES:
        out = out.replace(src, dst)
    for src, dst in _DEVICE_TOKEN_REWRITES:
        out = out.replace(src, dst)
    out = _TIDY_RE.sub(lambda m: "。" if "。" in m.group(0) else "，", out)
    out = _LEADING_PUNCT_RE.sub("", out)
    for token, clause in protected.items():
        out = out.replace(token, clause)
    return out


# ── 拍摄手法套件 ───────────────────────────────────────────────
@dataclass(frozen=True)
class ShootingKit:
    """一组成组的拍摄手法：镜头 / 机位 / 取景 / 景深 / 质感。

    字段均为画面语言，不含任何入镜设备；`camera` 只说明"用什么拍"，不产生画面元素。
    """

    key: str
    camera: str
    angle: str
    framing: str
    depth: str
    texture: str


# 按"氛围风格"配套（对应 _PHOTO_STYLE_TABLE 的标签）：惬意柔和、清新通透、
# 诱惑私密、氛围情绪——不同情绪配不同镜头与光线质感，避免所有图千篇一律。
_STYLE_KITS: dict[str, ShootingKit] = {
    "慵懒": ShootingKit(
        key="soft_cozy",
        camera="iPhone 前置摄像头，约 50mm 等效焦距",
        angle="眼平略低的机位，正对自己",
        framing="上半身入画，留一点环境余地",
        depth="浅景深，背景自然柔焦",
        texture="漫射柔光下的细腻肤色，柔和阴影，轻微胶片颗粒",
    ),
    "居家感": ShootingKit(
        key="cozy_home",
        camera="iPhone 前置摄像头，约 50mm 等效焦距",
        angle="眼平机位，机身微微倾斜",
        framing="肩部以上到胸口入画",
        depth="中等景深，背景可辨但不抢主体",
        texture="室内自然光，生活化质感，轻微颗粒",
    ),
    "清新": ShootingKit(
        key="fresh_clean",
        camera="iPhone 前置摄像头，约 50mm 等效焦距",
        angle="眼平机位，略微俯角",
        framing="肩部以上入画，画面干净留白",
        depth="中等景深，背景轻微虚化",
        texture="明亮通透的高键调，反差柔和，干净肤色",
    ),
    "诱惑感": ShootingKit(
        key="close_allure",
        camera="iPhone 前置摄像头，近距离取景",
        angle="略微俯视的近距离机位",
        framing="面部到锁骨入画，靠近镜头",
        depth="极浅景深，焦点落在眼睛",
        texture="低饱和柔焦皮肤，暗部有层次，暧昧的弱光",
    ),
    "氛围感": ShootingKit(
        key="moody",
        camera="iPhone 后置摄像头，约 85mm 等效焦距",
        angle="略低机位，稍偏侧的取景角度",
        framing="膝上到头部入画，背景被压缩",
        depth="浅景深，背景柔和虚化",
        texture="环境光氛围，暗部层次丰富，ISO 800 胶片颗粒",
    ),
}

# 按"画面用途"配套（对应 prompt_key）：没给氛围风格时的默认手法。
_PROMPT_KEY_KITS: dict[str, ShootingKit] = {
    "role_selfie": ShootingKit(
        key="selfie_default",
        camera="iPhone 前置摄像头，约 50mm 等效焦距",
        angle="眼平略低的机位，正对自己",
        framing="上半身入画",
        depth="浅景深，背景自然柔焦",
        texture="自然光下的真实肤色，轻微胶片颗粒",
    ),
    "role_in_scene": ShootingKit(
        key="life_scene",
        camera="iPhone 后置摄像头，约 35mm 等效焦距",
        angle="略低的自然机位，像随手举起",
        framing="带环境的中景，人物与所处空间都入画",
        depth="中等景深，环境可辨",
        texture="生活纪实的自然光感，轻微手持晃动",
    ),
    "couple_photo": ShootingKit(
        key="couple_wide",
        camera="iPhone 前置摄像头，广角",
        angle="机位略高，向下约 15 度",
        framing="两人肩部以上入画，靠得很近",
        depth="浅景深，背景柔和",
        texture="暖色调，肤色柔和自然",
    ),
}

# 景别覆盖：拉远成全身/远景时改用带环境的镜头语言，避免"贴身自拍"与全身构图打架。
_SHOT_KIT_OVERRIDES: dict[str, ShootingKit] = {
    "远景": ShootingKit(
        key="far_env",
        camera="iPhone 后置摄像头，约 35mm 广角",
        angle="自然站位的略低机位",
        framing="全身与所处环境一起入画，环境占比大",
        depth="中等景深，环境清晰可辨",
        texture="自然光下的纪实质感，轻微颗粒",
    ),
    "中景": ShootingKit(
        key="medium_env",
        camera="iPhone 后置摄像头，约 50mm 等效焦距",
        angle="眼平略低的机位",
        framing="膝上入画的中景",
        depth="中等景深，背景轻微虚化",
        texture="自然光下的真实肤质，轻微颗粒",
    ),
}

# 疲惫状态下的手法微调：低精力时用更柔的机位与质感，贴合"懒懒地拍一张"。
_LOW_ENERGY_KIT = ShootingKit(
    key="tired_soft",
    camera="iPhone 前置摄像头，约 50mm 等效焦距",
    angle="稍微倚靠的略低机位，不刻意摆正",
    framing="上半身入画，姿态松弛",
    depth="浅景深，背景柔和",
    texture="弱光柔焦，肤质细腻，轻微噪点",
)
_LOW_ENERGY_THRESHOLD = 0.35

# 暗时段质感补充：只补"颗粒/噪点"这类渲染质感，不写光线方向，
# 避免与 solar_time 的权威光照描述冲突（光线单一真源不变）。
_PHASE_GRAIN: dict[str, str] = {
    "night": "夜间弱光下适当提高感光度，允许轻微噪点",
    "late_evening": "夜深弱光下轻微噪点",
}


def resolve_kit(
    *,
    style: str = "",
    prompt_key: str = "",
    shot: str = "",
    energy: float | None = None,
) -> ShootingKit | None:
    """按 氛围风格 → 景别 → 用途 → 精力 的优先级解析出成组的拍摄手法。

    显式氛围风格优先（用户明确要的情绪说了算）；全身/远景景别次之（构图要成立）；
    再次是画面用途默认；最后在低精力且未指定风格时改用柔和手法。
    无法解析时返回 None，由调用方跳过拍摄手法模块（缺值即停防护）。
    """
    kit = _STYLE_KITS.get(str(style or "").strip())
    if kit is None:
        kit = _SHOT_KIT_OVERRIDES.get(str(shot or "").strip())
    if kit is None:
        kit = _PROMPT_KEY_KITS.get(str(prompt_key or "").strip())
    if kit is None:
        return None
    if kit.key in ("selfie_default", "cozy_home") and energy is not None:
        try:
            if float(energy) < _LOW_ENERGY_THRESHOLD:
                return _LOW_ENERGY_KIT
        except (TypeError, ValueError):
            pass
    return kit


def shooting_phrase(
    *,
    style: str = "",
    prompt_key: str = "",
    shot: str = "",
    phase: str = "",
    energy: float | None = None,
) -> str:
    """把拍摄手法套件拼成一句写进生图提示词的画面语言；无套件时返回空串。"""
    if str(prompt_key or "") == "environment_object":
        return ""
    kit = resolve_kit(style=style, prompt_key=prompt_key, shot=shot, energy=energy)
    if kit is None:
        return ""
    bits = [kit.camera, kit.angle, kit.framing, kit.depth, kit.texture]
    grain = _PHASE_GRAIN.get(str(phase or "").strip())
    if grain and grain not in bits:
        bits.append(grain)
    return "拍摄手法：" + "，".join(p for p in bits if p) + "。"
