---
title: Task 15-baseline
tags: [aerie, task, phase15, world]
kind: task
task_id: TASK-15-001
phase: Phase 15
subsystem: world
status: done
progress_note: "2026-07-21: implemented feature-flagged Electron world dashboard host contract and real renderer shell with redacted plugin/health status, hide/show continuity, sanitized candidate approval IPC, creative preview metadata, and preload exposure; no background plugin window was introduced."
priority: P1
dependencies: ["TASK-14-001"]
risk: high
decision_required: false
feature_flag: world_sidecar_v1
migration: false
files: ["electron/src/main.js", "electron/src/preload.js", "electron/src/world-dashboard-host.js", "electron/src/renderer/index.html", "electron/src/renderer/js/app.js", "electron/src/renderer/js/world-dashboard.js", "electron/src/renderer/styles/world-dashboard.css", "tests/test_phase15_world_dashboard_host.py", "electron/tests/world-dashboard-renderer.test.js"]
acceptance_ids: ["A-15-01", "A-15-02", "A-15-03"]
rollback_ready: true
owner: world-team
evidence: ["file:///E:/Agent_reply/electron/src/main.js", "file:///E:/Agent_reply/electron/src/preload.js", "file:///E:/Agent_reply/electron/src/world-dashboard-host.js", "file:///E:/Agent_reply/electron/src/renderer/index.html", "file:///E:/Agent_reply/electron/src/renderer/js/app.js", "file:///E:/Agent_reply/electron/src/renderer/js/world-dashboard.js", "file:///E:/Agent_reply/electron/src/renderer/styles/world-dashboard.css", "file:///E:/Agent_reply/tests/test_phase15_world_dashboard_host.py", "file:///E:/Agent_reply/electron/tests/world-dashboard-renderer.test.js"]
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
