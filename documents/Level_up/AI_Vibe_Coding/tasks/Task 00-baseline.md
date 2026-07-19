---
title: Task 00-baseline
tags: [aerie, task, phase00, core]
kind: task
task_id: TASK-00-001
phase: Phase 00
subsystem: core
status: planned
priority: P0
dependencies: []
risk: high
decision_required: false
feature_flag: migration_framework_v1
migration: true
files: ["core/database.py", "core/chat_events.py"]
acceptance_ids: ["A-00-01", "A-00-02"]
rollback_ready: false
owner: core-team
evidence: ["file:///E:/Agent_reply/core/database.py", "file:///E:/Agent_reply/core/chat_events.py"]
---
# Task 00-baseline
> [!todo] Phase 00
> 迁移账本、EventEnvelope 与 Feature Flag 审计；验收目标：空库、现有库、重复运行和中断续跑通过。

- [ ] 先提交失败测试证据
- [ ] 完成最小实现与兼容路径
- [ ] 验证 `migration_framework_v1` 关闭后的旧路径
- [ ] 记录脱敏 Evidence、指标与守恒结果
- [ ] 完成回滚演练并更新 `rollback_ready`

## 链接
[[Phase 00]] · [[90_全局验收清单]] · [[92_回滚演练]]
