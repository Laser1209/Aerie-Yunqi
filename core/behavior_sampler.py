"""Aerie · 行为层采样器（阶段 5）.

统一「主动推送是否发射」这一**行为层**的唯一采样点：所有调制信号
（话题复现的 m / 主动判断与欲望的 score）都经同一 sigmoid 映射为概率 p，
再由同一 ``sample_once`` 抽取一次随机数。

边界（重要）：
- 意图选择层（``core/decision.py``）有自己独立的 softmax 采样，本模块**不涉入**，
  聊天层也不新增任何采样；
- 同一决策链只允许一个采样点：调用方（话题复现 / ProactiveJudge / DesireEngine）
  对同一次「是否发射」的决策只调用本模块一次。资源 / 防撞车类硬闸门
  （``user_recent_active`` < 5min、cooldown）不采样化，仍在各自模块内硬拦。

概率映射（``emit_probability``）：
    p = floor + (ceiling - floor) * sigmoid((value - reference) / tau)
归一化口径：sigmoid 保证 p 严格落在 (floor, ceiling) 内——floor > 0 使低信号
仍有非零发射概率（不被饿死），ceiling < 1 使高信号仍保留未发射样本（不是硬闸门）。
"""

from __future__ import annotations

import math
import random
from typing import Callable

# 默认概率上下限：低信号非零、高信号非必然。
DEFAULT_P_FLOOR = 0.02
DEFAULT_P_CEILING = 0.95


def clamp01(value: float) -> float:
    """把数值裁剪到 [0, 1]。"""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return 0.0
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def sigmoid(x: float) -> float:
    """标准 logistic；数值稳定版（避免 exp 溢出）。"""
    x = float(x)
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def emit_probability(
    value: float,
    *,
    reference: float,
    tau: float,
    floor: float = DEFAULT_P_FLOOR,
    ceiling: float = DEFAULT_P_CEILING,
) -> float:
    """调制信号 → 发射概率 p（唯一映射，供三个触发源复用）。

    ``reference`` 是概率拐点（``value == reference`` 时 p 位于上下限中点），
    ``tau`` 是温度：越小越接近硬阈值、越大越随机。``tau <= 0`` 退化为硬阈值
    （仅用于配置异常兜底，正常配置不使用）。
    """
    lo = float(floor)
    hi = float(ceiling)
    if hi < lo:
        lo, hi = hi, lo
    t = float(tau)
    if t <= 0:
        return hi if float(value) >= float(reference) else lo
    raw = sigmoid((float(value) - float(reference)) / t)
    p = lo + (hi - lo) * raw
    return max(lo, min(hi, p))


def sample_once(p: float, rng: Callable[[], float] = random.random) -> bool:
    """对概率 p 采样一次（同一决策只调用一次）。rng 可注入以固定 seed 复现。"""
    return float(rng()) < float(p)
