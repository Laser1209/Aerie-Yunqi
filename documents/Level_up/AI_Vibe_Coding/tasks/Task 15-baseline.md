---
title: Task 15-baseline
tags: [aerie, task, phase15, world]
kind: task
task_id: TASK-15-001
phase: Phase 15
subsystem: world
status: done
progress_note: "2026-07-21: implemented feature-flagged Electron world dashboard host contract, real renderer shell, backend snapshot/approval API contracts, and Companion manual approval/snapshot handlers with redacted plugin/health status, hide/show continuity, sanitized candidate approval IPC, creative preview metadata, and preload exposure; no background plugin window was introduced."
priority: P1
dependencies: ["TASK-14-001"]
risk: high
decision_required: false
feature_flag: world_sidecar_v1
migration: false
files: ["electron/src/main.js", "electron/src/preload.js", "electron/src/world-dashboard-host.js", "electron/src/renderer/index.html", "electron/src/renderer/js/app.js", "electron/src/renderer/js/world-dashboard.js", "electron/src/renderer/styles/world-dashboard.css", "core/api_server.py", "core/companion.py", "core/world_image_candidates.py", "tests/test_phase15_world_dashboard_host.py", "electron/tests/world-dashboard-renderer.test.js", "tests/test_phase15_world_dashboard_api.py", "tests/test_phase15_world_dashboard_approval_handler.py", "tests/test_phase15_world_dashboard_snapshot.py"]
acceptance_ids: ["A-15-01", "A-15-02", "A-15-03"]
rollback_ready: true
owner: world-team
evidence: ["file:///E:/Agent_reply/electron/src/main.js", "file:///E:/Agent_reply/electron/src/preload.js", "file:///E:/Agent_reply/electron/src/world-dashboard-host.js", "file:///E:/Agent_reply/electron/src/renderer/index.html", "file:///E:/Agent_reply/electron/src/renderer/js/app.js", "file:///E:/Agent_reply/electron/src/renderer/js/world-dashboard.js", "file:///E:/Agent_reply/electron/src/renderer/styles/world-dashboard.css", "file:///E:/Agent_reply/core/api_server.py", "file:///E:/Agent_reply/core/companion.py", "file:///E:/Agent_reply/core/world_image_candidates.py", "file:///E:/Agent_reply/tests/test_phase15_world_dashboard_host.py", "file:///E:/Agent_reply/electron/tests/world-dashboard-renderer.test.js", "file:///E:/Agent_reply/tests/test_phase15_world_dashboard_api.py", "file:///E:/Agent_reply/tests/test_phase15_world_dashboard_approval_handler.py", "file:///E:/Agent_reply/tests/test_phase15_world_dashboard_snapshot.py"]
---
# Task 15-baseline
> [!todo] Phase 15
> Dashboard、候选审批、插件健康、创意工坊与发布状态；验收目标：异常状态完整，插件隐藏后聊天可发布。

- [x] 先提交失败测试证据
- [x] 完成最小实现与兼容路径
- [x] 验证 `world_sidecar_v1` 关闭后的旧路径
- [x] 记录脱敏 Evidence、指标与守恒结果
- [x] 完成回滚演练并更新 `rollback_ready`

## 链接
[[Phase 15]] · [[90_全局验收清单]] · [[92_回滚演练]]

## Evidence
- 2026-07-21 Red: `python -m pytest tests/test_phase15_world_dashboard_host.py -q` -> expected failures for missing `electron/src/world-dashboard-host.js` and missing main/preload world dashboard IPC exposure.
- 2026-07-21 Green: `python -m pytest tests/test_phase15_world_dashboard_host.py -q` -> `5 passed`.
- 2026-07-21 Regression: `python -m pytest tests/test_phase15_world_dashboard_host.py tests/test_phase14_world_image_candidates.py tests/test_phase13_world_sidecar.py tests/test_phase12_world_domain.py tests/test_phase11_world_port.py tests/test_phase10_image_workflow.py tests/test_upload.py tests/test_api.py tests/test_phase4_chat_request_service.py tests/test_phase4_api.py tests/test_phase8_proactive_feedback.py tests/test_phase1_proactive_baseline.py -q` -> `138 passed, 4 warnings`.
- 2026-07-21 Syntax: `node --check electron/src/world-dashboard-host.js` passed; `node --check electron/src/main.js` passed; `node --check electron/src/preload.js` passed.
- Rollback: keep `world_sidecar_v1: false` or set `AERIE_FEATURE_WORLD_SIDECAR_V1=false`; `worldDashboard.getStatus()` returns hidden/disabled without backend calls, candidate approval returns disabled without side effects, and legacy `aerie.api.request` plus chat publication remain available.

## Renderer Shell Evidence（2026-07-21）

