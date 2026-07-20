---
title: Phase 04 - 持久 Request 队列、取消、重试与纯附件
kind: phase
phase: Phase 04
status: review
tags: [aerie, phase, phase04, chat, queue]
---
# Phase 04：持久 Request 队列、取消、重试与纯附件

> [!info] 执行边界
> 只按获批设计与后续 TDD 实施计划执行；当前阶段未通过验收时停止后续阶段。

## 已批准决策

- `/api/chat/send` 保持原路径：`chat_request_queue_v1=true` 时返回 `202 Accepted`、`request_id` 和 `queued`；Flag 关闭时恢复现有同步 `200` 合同。
- 采用数据库驱动的 `ChatRequestWorker`，不采用 Renderer-only 队列或通用 `AsyncTaskManager`。
- 同一 Conversation 串行；不同 Conversation 默认最多并行 `4` 路。
- queued 与 running 均支持真实后端取消，不允许仅隐藏 UI。
- 重试创建新的 `request_id`，通过 `retry_of_request_id` 关联原请求；原请求终态不覆盖。
- 重启时恢复 queued；遗留 running 或租约过期请求转 `failed/process_interrupted`，不自动重排。
- 纯附件允许空可见文本；仅在内部生成中性 `effective_content`，不得写入用户可见历史。

## 目标

建立可持久、可取消、可重试、可恢复的聊天 Request 队列：同 Conversation 严格串行、跨 Conversation 最多四路并行；统一请求状态、事件标识和 Renderer 去重；保持旧同步路径、现有 Pipeline 与 legacy poll 兼容。

## 非目标

- 不整体重写 Pipeline。
- 不实现 Token 首段流式输出、Pacing 或快速输入合并；这些属于 Phase 06。
- 不把现有 SSE 升级为可靠 Outbox、ACK 或重放协议。
- 不创建完整平行聊天 v2。
- 不修改构建产物，不删除旧表、旧消息或旧附件。
- 不让租约过期请求自动重跑，避免未知副作用重复。

## 依赖与阶段门禁

- Phase 00–03 已于 2026-07-20 重新审计通过。
- Phase 03 提供 Conversation / Turn / Message / Request 四表和稳定 ID 合同。
- 依赖 [[05_Feature_Flag与回滚矩阵]]、[[06_AI_Vibe_Coding批次规约]]、[[90_全局验收清单]]、[[91_数据迁移核对]]、[[92_回滚演练]]。
- 执行任务：[[Task 04-baseline]]。

## 当前代码证据

