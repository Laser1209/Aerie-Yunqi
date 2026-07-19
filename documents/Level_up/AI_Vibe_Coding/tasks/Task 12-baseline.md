---
title: Task 12-baseline
tags: [aerie, task, phase12, world]
kind: task
task_id: TASK-12-001
phase: Phase 12
subsystem: world
status: planned
priority: P1
dependencies: ["TASK-11-001"]
risk: medium
decision_required: false
feature_flag: world_inprocess_v1
migration: false
files: ["core/companion.py", "core/context_builder.py"]
acceptance_ids: ["A-12-01", "A-12-02"]
rollback_ready: false
owner: world-team
evidence: ["file:///E:/Agent_reply/core/companion.py", "file:///E:/Agent_reply/core/context_builder.py"]
---
# Task 12-baseline
> [!todo] Phase 12
> 确定性 Tick、Action Registry、关系与 SelfModel；验收目标：同 seed/时钟同快照，关系按 Persona 隔离且可重置。

- [ ] 先提交失败测试证据
- [ ] 完成最小实现与兼容路径
- [ ] 验证 `world_inprocess_v1` 关闭后的旧路径
- [ ] 记录脱敏 Evidence、指标与守恒结果
- [ ] 完成回滚演练并更新 `rollback_ready`

## 链接
[[Phase 12]] · [[90_全局验收清单]] · [[92_回滚演练]]
