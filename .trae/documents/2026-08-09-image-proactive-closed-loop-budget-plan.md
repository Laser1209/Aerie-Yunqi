---
title: 主动发图生产闭环 + 统一预算（本地自记账）+ 每日限额方案
date: 2026-08-09
tags:
  - plan
  - image
  - proactive
  - budget
  - closed-loop
aliases:
  - 主动发图闭环与预算方案
status: draft
version: v0.1
---

# 主动发图生产闭环 + 统一预算（本地自记账）+ 每日限额方案

> [!abstract] 一句话结论
> 主动发图的生产闭环（世界侧候选 → Core 审批 → 派发）在代码里**已经存在**，缺的是"图片服务真正打通 + 统一记账 + 用户可配的每日限额"三块。统一预算走**本地自记账**（与中转站 provider 解耦，最稳）；每日限额只作用于**主动/自动发图**链路。本方案只做规划与可行性研判，**不写代码**。

---

## 1. 需求整理（From User）

| # | 需求点 | 用户原话（整理） | 本方案处置 |
|---|--------|------------------|-----------|
| R1 | 打通生产闭环 | 世界侧候选 → Core 审批 → 派发 全链路跑通 | ✅ 纳入（链路已存在，补全图片服务与记账） |
| R2 | 统一预算 + 查余额 | 能否通过 API 看剩余余额 | ✅ 改为**本地自记账**为主（用户已确认） |
| R3 | 专属提示词 | 设定相关，**先等会再讲** | ⏸️ 延后，见 §7 |
| R4 | 图生图 + 文生图 | 两种都要，准备两类 | ✅ 纳入（provider 双模式 + 优雅降级） |
| R5 | 每日限额 | 设置页下拉：6 / 10 / 20 / 不限，数量由用户自填 | ✅ 纳入（仅主动/自动发图，用户已确认） |

---

## 2. 现状分析（Current State）

### 2.1 主动发图闭环（已存在）
```
世界侧 WorldImageCandidate
  → Core WorldImageCandidateConsumer 审批/拒绝
      ├─ PushPolicy.can_push()  频控（每日上限/最小间隔/静默期/退避）
      └─ ProactiveJudge.evaluate()  加权打分
  → ImageWorkflow.generate_image()  生成
      └─ 幂等 / 安全检查 / 资产落盘 / 派发计划
```

