"""§十 场景池「世界地点硬约束」测试。

覆盖计划 §10.6 的验收项：
  1/2. outdoor=True/False → 单组内采样（100 次 100% 落组）
  3.   话题含"步行街" → 亲和生效，不再是纯随机
  4.   组级亲和：地点类词把整组室外权重抬起来
  5.   outdoor=None → 行为与改动前一致（不回归）
  6.   respect_world_location: false → 退回全摊平（回退开关）
  7.   约束分组为空 → 不空手（退回不分组）
"""

from __future__ import annotations

import random

import pytest

from core import image_scene_pool as pool


def _rng(seed: int):
    return random.Random(seed).random


def _reset_cache(monkeypatch, config_path):
    """把配置指向临时文件并清掉热加载缓存，避免污染其他用例。"""
    monkeypatch.setattr(pool, "_CONFIG_PATH", config_path)
    monkeypatch.setattr(pool, "_cache", None)
    monkeypatch.setattr(pool, "_cache_mtime", None)


# ── 1/2 · 硬约束：outdoor True/False 单组内采样 ─────────────────────────


def test_outdoor_constraint_never_crosses_group():
    """outdoor=True → 100 次采样全部落在 outdoor 组。"""
    rng = _rng(20260928)
    groups = {
        pool.select_scene(outdoor=True, rng=rng).get("group") for _ in range(100)
    }
    assert groups == {"outdoor"}


def test_indoor_constraint_never_crosses_group():
    """outdoor=False → 100 次采样全部落在 indoor 组。"""
    rng = _rng(424242)
    groups = {
        pool.select_scene(outdoor=False, rng=rng).get("group") for _ in range(100)
    }
    assert groups == {"indoor"}


def test_unconstrained_sampling_still_spans_both_groups():
    """outdoor=None → 不约束，两组都可能出现（= 改动前行为）。"""
    rng = _rng(7)
    groups = {pool.select_scene(rng=rng).get("group") for _ in range(200)}
    assert groups == {"indoor", "outdoor"}


def test_constraint_flags_are_reported():
    """诊断键：受约束时 constrained_by_world=True，且确实出现过被纠正的样本。"""
    rng = _rng(20260928)
    picks = [pool.select_scene(outdoor=True, rng=rng) for _ in range(100)]
    assert all(pick["constrained_by_world"] is True for pick in picks)
    # 不受约束时有相当比例会落 indoor，因此"被世界数据纠正"的样本不该为 0。
    assert any(pick["corrected_by_world"] is True for pick in picks)


def test_unconstrained_pick_reports_no_constraint():
    """outdoor=None → 不施加约束，诊断键为 False。"""
    pick = pool.select_scene(rng=_rng(1))
    assert pick["constrained_by_world"] is False
    assert pick["corrected_by_world"] is False


# ── 3 · 关键词亲和：步行街不再"零亲和" ───────────────────────────────


def test_walking_street_topic_is_no_longer_zero_affinity():
    """话题含"步行街" → 权重分布 != 空话题（§10.6 验收 3）。"""
    topic = "一抬头发现自己在步行街站了半小时 你说我是不是该找个地方坐坐"
    assert pool.scene_weights(topic) != pool.scene_weights("")


def test_walking_street_topic_boosts_street_scene():
    """步行街直接把风情街/街头散步两个场景的权重抬起来。"""
    topic = "一抬头发现自己在步行街站了半小时"
    baseline = pool.scene_weights("")
    boosted = pool.scene_weights(topic)
    assert boosted["hongyadong_street"] > baseline["hongyadong_street"]


def test_place_char_topic_boosts_whole_outdoor_group():
    """组级亲和：'路边'不命中任何具体场景关键词，也要把整组室外抬起来。"""
    baseline = pool.scene_weights("")
    boosted = pool.scene_weights("我在路边站着等了一会儿")
    outdoor_ids = [s["id"] for s in pool.list_scenes_unfiltered() if s["group"] == "outdoor"]
    indoor_ids = [s["id"] for s in pool.list_scenes_unfiltered() if s["group"] == "indoor"]
    assert all(boosted[scene_id] > baseline[scene_id] for scene_id in outdoor_ids)
    assert all(boosted[scene_id] == baseline[scene_id] for scene_id in indoor_ids)


# ── 5 · 无 world 快照：outdoor=None 不约束（不回归） ────────────────────


def test_none_constraint_matches_unfiltered_pool():
    """outdoor=None 时候选集合 == 全摊平列表（行为与改动前一致）。"""
    assert {s["id"] for s in pool.list_scenes(outdoor=None)} == {
        s["id"] for s in pool.list_scenes_unfiltered()
    }


# ── 6 · 回退开关 ─────────────────────────────────────────────────────


@pytest.fixture
def _switch_config(tmp_path):
    """写一份 respect_world_location: false 的临时场景池配置。"""
    config = tmp_path / "image_scenes.yaml"
    config.write_text(
        "default_region: chongqing\n"
        "respect_world_location: false\n"
        "regions:\n"
        "  chongqing:\n"
        "    indoor:\n"
        "      - id: a_indoor\n"
        "        name: 室内\n"
        "        weight: 1.0\n"
        "        keywords: [室内]\n"
        "        prompt: 室内画面\n"
        "    outdoor:\n"
        "      - id: b_outdoor\n"
        "        name: 室外\n"
        "        weight: 1.0\n"
        "        keywords: [室外]\n"
        "        prompt: 室外画面\n",
        encoding="utf-8",
    )
    return config


def test_switch_off_restores_unfiltered_sampling(monkeypatch, _switch_config):
    """respect_world_location: false → 即使 outdoor=True 也跨组采样。"""
    _reset_cache(monkeypatch, _switch_config)
    assert pool.respect_world_location() is False
    rng = _rng(99)
    groups = {pool.select_scene(outdoor=True, rng=rng).get("group") for _ in range(60)}
    assert groups == {"indoor", "outdoor"}


def test_switch_on_is_the_default(monkeypatch):
    """默认（真实配置）为 true —— 硬约束是默认行为。"""
    monkeypatch.setattr(pool, "_cache", None)
    monkeypatch.setattr(pool, "_cache_mtime", None)
    assert pool.respect_world_location() is True


# ── 7 · 约束分组为空时不空手 ─────────────────────────────────────────────


def test_empty_group_falls_back_to_unfiltered(tmp_path, monkeypatch):
    """配置里只有 indoor 时，outdoor=True 也必须选得出场景（不能空手）。"""
    config = tmp_path / "image_scenes.yaml"
    config.write_text(
        "default_region: chongqing\n"
        "respect_world_location: true\n"
        "regions:\n"
        "  chongqing:\n"
        "    indoor:\n"
        "      - id: only_indoor\n"
        "        name: 唯一室内\n"
        "        weight: 1.0\n"
        "        keywords: [室内]\n"
        "        prompt: 室内画面\n",
        encoding="utf-8",
    )
    _reset_cache(monkeypatch, config)
    pick = pool.select_scene(outdoor=True, rng=_rng(3))
    assert pick.get("id") == "only_indoor"
    # 退回了不分组采样 → 不再声称"受世界约束"
    assert pick["constrained_by_world"] is False
