---
title: Task 11-baseline
tags: [aerie, task, phase11, world]
kind: task
task_id: TASK-11-001
phase: Phase 11
subsystem: world
status: done
progress_note: "2026-07-21: implemented WorldPort DTO/Protocol with Null and InProcess adapters, idempotent redacted observation events, Python and Electron capability whitelists, and Companion world_port initialization behind world_inprocess_v1."
priority: P1
dependencies: ["TASK-10-001"]
risk: medium
decision_required: false
feature_flag: world_inprocess_v1
migration: false
files: ["core/world_port.py", "core/companion.py", "electron/src/main.js", "electron/src/capability-broker.js", "tests/test_phase11_world_port.py"]
acceptance_ids: ["A-11-01", "A-11-02", "A-11-03"]
rollback_ready: true
owner: world-team
evidence: ["file:///E:/Agent_reply/core/world_port.py", "file:///E:/Agent_reply/core/companion.py", "file:///E:/Agent_reply/electron/src/main.js", "file:///E:/Agent_reply/electron/src/capability-broker.js", "file:///E:/Agent_reply/tests/test_phase11_world_port.py"]
---
# Task 11-baseline
> [!todo] Phase 11
> WorldPort 五接口、Null/InProcess Adapter 与能力白名单；验收目标：禁用世界不影响聊天，契约测试一致。

- [x] 先提交失败测试证据
- [x] 完成最小实现与兼容路径
- [x] 验证 `world_inprocess_v1` 关闭后的旧路径
- [x] 记录脱敏 Evidence、指标与守恒结果
- [x] 完成回滚演练并更新 `rollback_ready`

## 链接
[[Phase 11]] · [[90_全局验收清单]] · [[92_回滚演练]]

## Evidence
- 2026-07-21 Red: `python -m pytest tests/test_phase11_world_port.py -q` -> expected collection error `ModuleNotFoundError: No module named 'core.world_port'`.
- 2026-07-21 Red: `python -m pytest tests/test_phase11_world_port.py::test_electron_capability_broker_is_narrow_and_redacted -q` -> expected missing `electron/src/capability-broker.js`.
- 2026-07-21 Green: `python -m pytest tests/test_phase11_world_port.py -q` -> `7 passed`.
- 2026-07-21 Regression: `python -m pytest tests/test_phase11_world_port.py tests/test_phase10_image_workflow.py tests/test_upload.py tests/test_api.py tests/test_phase4_chat_request_service.py tests/test_phase4_api.py tests/test_phase8_proactive_feedback.py tests/test_phase1_proactive_baseline.py -q` -> `113 passed, 4 warnings`.
- 2026-07-21 Syntax: `python -m py_compile core/world_port.py core/companion.py core/api_server.py core/image_service.py core/attachment_handler.py core/chat_request_service.py` passed; `node --check electron/src/main.js` passed; `node --check electron/src/capability-broker.js` passed.
- Rollback: keep `world_inprocess_v1: false` or set `AERIE_FEATURE_WORLD_INPROCESS_V1=false`; `Companion.world_port` uses `NullWorldAdapter`, no world loop starts, no world database or sidecar is touched, and existing chat/API paths remain unchanged.
