---
title: Task 04-baseline
tags: [aerie, task, phase04, core]
kind: task
task_id: TASK-04-001
phase: Phase 04
subsystem: core
status: planned
priority: P1
dependencies: ["TASK-03-001"]
risk: medium
decision_required: false
feature_flag: chat_request_queue_v1
migration: false
files: ["core/api_server.py", "electron/src/renderer/js/chat.js"]
acceptance_ids: ["A-04-01", "A-04-02"]
rollback_ready: false
owner: core-team
evidence: ["file:///E:/Agent_reply/core/api_server.py", "file:///E:/Agent_reply/electron/src/renderer/js/chat.js"]
---
# Task 04-baseline
> [!todo] Phase 04
> 同 Conversation 串行、跨 Conversation 并行、取消重试与纯附件合同；验收目标：连续三条输入不丢失，取消不误记 completed。

- [ ] 先提交失败测试证据
- [ ] 完成最小实现与兼容路径
- [ ] 验证 `chat_request_queue_v1` 关闭后的旧路径
- [ ] 记录脱敏 Evidence、指标与守恒结果
- [ ] 完成回滚演练并更新 `rollback_ready`

## 链接
[[Phase 04]] · [[90_全局验收清单]] · [[92_回滚演练]]
