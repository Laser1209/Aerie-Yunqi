"""阶段2 · 生图生活记录场景池测试：固定 seed 分布检验。"""

import random

from core import image_scene_pool as pool


def _rng(seed: int):
    """构造固定 seed 的 RNG 可调用对象，注入 select_scene 保证可复现。"""
    return random.Random(seed).random


def test_region_group_split_is_18_indoor_14_outdoor():
    """场景池按地域分组：重庆室内 18 + 室外 14。"""
    groups = pool.load_regions()
    assert len(groups["indoor"]) == 18
    assert len(groups["outdoor"]) == 14


def test_unknown_region_falls_back_to_default():
    """找不到指定地域时回退 default_region。"""
    assert pool.load_regions("nowhere") == pool.load_regions()


def test_sampling_covers_at_least_three_scenes():
    """① 连续采样 N 次，覆盖的场景类别数 ≥ 3。"""
    rng = _rng(20260927)
    seen = {pool.select_scene(rng=rng)["id"] for _ in range(3000)}
    assert len(seen) >= 3


def test_every_configured_scene_has_positive_probability():
    """② 每个已配置场景的概率 > 0（softmax 无概率为 0 的场景）。"""
    probabilities = pool.scene_probabilities()
    configured_ids = {scene["id"] for scene in pool.list_scenes()}
    assert set(probabilities) == configured_ids
    assert all(prob > 0 for prob in probabilities.values())


def test_same_seed_is_reproducible():
    """③ 固定 seed 下结果可复现（两次相同 seed 序列一致）。"""

    def sample() -> list[str]:
        rng = _rng(1234)
        return [pool.select_scene(rng=rng)["id"] for _ in range(200)]

    assert sample() == sample()


def test_low_temperature_concentrates_distribution():
    """④ τ 很小 → 分布更集中于高权重场景（最大概率更大）。"""
    weights = [2.0, 1.0, 1.0, 0.8]
    concentrated = max(pool.softmax_probabilities(weights, 0.05))
    flattened = max(pool.softmax_probabilities(weights, 5.0))
    assert concentrated > flattened


def test_topic_keyword_hit_raises_weight():
    """⑤ 话题关键词命中时，对应场景权重上升，整体平均权重随之上升。"""
    target = next(scene for scene in pool.list_scenes() if scene.get("keywords"))
    keyword = str(target["keywords"][0])
    baseline = pool.scene_weights("")
    boosted = pool.scene_weights(keyword)
    assert boosted[target["id"]] > baseline[target["id"]]
    assert sum(boosted.values()) / len(boosted) > sum(baseline.values()) / len(baseline)
