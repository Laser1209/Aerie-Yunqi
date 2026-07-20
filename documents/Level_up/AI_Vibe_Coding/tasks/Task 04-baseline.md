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

> [!success] Phase 04 Task 1–6 已按严格 TDD 收口
> 书面规范和逐批实施计划已批准；Phase 00–03 门禁、006 Migration、测试 Fixture、ChatRequestRepository、ConversationRepository 完成路径与 ChatRequestService 均已通过真实 Red → Green 和完整回归。当前下一小节为 ChatRequestWorker Red，`rollback_ready` 继续保持 false。
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
- [x] Repository Red/Green：验证提交原子性、预分配 Turn、claim、Conversation 互斥、lease/heartbeat、恢复、retry 与状态守恒。
- [x] ConversationRepository Red/Green：完成同一预分配 Request/Turn、可信输入快照、幂等冲突、SAVEPOINT 回滚、completed-only history 和 orphan 守恒。
- [x] Service Red/Green：验证可信提交、纯附件、所有权、取消竞态、稳定错误合同、脱敏 DTO 与新 ID 重试；HTTP 202 映射保留至 API Task 9。
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

## ConversationRepository Task 5 Evidence

- 接管基线为 `16 passed`，但缺 3 个固定测试名且允许 queued 直接完成；补齐状态、快照和终态清理合同后观察到目标 Red：`6 failed, 18 passed`。
- Green：Repository 专项 `24 passed in 4.18s`；Phase 3 + Phase 4 migration/repository `50 passed in 6.07s`；Phase 00–04 + API + Pipeline `174 passed, 5 warnings in 11.84s`。
- 完整 Python：`387 passed, 1 deselected, 7 warnings in 28.35s`；被排除的办公目录环境用例在工作区临时目录中单独 `1 passed`。
- 状态与原子性：仅 running/running 可完成；queued/cancelling 不可覆盖；Message、Request、Turn 在同一 SAVEPOINT 内提交，注入失败后保持 running/running 且 Message=0。
- 不可变快照：conversation/turn、Actor、Channel、Channel Account、legacy user_id、可见输入与附件不一致统一抛 `RequestConflict`；completed 幂等返回原 ID，不同结果不覆盖。
- 终态清理：completed 同时清 `lease_owner`、`lease_expires_at`、`error`、`error_code`；failed/cancelled/pending 不进入近期完成历史。
- 只读生产审计：四表计数 `4/299/299/1754`；`quick_check=ok`，FK、活跃 Conversation、Request/Turn 状态错配、orphan Turn/Request/Message 均为 0；未写生产库。
- Python `py_compile`、Electron Persona `3 passed`、相关 Node 语法检查与 `git diff --check` 通过；`rollback_ready=false`，下一批从 Service Red 开始。

## ChatRequestService Task 6 Evidence

- 首轮 Red：`15 failed, 1 passed`，目标缺口为 Service 模块不存在；未修改 API。首轮 Green 后风险复核补出 cancel/附件边界 Red：`5 failed, 18 passed`。
- 最终 Green：Service 专项 `25 passed in 4.40s`；身份/Conversation/migration/Repository/Service/upload 关联 `114 passed, 5 warnings`；Phase 00–04 + API + Pipeline `199 passed, 5 warnings`。
- 完整 Python：`411 passed, 1 deselected, 7 warnings`；办公目录环境用例在工作区临时目录单独通过。
- 可信身份：只调用 `IdentityRepository.resolve("desktop", "local")`；公开 submit 签名不含 actor/conversation/turn，legacy user_id 仅作兼容寻址。
- 纯附件与安全：空可见输入和内部中性输入分离；只接收 ready、五字段、单层 safe-name 上传元数据，拒绝非 ready、穿越、编码分隔符和客户端正文/路径/Markdown。
- 所有权与 DTO：get/cancel/retry 对缺失和非所有者完全等价；响应不含 input/effective/attachments/lease/error，序列化值扫描也不含敏感测试值。
- cancel/retry：三种终态 cancel 幂等；非法状态 retry 冲突；failed/cancelled 创建新 Request/Turn；事务返回状态消除 queued→running 与 running→completed 的 cancel TOCTOU。
- 兼容边界：Service 尚未注入 Companion/API，旧同步聊天、Pipeline、QQ 和 Renderer 没有行为变化；`rollback_ready=false`，下一批从 Worker Red 开始。

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
