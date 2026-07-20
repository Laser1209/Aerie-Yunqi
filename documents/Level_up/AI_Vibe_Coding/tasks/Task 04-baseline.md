---
title: Task 04-baseline
tags: [aerie, task, phase04, core, chat, queue]
kind: task
task_id: TASK-04-001
phase: Phase 04
subsystem: chat
status: in_progress
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

> [!success] Phase 04 已进入严格 TDD 实施
> 书面规范和逐批实施计划已批准；Phase 00–03 门禁、006 Migration 与测试 Fixture 批次均已通过真实 Red → Green 和完整回归。当前下一小节为 Repository Red，`rollback_ready` 继续保持 false。
>
> [Phase 04 持久 Request 队列实施计划](file:///E:/Agent_reply/documents/Level_up/AI_Vibe_Coding/plans/2026-07-20-Phase-04-%E6%8C%81%E4%B9%85Request%E9%98%9F%E5%88%97%E5%AE%9E%E6%96%BD%E8%AE%A1%E5%88%92.md)

## 执行基线

- [x] 2026-07-20 重读总实施计划、Phase 04 规范、Task 与批次规约。
- [x] Phase 00–03 + API + Pipeline 门禁复验：`141 passed, 4 warnings in 4.64s`。
- [x] 完整 Python 基线：`353 passed, 6 warnings in 10.56s`。
- [x] 确认 006 尚不存在且 Renderer `_loading` 仍有 4 处；Phase 04 未被提前实现。
- [x] 确认未写生产库、构建产物或无关文件，下一批从 Migration Red 开始。

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

- [x] Migration Red/Green：独立 `006_chat_request_queue` 已由真实失败测试驱动完成；16 个字段、3 个索引、固定 checksum、dry-run、幂等、部分应用恢复、旧库兼容与 quick_check 均通过。
- [ ] Repository Red：验证提交原子性、预分配 Turn、claim、Conversation 互斥、lease/heartbeat 与状态守恒。
- [ ] Service Red：验证 202 提交、纯附件、所有权、取消与新 ID 重试。
- [ ] Worker Red：验证四路槽、同 Conversation 串行、真实 Task 取消、启动恢复与 lease 过期失败。
- [ ] Pipeline Red：在模型、持久化、规范镜像、事件和外部投递边界检查取消，禁止重复副作用。
- [ ] API Red：Flag 开启为异步 202；Flag 关闭保持原同步 200 与空消息 400 合同。
- [ ] Renderer Red：连续三条输入、请求级状态、取消/重试、统一去重与页面恢复。
- [ ] 集成与 Electron smoke：IPC/SSE/poll 不重复，状态恢复符合后端真源。
- [ ] 使用生产数据一致性副本完成迁移、恢复与数据守恒演练，不直接改写生产库。
- [ ] 完整回归、脱敏 Evidence、指标与回滚文档收口后更新 `rollback_ready`。

## 006 Migration Evidence

- Red：`8 failed, 1 passed in 0.39s`，目标缺口为 006 工厂、字段和 Database 注册缺失。
- Green：专项 `9 passed in 0.24s`；迁移 + Phase 0/3 `40 passed in 1.82s`；关联回归 `112 passed, 4 warnings in 4.72s`；完整 Python `362 passed, 6 warnings in 12.47s`。
- checksum：`2e649f6834695ca7b9250c3e2f7c110ab9c5b2c4ed2a230d1cd4fb5e0654ea05`；004/005 未修改。
- 本批未操作生产库；一致性副本迁移和实际恢复仍未完成，因此 `rollback_ready=false`。

## ChatRequestRepository Evidence

- Red：收集阶段 `ModuleNotFoundError: No module named 'core.chat_request_repository'`，目标缺口明确。
- Green：Repository 专项 `10 passed in 1.01s`；Phase 3/4 关联 `36 passed in 2.99s`；完整 Python `374 passed, 6 warnings in 18.17s`。
- 状态守恒：queued/pending、running/running、cancelled/cancelled、failed/failed 均由测试查询验证；恢复计数为 `2`，运行项转 `failed/process_interrupted`，queued 未被自动重排。
- 并发与租约：同 Conversation 第二请求保持 queued；不同 Conversation 可继续 claim；错误 lease owner heartbeat 返回 false，正确 owner 延长 UTC lease。
- retry：原 request 保持 failed/error_code，新 request 与新 pending turn 使用独立 ID 并写入 `retry_of_request_id`。
- 安全边界：Repository 无 Brain/Pipeline/chat_events/QQ 依赖；Evidence 不记录 input/effective content；`rollback_ready=false` 保持不变。

## 测试 Fixture Evidence

- Red：`2 errors in 0.07s`，目标缺口明确为 `phase4_db` 和 `ready_attachment` Fixture 尚未定义。
- Green：三个 Fixture 探针 `3 passed in 0.20s`；Phase 0/3/4 关联回归 `43 passed in 2.03s`；完整 Python `365 passed, 6 warnings in 14.83s`。
- 隔离合同：临时文件名 `phase4.db`、固定 UTC `2026-07-20T00:00:00+00:00`、ready 附件只含脱敏服务端元数据；异步 double 暴露 `started/release/cancel_seen`，不访问网络、QQ 或真实模型。
- `py_compile`、相关 diagnostics 与 `git diff --check` 通过；尚未勾选 Service、Worker 或回滚验收。

## 阶段门禁

- [ ] 先提交并亲自观察每批目标行为缺失导致的 Red。
- [ ] 每批只写使目标测试 Green 的最小实现，再运行关联与完整回归。
- [ ] Request/Turn/Message 状态和记录数守恒，无重复主键、孤立 Turn 或半完成 Request。
- [ ] `chat_request_queue_v1=false` 完整恢复旧路径，但不破坏新列、新数据或 Evidence。
- [ ] 完成 Phase 04 全部验收与回滚演练前，不进入 Phase 05。

## 链接

[[Phase 04]] · [[05_Feature_Flag与回滚矩阵]] · [[90_全局验收清单]] · [[91_数据迁移核对]] · [[92_回滚演练]]
