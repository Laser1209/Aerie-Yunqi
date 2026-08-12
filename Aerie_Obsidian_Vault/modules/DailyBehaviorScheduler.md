---
title: DailyBehaviorScheduler
kind: module_note
status: Implemented
updated_at: 2026-08-13
owners:
  - CORE
related_modules:
  - WorldSimulation
  - Movement
  - HomeSpace
tags:
  - module
  - world/behavior
---

# DailyBehaviorScheduler — 时序行为调度与每日规划

> [!info] 定位
> 行为多样性的引擎 = **每日规划**（跨天一次性生成），而非时间档位数量。7 档时间（`world_phase.py`）只承担"氛围/光线细分"。

## 时间档单一真源（world_phase.py）

7 档：`dawn 05–07 / morning 07–12 / noon 12–14 / afternoon 14–18 / evening 18–21:30 / late_evening 21:30–23:30 / night 23:30–05:00`。

收拢全库 phase 定义（加档位只改一处）：
- `DEFAULT_WORLD_PHASES`（location/activity/energy/social）
- `TIME_OF_DAY_CN` / `TIME_OF_DAY_LIGHT_CN`（中文/光线翻译）
- `PHASE_ZONE`（phase→zone，home_space 引用）
- `phase_for_hour(hour)`

consumers：`world_simulation.py`（import DEFAULT_WORLD_PHASES）、`home_space.py`（import PHASE_ZONE）、`companion.py`（`_time_of_day_phase` → `phase_for_hour`，翻译表 import，月相集合补 `late_evening`）。

## 行为资源库（behavior_library.py）

`Behavior { obj_id, zone_id, behavior_desc, duration_min, energy_delta, social, visual_topic }`

- 起步 33 条：7 活跃 zone（living/kitchen/studio/master_bedroom/master_bath/balcony/dining）× 3-6 条。
- **visual_topic 值域契约**：必须命中翻译表键（活动话题 14 键 / OBJ-xxx），`validate_visual_topics()` 校验，杜绝英文 token 进生图。
- 未绑定 zone 走通用 fallback（防空池）。

## 每日规划（daily_planner.py）

`DailyPlan { date, slots: [{start,end,phase,zone,obj_id,behavior_desc,visual_topic,source}] }`，持久化 `data/daily_plan.json`（跨天覆盖，原子写）。

- **跨天一次性生成**：每 phase 从该 zone 行为池加权随机选（同日不重复），写入决策日志埋点 2（kind=behavior）。
- **动机句按需**：不为每个 slot 预生成；主动消息/被问"你在干什么"时才由上层补动机句（默认 0 调用/天）。
- **局部重规划**：`slot_for_now` 在计划过期/空洞时惰性重选单点 slot。
- **固定种子可复现**：`seed:日期` 驱动 random，同 seed 同日计划相同。

## 世界消费（companion.py）

`_run_world_loop` tick 后调 `_consume_daily_plan(snap)`：当前 slot 目标 zone ≠ 当前位置 → `movement_manager.move_to(current, target, reason=行为描述)`（决策埋点 3）。

## 文件

- `core/world_phase.py` — 时间档单一真源
- `core/behavior_library.py` — 行为资源库
- `core/daily_planner.py` — 每日规划
- `tests/test_behavior_planner.py` — 14 例

## 互链

- 模块入口：[[01_模块总览]]
- 话题管控：[[TopicTracking]]
- 寻路感知：[[IndoorNavigation]]
- 房间数据：`ita-river-loft-room.design-project/`
