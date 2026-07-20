---
title: Task 15-baseline
tags: [aerie, task, phase15, world]
kind: task
task_id: TASK-15-001
phase: Phase 15
subsystem: world
status: done
progress_note: "2026-07-21: implemented feature-flagged Electron world dashboard host contract with redacted plugin/health status, hide/show continuity, sanitized candidate approval IPC, creative preview metadata, and preload exposure; no renderer page or background plugin window was introduced."
priority: P1
dependencies: ["TASK-14-001"]
risk: high
decision_required: false
feature_flag: world_sidecar_v1
migration: false
files: ["electron/src/main.js", "electron/src/preload.js", "electron/src/world-dashboard-host.js", "tests/test_phase15_world_dashboard_host.py"]
acceptance_ids: ["A-15-01", "A-15-02", "A-15-03"]
rollback_ready: true
owner: world-team
evidence: ["file:///E:/Agent_reply/electron/src/main.js", "file:///E:/Agent_reply/electron/src/preload.js", "file:///E:/Agent_reply/electron/src/world-dashboard-host.js", "file:///E:/Agent_reply/tests/test_phase15_world_dashboard_host.py"]
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
