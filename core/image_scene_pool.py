"""生图「生活记录」场景池：按地域分组加载 + softmax 采样选场景。

设计要点：
- 场景池配置在 ``config/image_scenes.yaml``，按地域分组（indoor / outdoor）。
  找不到指定地域时回退 ``default_region``；未来加地域 = 只加 yaml 分组，零代码改动。
- 采样用 softmax(weight / temperature) 归一：话题亲和度只把命中关键词的场景权重
  乘一个亲和系数，**任何场景概率都不为 0**，不存在「命中则用关联场景，否则随机」的硬分支。
- 热加载：每次取用按文件 mtime 判断是否重新解析；解析失败不抛错，退回内置默认。
- RNG 依赖注入：``select_scene(..., rng=...)`` 接收 ``Callable[[], float]``（返回 [0,1)），
  便于固定 seed 测试；缺省用 ``random.random``。
"""

from __future__ import annotations

import logging
import math
import random
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config" / "image_scenes.yaml"

# 配置文件缺失/解析失败时的内置兜底（仅保证有可用场景，不复刻全量清单）。
_DEFAULT_REGION = "chongqing"
_DEFAULT_SAMPLING: dict[str, float] = {"temperature": 1.0, "affinity_boost": 2.5}
_BUILTIN_REGIONS: dict[str, dict[str, list[dict[str, Any]]]] = {
    _DEFAULT_REGION: {
        "indoor": [
            {"id": "wake_up", "name": "刚醒", "weight": 1.2, "keywords": ["刚醒", "起床"], "prompt": "她刚醒，靠在枕头上睁眼，晨光从窗帘缝里漏进来"},
            {"id": "watching_drama_sofa", "name": "沙发看剧", "weight": 1.3, "keywords": ["看剧", "沙发"], "prompt": "她窝在沙发上看剧，屏幕的光映在脸上"},
            {"id": "studio_work", "name": "工作室工作", "weight": 1.2, "keywords": ["工作", "电脑"], "prompt": "她坐在工作室书桌前对着电脑工作"},
        ],
        "outdoor": [
            {"id": "noodle_shop", "name": "楼下小吃店", "weight": 1.3, "keywords": ["小面", "小吃店"], "prompt": "她坐在重庆楼下的小吃店里吃一碗红油小面"},
        ],
    },
}

# 场景池缓存：按 (mtime) 判断是否需要重新解析。
_cache: dict[str, Any] | None = None
_cache_mtime: float | None = None


def _builtin_config() -> dict[str, Any]:
    """构造内置兜底配置（结构同 _normalize_config 的产出）。"""
    regions: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for region_name, groups in _BUILTIN_REGIONS.items():
        regions[region_name] = {
            group_name: [_normalize_scene(item, group_name, region_name) for item in scenelist]
            for group_name, scenelist in groups.items()
        }
    return {
        "default_region": _DEFAULT_REGION,
        "sampling": dict(_DEFAULT_SAMPLING),
        "regions": regions,
    }


def _normalize_scene(raw: Any, group: str, region: str) -> dict[str, Any]:
    """把单个场景条目归一为统一结构；缺 id/name 视为无效，返回空 dict。"""
    if not isinstance(raw, dict):
        return {}
    scene_id = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or "").strip()
    if not scene_id or not name:
        return {}
    keywords_raw = raw.get("keywords")
    keywords = [str(k).strip() for k in keywords_raw if str(k).strip()] if isinstance(keywords_raw, list) else []
    try:
        weight = float(raw.get("weight", 1.0))
    except (TypeError, ValueError):
        weight = 1.0
    return {
        "id": scene_id,
        "name": name,
        "weight": max(0.0, weight),
        "keywords": keywords,
        "prompt": str(raw.get("prompt") or "").strip(),
        "group": group,
        "region": region,
    }


def _normalize_sampling(raw: Any) -> dict[str, float]:
    """归一采样参数，保证 temperature/affinity_boost 为正数。"""
    if not isinstance(raw, dict):
        return dict(_DEFAULT_SAMPLING)
    try:
        temperature = float(raw.get("temperature", _DEFAULT_SAMPLING["temperature"]))
    except (TypeError, ValueError):
        temperature = _DEFAULT_SAMPLING["temperature"]
    try:
        affinity = float(raw.get("affinity_boost", _DEFAULT_SAMPLING["affinity_boost"]))
    except (TypeError, ValueError):
        affinity = _DEFAULT_SAMPLING["affinity_boost"]
    return {
        "temperature": temperature if temperature > 0 else _DEFAULT_SAMPLING["temperature"],
        "affinity_boost": affinity if affinity > 0 else _DEFAULT_SAMPLING["affinity_boost"],
    }


def _normalize_config(raw: Any) -> dict[str, Any] | None:
    """把 yaml 原文归一为内部结构；无有效场景时返回 None。"""
    if not isinstance(raw, dict):
        return None
    default_region = str(raw.get("default_region") or "").strip() or _DEFAULT_REGION
    sampling = _normalize_sampling(raw.get("sampling") if isinstance(raw.get("sampling"), dict) else raw)
    regions_raw = raw.get("regions")
    if not isinstance(regions_raw, dict):
        return None
    regions: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for region_name, groups in regions_raw.items():
        if not isinstance(groups, dict):
            continue
        normalized_groups: dict[str, list[dict[str, Any]]] = {}
        for group_name in ("indoor", "outdoor"):
            scenelist = groups.get(group_name)
            if not isinstance(scenelist, list):
                continue
            scenes = [
                scene
                for scene in (_normalize_scene(item, group_name, str(region_name)) for item in scenelist)
                if scene
            ]
            if scenes:
                normalized_groups[group_name] = scenes
        if normalized_groups:
            regions[str(region_name)] = normalized_groups
    if not regions:
        return None
    return {"default_region": default_region, "sampling": sampling, "regions": regions}


