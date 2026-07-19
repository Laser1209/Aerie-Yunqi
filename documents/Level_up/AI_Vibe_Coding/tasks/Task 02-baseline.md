---
title: Task 02-baseline
tags: [aerie, task, phase02, core]
kind: task
task_id: TASK-02-001
phase: Phase 02
subsystem: core
status: planned
priority: P1
dependencies: ["TASK-01-001"]
risk: medium
decision_required: true
feature_flag: identity_contract_v1
migration: true
files: ["core/context_builder.py", "core/persona_hub/persona_manager.py"]
acceptance_ids: ["A-02-01", "A-02-02"]
rollback_ready: false
owner: core-team
evidence: ["file:///E:/Agent_reply/core/context_builder.py", "file:///E:/Agent_reply/core/persona_hub/persona_manager.py"]
---
# Task 02-baseline
> [!todo] Phase 02
> IncomingMessage 增加 Actor/Channel 身份合同，Persona Hub 为真源；验收目标：同 Actor 跨 Channel 只共享长期记忆。

- [ ] 先提交失败测试证据
- [ ] 完成最小实现与兼容路径
- [ ] 验证 `identity_contract_v1` 关闭后的旧路径
- [ ] 记录脱敏 Evidence、指标与守恒结果
- [ ] 完成回滚演练并更新 `rollback_ready`

## 链接
[[Phase 02]] · [[90_全局验收清单]] · [[92_回滚演练]]
