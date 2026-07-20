---
title: Phase 15 - World Dashboard、Creative Workshop 与发布
kind: phase
phase: Phase 15
status: done
progress_note: "2026-07-21: Phase 15 is green for a feature-flagged Electron world dashboard host contract, redacted plugin health, hidden-dashboard chat continuity, sanitized candidate approval IPC, creative preview metadata, and preload exposure without generic plugin escape."
tags: [aerie, phase, phase15]
---
# Phase 15：World Dashboard、Creative Workshop 与发布
> [!info] 执行边界
> 只按获批实施计划执行；当前阶段未通过验收时停止后续阶段。

## 目标
Dashboard、候选审批、插件健康、创意工坊与发布状态；保持兼容、可观测与可回滚。

## 非目标
不整体重写 Pipeline；不删除旧表或旧文件；不创建平行 v2；不复制疑似凭据。

## 依赖
- Phase 14
- [[05_Feature_Flag与回滚矩阵]]、[[06_AI_Vibe_Coding批次规约]]

## 当前代码证据
- [main.js](file:///E:/Agent_reply/electron/src/main.js)
- [preload.js](file:///E:/Agent_reply/electron/src/preload.js)
- [world-dashboard-host.js](file:///E:/Agent_reply/electron/src/world-dashboard-host.js)
- [test_phase15_world_dashboard_host.py](file:///E:/Agent_reply/tests/test_phase15_world_dashboard_host.py)
- [pipeline.py](file:///E:/Agent_reply/core/pipeline.py)
- [api_server.py](file:///E:/Agent_reply/core/api_server.py)

## 文件范围
- 已修改或演进：`electron/src/main.js`、`electron/src/preload.js`
- 已新增：`electron/src/world-dashboard-host.js`、`tests/test_phase15_world_dashboard_host.py`
- 未创建实际 Dashboard Renderer 页面；未启动新的插件窗口；未改变聊天发布路径；未暴露通用插件逃逸 IPC。
- 执行任务：[[Task 15-baseline]]

## 数据/API 合同
- Feature Flag：`world_sidecar_v1`。
- Dashboard、候选审批、插件健康、创意工坊与发布状态。
- ID、状态、sequence、幂等键和所有权边界必须可审计。
- 涉及迁移时支持 backup、dry-run、checksum、幂等、cursor、断点续跑与守恒。

## TDD 步骤
1. 先新增失败测试覆盖主路径、异常路径与回滚路径。
2. 实现最小变更使测试通过，保留兼容适配器。
3. 运行受影响模块测试与完整回归。
4. 验证 Flag 关闭、迁移/协议恢复和 Evidence 脱敏。

## 验收
- [x] 异常状态完整，插件隐藏后聊天可发布
- [x] Feature Flag 关闭恢复旧路径且不丢新数据
- [x] 不产生重复副作用、历史串线或敏感值泄漏

## 回滚
关闭 `world_sidecar_v1`，恢复备份或旧读路径；保留新表、元数据、Outbox、旧表和旧文件。

## 指标
成功率、延迟、重复计数、守恒差异、恢复时间和回滚耗时；禁止记录消息正文、个人数据或凭据。

## 提交边界
只提交 Phase 15 相关源码、测试、迁移与文档；不混入无关重构、格式化或构建产物。

## Evidence
- [实施计划](file:///E:/Agent_reply/.trae/documents/Aerie_AI_Vibe_Coding_全面升级实施计划.md)
- [main.js](file:///E:/Agent_reply/electron/src/main.js)
- [preload.js](file:///E:/Agent_reply/electron/src/preload.js)
- [world-dashboard-host.js](file:///E:/Agent_reply/electron/src/world-dashboard-host.js)
- [test_phase15_world_dashboard_host.py](file:///E:/Agent_reply/tests/test_phase15_world_dashboard_host.py)
- [[90_全局验收清单]] · [[92_回滚演练]]
- 2026-07-21 Red: `python -m pytest tests/test_phase15_world_dashboard_host.py -q` -> expected failures for missing `electron/src/world-dashboard-host.js` and missing main/preload world dashboard IPC exposure.
- 2026-07-21 Green: `python -m pytest tests/test_phase15_world_dashboard_host.py -q` -> `5 passed`.
- 2026-07-21 Regression: `python -m pytest tests/test_phase15_world_dashboard_host.py tests/test_phase14_world_image_candidates.py tests/test_phase13_world_sidecar.py tests/test_phase12_world_domain.py tests/test_phase11_world_port.py tests/test_phase10_image_workflow.py tests/test_upload.py tests/test_api.py tests/test_phase4_chat_request_service.py tests/test_phase4_api.py tests/test_phase8_proactive_feedback.py tests/test_phase1_proactive_baseline.py -q` -> `138 passed, 4 warnings`.
- 2026-07-21 Syntax: `node --check electron/src/world-dashboard-host.js` passed; `node --check electron/src/main.js` passed; `node --check electron/src/preload.js` passed.
