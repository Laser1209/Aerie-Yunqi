---
title: Task 05-baseline
tags: [aerie, task, phase05, core]
kind: task
task_id: TASK-05-001
phase: Phase 05
subsystem: core
status: planned
priority: P1
dependencies: ["TASK-04-001"]
risk: medium
decision_required: false
feature_flag: chat_stream_v1
migration: false
files: ["core/event_stream.py", "electron/src/main.js"]
acceptance_ids: ["A-05-01", "A-05-02"]
rollback_ready: false
owner: core-team
evidence: ["file:///E:/Agent_reply/core/event_stream.py", "file:///E:/Agent_reply/electron/src/main.js"]
---
# Task 05-baseline
> [!todo] Phase 05
> SSE id、恢复窗口、Renderer 去重排序与游标续连；验收目标：stderr、IPC、SSE、poll 不重复气泡。

- [ ] 先提交失败测试证据
- [ ] 完成最小实现与兼容路径
- [ ] 验证 `chat_stream_v1` 关闭后的旧路径
- [ ] 记录脱敏 Evidence、指标与守恒结果
- [ ] 完成回滚演练并更新 `rollback_ready`

## 链接
[[Phase 05]] · [[90_全局验收清单]] · [[92_回滚演练]]
