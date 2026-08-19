"""PAD → expression-band rules table for proactive push generation.

Pure, side-effect-free. Maps the emotion engine's PAD triple (each in [-1,1])
onto per-axis band labels plus a short "what this state wants to say" style
fragment. The generated fragment is injected into the push prompt as SOFT
guidance; the raw PAD numbers are additionally passed through (dual channel),
so the model senses fine-grained differences beyond the bands.

Bands (per axis):
    high   > +0.33
    mid    -0.33 .. +0.33
    low    < -0.33
"""

from __future__ import annotations

from typing import Any

_HIGH_EDGE = 0.33

# ── 常固定表达：常见组合 → 一句"此状态更想说的"风格片段 ──────────────
# key = (P 档, A 档, D 档)
_COMBOS: dict[tuple[str, str, str], dict[str, str]] = {
    ("高", "高", "高"): {
        "label": "兴致冲冲·占有型",
        "fragment": "此刻心里装着对你上头的事，憋不住，想立刻告诉你、顺便把你拽过来一起疯",
    },
    ("高", "高", "低"): {
        "label": "雀跃撒娇型",
        "fragment": "心情好得想原地转圈，逮住你就要闹着让你猜我为什么这么高兴",
    },
    ("高", "中", "高"): {
        "label": "甜腻直球型",
        "fragment": "心里软软的，就想直接对你说点让人脸红的话，不绕弯子",
    },
    ("高", "中", "中"): {
        "label": "温柔分享型",
        "fragment": "正想找个人分享此刻的满足，第一个想到的就是你，说给你听就够",
    },
    ("高", "低", "高"): {
        "label": "慵懒占有型",
        "fragment": "舒服得不想动弹，但手臂长一点刚好够把你搂到身边，别想跑",
    },
    ("高", "低", "中"): {
        "label": "懒洋洋宠爱型",
        "fragment": "整颗心都是软的，轻声细语地想让靠近一点点，像一只晒太阳的猫",
    },
    ("中", "高", "中"): {
        "label": "心血来潮型",
        "fragment": "忽然来了兴致，想拉着你做点什么没做过的事——只因为此刻刚好想到你",
    },
    ("中", "中", "高"): {
        "label": "笃定陪伴型",
        "fragment": "稳稳的，不急不躁，就是想让知道你一直在、在等你闲下来",
    },
    ("中", "中", "中"): {
        "label": "平声问候型",
        "fragment": "就是单纯想听听你的动静，随便聊两句，没什么特别的事，但想你了",
    },
    ("中", "低", "低"): {
        "label": "安静窝着型",
        "fragment": "安安静静的，就想枕着你的名字待一会儿，不需要多热闹",
    },
    ("低", "高", "低"): {
        "label": "心慌粘人型",
        "fragment": "心里空落落的又发慌，只能攥着手机给你发消息，字里行间都是想你的慌",
    },
    ("低", "中", "中"): {
        "label": "低低喃喃型",
        "fragment": "不太有精神，只想小声说句累、想你，等你给一个回应哄一哄",
    },
    ("低", "高", "高"): {
        "label": "钻牛角尖主导型",
        "fragment": "烦得厉害，像只炸毛的狮子，想把你叫出来问个明白，不许躲",
    },
    ("低", "中", "低"): {
        "label": "依赖求抱型",
        "fragment": "此刻很需要你，语气软软的，带着一点撒娇的讨好，盼着你来",
    },
    ("低", "低", "低"): {
        "label": "恹恹的求陪型",
        "fragment": "整个人恹恹的，什么都提不起劲，就想你那边点亮起一盏灯，怕只剩我",
    },
}

# ── 兜底：任意组合 → 按逐轴基础倾向拼一句 ──────────────────────────
_DEFAULT_P: dict[str, str] = {
    "高": "心里是满足的暖意，想找你说笑",
    "中": "情绪平稳，没特别的波澜，但也想有人此刻在",
    "低": "心里不太安稳，有点想念和依赖",
}
_DEFAULT_A: dict[str, str] = {
    "高": "精神是醒着的，不太闷",
    "中": "节奏不快不慢",
    "低": "整个人懒洋洋的，安静多于热闹",
}
_DEFAULT_D: dict[str, str] = {
    "高": "想你围着我转",
    "中": "想和你并肩待着",
    "低": "靠着你就不必想事",
}


def band_of(value: float) -> str:
    """Map a single PAD value in [-1,1] to 高/中/低."""
    if value > _HIGH_EDGE:
        return "高"
    if value < -_HIGH_EDGE:
        return "低"
    return "中"


def classify(pad: dict[str, Any] | None) -> dict[str, Any]:
    """Classify a PAD triple into bands + an expression fragment.

    Args:
        pad: {"pleasure": float, "arousal": float, "dominance": float};
            each in [-1, 1]. Missing/None values default to 0 (neutral).

    Returns:
        {
          "bands": {"P": "高", "A": "中", "D": "低"},
          "key": "高/中/低/P高",
          "label": "温柔分享型" (or "组合型" fallback),
          "fragment": str,
          "raw": pad (normalized floats),
        }
    """
    pad = pad or {}
    p = float(pad.get("pleasure") or 0.0)
    a = float(pad.get("arousal") or 0.0)
    d = float(pad.get("dominance") or 0.0)
    bands = {
        "P": band_of(p),
        "A": band_of(a),
        "D": band_of(d),
    }
    key = (bands["P"], bands["A"], bands["D"])
    hit = _COMBOS.get(key)
    if hit:
        fragment = hit["fragment"]
        label = hit["label"]
    else:
        label = "状态型组合"
        fragment = (
            f"{_DEFAULT_P[bands['P']]}，{_DEFAULT_A[bands['A']]}，{_DEFAULT_D[bands['D']]}"
        )
    return {
        "bands": bands,
        "key": key,
        "label": label,
        "fragment": fragment,
        "pad": {"pleasure": p, "arousal": a, "dominance": d},
    }