- Red：`node --test electron/tests/world-dashboard-renderer.test.js` 初跑 `0 passed, 2 failed`，失败点为缺少真实 `world-dashboard` sidebar tab、panel、renderer script/style 与 `world-dashboard.js`。
- Green：新增实际 renderer 页面壳，展示 status/plugin/backend/chat publish/panels/errors，支持 show/hide/refresh、图片候选审批和 Creative Workshop 元数据预览；renderer 只调用 `window.aerie.worldDashboard` 窄 API，不包含 `world-dashboard:raw`，不展示原始 secret 文本。
- 验证：目标 `2 passed`；Electron Node `25 passed`；`node --check electron/src/renderer/js/world-dashboard.js`、`node --check electron/src/renderer/js/app.js` 通过；`npm run check:all` 通过；完整 Python `542 passed, 6 warnings`；当前工作区 provider-key 扫描通过。
- 回滚：移除新增 renderer tab/panel/script/style 即恢复上一批 host-only 状态；`world_sidecar_v1=false` 时 host 仍返回 disabled/hidden 且无 backend side effect，聊天发布路径未被修改。

## Backend API Contract Evidence（2026-07-21）

- Red：`python -m pytest tests/test_phase15_world_dashboard_api.py -q` 初跑 `3 failed`，失败点均为 `/api/world/candidates/approve` 返回 `404 Not Found`。
- Green：`core/api_server.py` 新增 dashboard-only approval endpoint；Flag off 返回 `disabled` 且不调用 handler；Flag on 只把白名单 approval payload 传给 `companion.approve_world_image_candidate()`；handler 缺失降级为 `backend_unavailable`，异常降级为 `approval_handler_failed`，响应不包含 raw prompt、secret 或异常详情。
- 验证：目标 API `3 passed, 4 warnings`；Phase 14/15 相关 `15 passed, 4 warnings`；`python -m py_compile core/api_server.py` 通过；完整 Python `545 passed, 6 warnings`；Electron Node `25 passed`；`npm run check:all` 与当前工作区 provider-key 扫描通过。
- 回滚：关闭 `world_sidecar_v1` 保持 no-side-effect disabled；移除 endpoint 只影响 Dashboard 手动候选审批 API，不影响 Phase 14 自动候选消费或旧聊天发布路径。

## Manual Approval Handler Evidence（2026-07-21）

- Red：`python -m pytest tests/test_phase15_world_dashboard_approval_handler.py -q` 初跑 `4 failed`，失败点均为 `Companion` 缺少 `approve_world_image_candidate`。
- Green：`Companion.approve_world_image_candidate()` 委托 Phase 14 consumer；`WorldImageCandidateConsumer.approve_candidate()` 从 `WorldPort.replay_events(last_seq=0)` 查 canonical candidate，approve 走原 ImageWorkflow/ACK/idempotency 路径，reject 终态记录并 ACK 但无图片工作流副作用，postpone 不 ACK 以保留候选可重放，not_found 无副作用返回。
- 验证：目标 handler `4 passed`；Phase 14/15 相关 `19 passed, 4 warnings`；`python -m py_compile core/world_image_candidates.py core/companion.py` 通过；完整 Python `549 passed, 6 warnings`；Electron Node `25 passed`；`npm run check:all` 与当前工作区 provider-key 扫描通过。
- 回滚：关闭 `world_image_candidates_v1` 或 `world_sidecar_v1` 均保持 disabled/no-side-effect；删除 handler 只影响 Dashboard 手动审批真实执行，不影响旧聊天或 Phase 14 自动消费入口。

## Dashboard Snapshot Evidence（2026-07-21）

- Red：`python -m pytest tests/test_phase15_world_dashboard_snapshot.py -q` 初跑 `3 failed`，失败点为 snapshot API 404 与 `Companion` 缺少 `get_world_dashboard_snapshot`；扩展 host/renderer 测试后，失败点为缺 `worldDashboard.getSnapshot`、`world-dashboard:get-snapshot` IPC 和四个 snapshot DOM。
- Green：新增 `/api/world/dashboard/snapshot` 只读脱敏 API、`Companion.get_world_dashboard_snapshot()`、host `getSnapshot()`、main/preload 窄 IPC、renderer 四块 snapshot 显示；输出仅包含 world summary、relationship、self model、timeline metadata 与 image candidate metadata，不展示 raw prompt、raw thought、secret values 或 provider payload。
- 验证：目标 snapshot `3 passed, 4 warnings`；Phase 14/15 相关 `23 passed, 4 warnings`；`python -m py_compile core/api_server.py core/companion.py` 与 Electron `node --check` 通过；完整 Python `553 passed, 6 warnings`；Electron Node `25 passed`；`npm run check:all` 与 provider-key 工作区扫描通过。
- 回滚：关闭 `world_sidecar_v1` 恢复 disabled/no-handler-call；移除 snapshot IPC/DOM 仅回到 status-only Dashboard，不影响旧聊天、候选审批或自动消费入口。
