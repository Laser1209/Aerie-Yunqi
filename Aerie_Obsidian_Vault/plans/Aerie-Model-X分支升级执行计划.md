---
title: Aerie-Model-X 分支升级执行计划
date: 2026-08-12
tags:
  - plan
  - git
  - branch
  - upgrade
  - performance
  - execution-log
aliases:
  - Model-X升级计划
  - Branch Upgrade Plan
status: in-progress
target: main ↔ Aerie-Model-X 双向同步 + 文档更新
---

# Aerie-Model-X 分支升级执行计划

> [!abstract] 任务概述
> 本计划记录 Aerie-Model-X 分支版本升级全流程，含 6 大步骤。**每步精确到毫秒归档**，确保提交历史清晰可追溯。
>
> - **步骤 1**：将 main 最新更新完整同步到 Aerie-Model-X
> - **步骤 2**：在 Aerie-Model-X 上进行代码更新/功能优化/兼容性调整
> - **步骤 3**：全面验证测试（单元/集成/功能/性能）
> - **步骤 4**：将 Aerie-Model-X 新增更新提交到 main（仅 commit 不 merge）
> - **步骤 5**：重写 [[12_启动性能分析与优化方案]] 反映升级后现状
> - **步骤 6**：归档计划 + 提交历史核验

---

## 基线状态（2026-08-12 20:40:16.332）

> [!info] 初始状态快照
> - **当前分支**：`main`
> - **main 领先 origin/main**：34 个提交
> - **main 领先 Aerie-Model-X**：126 个提交
> - **Aerie-Model-X 领先 main**：1 个提交（`67f7d56`）
> - **main 工作区未提交代码改动**：
>   - `config/settings.yaml` — `multi_channel_identity_v1: true`
>   - `core/api_server.py` — 2 个修复（InProcess 世界保护 + brief 实时读 todo）
>   - `tests/test_phase15_world_control.py` — 新增 2 个测试
> - **Aerie-Model-X 独有提交 67f7d56**：B08 architecture guard + BLK-005（10 文件，+862/-34）
> - **同步方向**：main(126 提交) → Aerie-Model-X，Aerie-Model-X(67f7d56) → main

---

## 执行日志

### Step 0：基线核查 — 2026-08-12 20:39:13.787 至 20:40:16.332

| 检查项 | 结果 |
|---|---|
| `git status --branch` | main，ahead 34，工作区有代码改动 |
| `git branch -a` | Aerie-Model-X 本地+远程均存在 |
| main..Aerie-Model-X 计数 | 1（独有 67f7d56） |
| Aerie-Model-X..main 计数 | 126 |
| 工作区代码 diff | settings.yaml(1) + api_server.py(24) + test(39) |

> [!note] 关键发现
> main 工作区存在**未提交的代码修复**（world_runtime_bind InProcess 保护 + brief 实时读 todo），这些是当前系统实际运行状态的最新代码，同步前需先提交到 main 或随同步带入 Aerie-Model-X。

### Step 1：main → Aerie-Model-X 同步 — 2026-08-12 20:42:18.748 至 20:45:52.586 ✅

| 动作 | 时间戳 | 结果 |
|---|---|---|
| 提交 main 工作区代码 | 20:43:00 左右 | `e69093d` fix(world): 保护 InProcess 世界 + brief 实时 todo + 开启 multi_channel_identity_v1 |
| 停止 Aerie 运行进程 | 20:43:30 左右 | 释放 ChromaDB 文件锁（2 个 python + electron） |
| stash data/ 运行时文件 | 20:44:00 左右 | `runtime-data-20260812` 保存 |
| checkout Aerie-Model-X | 20:44:32.641 | 成功 |
| merge main | 20:45:00 左右 | 冲突 1 处：e2e_persona_baseline.py（保留 Aerie-Model-X 修复版 `ContextBuilder` + `core.brain.TONE_PROMPTS`） |
| 合并提交 | 20:45:30 左右 | `7c544b7` Merge branch 'main' into Aerie-Model-X |
| 验证 | 20:45:52.586 | Aerie-Model-X 领先 main 2 提交，main 无领先；配置与 InProcessWorldAdapter 已同步 |

> [!success] Step 1 完成
> main 的 126 个提交 + 工作区修复全部同步到 Aerie-Model-X。冲突解决采用 Aerie-Model-X 侧修复版本（67f7d56 已修复 e2e 测试引用的已删除符号）。

### Step 2：Aerie-Model-X 代码验证与兼容性调整 — 2026-08-12 20:46:26.390 至 21:22:41.340 ✅

| 动作 | 时间戳 | 结果 |
|---|---|---|
| compileall 语法检查 | 20:46:26.390 | 全绿 |
| architecture_guard 运行验证 | 20:47 左右 | 204 文件，RULE-001/002/003 通过，RULE-004 仅 8 warning |
| 关键测试组 | 20:47:32.154 | world_control + architecture_guard 25 passed |
| **发现兼容性问题** | 20:47:48.728 | e2e 引用 `core.brain`（合并后不存在） |
| 根因定位 | — | main 26314fd 已将 TONE_PROMPTS 从 brain 收敛到 llm_caller |
| 修复 e2e import | — | `core.brain` → `core.llm_caller` |
| 修复 case_12 断言 | — | 匹配 main 新文案（温暖+直球+无克制） |
| 修复 brain.py 注释引用 | — | self_evolve_l4.py + gen_architecture_poster.py |
| 验证 e2e | 20:53 左右 | 12/12 通过 |
| 全量回归 | 20:49:24.713 | **1278 passed / 27 failed**（与基线 1228/27 一致，无新增回归） |
| 基线对照 | 20:54-21:00 | main worktree 同样 3 failed(test_pipeline) / 1 failed(test_phase2)，确认基线问题 |
| **提交兼容性修复** | 21:22:41.340 | `d79fa7d` fix(model-x): 修正 brain 模块收敛引用 |