- [chat.js](file:///E:/Agent_reply/electron/src/renderer/js/chat.js#L322-L377)：全局 `_loading` 阻止连续输入，发送端同步等待 `/api/chat/send`。
- [api_server.py](file:///E:/Agent_reply/core/api_server.py#L391-L451)：聊天接口同步 `await comp.pipeline.handle(...)`，空文本直接 400。
- [conversation_repository.py](file:///E:/Agent_reply/core/conversation_repository.py#L43-L130)：当前 Request 只在完整 Turn 镜像结束时以 `completed` 写入，尚不能承载 queued/running/cancel/retry。
- [migrations/__init__.py](file:///E:/Agent_reply/core/migrations/__init__.py#L154-L163)：现有 requests 表只有基础状态、时间与 error。
- [event_contracts.py](file:///E:/Agent_reply/core/event_contracts.py#L10-L50)：已有 `event_id/request_id/conversation_id/turn_id/message_id/sequence` 信封。
- [event_stream.py](file:///E:/Agent_reply/core/event_stream.py#L30-L113)：SSE 为有界 best-effort 广播，不是可靠任务队列。
- [async_task_manager.py](file:///E:/Agent_reply/core/async_task_manager.py#L132-L420)：通用任务管理器缺少 Conversation 顺序、持久 claim/lease 和真实运行 Task 取消，不作为聊天队列实现。

## 架构

```mermaid
flowchart LR
    R[Electron Renderer] -->|POST /api/chat/send| API[FastAPI]
    API --> S[ChatRequestService]
    S --> DB[(aerie.db requests)]
    API -->|202 request_id + queued| R
    DB --> W[ChatRequestWorker]
    W --> C{原子 claim\nConversation 无 running}
    C --> P[现有 Pipeline]
    P --> E[EventEnvelope]
    E --> I[stderr / IPC]
    E --> SSE[SSE]
    R -->|status / cancel / retry| API
```

### `ChatRequestRepository`

只负责持久化和并发控制：

- 创建 queued Request 与不可变输入快照。
- 原子 claim：只能领取 queued 且其 Conversation 当前没有 running/cancelling Request 的最早请求。
- 更新 lease、heartbeat、状态、错误码和终态时间。
- 恢复 queued；将启动时遗留 running/cancelling 或租约过期请求标记为 `failed/process_interrupted`。
- 提供按 `request_id` 查询和所有权校验。
- 不调用模型、不发送事件、不操作 Renderer。

### `ChatRequestWorker`

- 默认四个执行槽，可通过配置调整。
- 每个槽循环 claim 一个可运行 Request；没有任务时退避等待。
- claim 与状态变更使用短事务；模型执行期间不持有数据库事务。
- 运行期间定时 heartbeat 续租。
- 为 running Request 保存可取消的 `asyncio.Task` 和取消令牌。
- 调用现有 `Pipeline.handle()`，不复制或简化 Pipeline。
- 只由 Companion 组合根启动和停止。

### `ChatRequestService`

供 API 使用：

- `submit()`：验证文本/附件，解析 Conversation，创建输入快照并返回 queued Request。
- `cancel()`：执行 queued 或 running 取消。
- `retry()`：仅从 failed/cancelled 创建新 Request，并关联原请求。
- `get()`：返回脱敏状态，不返回内部错误堆栈或敏感输入。
- Flag 关闭时 API 完全绕过 Service/Worker，继续旧同步路径。

## 数据模型与迁移

Phase 04 从 `migration: false` 改为 `migration: true`。新增版本化迁移，不修改已发布 004/005 checksum。

现有 `requests` 表最小扩展：

| 字段 | 用途 |
|---|---|
| `actor_id` | Request 所有者 |
| `channel` | 短期会话 Channel |
| `channel_account_id` | 同 Channel 账号边界 |
| `user_id` | legacy 兼容寻址 |
| `input_content` | 用户原始可见文本，可为空 |
| `effective_content` | Pipeline 内部输入；纯附件使用中性指令 |
| `attachments` | 提交时附件 JSON 快照 |
| `reply_to_id` | 引用消息兼容字段 |
| `retry_of_request_id` | 新重试请求关联原请求 |
| `cancel_requested_at` | 取消请求时间 |
| `cancelled_at` | 确认取消终态时间 |
| `started_at` | Worker 开始处理时间 |
| `lease_owner` | claim 的 Worker 实例 ID |
| `lease_expires_at` | 当前租约到期时间 |
| `last_heartbeat_at` | 最近续租时间 |
| `error_code` | 稳定机器可读错误码 |

迁移要求：backup、dry-run、固定 checksum、重复运行幂等、旧行兼容、`PRAGMA quick_check`、失败状态可审计。现有历史 completed Request 不反推或猜测输入快照。

## 状态机

```mermaid
stateDiagram-v2
    [*] --> queued
    queued --> running: atomic claim
    queued --> cancelled: cancel
    running --> completed: pipeline success
    running --> cancelling: cancel requested
    cancelling --> cancelled: task stopped before terminal side effect
    running --> failed: pipeline error
    cancelling --> failed: side effect already terminal / cancel failure
    running --> failed: process restart or lease expired
    failed --> queued: retry creates new request
    cancelled --> queued: retry creates new request
```

不变量：

- `cancelled` 不能再转 `completed`。
- 原 Request 不原地重试。
- 同一 Conversation 不得同时有两个 running/cancelling Request。
- lease 过期只转失败，不自动重排。
- completed/failed/cancelled 为终态。

## API 合同

### `POST /api/chat/send`

Flag 开启：

```json
{
  "request_id": "req_...",
  "conversation_id": "conv_...",
  "status": "queued"
}
```

- HTTP `202 Accepted`。
- 文本为空时必须至少有一个合法附件。
- 不同步返回 assistant reply。

Flag 关闭：

- 保持当前同步 HTTP `200`、`reply/user_msg_id/ai_msg_id/persisted` 合同。

### `GET /api/chat/requests/{request_id}`

返回状态、稳定错误码、时间戳、可重试/可取消能力和终态消息 ID；不返回内部堆栈。

### `POST /api/chat/requests/{request_id}/cancel`

- queued：直接终止为 cancelled。
- running：转 cancelling 并请求 Task 取消。
- 已终态：幂等返回当前状态，不伪造取消成功。

### `POST /api/chat/requests/{request_id}/retry`

- 只允许 failed/cancelled。
- 返回 HTTP `202` 和新的 `request_id`。
- 新 Request 的 `retry_of_request_id` 指向原 Request。

## 取消与副作用边界

Pipeline 增量接收取消令牌，在以下边界检查：

1. 模型调用前后。
2. legacy 用户/assistant 持久化前。
3. 规范 Turn 镜像前。
4. chat event 发射前。
5. QQ 或其他外部投递前。

若某个不可逆终态副作用已完成，不把 Request 伪装为 cancelled；记录稳定错误码并返回真实终态。取消不得产生第二次模型调用、重复 Message、重复事件或重复 QQ 投递。

## 纯附件合同

- `input_content=""` 保持用户真实输入。
- `effective_content` 使用内部中性指令，仅供 Pipeline/Context 使用。
- 用户气泡、legacy `chat_log` 与规范 Message 不写入内部中性指令。
- 附件 Markdown/元数据继续复用现有安全提取链路。
- 无文本且无附件继续返回 400。

## 事件与 Renderer 去重

复用 `EventEnvelope`，不创建第二套协议。Request 生命周期事件至少包括：

- `chat_request_queued`
- `chat_request_running`
- `chat_request_cancelling`
- `chat_request_cancelled`
- `chat_request_failed`
- `chat_request_completed`

合同：

- `event_id` 为跨 IPC/SSE 的主去重键。
- `request_id + sequence` 用于单 Request 排序和异常检测。
- 消息事件携带 `message_id/turn_id/conversation_id/response_group_id`。
- Renderer 以服务端 Request 状态为准，不再使用全局 `_loading` 宣告请求完成。
- legacy poll 继续使用 chat_log id 去重；Phase 04 只逐步降低依赖，不移除 poll。
- SSE 断线后通过 Request 状态查询恢复，不承诺事件重放。

## Renderer 行为

- 移除全局 `_loading` 发送阻塞，改为 `Map<request_id, RequestViewState>`。
- 每次发送立即乐观渲染独立用户气泡，并绑定临时 client id；收到 queued 响应后绑定真实 request_id。
- 同时允许继续输入和提交。
- 每个请求单独显示 queued/running/cancelling/failed/cancelled 状态与取消/重试操作。
- IPC、SSE、poll 进入同一去重入口；先按 `event_id`，消息兼容路径再按 message id。
- 页面恢复时查询未终态 Request，不把本地状态当权威真源。

## 错误处理与恢复

- Worker 启动时先完成恢复审计，再开始 claim。
- queued 保持可领取；遗留 running/cancelling 与过期 lease 转 `failed/process_interrupted`。
- 数据库暂时不可用时不调用 Pipeline，Worker 退避并记录结构化错误。
- Pipeline 失败写 `failed` 与稳定 `error_code`；用户可显式重试。
- 事件发送失败不反转已提交数据库终态；Renderer 可查询状态恢复。
- Flag 关闭时 Worker 停止消费，但不删除 queued Request 或新字段。

## TDD 实施顺序

1. Migration Red：缺少 Phase 04 字段、checksum/幂等/旧库兼容失败。
2. Repository Red：原子 claim、Conversation 串行、四路并行、lease/heartbeat/过期失败。
3. Service Red：202 提交、纯附件、所有权、取消、重试新 ID。
4. Worker Red：真实 Task 取消、状态不误转 completed、启动恢复。
5. Pipeline Red：取消边界阻止持久化、事件和 QQ 重复副作用。
6. API Red：Flag 开启异步 202，Flag 关闭同步 200 原合同。
7. Renderer Red：连续三条输入、请求级状态、取消/重试、统一去重。
8. 集成与 Electron smoke：IPC/SSE/poll 不重复，重启恢复符合合同。
9. 生产数据副本迁移、回滚演练、完整回归和 Evidence 收口。

## 验收

- [ ] 连续三条输入全部持久 queued，不丢失、不被全局 loading 阻止。
- [ ] 同 Conversation 严格串行；不同 Conversation 默认最多四路并行。
- [ ] queued/running 取消均保持真实终态，cancelled 不误记 completed。
- [ ] retry 创建新 ID 并关联原请求，不产生重复模型、Message、事件或 QQ 副作用。
- [ ] lease 过期与进程重启把遗留 running 标为 failed，不自动重排。
- [ ] 纯附件可处理，用户历史不出现内部占位文本。
- [ ] `event_id` 去重、`request_id + sequence` 有序，IPC/SSE/poll 不重复渲染。
- [ ] Feature Flag 关闭恢复旧同步路径且不删除新数据。
- [ ] 迁移 backup/dry-run/checksum/幂等/恢复/quick_check 通过。
- [ ] 不产生历史串线、敏感值泄漏或无所有权访问。

## 回滚

1. 停止 `ChatRequestWorker` claim 新请求。
2. 关闭 `chat_request_queue_v1`。
3. `/api/chat/send` 恢复旧同步 `200` 路径。
4. 保留 requests 新列、queued/failed 记录、规范表、legacy 数据和附件。
5. 已 queued Request 不在 Flag 关闭态消费；重新开启后按恢复规则处理。
6. 若迁移异常，使用一致性备份恢复并记录恢复耗时与数据损失。

## 指标与脱敏

记录：提交成功率、排队时长、运行时长、取消时延、重试次数、lease 过期数、重复事件数、Conversation 并发冲突数、恢复耗时和数据损失。

禁止记录：消息正文、附件 Markdown、个人账号、凭据、完整路径、模型密钥和内部堆栈。

## 计划文件范围

- 新增：`core/chat_request_repository.py`、`core/chat_request_worker.py`、`core/chat_request_service.py`、独立 Phase 04 测试文件。
- 演进：`core/migrations/__init__.py`、`core/companion.py`、`core/api_server.py`、`core/pipeline.py`、`electron/src/renderer/js/chat.js`、相关配置和阶段文档。
- 不编辑：`electron/dist-*`、生产数据库内容、无关审计日志或历史备份。

## Evidence

- [实施计划](file:///E:/Agent_reply/documents/Level_up/实施计划.md)
- [api_server.py](file:///E:/Agent_reply/core/api_server.py#L391-L451)
- [chat.js](file:///E:/Agent_reply/electron/src/renderer/js/chat.js#L322-L377)
- [conversation_repository.py](file:///E:/Agent_reply/core/conversation_repository.py)
- [event_contracts.py](file:///E:/Agent_reply/core/event_contracts.py)
- [[Task 04-baseline]] · [[90_全局验收清单]] · [[91_数据迁移核对]] · [[92_回滚演练]]
