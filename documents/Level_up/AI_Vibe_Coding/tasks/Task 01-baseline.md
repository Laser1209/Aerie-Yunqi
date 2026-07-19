---
title: Task 01-baseline
tags: [aerie, task, phase01, core]
kind: task
task_id: TASK-01-001
phase: Phase 01
subsystem: core
status: planned
priority: P0
dependencies: ["TASK-00-001"]
risk: medium
decision_required: false
feature_flag: proactive_delivery_v2
migration: false
files: ["core/push_scheduler.py", "core/companion.py"]
acceptance_ids: ["A-01-01", "A-01-02"]
rollback_ready: false
owner: core-team
evidence: ["file:///E:/Agent_reply/core/push_scheduler.py", "file:///E:/Agent_reply/core/companion.py"]
---
# Task 01-baseline
> [!todo] Phase 01
> 统一 trigger、生命周期、Desire 属性与独立 Delivery；验收目标：Cron、手动、Desire、Idle、quiet、force 与 QQ 断线通过。

- [ ] 先提交失败测试证据
- [ ] 完成最小实现与兼容路径
- [ ] 验证 `proactive_delivery_v2` 关闭后的旧路径
- [ ] 记录脱敏 Evidence、指标与守恒结果
- [ ] 完成回滚演练并更新 `rollback_ready`

## 链接
[[Phase 01]] · [[90_全局验收清单]] · [[92_回滚演练]]
