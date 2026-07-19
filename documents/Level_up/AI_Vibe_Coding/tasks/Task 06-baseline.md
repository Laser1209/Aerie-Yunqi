---
title: Task 06-baseline
tags: [aerie, task, phase06, core]
kind: task
task_id: TASK-06-001
phase: Phase 06
subsystem: core
status: planned
priority: P1
dependencies: ["TASK-05-001"]
risk: medium
decision_required: false
feature_flag: context_budget_v1
migration: false
files: ["core/context_builder.py", "core/pipeline.py"]
acceptance_ids: ["A-06-01", "A-06-02"]
rollback_ready: false
owner: core-team
evidence: ["file:///E:/Agent_reply/core/context_builder.py", "file:///E:/Agent_reply/core/pipeline.py"]
---
# Task 06-baseline
> [!todo] Phase 06
> 按固定优先级构建完整 Turn 上下文并审计 token；验收目标：多气泡合并为完整 assistant 响应，短期不跨 Channel。

- [ ] 先提交失败测试证据
- [ ] 完成最小实现与兼容路径
- [ ] 验证 `context_budget_v1` 关闭后的旧路径
- [ ] 记录脱敏 Evidence、指标与守恒结果
- [ ] 完成回滚演练并更新 `rollback_ready`

## 链接
[[Phase 06]] · [[90_全局验收清单]] · [[92_回滚演练]]
