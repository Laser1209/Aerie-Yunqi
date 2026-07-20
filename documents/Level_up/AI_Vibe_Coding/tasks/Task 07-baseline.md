---
title: Task 07-baseline
tags: [aerie, task, phase07, core]
kind: task
task_id: TASK-07-001
phase: Phase 07
subsystem: core
status: done
priority: P1
dependencies: ["TASK-06-001"]
risk: medium
decision_required: false
feature_flag: chat_stream_v1
migration: false
files: ["electron/src/renderer/js/chat.js", "electron/src/renderer/styles/main.css", "electron/tests/chat-request-queue.test.js"]
acceptance_ids: ["A-07-01", "A-07-02"]
rollback_ready: true
owner: core-team
evidence: ["file:///E:/Agent_reply/electron/src/renderer/js/chat.js", "file:///E:/Agent_reply/electron/src/renderer/styles/main.css", "file:///E:/Agent_reply/electron/tests/chat-request-queue.test.js"]
progress_note: "2026-07-21: renderer typing bubble, request rebinding, reduced-motion fallback, chat_stream_v1-off path, and rollback matrix checks are green."
---
# Task 07-baseline
> [!todo] Phase 07
> delta 临时气泡、最终语义拆分、Typing 与 Persona Pacing；验收目标：Typing/首 delta/取消/多气泡顺序达标。

- [x] 先提交失败测试证据
- [x] 完成最小实现与兼容路径
- [x] 验证 `chat_stream_v1` 关闭后的旧路径
- [x] 记录脱敏 Evidence、指标与守恒结果
- [x] 完成回滚演练并更新 `rollback_ready`

## Evidence
- 2026-07-21：`node --test electron/tests/chat-request-queue.test.js` → `15 passed`；`node --test electron/tests/sse-bridge.test.js` → `5 passed`。
- 2026-07-21：`pytest -q tests/test_phase5_event_stream.py` → `5 passed`；`pytest -q tests/test_phase4_integration.py -k flag_rollback_matrix` → `1 passed`。

## 链接
[[Phase 07]] · [[90_全局验收清单]] · [[92_回滚演练]]
