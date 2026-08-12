---
title: IndoorNavigation
kind: module_note
status: Implemented
updated_at: 2026-08-13
owners:
  - CORE
related_modules:
  - HomeSpace
  - DailyBehaviorScheduler
  - WorldSimulation
tags:
  - module
  - world/navigation
---

# IndoorNavigation — 环境寻路感知系统

> [!info] 定位
> 蓝点在地图内**行进**（非瞬移），对话中可感知"正在移动/目标/周边物件"。三层分离：**叙事层**（zone BFS 路径，进 LLM 上下文）+ **呈现层**（坐标 waypoint 避障路径，前端渲染）+ **证据层**（movement 决策日志）。

## zone 连通图（home_space.py）

`ZONE_ADJACENCY` 邻接表（bounds 相邻校正）：
- 一层链式：`entrance ↔ stair ↔ living ↔ dining ↔ kitchen ↔ guest_bath`；`living ↔ balcony`
- 跨层仅 `stair ↔ corridor`（楼梯）
- 二层：`corridor ↔ studio ↔ master_bedroom ↔ master_bath ↔ closet ↔ bridge`

`path_between(from, to)` BFS 最短路径（例：`living→stair→corridor→master_bedroom`）。

## 避障寻路（navigation_data.py）

- **障碍表**：从设计 JSON `objects` 按 category 派生大件（≤24 个，AABB + 0.3m 人宽膨胀）；`openings` 门洞为可选连接点。数据缺失安全降级为空。
- **几何**：Liang-Barsky 线段-矩形相交（`segment_hits_obstacles`）。
- **A***：waypoint 图上互可见建边 + 欧氏启发（`a_star_path`）；无路回退直连。
- **视线拉直**：string pulling（`straighten_path`）。
- **高层**：`coordinate_route(from, to)` 输出 zone 路径 + 坐标 waypoints。

## 移动状态机（movement.py）

`MovementManager`：
- `move_to(from, to, reason)` 发起（一次性算 path + waypoints），写决策日志埋点 3（kind=movement）。
- **实时派生**：`snapshot()` 按注入 clock() 推进 progress（每段 `clamp(段距/1.5m/s, 15s, 120s)`），**不进确定性快照缓存**（防破坏 tick 幂等）；禁 `datetime.now()`。
- **PHASE_ZONE 优先级**：移动中 `current_zone` 派生优先于静态映射，防 tick 位置回跳。
- **重启即复位**：restore 不补时序字段，轨迹保留在 `movement_log`。

## 位置联动对话

- `_world_snapshot_for_context` 附加 `movement` 字段 + 移动中覆盖 zone/position_desc。
- `context_builder` world 段注入叙事层："移动中：她正在从客厅走向主卧，准备去睡觉"（只暴露 from/to/reason，不暴露避障细节）。
- 周边物件：`nearby_objects` 按 `path[current_idx]` zone 派生（不 find_zone 反推，防 bounds 重叠抖动）。

## 前端蓝点行进（Electron）

- `world-dashboard-window.html`：`#wdw-map-path` SVG overlay（viewBox 1400×980）。
- `world-dashboard-window.js`：`toSvg(level,x,y)` 米制换算 + 折线渲染 + 蓝点按 `pathLength × progress` 插值。
- 障碍数据唯一真源 = JSON 米制坐标；SVG 仅呈现层。

## 文件

- `core/home_space.py` — zone 邻接 + BFS
- `core/navigation_data.py` — 避障寻路
- `core/movement.py` — 移动状态机
- `tests/test_navigation.py` — 29 例

## 互链

- 模块入口：[[01_模块总览]]
- 话题管控：[[TopicTracking]]
- 行为调度：[[DailyBehaviorScheduler]]
- 计划：[[对话话题·行为调度·寻路感知系统修缮计划]]