- 核心文件：
  - [image_service.py](file:///e:/Agent_reply/core/image_service.py) — `ImageWorkflow.generate_image()`（幂等、安全、资产、派发计划四段式）
  - [world_image_candidates.py](file:///e:/Agent_reply/core/world_image_candidates.py) — `WorldImageCandidateConsumer`（审批与 ACK）
  - [push_scheduler.py](file:///e:/Agent_reply/core/push_scheduler.py) — `PushPolicy`（现有全局频控，含每日上限 `max_per_day` 等）
  - [proactive_judge.py](file:///e:/Agent_reply/core/proactive_judge.py) — 加权打分

### 2.2 图片服务现状（真实配置）
- 生产图片 provider 是**第三方 OpenAI 兼容中转站**：
  - `IMAGE_GEN_BASE_URL=https://image2.inian.one/v1`
  - `IMAGE_GEN_MODEL=gpt-image-2`
  - 见 [brain.py](file:///e:/Agent_reply/core/brain.py) `_brain_generate_image`：仅实现 `POST /images/generations`（**文生图**）
- **图生图缺失**：当前 `generate_image` 只调 `/images/generations`，无 `/images/edits`（OpenAI 兼容的图生图端点）或 `image` 参考图参数。
- **余额查询**：中转站的余额接口**非标准**，能否查取决于该站点是否暴露 `/v1/balance` / `/user/info` 等端点，**静态无法确认**。→ 这是 R2 选择"本地自记账"的根本原因。
- `txt2img` / `img2img` / `seedream` 技能均为 stub，未接真实后端（[skills/local/txt2img/run.py](file:///e:/Agent_reply/skills/local/txt2img/run.py)、[skills/local/img2img/run.py](file:///e:/Agent_reply/skills/local/img2img/run.py)、[skills/cloud/byted-seedream/run.py](file:///e:/Agent_reply/skills/cloud/byted-seedream/run.py)）。

### 2.3 设置页现状
- 主动推送开关：`setting-proactive` 复选框
  - 位置：[index.html](file:///e:/Agent_reply/electron/src/renderer/index.html)（约 L1116-1119）
  - 读写：[settings.js](file:///e:/Agent_reply/electron/src/renderer/js/settings.js) `load()` / `save()`，走 `/api/settings` GET/PUT
  - 后端：[api_server.py](file:///e:/Agent_reply/core/api_server.py) `settings_get` / `settings_put`（YAML + 默认值合并）
- YAML 直接编辑入口已存在（`/api/config/yaml`，可编辑 settings.yaml / proactive.yaml）

---

## 3. 可行性研判（Feasibility Assessment）

### 3.1 与主流做法对比

| 维度 | 主流实践 | 本项目方案 | 可行性 |
|------|----------|-----------|--------|
| 预算/配额 | 云平台自带余额 API（SiliconFlow `/v1/user/info` 返回 balance；OpenAI `/dashboard/billing/credit_grants`） | 本地自记账（按实际生成次数计），不依赖 provider 余额接口 | ✅ 高。与 provider 解耦，任何图生图/文生图都统一计 |
| 图生图 | SiliconFlow `/v1/images/generations` 原生支持 `image` 参考图；OpenAI 用 `/images/edits` | 在 `ImageWorkflow` 增加 i2i 路径，provider 按能力优雅降级 | ⚠️ 中。当前中转站是否支持 `/images/edits` **需运行时探测**，不支持则返回 unavailable 并在 UI 提示 |
| 每日限额 | 产品端通常做用户可配的限额（如 6/10/20/不限） | 设置页下拉，仅约束主动/自动发图链路 | ✅ 高。复用现有 PushPolicy 与 JSON 状态持久化模式 |
| 闭环 | 候选生成 → 审批 → 派发 → 反馈 → 退避 | 链路已存在（World→Core→Delivery），补全记账与限额 | ✅ 高 |

### 3.2 关键风险与对策

| 风险 | 说明 | 对策 |
|------|------|------|
| 余额接口不确定 | 中转站无标准余额接口 | 已选**本地自记账**，彻底绕开该依赖；设置页显示"今日已用/上限"，不承诺显示钱数 |
| 图生图支持不确定 | 中转站可能不支持 `/images/edits` | 增加运行时能力探测 + 优雅降级：不支持则返回 `unavailable`，不中断闭环 |
| 限额作用域 | 易误伤用户主动生成 | 已确认**仅主动/自动发图**；用户手动触发生成不扣主动额度 |

---

## 4. 总体方案（Proposed Design）

**三个独立但配套的改动：**

1. **本地记账层 `ImageBudget`（新模块）**：按日、按类别（主动/自动）统计图片生成次数，JSON 状态持久化（沿用 `proactive_policy_state.json` 的成熟模式）。提供"记账 +1 / 读今日用量 / 读配置上限 / 是否可发"。
2. **每日限额接入主动链路 + 设置页控制**：`config/settings.yaml` 增加配置项，前端下拉（6/10/20/不限），`WorldImageCandidateConsumer` 在审批前检查额度。
3. **图生图 + 文生图双模式**：`ImageWorkflow` 增加 i2i 生成路径；`brain.py` 增加 `/images/edits`（或 `image` 参数）的 best-effort 调用 + 降级。

---

## 5. 具体改动（Proposed Changes）

> 变更均遵循项目约定：最小改动、路由文件不动、新逻辑独立文件、面向用户文案中英双语、代码级标识符用英文。

### 5.1 新增 `core/image_budget.py`（本地自记账）
- **做什么**：统一记账组件，与 provider 解耦。
- **为什么**：R2 定为本地自记账；需要一个稳定、可持久化、可测试的计数器。
- **怎么做**：
  - `class ImageBudget`，`__init__(state_path, clock, enabled)`。
  - 状态 JSON：`{"today": "YYYY-MM-DD", "proactive_used": int, ...}`，跨天自动归零（复用 [push_scheduler.py](file:///e:/Agent_reply/core/push_scheduler.py) 的 `today != self.today → 重置` 逻辑）。
  - 方法：`record(kind)` 记账+1；`used(kind)` 读今日已用；`limit()` 读配置上限；`can_record(kind)` → `(bool, reason)`；`_persist()` 落盘。
  - 类别目前只细分 `proactive`（主动/自动），预留 `manual`（用户触发，不计入主动额度）便于扩展。

### 5.2 `config/settings.yaml` 增加限额配置
- **做什么**：新增 `proactive.image_max_per_day`（0 表示不限制），默认给一个值（建议 `10`，与下拉档位一致）。
- **为什么**：给设置页与记账层一个单一配置来源（沿用 `/api/settings` + YAML 合并机制）。
- **怎么做**：在 `proactive:` 段下新增键，并在 [settings.js](file:///e:/Agent_reply/electron/src/renderer/js/settings.js) `load()/save()` 中同步读写。

### 5.3 设置页前端：每日主动发图上限下拉
- **文件**：[index.html](file:///e:/Agent_reply/electron/src/renderer/index.html)（主动推送开关附近）+ [settings.js](file:///e:/Agent_reply/electron/src/renderer/js/settings.js)。
- **做什么**：新增下拉 `setting-proactive-image-limit`，选项 `6 / 10 / 20 / 不限`；`load()` 回填当前值，`save()` 写入 `proactive.image_max_per_day`。
- **为什么**：R5 明确要求"设置页加一个控制，一天 6/10/20/不限"。
- **怎么做**：UI 状态即时更新，保存走 `PUT /api/settings`（沿用现有模式，不新增路由）。

### 5.4 主动链路接入限额 + 记账
- **文件**：[world_image_candidates.py](file:///e:/Agent_reply/core/world_image_candidates.py)（`WorldImageCandidateConsumer`）。
- **做什么**：审批/派发前调用 `ImageBudget.can_record("proactive")`，不通过则拒绝并 ACK（reason 含 `daily_image_limit`）；每次成功生成后 `record("proactive")`。
- **为什么**：R5 仅约束主动/自动链路；这里是主动发图必经之地。
- **怎么做**：注入 `image_budget`（构造参数可选，保持向后兼容，参考现有 `push_policy` 注入方式）；不修改路由文件。

### 5.5 图生图 + 文生图双模式
- **文件**：[image_service.py](file:///e:/Agent_reply/core/image_service.py) + [brain.py](file:///e:/Agent_reply/core/brain.py)。
- **做什么**：`ImageWorkflow` 增加 `generate_image_edit`（或 `generate_image(..., reference_assets=...)`）路径；`brain._brain_generate_image` 增加图生图分支。
- **为什么**：R4 要求文生图与图生图两类。
- **怎么做**：
  - brain 侧：优先探测 `/images/edits`（OpenAI 兼容，`image` + `prompt`）；或对支持 `image` 参数的生成端点传 `image` 参考图 URL。
  - 探测/调用失败 → 返回 `{"status":"unavailable","error_code":"image_edit_unsupported"}`，`ImageWorkflow` 记录并优雅返回，**不中断闭环**。
  - 沿用幂等、安全检查、资产落盘、派发计划四段式。

### 5.6 预算读口（供设置页展示）
- **文件**：[api_server.py](file:///e:/Agent_reply/core/api_server.py)。
- **做什么**：让设置页能读到"今日主动已用 / 上限"。
- **怎么做**：在现有 `/api/settings` 返回体或一个只读字段中附带 `proactive.image_used_today` 与 `proactive.image_max_per_day`（**只读不改写**，不新增复杂路由）。

---

## 6. 假设与决策（Assumptions & Decisions）

| 决策 | 内容 |
|------|------|
| 统一预算 | 本地自记账为主（用户确认）；不依赖中转站余额接口 |
| 限额作用域 | 仅主动/自动发图（用户确认）；用户手动生成不扣主动额度 |
| 限额默认值 | `image_max_per_day` 默认 `10`，档位 6/10/20/不限 |
| 图生图策略 | best-effort：支持则用，不支持则 `unavailable` 降级，不硬依赖 |
| 延后项 | 专属提示词（R3）不在本方案实现，等用户讲"设定"后再补 |
| 后端路由 | 不改动任何 route 文件 |
| 状态持久化 | 沿用 JSON 文件模式（如 `data/proactive_policy_state.json`、`.image_assets/image_workflows.json`） |

---

## 7. 延后事项（Deferred）

- **R3 专属提示词 / 设定**：用户明确"先等会再讲"，本方案不做。后续可落为 `persona_behavior.yaml` 或专属 prompt 模板，待设定讨论后单独规划。

---

## 8. 验证步骤（Verification）

> 沿用项目既有验证方式（backend pytest + Electron 单测 + E2E）。

1. **后端单测**：新增 `tests/test_image_budget.py`，覆盖：跨天归零、`record/used/limit/can_record`、`image_max_per_day=0` 表示不限。
2. **主动链路测试**：`tests/test_phase14_world_image_candidates.py` 增补用例——额度耗尽时拒绝并 ACK `daily_image_limit`；额度内成功生成后 `used` 递增。
3. **设置读写测试**：校验 `/api/settings` GET 回填、PUT 后 YAML 中 `proactive.image_max_per_day` 正确落盘。
4. **i2i 降级测试**：mock provider 不支持 `/images/edits` → 返回 `unavailable`，闭环不中断。
5. **E2E 冒烟**：Electron 设置页新增下拉可见、可保存、可回填；主动发图在达到上限后停止。
6. 跑通后端全量 pytest + Electron 单测，确认无回归。

---

## 9. 待确认/下一步

- 默认上限值 `10` 是否合适（可改）。
- 是否需要在设置页"主动推送"下同时展示"今日已用 X / 上限 Y"（预算可见性，用户偏好图表/数字优先展示，建议做）。
- 等用户确认本方案后，再进入实现（当前为 Plan 阶段，未写代码）。
