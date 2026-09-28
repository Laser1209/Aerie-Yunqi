"""生图模型分级路由：按「画面信息量」四档选模型与分辨率（§八）。

**为什么需要它**

此前 ``jimeng_canvas.default_model()`` 只读一个环境变量 ``JIMENG_IMAGE_MODEL``，
``JimengCanvasImageGenerationProvider.model`` 在构造时固定 —— 也就是**自拍和海报
用的是同一个模型、同一个分辨率**。用户的原话是"不要一味用最高那一档"：

> 生成人像可以使用第 2 个以及第 3 个，在一些小的一部件可以使用第 4 个。
> 只有在信息量比较大的环境下（场景照片、用户指定画海报）再去调用第一个。

**分级口径**：不按"谁最重要"分，而按**画面里有多少信息要模型同时处理**分。
人像是单主体中等信息量、小部件是低信息量、场景/海报是高信息量。

| 档 | 名称 | 触发信号 |
|---|---|---|
| T1 | 信息量高 | 用户显式指定（海报/封面/设计稿）；``environment_object``；``shot == 远景`` |
| T2 | 人像·日常 | 人像类，且未命中 T3/T4 |
| T3 | 人像·写真感 | 人像类 + ``style ∈ artistic_styles``（氛围感/诱惑感/慵懒） |
| T4 | 低信息量·小部件 | ``focus`` 命中局部特写（手/腿/脚/腰/肩颈/背影/头发/脸/眼睛…） |

判定优先级见 :func:`decide`；规则与报价全部外置在 ``config/image_tiers.yaml``，
改一行即可换模型，零代码改动；``enabled: false`` 一键回落到"全局单模型"。

本模块**纯函数 + 热加载配置**，不 import companion / world_image_candidates，
避免循环依赖；需要特写部位集合时由调用方传入（见 :func:`decide` 的
``closeup_focus`` 参数）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config" / "image_tiers.yaml"

RELAY_PROVIDER = "relay"
JIMENG_PROVIDER = "jimeng"

# 兜底档位（配置缺失/解析失败时用）：人像日常 = 最常用、最便宜、质量够日常。
_DEFAULT_TIER_KEY = "t2_portrait"
_FALLBACK_TIER_KEYS = ("t2_portrait", "t1_high", "t3_artistic", "t4_detail", "t1_poster")

_BUILTIN_CONFIG: dict[str, Any] = {
    "enabled": True,
    "tiers": {
        "t1_high": {"label": "信息量高", "model": "seedream_5.0_pro", "resolution": "2K", "provider": JIMENG_PROVIDER},
        "t1_poster": {"label": "海报/封面", "model": "seedream_5.0_pro", "resolution": "4K", "provider": JIMENG_PROVIDER},
        "t2_portrait": {"label": "人像·日常", "model": "high_aes_general_v50_flash", "resolution": "2K", "provider": JIMENG_PROVIDER},
        "t3_artistic": {"label": "人像·写真感", "model": "jm_image_model_yc_mj82", "resolution": "2K", "provider": JIMENG_PROVIDER},
        "t4_detail": {"label": "低信息量·小部件", "model": "seedream_5.0_lite", "resolution": "2K", "provider": JIMENG_PROVIDER},
    },
    "credit_table": {},
    "poster_keywords": ["海报", "封面", "长图", "信息图", "宣传图", "设计稿", "图集", "排版"],
    "artistic_styles": ["氛围感", "诱惑感", "慵懒"],
    "persona_prompt_keys": ["role_selfie", "role_in_scene", "couple_photo"],
    "environment_prompt_keys": ["environment_object"],
    "fallback": {
        "t1_poster": ["t1_high", "t2_portrait", RELAY_PROVIDER],
        "t1_high": ["t2_portrait", RELAY_PROVIDER],
        "t3_artistic": ["t2_portrait", RELAY_PROVIDER],
        "t4_detail": ["t2_portrait", "t1_high", RELAY_PROVIDER],
        "t2_portrait": ["t1_high", RELAY_PROVIDER],
    },
    "max_fallback_steps": 1,
}

_cache: dict[str, Any] | None = None
_cache_mtime: float | None = None


@dataclass(frozen=True)
class ImageTier:
    """一个档位：模型 + 分辨率 + 生成通道。"""

    key: str
    model: str
    resolution: str
    provider: str
    label: str
    credits: int = 0

    def as_payload(self) -> dict[str, Any]:
        """写进 candidate / metadata 的结构（键名固定，便于透传与审计）。"""
        return {
            "tier": self.key,
            "label": self.label,
            "provider": self.provider,
            "jimeng_model": self.model,
            "jimeng_resolution": self.resolution,
            "credits": self.credits,
        }


def _str_list(raw: Any, default: list[str]) -> list[str]:
    if not isinstance(raw, list):
        return list(default)
    out = [str(x).strip() for x in raw if str(x).strip()]
    return out or list(default)


def _normalize_tier(key: str, raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    model = str(raw.get("model") or "").strip()
    if not model:
        return None
    resolution = str(raw.get("resolution") or "").strip()
    provider = str(raw.get("provider") or JIMENG_PROVIDER).strip().lower()
    return {
        "label": str(raw.get("label") or key).strip(),
        "model": model,
        "resolution": resolution,
        "provider": provider if provider else JIMENG_PROVIDER,
    }


def _normalize_fallback(raw: Any, tier_keys: list[str]) -> dict[str, list[str]]:
    """归一降级链：条目只能是已知档位键或 ``relay``，其余丢弃。"""
    allowed = set(tier_keys) | {RELAY_PROVIDER}
    out: dict[str, list[str]] = {}
    if isinstance(raw, dict):
        for key, chain in raw.items():
            if str(key) not in allowed or not isinstance(chain, list):
                continue
            steps = [str(x).strip() for x in chain if str(x).strip() in allowed]
            if steps:
                out[str(key)] = steps
    if not out:
        return {k: list(v) for k, v in _BUILTIN_CONFIG["fallback"].items() if k in set(tier_keys)}
    return out


def _normalize_config(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    tiers_raw = raw.get("tiers")
    tiers: dict[str, Any] = {}
    if isinstance(tiers_raw, dict):
        for key, value in tiers_raw.items():
            normalized = _normalize_tier(str(key), value)
            if normalized:
                tiers[str(key)] = normalized
    if not tiers:
        return None
    credit_table = raw.get("credit_table")
    try:
        max_steps = int(raw.get("max_fallback_steps", _BUILTIN_CONFIG["max_fallback_steps"]))
    except (TypeError, ValueError):
        max_steps = int(_BUILTIN_CONFIG["max_fallback_steps"])
    return {
        "enabled": bool(raw.get("enabled", True)),
        "tiers": tiers,
        "credit_table": credit_table if isinstance(credit_table, dict) else {},
        "poster_keywords": _str_list(raw.get("poster_keywords"), _BUILTIN_CONFIG["poster_keywords"]),
        "artistic_styles": _str_list(raw.get("artistic_styles"), _BUILTIN_CONFIG["artistic_styles"]),
        "persona_prompt_keys": _str_list(raw.get("persona_prompt_keys"), _BUILTIN_CONFIG["persona_prompt_keys"]),
        "environment_prompt_keys": _str_list(raw.get("environment_prompt_keys"), _BUILTIN_CONFIG["environment_prompt_keys"]),
        "fallback": _normalize_fallback(raw.get("fallback"), list(tiers)),
        "max_fallback_steps": max(0, max_steps),
    }


def _load_config() -> dict[str, Any]:
    """读取并热加载分档配置；失败退回内置默认，绝不抛错。"""
    global _cache, _cache_mtime
    try:
        mtime = _CONFIG_PATH.stat().st_mtime
    except OSError:
        return _BUILTIN_CONFIG
    if _cache is not None and _cache_mtime is not None and mtime <= _cache_mtime:
        return _cache
    try:
        raw = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.exception("image_tiers.yaml 解析失败，退回内置分档表")
        return _BUILTIN_CONFIG
    config = _normalize_config(raw)
    if config is None:
        logger.warning("image_tiers.yaml 无有效档位，退回内置分档表")
        return _BUILTIN_CONFIG
    _cache = config
    _cache_mtime = mtime
    return config


def enabled() -> bool:
    """总开关；关闭即回落"全局单模型"（= 改动前行为）。"""
    return bool(_load_config().get("enabled", True))


def tier_keys() -> list[str]:
    return list((_load_config().get("tiers") or {}).keys())


def _credits(config: dict[str, Any], model: str, resolution: str) -> int:
    table = config.get("credit_table") or {}
    per_model = table.get(model) if isinstance(table, dict) else None
    if not isinstance(per_model, dict):
        return 0
    try:
        return int(per_model.get(resolution, 0) or 0)
    except (TypeError, ValueError):
        return 0


def tier(key: str) -> ImageTier:
    """按 key 取档位；未知 key 回落默认档。"""
    config = _load_config()
    tiers = config.get("tiers") or {}
    raw = tiers.get(key) or tiers.get(_DEFAULT_TIER_KEY) or _BUILTIN_CONFIG["tiers"][_DEFAULT_TIER_KEY]
    actual_key = key if key in tiers else _DEFAULT_TIER_KEY
    return ImageTier(
        key=actual_key,
        model=str(raw.get("model") or ""),
        resolution=str(raw.get("resolution") or ""),
        provider=str(raw.get("provider") or JIMENG_PROVIDER),
        label=str(raw.get("label") or actual_key),
        credits=_credits(config, str(raw.get("model") or ""), str(raw.get("resolution") or "")),
    )


def decide(
    *,
    prompt_key: str = "",
    scene: str = "",
    spec: dict[str, Any] | None = None,
    user_raw: str = "",
    closeup_focus: Any = (),
) -> ImageTier:
    """按 §8.3 的优先级判定档位。纯函数、无 IO、可单测。

    优先级（从高到低，先命中先定）：
    1. 用户显式指定（海报/封面/设计）→ T1（4K）—— 用户意图压倒一切
    2. 局部特写 / 小部件 → T4
    3. 环境 / 大场景 → T1
    4. 人像 + 写真感风格 → T3
    5. 人像（其余）→ T2
    6. 兜底 → T2

    ``closeup_focus`` 由调用方传入特写部位集合（``companion._CLOSEUP_FOCUS_SET``），
    避免本模块反向依赖 companion。
    """
    key = str(prompt_key or "")
    text = str(user_raw or "")
    spec = spec if isinstance(spec, dict) else {}
    focus = str(spec.get("focus") or "").strip()
    shot = str(spec.get("shot") or "").strip()
    style = str(spec.get("style") or "").strip()

    config = _load_config()
    posters = config.get("poster_keywords") or []
    artistic = config.get("artistic_styles") or []
    persona_keys = set(config.get("persona_prompt_keys") or [])
    env_keys = set(config.get("environment_prompt_keys") or [])
    is_persona = key in persona_keys

    # 1. 用户显式指定（海报/封面/设计）—— 用户意图优先，压倒一切
    if text and any(word and word in text for word in posters):
        return tier("t1_poster")
    # 2. 局部特写 / 小部件
    if focus and (not closeup_focus or focus in closeup_focus):
        return tier("t4_detail")
    if not is_persona and shot in ("特写", "大特写"):
        return tier("t4_detail")
    # 3. 环境 / 大场景
    if key in env_keys or shot == "远景":
        return tier("t1_high")
    # 4. 人像 + 写真感风格
    if is_persona and style and style in artistic:
        return tier("t3_artistic")
    # 5./6. 人像（其余）与兜底
    return tier("t2_portrait")


def fallback_chain(current: ImageTier) -> list[ImageTier]:
    """失败降级链：返回当前档之后应依次尝试的档位。

    链尾的 ``relay`` 表示"转 gpt-image 中转"，由调用方处理（它不是即梦档位）。
    实际重试步数由 ``max_fallback_steps`` 约束 —— 即梦失败同样扣费，不能无限降级。
    """
    config = _load_config()
    raw_chain = (config.get("fallback") or {}).get(current.key) or []
    out: list[ImageTier] = []
    for step in raw_chain:
        if step == RELAY_PROVIDER:
            break
        out.append(tier(step))
    return out


def fallback_target(current: ImageTier) -> ImageTier | None:
    """本次失败后应改用哪一档；返回 None 表示直接转中转（或降级已用尽）。"""
    if not enabled():
        return None
    steps = int(_load_config().get("max_fallback_steps", 1) or 0)
    if steps <= 0:
        return None
    chain = fallback_chain(current)
    if not chain:
        return None
    nxt = chain[0]
    return nxt if nxt.key != current.key else None


def tier_from_candidate(candidate: dict[str, Any] | None) -> ImageTier | None:
    """读取候选上已由提示词层盖章的档位（``candidate["image_tier"]``）。"""
    payload = (candidate or {}).get("image_tier")
    if not isinstance(payload, dict):
        return None
    key = str(payload.get("tier") or "").strip()
    if not key:
        return None
    return tier(key)
