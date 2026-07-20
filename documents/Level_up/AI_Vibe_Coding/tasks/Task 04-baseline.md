---
title: Task 04-baseline
tags: [aerie, task, phase04, core, chat, queue]
kind: task
task_id: TASK-04-001
phase: Phase 04
subsystem: chat
status: review
priority: P0
dependencies: ["TASK-03-001"]
risk: high
decision_required: false
feature_flag: chat_request_queue_v1
migration: true
files:
  - core/chat_request_repository.py
  - core/chat_request_worker.py
  - core/chat_request_service.py
  - core/migrations/__init__.py
  - core/conversation_repository.py
  - core/companion.py
  - core/api_server.py
  - core/pipeline.py
  - electron/src/renderer/js/chat.js
acceptance_ids: ["A-04-01", "A-04-02", "A-04-03", "A-04-04", "A-04-05", "A-04-06", "A-04-07", "A-04-08", "A-04-09", "A-04-10"]
rollback_ready: false
owner: core-team
evidence:
  - file:///E:/Agent_reply/documents/Level_up/AI_Vibe_Coding/phases/Phase%2004.md
  - file:///E:/Agent_reply/core/api_server.py
  - file:///E:/Agent_reply/core/conversation_repository.py
  - file:///E:/Agent_reply/electron/src/renderer/js/chat.js
---
# Task 04-baseline

> [!todo] Phase 04 书面设计已批准，待规范审核
> 建立数据库驱动的持久 Request 队列：同 Conversation 串行、跨 Conversation 默认四路并行，支持 queued/running 真实取消、新 Request 重试、重启恢复、租约与纯附件。当前只完成设计固化，尚未进入 TDD 实施。

## 已批准合同

- `/api/chat/send` 在 `chat_request_queue_v1=true` 时原路径异步化并返回 HTTP 202；关闭时保持同步 HTTP 200。
- queued Request 在同一短事务中创建 Conversation、pending Turn 与不可变输入快照，保持 `requests.turn_id NOT NULL`。
- `ConversationRepository.persist_turn()` 完成已有 Turn/Request，禁止重复插入同一 `request_id`；legacy 同步路径保持兼容。
- 同一 Conversation 串行；不同 Conversation 默认最多四路。
- queued 直接取消；running 进入 cancelling 并真实取消 `asyncio.Task`。
- failed/cancelled 仅通过新 Request 重试；新请求关联 `retry_of_request_id` 并分配新 Turn。
- queued 在重启后继续可领取；遗留 running/cancelling 和 lease 过期转 `failed/process_interrupted`，不自动重排。
- 纯附件保留空 `input_content`，内部 `effective_content` 不进入用户可见历史。
- 复用 EventEnvelope；SSE 保持 best-effort，断线后查询 Request 状态恢复。

## TDD 批次

- [ ] Migration Red：新增独立版本，验证字段、索引、checksum、幂等、旧库兼容与 quick_check。
- [ ] Repository Red：验证提交原子性、预分配 Turn、claim、Conversation 互斥、lease/heartbeat 与状态守恒。
- [ ] Service Red：验证 202 提交、纯附件、所有权、取消与新 ID 重试。
- [ ] Worker Red：验证四路槽、同 Conversation 串行、真实 Task 取消、启动恢复与 lease 过期失败。
- [ ] Pipeline Red：在模型、持久化、规范镜像、事件和外部投递边界检查取消，禁止重复副作用。
- [ ] API Red：Flag 开启为异步 202；Flag 关闭保持原同步 200 与空消息 400 合同。
- [ ] Renderer Red：连续三条输入、请求级状态、取消/重试、统一去重与页面恢复。
- [ ] 集成与 Electron smoke：IPC/SSE/poll 不重复，状态恢复符合后端真源。
- [ ] 使用生产数据一致性副本完成迁移、恢复与数据守恒演练，不直接改写生产库。
- [ ] 完整回归、脱敏 Evidence、指标与回滚文档收口后更新 `rollback_ready`。

## 阶段门禁

- [ ] 先提交并亲自观察每批目标行为缺失导致的 Red。
- [ ] 每批只写使目标测试 Green 的最小实现，再运行关联与完整回归。
- [ ] Request/Turn/Message 状态和记录数守恒，无重复主键、孤立 Turn 或半完成 Request。
- [ ] `chat_request_queue_v1=false` 完整恢复旧路径，但不破坏新列、新数据或 Evidence。
- [ ] 完成 Phase 04 全部验收与回滚演练前，不进入 Phase 05。

## 链接

[[Phase 04]] · [[05_Feature_Flag与回滚矩阵]] · [[90_全局验收清单]] · [[91_数据迁移核对]] · [[92_回滚演练]]