def _load_config() -> dict[str, Any]:
    """读取并热加载场景池配置；失败退回内置默认，绝不抛错。"""
    global _cache, _cache_mtime
    try:
        mtime = _CONFIG_PATH.stat().st_mtime
    except OSError:
        # 文件不存在：用内置默认（不写缓存，下次仍尝试读盘）。
        return _builtin_config()
    if _cache is not None and _cache_mtime is not None and mtime <= _cache_mtime:
        return _cache
    try:
        raw = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.exception("image_scenes.yaml 解析失败，退回内置默认场景池")
        return _builtin_config()
    config = _normalize_config(raw)
    if config is None:
        logger.warning("image_scenes.yaml 无有效场景，退回内置默认场景池")
        return _builtin_config()
    _cache = config
    _cache_mtime = mtime
    return config


def get_sampling_config() -> dict[str, float]:
    """返回采样参数（temperature / affinity_boost），供前端与测试读取。"""
    return dict(_load_config().get("sampling") or _DEFAULT_SAMPLING)


def _resolve_region(config: dict[str, Any], region: str) -> str:
    """解析目标地域：显式指定优先，找不到回退 default_region。"""
    regions = config.get("regions") or {}
    requested = str(region or "").strip()
    if requested and requested in regions:
        return requested
    default_region = str(config.get("default_region") or "").strip()
    if default_region and default_region in regions:
        return default_region
    return next(iter(regions), _DEFAULT_REGION)


def load_regions(region: str = "") -> dict[str, list[dict[str, Any]]]:
    """加载某地域的场景池，返回 ``{"indoor": [...], "outdoor": [...]}``。

    地域缺省或找不到时回退 ``default_region``。
    """
    config = _load_config()
    regions = config.get("regions") or {}
    groups = regions.get(_resolve_region(config, region)) or {}
    return {
        "indoor": list(groups.get("indoor") or []),
        "outdoor": list(groups.get("outdoor") or []),
    }


def list_scenes(region: str = "") -> list[dict[str, Any]]:
    """把某地域的室内+室外场景摊平成单一列表。"""
    groups = load_regions(region)
    return [*groups["indoor"], *groups["outdoor"]]


def scene_weights(topic_text: str = "", region: str = "") -> dict[str, float]:
    """计算场景权重：命中话题关键词的场景权重乘亲和系数（只改权重，不清零）。"""
    affinity = float(get_sampling_config().get("affinity_boost") or _DEFAULT_SAMPLING["affinity_boost"])
    text = str(topic_text or "")
    weights: dict[str, float] = {}
    for scene in list_scenes(region):
        weight = float(scene.get("weight", 1.0))
        keywords = scene.get("keywords") or []
        if text and any(kw and kw in text for kw in keywords):
            weight *= affinity
        weights[str(scene["id"])] = weight
    return weights


def softmax_probabilities(weights: list[float], temperature: float) -> list[float]:
    """对权重做 softmax(weight / temperature) 归一，数值稳定且每项恒 > 0。"""
    if not weights:
        return []
    tau = float(temperature)
    if not math.isfinite(tau) or tau <= 0:
        tau = _DEFAULT_SAMPLING["temperature"]
    peak = max(weights)
    exps = [math.exp((float(w) - peak) / tau) for w in weights]
    total = sum(exps)
    if total <= 0:
        return [1.0 / len(weights)] * len(weights)
    return [e / total for e in exps]


def scene_probabilities(topic_text: str = "", region: str = "") -> dict[str, float]:
    """返回各场景的采样概率（softmax 后），用于前端展示与测试断言。"""
    scenes = list_scenes(region)
    if not scenes:
        return {}
    weights = scene_weights(topic_text, region)
    ordered = [float(weights.get(str(scene["id"]), scene.get("weight", 1.0))) for scene in scenes]
    temperature = float(get_sampling_config().get("temperature") or _DEFAULT_SAMPLING["temperature"])
    probs = softmax_probabilities(ordered, temperature)
    return {str(scene["id"]): prob for scene, prob in zip(scenes, probs)}


def select_scene(
    topic_text: str = "",
    region: str = "",
    rng: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """softmax 采样选一个场景，返回含 id/name/prompt 的 dict；无场景时返回空 dict。

    ``rng`` 为依赖注入的随机源（返回 [0,1) 的可调用对象），缺省 ``random.random``。
    """
    scenes = list_scenes(region)
    if not scenes:
        return {}
    weights = scene_weights(topic_text, region)
    ordered = [float(weights.get(str(scene["id"]), scene.get("weight", 1.0))) for scene in scenes]
    temperature = float(get_sampling_config().get("temperature") or _DEFAULT_SAMPLING["temperature"])
    probs = softmax_probabilities(ordered, temperature)
    draw = float((rng or random.random)())
    cumulative = 0.0
    chosen = scenes[-1]
    for scene, prob in zip(scenes, probs):
        cumulative += prob
        if draw < cumulative:
            chosen = scene
            break
    return dict(chosen)
