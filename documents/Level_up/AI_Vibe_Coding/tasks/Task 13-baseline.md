---
title: Task 13-baseline
tags: [aerie, task, phase13, world]
kind: task
task_id: TASK-13-001
phase: Phase 13
subsystem: world
status: blocked
priority: P0
dependencies: ["TASK-12-001"]
risk: high
decision_required: true
feature_flag: world_sidecar_v1
migration: true
files: ["electron/src/main.js", "core/event_stream.py"]
acceptance_ids: ["A-13-01", "A-13-02"]
rollback_ready: false
owner: world-team
evidence: ["file:///E:/Agent_reply/electron/src/main.js", "file:///E:/Agent_reply/core/event_stream.py"]
---
# Task 13-baseline
> [!todo] Phase 13
> world.db 单一所有者、Outbox、ACK cursor、heartbeat 与监管；验收目标：Sidecar 崩溃聊天继续，重启续传不重复。

- [ ] 先提交失败测试证据
- [ ] 完成最小实现与兼容路径
- [ ] 验证 `world_sidecar_v1` 关闭后的旧路径
- [ ] 记录脱敏 Evidence、指标与守恒结果
- [ ] 完成回滚演练并更新 `rollback_ready`

## 链接
[[Phase 13]] · [[90_全局验收清单]] · [[92_回滚演练]]
