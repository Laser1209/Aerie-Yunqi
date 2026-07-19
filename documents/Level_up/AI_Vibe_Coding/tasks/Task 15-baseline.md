---
title: Task 15-baseline
tags: [aerie, task, phase15, world]
kind: task
task_id: TASK-15-001
phase: Phase 15
subsystem: world
status: planned
priority: P1
dependencies: ["TASK-14-001"]
risk: high
decision_required: false
feature_flag: world_sidecar_v1
migration: false
files: ["electron/src/main.js", "electron/src/preload.js"]
acceptance_ids: ["A-15-01", "A-15-02"]
rollback_ready: false
owner: world-team
evidence: ["file:///E:/Agent_reply/electron/src/main.js", "file:///E:/Agent_reply/electron/src/preload.js"]
---
# Task 15-baseline
> [!todo] Phase 15
> Dashboard、候选审批、插件健康、创意工坊与发布状态；验收目标：异常状态完整，插件隐藏后聊天可发布。

- [ ] 先提交失败测试证据
- [ ] 完成最小实现与兼容路径
- [ ] 验证 `world_sidecar_v1` 关闭后的旧路径
- [ ] 记录脱敏 Evidence、指标与守恒结果
- [ ] 完成回滚演练并更新 `rollback_ready`

## 链接
[[Phase 15]] · [[90_全局验收清单]] · [[92_回滚演练]]
