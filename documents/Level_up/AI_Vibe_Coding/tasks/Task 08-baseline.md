---
title: Task 08-baseline
tags: [aerie, task, phase08, core]
kind: task
task_id: TASK-08-001
phase: Phase 08
subsystem: core
status: planned
priority: P1
dependencies: ["TASK-07-001"]
risk: medium
decision_required: false
feature_flag: proactive_delivery_v2
migration: false
files: ["core/proactive_judge.py", "core/push_scheduler.py"]
acceptance_ids: ["A-08-01", "A-08-02"]
rollback_ready: false
owner: core-team
evidence: ["file:///E:/Agent_reply/core/proactive_judge.py", "file:///E:/Agent_reply/core/push_scheduler.py"]
---
# Task 08-baseline
> [!todo] Phase 08
> 持久化 cooldown、反馈、mute、postpone 与用户设置；验收目标：设置与频控跨重启，负反馈降频。

- [ ] 先提交失败测试证据
- [ ] 完成最小实现与兼容路径
- [ ] 验证 `proactive_delivery_v2` 关闭后的旧路径
- [ ] 记录脱敏 Evidence、指标与守恒结果
- [ ] 完成回滚演练并更新 `rollback_ready`

## 链接
[[Phase 08]] · [[90_全局验收清单]] · [[92_回滚演练]]
