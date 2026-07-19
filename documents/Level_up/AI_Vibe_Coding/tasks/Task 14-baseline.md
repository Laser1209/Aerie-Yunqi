---
title: Task 14-baseline
tags: [aerie, task, phase14, world]
kind: task
task_id: TASK-14-001
phase: Phase 14
subsystem: world
status: planned
priority: P0
dependencies: ["TASK-13-001"]
risk: high
decision_required: false
feature_flag: world_image_candidates_v1
migration: false
files: ["core/proactive_judge.py", "core/attachment_handler.py"]
acceptance_ids: ["A-14-01", "A-14-02"]
rollback_ready: false
owner: world-team
evidence: ["file:///E:/Agent_reply/core/proactive_judge.py", "file:///E:/Agent_reply/core/attachment_handler.py"]
---
# Task 14-baseline
> [!todo] Phase 14
> World 只产 ImageCandidate，Core 执行 Judge 到 ACK；验收目标：重复、过期、静音、拒绝、失败、离线均无重复副作用。

- [ ] 先提交失败测试证据
- [ ] 完成最小实现与兼容路径
- [ ] 验证 `world_image_candidates_v1` 关闭后的旧路径
- [ ] 记录脱敏 Evidence、指标与守恒结果
- [ ] 完成回滚演练并更新 `rollback_ready`

## 链接
[[Phase 14]] · [[90_全局验收清单]] · [[92_回滚演练]]
