---
title: Task 14-baseline
tags: [aerie, task, phase14, world]
kind: task
task_id: TASK-14-001
phase: Phase 14
subsystem: world
status: done
progress_note: "2026-07-21: implemented a Core-owned world ImageCandidate consumer with feature-flag no-ACK rollback, proactive policy/judge approval, idempotent ImageWorkflow planning, terminal ACK, offline/workflow-disabled recovery, sidecar candidate publish, and Companion one-shot entrypoint."
priority: P0
dependencies: ["TASK-13-001"]
risk: high
decision_required: false
feature_flag: world_image_candidates_v1
migration: false
files: ["core/world_image_candidates.py", "core/companion.py", "world_service/main.py", "world_service/storage/sqlite_store.py", "tests/test_phase14_world_image_candidates.py"]
acceptance_ids: ["A-14-01", "A-14-02", "A-14-03"]
rollback_ready: true
owner: world-team
evidence: ["file:///E:/Agent_reply/core/world_image_candidates.py", "file:///E:/Agent_reply/core/companion.py", "file:///E:/Agent_reply/world_service/main.py", "file:///E:/Agent_reply/world_service/storage/sqlite_store.py", "file:///E:/Agent_reply/tests/test_phase14_world_image_candidates.py"]
---
# Task 14-baseline
> [!todo] Phase 14
> World 只产 ImageCandidate，Core 执行 Judge 到 ACK；验收目标：重复、过期、静音、拒绝、失败、离线均无重复副作用。

- [x] 先提交失败测试证据
- [x] 完成最小实现与兼容路径
- [x] 验证 `world_image_candidates_v1` 关闭后的旧路径
- [x] 记录脱敏 Evidence、指标与守恒结果
- [x] 完成回滚演练并更新 `rollback_ready`

## 链接
[[Phase 14]] · [[90_全局验收清单]] · [[92_回滚演练]]

## Evidence
- 2026-07-21 Red: `python -m pytest tests/test_phase14_world_image_candidates.py -q` -> expected failures for missing `core.world_image_candidates` and `LocalWorldSidecarService.publish_image_candidate`.
- 2026-07-21 Red: `python -m pytest tests/test_phase14_world_image_candidates.py::test_companion_exposes_one_shot_candidate_consumer -q` -> expected failure for missing `Companion.process_world_image_candidates_once`.
- 2026-07-21 Red: `python -m pytest tests/test_phase14_world_image_candidates.py::test_image_workflow_disabled_does_not_ack_or_record_candidate -q` -> expected `failed` before no-ACK workflow-disabled guard.
- 2026-07-21 Green: `python -m pytest tests/test_phase14_world_image_candidates.py -q` -> `7 passed`.
- 2026-07-21 Sidecar regression: `python -m pytest tests/test_phase14_world_image_candidates.py tests/test_phase13_world_sidecar.py -q` -> `13 passed`.
- 2026-07-21 Regression: `python -m pytest tests/test_phase14_world_image_candidates.py tests/test_phase13_world_sidecar.py tests/test_phase12_world_domain.py tests/test_phase11_world_port.py tests/test_phase10_image_workflow.py tests/test_upload.py tests/test_api.py tests/test_phase4_chat_request_service.py tests/test_phase4_api.py tests/test_phase8_proactive_feedback.py tests/test_phase1_proactive_baseline.py -q` -> `133 passed, 4 warnings`.
- 2026-07-21 Syntax: `python -m py_compile core/world_image_candidates.py world_service/main.py world_service/storage/sqlite_store.py core/companion.py` passed.
- Rollback: keep `world_image_candidates_v1: false` or set `AERIE_FEATURE_WORLD_IMAGE_CANDIDATES_V1=false`; the consumer returns `disabled` without ACK, without ImageWorkflow calls, and without terminal records, so sidecar Outbox data remains available for later replay. If `image_assets_v1` is off while candidate flag is on, workflow-disabled candidates also remain unacked and unrecorded to avoid half-enabled data loss.
