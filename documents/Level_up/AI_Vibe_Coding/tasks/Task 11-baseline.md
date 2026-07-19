---
title: Task 11-baseline
tags: [aerie, task, phase11, world]
kind: task
task_id: TASK-11-001
phase: Phase 11
subsystem: world
status: planned
priority: P1
dependencies: ["TASK-10-001"]
risk: medium
decision_required: true
feature_flag: world_inprocess_v1
migration: false
files: ["core/companion.py", "electron/src/main.js"]
acceptance_ids: ["A-11-01", "A-11-02"]
rollback_ready: false
owner: world-team
evidence: ["file:///E:/Agent_reply/core/companion.py", "file:///E:/Agent_reply/electron/src/main.js"]
---
# Task 11-baseline
> [!todo] Phase 11
> WorldPort 五接口、Null/InProcess Adapter 与能力白名单；验收目标：禁用世界不影响聊天，契约测试一致。

- [ ] 先提交失败测试证据
- [ ] 完成最小实现与兼容路径
- [ ] 验证 `world_inprocess_v1` 关闭后的旧路径
- [ ] 记录脱敏 Evidence、指标与守恒结果
- [ ] 完成回滚演练并更新 `rollback_ready`

## 链接
[[Phase 11]] · [[90_全局验收清单]] · [[92_回滚演练]]
