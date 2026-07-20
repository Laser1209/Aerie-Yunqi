---
title: Phase 15 - World Dashboard、Creative Workshop 与发布
kind: phase
phase: Phase 15
status: done
progress_note: "2026-07-21: Phase 15 is green for a feature-flagged Electron world dashboard host contract, real renderer dashboard shell, backend candidate approval API contract, and Companion manual approval handler with redacted plugin health, hidden-dashboard chat continuity, sanitized candidate approval IPC, creative preview metadata, and preload exposure without generic plugin escape."
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
- [world-dashboard.js](file:///E:/Agent_reply/electron/src/renderer/js/world-dashboard.js)
- [world-dashboard.css](file:///E:/Agent_reply/electron/src/renderer/styles/world-dashboard.css)
- [index.html](file:///E:/Agent_reply/electron/src/renderer/index.html)
- [app.js](file:///E:/Agent_reply/electron/src/renderer/js/app.js)
- [test_phase15_world_dashboard_host.py](file:///E:/Agent_reply/tests/test_phase15_world_dashboard_host.py)
- [world-dashboard-renderer.test.js](file:///E:/Agent_reply/electron/tests/world-dashboard-renderer.test.js)
- [test_phase15_world_dashboard_api.py](file:///E:/Agent_reply/tests/test_phase15_world_dashboard_api.py)
- [test_phase15_world_dashboard_approval_handler.py](file:///E:/Agent_reply/tests/test_phase15_world_dashboard_approval_handler.py)
- [companion.py](file:///E:/Agent_reply/core/companion.py)
- [world_image_candidates.py](file:///E:/Agent_reply/core/world_image_candidates.py)
- [pipeline.py](file:///E:/Agent_reply/core/pipeline.py)
- [api_server.py](file:///E:/Agent_reply/core/api_server.py)

## 文件范围
- 已修改或演进：`electron/src/main.js`、`electron/src/preload.js`、`core/api_server.py`、`core/companion.py`、`core/world_image_candidates.py`
- 已新增：`electron/src/world-dashboard-host.js`、`electron/src/renderer/js/world-dashboard.js`、`electron/src/renderer/styles/world-dashboard.css`、`tests/test_phase15_world_dashboard_host.py`、`electron/tests/world-dashboard-renderer.test.js`、`tests/test_phase15_world_dashboard_api.py`、`tests/test_phase15_world_dashboard_approval_handler.py`
- 已创建实际 Dashboard Renderer 页面壳；未启动新的插件窗口；未改变聊天发布路径；未暴露通用插件逃逸 IPC。
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
- [world-dashboard.js](file:///E:/Agent_reply/electron/src/renderer/js/world-dashboard.js)
- [world-dashboard.css](file:///E:/Agent_reply/electron/src/renderer/styles/world-dashboard.css)
- [world-dashboard-renderer.test.js](file:///E:/Agent_reply/electron/tests/world-dashboard-renderer.test.js)
- [test_phase15_world_dashboard_api.py](file:///E:/Agent_reply/tests/test_phase15_world_dashboard_api.py)
- [test_phase15_world_dashboard_approval_handler.py](file:///E:/Agent_reply/tests/test_phase15_world_dashboard_approval_handler.py)
- [test_phase15_world_dashboard_host.py](file:///E:/Agent_reply/tests/test_phase15_world_dashboard_host.py)
- [companion.py](file:///E:/Agent_reply/core/companion.py)
- [world_image_candidates.py](file:///E:/Agent_reply/core/world_image_candidates.py)
- [[90_全局验收清单]] · [[92_回滚演练]]
- 2026-07-21 Red: `python -m pytest tests/test_phase15_world_dashboard_host.py -q` -> expected failures for missing `electron/src/world-dashboard-host.js` and missing main/preload world dashboard IPC exposure.
- 2026-07-21 Green: `python -m pytest tests/test_phase15_world_dashboard_host.py -q` -> `5 passed`.
- 2026-07-21 Regression: `python -m pytest tests/test_phase15_world_dashboard_host.py tests/test_phase14_world_image_candidates.py tests/test_phase13_world_sidecar.py tests/test_phase12_world_domain.py tests/test_phase11_world_port.py tests/test_phase10_image_workflow.py tests/test_upload.py tests/test_api.py tests/test_phase4_chat_request_service.py tests/test_phase4_api.py tests/test_phase8_proactive_feedback.py tests/test_phase1_proactive_baseline.py -q` -> `138 passed, 4 warnings`.
- 2026-07-21 Syntax: `node --check electron/src/world-dashboard-host.js` passed; `node --check electron/src/main.js` passed; `node --check electron/src/preload.js` passed.

### Renderer Shell Evidence（2026-07-21）

- Red：新增 `electron/tests/world-dashboard-renderer.test.js` 后，目标测试按预期失败：`index.html` 缺少 `data-tab="world-dashboard"` / `panel-world-dashboard` / `js/world-dashboard.js`，且 renderer 控制器文件不存在。
- Green：`electron/src/renderer/index.html` 增加实际 World Dashboard tab、panel、Creative Workshop 预览表单与图片候选审批表单；`electron/src/renderer/js/world-dashboard.js` 只调用 `window.aerie.worldDashboard` 窄 preload API，审批 payload 仅包含 `candidateId/action/reasonCode/idempotencyKey`，预览结果只展示 digest/keys 等元数据；`electron/src/renderer/js/app.js` 只在切到世界 tab 时通知刷新。
- 回滚：删除新增 renderer tab/panel/script/style 或保持 `world_sidecar_v1=false`；host/preload 旧合同不变，聊天发布路径不变。
- 验证：`node --test electron/tests/world-dashboard-renderer.test.js` → `2 passed`；`node --check electron/src/renderer/js/world-dashboard.js` 与 `node --check electron/src/renderer/js/app.js` 通过；`node --test electron/tests/*.test.js` → `25 passed`；`npm run check:all` 通过；`python -m pytest tests -q` → `542 passed, 6 warnings`；`python tools/scan_provider_key_patterns.py` → `PROVIDER_KEY_SCAN_OK`。

### Backend API Contract Evidence（2026-07-21）

- Red：新增 `tests/test_phase15_world_dashboard_api.py` 后，目标测试按预期失败为 `404 Not Found`，证明 Electron host 的 `/api/world/candidates/approve` 后端合同缺失。
- Green：`core/api_server.py` 新增 `POST /api/world/candidates/approve` 薄接线；`world_sidecar_v1=false` 时返回 `disabled` 且不调用 handler；Flag 开启时仅把 `candidate_id/action/idempotency_key/reason_code` 白名单字段交给 `companion.approve_world_image_candidate()`，handler 缺失时返回稳定 `backend_unavailable`，异常时返回 `approval_handler_failed`，响应不回显 raw body、prompt、secret 或异常详情。
- 回滚：关闭 `world_sidecar_v1` 即恢复 disabled/no-side-effect；删除该 endpoint 只影响 dashboard 候选审批 API，不影响聊天发布、Phase 14 自动候选消费、host/preload/renderer 窄 IPC。
- 验证：`python -m py_compile core/api_server.py` 通过；`python -m pytest tests/test_phase15_world_dashboard_api.py -q` → `3 passed, 4 warnings`；Phase 14/15 相关 `15 passed, 4 warnings`；`python -m pytest tests -q` → `545 passed, 6 warnings`；Electron Node `25 passed`；`npm run check:all` 通过；`python tools/scan_provider_key_patterns.py` → `PROVIDER_KEY_SCAN_OK`。

### Manual Approval Handler Evidence（2026-07-21）

- Red：新增 `tests/test_phase15_world_dashboard_approval_handler.py` 后，目标测试按预期失败为 `AttributeError: 'Companion' object has no attribute 'approve_world_image_candidate'`，证明 Dashboard API 只能薄转发但缺真实 Companion handler。
- Green：`core/companion.py` 新增 `approve_world_image_candidate()`，委托 Phase 14 `WorldImageCandidateConsumer`；`core/world_image_candidates.py` 新增 `approve_candidate()`，按 `candidate_id`/候选幂等键从 `WorldPort.replay_events(last_seq=0)` 查 canonical ImageCandidate。`approve` 复用原自动消费路径与 ImageWorkflow 幂等键；`reject` 记录终态并 ACK、不调用图片工作流；`postpone` 不 ACK、不记录终态以保留后续 replay；`not_found` 无副作用返回。
- 回滚：关闭 `world_image_candidates_v1` 时 handler 返回 disabled/no-ACK；关闭 `world_sidecar_v1` 时 API 层仍直接 disabled/no-side-effect。删除 handler 只会回到 backend_unavailable，不影响旧聊天或自动候选消费入口。
- 验证：`python -m py_compile core/world_image_candidates.py core/companion.py` 通过；`python -m pytest tests/test_phase15_world_dashboard_approval_handler.py -q` → `4 passed`；Phase 14/15 相关 `19 passed, 4 warnings`；`python -m pytest tests -q` → `549 passed, 6 warnings`；Electron Node `25 passed`；`npm run check:all` 通过；`python tools/scan_provider_key_patterns.py` → `PROVIDER_KEY_SCAN_OK`。