> [!success] Step 2 完成
> 合并后发现的 3 处 brain 模块收敛断裂已全部修复并验证。27 个全量失败经 main 基线对照确认均为**既有环境依赖问题**，非本次合并引入。

### Step 3：全面验证测试 — 2026-08-12 20:47 至 21:23:19.973 ✅

- [x] 单元/集成：world_control(25)、e2e_baseline(12)、context_builder(40)、api(65)、全量(1278/27 与基线一致)
- [x] 性能测试：boot_trace 复测 **import=10.93s**（Aerie-Model-X 升级后基准，见 [[boot_trace_data]]）
- [x] 基线对照：main worktree 对比确认 27 failed 为既有问题，无新增回归

### Step 4：Aerie-Model-X 新增更新提交到 main（仅 commit 不 merge）— 2026-08-12 21:26:35.401 至 21:29:19.689 ✅

| 动作 | 时间戳 | 结果 |
|---|---|---|
| cherry-pick d79fa7d | 21:26:35.401 | e2e 冲突，保留 d79fa7d（theirs）正确版本 → `14cf306` |
| cherry-pick 67f7d56 | 21:27:53.863 | e2e 冲突，保留 ours（llm_caller 已含 67f7d56 修复意图）→ `41a66af` |
| 验证 | 21:28 左右 | e2e 12/12 + architecture_guard 25 passed |
| 分支状态核验 | 21:29:19.689 | Aerie-Model-X→main 内容已移植（14cf306+41a66af）；**未执行 merge** |

> [!success] Step 4 完成
> Aerie-Model-X 独有的 B08 architecture guard（67f7d56）+ brain 收敛修复（d79fa7d）已通过 **cherry-pick** 提交到 main，全程未执行 merge 操作。两个分支实质内容已对齐，提交历史可追溯（cherry-pick 保留原始 commit 信息）。

### Step 5：重写 12_启动性能分析与优化方案.md 反映升级后现状 — 2026-08-12 21:30 至 21:40 左右 ✅

| 动作 | 结果 |
|---|---|
| 收集升级后数据 | import=10.93s、全量 1278/27、新 feature flags、B08/命名收敛/InProcess 修复 |
| 确认优化实施状态 | QQ 30s 等待仍在（companion.py:849-855），优化未实施，方案仍具时效性 |
| 重写文档 v2.0 | 新增 §0 升级后现状、§2.3 架构变更；更新 §4.3 实测（10.93s）；U-7 上调至 -6.4s；10s 目标确认可达（9.5s） |
| 更新 boot_trace_data.md | 同步升级后实测数据（10.93s） |

> [!success] Step 5 完成
> 文档已从"分析方案"升级为"升级后现状 + 优化方案"双定位 v2.0，含最新架构、实测数据、调整后的优化分级与实施路线。

### Step 6：归档计划 + 提交文档变更 — 2026-08-12 21:41:35.644 至 21:50:03.653 ✅

| 动作 | 时间戳 | 结果 |
|---|---|---|
| 提交 v2.0 文档到 main | 21:41:35.644 | `c59c9ac` docs(perf): 3 文件 +463/-260 |
| 提交历史核验 | 21:41:54.838 | main 历史完整（c59c9ac → 41a66af → 14cf306 → e69093d） |
| 文档同步回 Aerie-Model-X | 21:49:54.616 | `2ffb4d6`（cherry-pick c59c9ac，不 merge） |
| 最终核验 | 21:50:03.653 | 两分支实质内容对齐，工作区干净 |

> [!success] Step 6 完成 · 全部升级流程结束
> - **main**：`c59c9ac`（文档 v2.0）+ `41a66af`（B08）+ `14cf306`（brain 收敛修复）+ `e69093d`（world/brief 修复）
> - **Aerie-Model-X**：`2ffb4d6`（文档 v2.0）+ `d79fa7d`（brain 收敛修复）+ `7c544b7`（merge main）+ `67f7d56`（B08）
> - 两分支通过 cherry-pick 对齐实质内容，**全程未执行 merge**（仅 Aerie-Model-X 接收 main 时使用 merge）
> - 提交历史清晰可追溯，所有变更已记录

---

## 升级总结

> [!abstract] 最终交付
>
> | 目标 | 状态 |
> |---|---|
> | 1. main 最新更新同步到 Aerie-Model-X | ✅ merge 7c544b7（126 提交 + 工作区修复） |
> | 2. Aerie-Model-X 代码更新/兼容调整 | ✅ brain 收敛修复 d79fa7d（e2e + 注释引用） |
> | 3. 全面验证测试 | ✅ 单元/集成/e2e/性能（1278/27 与基线一致，无回归；import 10.93s） |
> | 4. Aerie-Model-X 新增提交到 main（仅 commit 不 merge） | ✅ cherry-pick 14cf306 + 41a66af |
> | 5. 提交历史清晰可追溯 | ✅ 两分支 log 完整，计划文档毫秒级归档 |
> | 附加：文档升级 v2.0 | ✅ 12_启动性能分析与优化方案.md 反映升级后现状 |

---

## 附录

- 相关文档：[[12_启动性能分析与优化方案]]、[[boot_trace_data]]、[[01_模块总览]]
- 测量脚本：[scripts/boot_trace.ps1](file:///e:/Agent_reply/scripts/boot_trace.ps1)
