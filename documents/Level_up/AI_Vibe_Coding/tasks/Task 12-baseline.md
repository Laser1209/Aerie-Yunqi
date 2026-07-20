---
title: Task 12-baseline
tags: [aerie, task, phase12, world]
kind: task
task_id: TASK-12-001
phase: Phase 12
subsystem: world
status: done
progress_note: "2026-07-21: implemented deterministic WorldSimulation, finite ActionRegistry, persona-scoped RelationshipEngine, computed SelfModel, InProcessWorldAdapter domain wiring, FULL-only ContextBuilder injection, and optional Pipeline providers."
priority: P1
dependencies: ["TASK-11-001"]
risk: medium
decision_required: false
feature_flag: world_inprocess_v1
migration: false
files: ["core/world_simulation.py", "core/action_registry.py", "core/relationship_engine.py", "core/self_model.py", "core/world_port.py", "core/companion.py", "core/context_builder.py", "core/pipeline.py", "tests/test_phase12_world_domain.py"]
acceptance_ids: ["A-12-01", "A-12-02", "A-12-03"]
rollback_ready: true
owner: world-team
evidence: ["file:///E:/Agent_reply/core/world_simulation.py", "file:///E:/Agent_reply/core/action_registry.py", "file:///E:/Agent_reply/core/relationship_engine.py", "file:///E:/Agent_reply/core/self_model.py", "file:///E:/Agent_reply/core/world_port.py", "file:///E:/Agent_reply/core/companion.py", "file:///E:/Agent_reply/core/context_builder.py", "file:///E:/Agent_reply/core/pipeline.py", "file:///E:/Agent_reply/tests/test_phase12_world_domain.py"]
---
# Task 12-baseline
> [!todo] Phase 12
> 确定性 Tick、Action Registry、关系与 SelfModel；验收目标：同 seed/时钟同快照，关系按 Persona 隔离且可重置。

- [x] 先提交失败测试证据
- [x] 完成最小实现与兼容路径
- [x] 验证 `world_inprocess_v1` 关闭后的旧路径
- [x] 记录脱敏 Evidence、指标与守恒结果
- [x] 完成回滚演练并更新 `rollback_ready`

## 链接
[[Phase 12]] · [[90_全局验收清单]] · [[92_回滚演练]]

## Evidence
- 2026-07-21 Red: `python -m pytest tests/test_phase12_world_domain.py -q` -> expected failures for missing `core.world_simulation`, `core.action_registry`, `core.relationship_engine`, `core.self_model`, ContextBuilder world args, and Pipeline provider passthrough.
- 2026-07-21 Green: `python -m pytest tests/test_phase12_world_domain.py -q` -> `7 passed`.
- 2026-07-21 Regression: `python -m pytest tests/test_phase12_world_domain.py tests/test_phase11_world_port.py tests/test_phase10_image_workflow.py tests/test_upload.py tests/test_api.py tests/test_phase4_chat_request_service.py tests/test_phase4_api.py tests/test_phase8_proactive_feedback.py tests/test_phase1_proactive_baseline.py -q` -> `120 passed, 4 warnings`.
- 2026-07-21 Syntax: `python -m py_compile core/world_simulation.py core/action_registry.py core/relationship_engine.py core/self_model.py core/world_port.py core/companion.py core/context_builder.py core/pipeline.py` passed.
- Rollback: keep `world_inprocess_v1: false` or set `AERIE_FEATURE_WORLD_INPROCESS_V1=false`; Companion uses `NullWorldAdapter`, Pipeline providers return no world/relationship/SelfModel context, no world.db/Sidecar/image-candidate side effects are created.
