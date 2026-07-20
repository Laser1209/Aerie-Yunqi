---
title: Task 13-baseline
tags: [aerie, task, phase13, world]
kind: task
task_id: TASK-13-001
phase: Phase 13
subsystem: world
status: done
progress_note: "2026-07-21: implemented local world sidecar baseline with world.db-owned store, idempotent outbox, ACK cursor, heartbeat/checkpoint redaction, RemoteWorldAdapter crash degradation, Electron PluginSupervisor, and Core world event dedupe."
priority: P0
dependencies: ["TASK-12-001"]
risk: high
decision_required: false
feature_flag: world_sidecar_v1
migration: true
files: ["world_service/main.py", "world_service/storage/sqlite_store.py", "core/world_adapters/remote.py", "core/world_port.py", "core/event_stream.py", "electron/src/main.js", "electron/src/plugin-supervisor.js", "tests/test_phase13_world_sidecar.py"]
acceptance_ids: ["A-13-01", "A-13-02", "A-13-03"]
rollback_ready: true
owner: world-team
evidence: ["file:///E:/Agent_reply/world_service/main.py", "file:///E:/Agent_reply/world_service/storage/sqlite_store.py", "file:///E:/Agent_reply/core/world_adapters/remote.py", "file:///E:/Agent_reply/core/event_stream.py", "file:///E:/Agent_reply/electron/src/main.js", "file:///E:/Agent_reply/electron/src/plugin-supervisor.js", "file:///E:/Agent_reply/tests/test_phase13_world_sidecar.py"]
---
# Task 13-baseline
> [!todo] Phase 13
> world.db 单一所有者、Outbox、ACK cursor、heartbeat 与监管；验收目标：Sidecar 崩溃聊天继续，重启续传不重复。

- [x] 先提交失败测试证据
- [x] 完成最小实现与兼容路径
- [x] 验证 `world_sidecar_v1` 关闭后的旧路径
- [x] 记录脱敏 Evidence、指标与守恒结果
- [x] 完成回滚演练并更新 `rollback_ready`

## 链接
[[Phase 13]] · [[90_全局验收清单]] · [[92_回滚演练]]

## Evidence
- 2026-07-21 Red: `python -m pytest tests/test_phase13_world_sidecar.py -q` -> expected failures for missing `world_service`, `core.world_adapters.remote`, and `electron/src/plugin-supervisor.js`.
- 2026-07-21 Green: `python -m pytest tests/test_phase13_world_sidecar.py -q` -> `6 passed`.
- 2026-07-21 Regression: `python -m pytest tests/test_phase13_world_sidecar.py tests/test_phase12_world_domain.py tests/test_phase11_world_port.py tests/test_phase10_image_workflow.py tests/test_upload.py tests/test_api.py tests/test_phase4_chat_request_service.py tests/test_phase4_api.py tests/test_phase8_proactive_feedback.py tests/test_phase1_proactive_baseline.py -q` -> `126 passed, 4 warnings`.
- 2026-07-21 Syntax: `python -m py_compile world_service/main.py world_service/storage/sqlite_store.py core/world_adapters/remote.py core/world_port.py core/event_stream.py core/companion.py core/pipeline.py core/context_builder.py` passed; `node --check electron/src/plugin-supervisor.js` passed; `node --check electron/src/main.js` passed.
- Rollback: keep `world_sidecar_v1: false` or set `AERIE_FEATURE_WORLD_SIDECAR_V1=false`; Core continues to use InProcess/Null world adapters, existing chat paths do not depend on Sidecar availability, and retained world.db/Outbox data is not destructively modified.
