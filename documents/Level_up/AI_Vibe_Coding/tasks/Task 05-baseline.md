---
title: Task 05-baseline
tags: [aerie, task, phase05, core]
kind: task
task_id: TASK-05-001
phase: Phase 05
subsystem: core
status: done
priority: P1
dependencies: ["TASK-04-001"]
risk: medium
decision_required: false
feature_flag: chat_stream_v1
migration: false
files: ["core/event_stream.py", "core/api_server.py", "electron/src/main.js"]
acceptance_ids: ["A-05-01", "A-05-02"]
rollback_ready: true
owner: core-team
evidence: ["file:///E:/Agent_reply/core/event_stream.py", "file:///E:/Agent_reply/core/api_server.py", "file:///E:/Agent_reply/electron/src/main.js", "file:///E:/Agent_reply/tests/test_phase5_event_stream.py", "file:///E:/Agent_reply/electron/tests/sse-bridge.test.js"]
---
# Task 05-baseline
> [!todo] Phase 05
> SSE id、恢复窗口、Renderer 去重排序与游标续连；验收目标：stderr、IPC、SSE、poll 不重复气泡。

- [x] 先提交失败测试证据
- [x] 完成最小实现与兼容路径
- [x] 验证 `chat_stream_v1` 关闭后的旧路径
- [x] 记录脱敏 Evidence、指标与守恒结果
- [x] 完成回滚演练并更新 `rollback_ready`

## Evidence（2026-07-20）

- Red：`tests/test_phase5_event_stream.py` 初跑 `5 errors in 3.55s`，失败点为缺少 event stream 测试 reset、新 stream replay 参数与 API Flag 传参；`electron/tests/sse-bridge.test.js` 初跑 `3 failed`，失败点为缺少 Electron SSE helper。
- Green：新增后端 `5 passed, 4 warnings in 2.77s`；Electron SSE helper 与聊天队列合并回归 `16 passed`。
- 关联门禁：Phase 00–05/API/Pipeline 显式范围 `264 passed, 4 warnings in 27.60s`；完整 `tests` 收集 `477 passed, 6 warnings in 35.77s`。
- 静态/收尾：`py_compile`、`node --check electron/src/main.js`、`node --check electron/src/preload.js` 均通过；`git diff --check` 只有 Windows LF→CRLF 提示；项目进程检查无残留。
- 回滚：关闭 `chat_stream_v1` 后 API 不传 `Last-Event-ID`、不启用 replay，`stream()` 保持旧 `data:` 帧；本阶段没有 schema/data migration，也没有生产 DB 写入。

## 链接
[[Phase 05]] · [[90_全局验收清单]] · [[92_回滚演练]]
