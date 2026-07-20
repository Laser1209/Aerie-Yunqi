---
title: Task 03-baseline
tags: [aerie, task, phase03, core]
kind: task
task_id: TASK-03-001
phase: Phase 03
subsystem: core
status: in_progress
priority: P0
dependencies: ["TASK-02-001"]
risk: high
decision_required: false
feature_flag: conversation_model_v1
migration: true
files: ["core/database.py", "core/pipeline.py"]
acceptance_ids: ["A-03-01", "A-03-02"]
rollback_ready: false
owner: core-team
evidence: ["file:///E:/Agent_reply/core/database.py", "file:///E:/Agent_reply/core/pipeline.py"]
---
# Task 03-baseline
> [!todo] Phase 03
> 四表、状态机、response_group_id、sequence 与幂等回填；验收目标：记录、附件、角色顺序和 Channel 守恒。

- [ ] 先提交失败测试证据
- [ ] 完成最小实现与兼容路径
- [ ] 验证 `conversation_model_v1` 关闭后的旧路径
- [ ] 记录脱敏 Evidence、指标与守恒结果
- [ ] 完成回滚演练并更新 `rollback_ready`

## 链接
[[Phase 03]] · [[90_全局验收清单]] · [[92_回滚演练]]
