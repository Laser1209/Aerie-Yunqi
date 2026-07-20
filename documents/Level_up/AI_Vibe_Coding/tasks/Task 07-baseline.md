---
title: Task 07-baseline
tags: [aerie, task, phase07, core]
kind: task
task_id: TASK-07-001
phase: Phase 07
subsystem: core
status: in_progress
priority: P1
dependencies: ["TASK-06-001"]
risk: medium
decision_required: false
feature_flag: chat_stream_v1
migration: false
files: ["electron/src/renderer/js/chat.js", "electron/src/renderer/styles/main.css", "electron/tests/chat-request-queue.test.js"]
acceptance_ids: ["A-07-01", "A-07-02"]
rollback_ready: false
owner: core-team
evidence: ["file:///E:/Agent_reply/electron/src/renderer/js/chat.js", "file:///E:/Agent_reply/electron/src/renderer/styles/main.css", "file:///E:/Agent_reply/electron/tests/chat-request-queue.test.js"]
---
# Task 07-baseline
> [!todo] Phase 07
> delta 临时气泡、最终语义拆分、Typing 与 Persona Pacing；验收目标：Typing/首 delta/取消/多气泡顺序达标。

- [ ] 先提交失败测试证据
- [ ] 完成最小实现与兼容路径
- [ ] 验证 `chat_stream_v1` 关闭后的旧路径
- [ ] 记录脱敏 Evidence、指标与守恒结果
- [ ] 完成回滚演练并更新 `rollback_ready`

## 链接
[[Phase 07]] · [[90_全局验收清单]] · [[92_回滚演练]]
