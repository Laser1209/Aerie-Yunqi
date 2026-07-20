---
title: Task 04-baseline
tags: [aerie, task, phase04, core, chat, queue]
kind: task
task_id: TASK-04-001
phase: Phase 04
subsystem: chat
status: done
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
rollback_ready: true
owner: core-team
evidence:
  - file:///E:/Agent_reply/documents/Level_up/AI_Vibe_Coding/phases/Phase%2004.md
  - file:///E:/Agent_reply/core/api_server.py
  - file:///E:/Agent_reply/core/conversation_repository.py
  - file:///E:/Agent_reply/electron/src/renderer/js/chat.js
---
# Task 04-baseline

> [!success] Phase 04 Task 1–12 已按严格 TDD / current-state audit 收口
> 书面规范和逐批实施计划已批准；Phase 00–03 门禁、006 Migration、测试 Fixture、ChatRequestRepository、ConversationRepository 完成路径、ChatRequestService、ChatRequestWorker、Pipeline RequestContext/取消边界、Companion 组合根与 API 双合同、Renderer/Electron 请求级状态与统一 ingest、端到端集成与 Electron smoke、生产一致性副本迁移/恢复和回滚演练均已通过。`rollback_ready=true`；进入 Phase 05 前仍需重新读取计划并复核 Phase 00–04 门禁。
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
- [x] Worker Red/Green：验证四路槽、同 Conversation 串行、真实 Task、heartbeat、用户取消、stop、启动恢复与丢失 Task 收口。
- [x] Pipeline Red/Green：在模型、持久化、规范镜像、事件和外部投递边界检查取消，禁止重复副作用；FULL/BASIC 可见输入隔离、ID 复用、事件 sequence 和可信附件重提取均已覆盖。
- [x] API Red/Green：Flag 开启为异步 202 且不等待 Pipeline；Flag 关闭保持原同步 200 与空消息 400 合同；依赖缺失 fail closed/503。
- [x] Renderer Red/Green：连续三条输入、请求级状态、取消/重试、统一去重与页面恢复已由 Node VM 测试真实 `chat.js` 覆盖。
- [x] 集成与 Electron smoke：IPC/SSE/poll 不重复，状态恢复符合后端真源。
- [x] 使用生产数据一致性副本完成迁移、恢复与数据守恒演练，不直接改写生产库。
- [x] 完整回归、脱敏 Evidence、指标与回滚文档收口后更新 `rollback_ready`。

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
- 兼容边界：Service 尚未注入 Companion/API，旧同步聊天、Pipeline、QQ 和 Renderer 没有行为变化；该批次收口时下一批为 Worker Red，现已由下节 Task 7 Evidence 收口。

## ChatRequestWorker Task 7 Evidence

- 接管 Red：`13 failed, 1 passed`，目标缺口为严格完成接口、严格取消终态和 Worker 模块不存在；没有用导入外的无关失败替代业务 Red。
- 风险复核 Red：`5 failed, 15 passed`，覆盖 lease 过期复活、failure 双表错配、lease 丢失副作用、取消等待无界和 pre-start cancel；随后追加三个 stop 竞态场景。
- Green：Worker 专项 `23 passed in 5.09s`；默认四槽最大 active=4，第五条等待；同 Conversation 最大 active=1；`_running_tasks` 保存真实 execution Task；heartbeat 在 Pipeline 运行时立即续租。
- 终态：completed/cancelled 要求匹配未过期 lease 与精确来源状态；owner failure 校验 Request/Turn 双 rowcount；用户取消等待上限 250ms；意外取消为 `pipeline_cancelled`；lease 丢失为 `lease_lost`；stop 的 `worker_stopped` 覆盖仍 active 的用户取消和 pre-start 窗口；丢 Task 为 `cancel_task_missing`。
- 事件：数据库先提交，生命周期事件后 best-effort emit；emit 抛错不反转 completed，事件 payload 不含输入、附件、lease 或堆栈。
- 加固关联回归：Repository/Service/Worker/Conversation/Pipeline/API `136 passed, 4 warnings in 18.95s`。
- 完整 Python：`433 passed, 1 deselected, 6 warnings in 33.59s`；办公目录环境用例运行时改用工作区临时目录后单独 `1 passed in 0.05s`，未改配置。
- `py_compile` 与 `git diff --check` 通过；当前环境无 `ruff` 可执行文件。Worker 与 Service 仍未注入 Companion/API，旧同步聊天、Pipeline、QQ、Renderer 和生产数据库均未改变。
- Task 8 裁决与实现：采用 ConversationRepository 作为 canonical completion 写入者；Pipeline 返回 `canonical_completed` 时 Worker 不再二次 `mark_completed()`；legacy 已写但 canonical 未完成的过晚取消使用 `terminal_side_effect_committed` fail-closed；canonical 已完成后 completion-wins，停止后续事件/QQ 副作用。
- 残余 fail-closed 边界：heartbeat 数据库异常与终态写入同时失败时停止 execution，但 active Request 依赖下一次启动 recovery；未宣称运行期数据库恢复后自动收口。

## Pipeline Task 8 Evidence

- Red：新增 `tests/test_phase4_pipeline.py` 后，`python -m pytest --basetemp=E:\Agent_reply\tmp\pytest-task8-red tests/test_phase4_pipeline.py -q` 收集期失败为 `ImportError: cannot import name 'CancellationToken'`，目标缺口明确。
- Green：Task 8 专项 `13 passed in 1.59s`；Task 8 + 旧 Pipeline `36 passed in 2.36s`。
- 关联回归：Repository/Service/Worker/Pipeline/API `135 passed, 4 warnings in 17.68s`。
- 完整回归：仓库根收集曾因 `tmp/` 历史无权限目录触发 35 个 collection `WinError 5`；明确收集 `tests` 后 `447 passed, 6 warnings in 26.85s`。
- 实现边界：`communication.message` 新增取消合同；`core.pipeline` 接收 `RequestContext`/token、复用 canonical ID、隔离 visible/effective content、过滤客户端附件正文并按可信 URL 重提取；`core.chat_request_worker` 仅做 token 传递和 canonical completed 跳过二次完成，不接入 Companion/API。
- `py_compile` 与 `git diff --check` 通过；未读写生产数据库、未修改 Renderer、未异步化 `/api/chat/send`。

## Companion/API Task 9 Evidence

- Red：`python -m pytest --basetemp=E:\Agent_reply\tmp\pytest-task9-red tests/test_phase4_api.py tests/test_phase4_integration.py -q` → `13 failed, 2 passed`，目标缺口为 API 仍同步 200、新端点不存在、Companion 无 Service/Worker/依赖门禁；静态身份测试的 FK 失败已作为夹具修正。
- Green：Task 9 专项 `15 passed, 4 warnings in 5.06s`。
- 关联回归：旧 API、Service、Repository、Worker、Pipeline `135 passed, 4 warnings in 18.46s`。
- 顺序无关回归：修复 integration 真实 `Companion` 与旧 API mock 的模块级污染后，按 `tests/test_phase4_api.py tests/test_phase4_integration.py tests/test_api.py tests/test_phase4_chat_request_service.py` 顺序复验 `67 passed, 4 warnings in 12.55s`。
- 完整回归：明确 `tests` 范围 `462 passed, 6 warnings in 35.41s`；`py_compile` 与 `git diff --check` 通过，后者仅 LF→CRLF 工作区提示。
- 组合根：`Companion` 只创建一个 `ChatRequestRepository`，同一实例注入 Service/Worker；`ChatRequestWorker.pipeline is companion.pipeline`，`pipeline.conversation_repository is companion.conversation_repository`。
- 门禁：`chat_request_queue_v1=true` 要求 migration + conversation 两 Flag；依赖缺失返回 `queue_dependencies_unavailable`，不回退旧同步路径；Flag 关闭不启动 Worker、不消费 queued。
- API：Flag 开 `/api/chat/send` 返回 202 queued；纯附件可排队；空文本无附件 400；Flag 关旧 200 shape 保持；status/cancel/retry 端点只暴露脱敏 `RequestStatusView`。
- 所有权：`reply_to_id` 必须属于同一 Actor、Channel、Channel Account 与 Conversation；缺失和跨所有权统一 `request_not_found`。API 不实例化 Repository。
- 未完成边界：Renderer `_loading`、统一 ingest、IPC/SSE/poll 去重、Electron smoke 与生产数据一致性副本演练仍待后续 Task，因此 `rollback_ready=false`。

## Renderer/Electron Task 10 Evidence

- Red：`node --test tests\chat-request-queue.test.js` → `10 failed, 0 passed`；第一项 `_loading` 只发出 1 个 POST，其余缺 `_requests/_ingestChatSignal/cancel/retry/restore/SSE`。
- Green：Task 10 定向 `10 passed in 149.8285ms`；Electron 关联 `node --test tests\persona-hub.test.js tests\chat-request-queue.test.js` → `13 passed in 115.723ms`。
- 语法：`node --check src\renderer\js\chat.js`、`chat-uploader.js`、`preload.js` 均通过。
- Python 完整回归：明确 `tests` 范围 `462 passed, 6 warnings in 35.06s`；`git diff --check` 通过，仅 LF→CRLF 提示。
- 实现：`chat.js` 新增 `_requests`、`_clientToRequest`、`_seenEventIds`、`_requestSequences`；send 每次生成 client id 并独立 POST，202 后绑定 request id；IPC/SSE/poll 进入 `_ingestChatSignal`；`event_id` 去重，`request_id+sequence` 缓冲，legacy numeric id 继续兼容。
- 操作与恢复：request-scoped cancel/retry 调用新 API；非终态 Request 写入 localStorage，页面恢复或 SSE 断线后用 GET status 恢复后端真源；SSE disconnect 不伪造 failed。
- 范围：未改 uploader/preload 功能，未新增依赖，未连接真实 QQ，未执行 Electron smoke 或生产数据一致性副本演练；`rollback_ready=false`。

## Integration/Electron Smoke Task 11 Evidence

- Red：Task 11 固定端到端场景首轮 `3 failed, 12 passed, 4 warnings`，失败集中在 GET status 缺少完成后的 legacy/canonical id 和 retry 响应缺少 `retry_of_request_id`，属于目标业务缺口。
- Green：`tests/test_phase4_integration.py` → `15 passed, 4 warnings`，覆盖提交→claim→Pipeline→completed/status/events、同 Conversation 三请求顺序、跨 Conversation 四路并发、queued/running cancel 副作用守恒、retry 新请求、启动恢复、事件失败后 GET status 恢复和 Flag-off 旧同步合同。
- 最小实现：canonical `messages.legacy_chat_log_id` 链回 legacy `chat_log.id`；Pipeline 向 canonical completion 传入 legacy id 并返回 `event_sequence`；Worker terminal request event 使用后续 sequence；Service DTO 增加 `retry_of_request_id` 且 submit/retry 唤醒 Worker。
- Smoke 安全：新增 `AERIE_DISABLE_MODEL_CALLS` 本地 stub 和 `AERIE_DISABLE_QQ`，Electron 后端启动尊重显式临时 `AERIE_DATA_DIR/AERIE_DB_PATH/LOG_DIR`；默认生产行为不变。
- Electron smoke：使用 `E:\Agent_reply\tmp\aerie-phase4-smoke3.db`、临时 data/log、三个 Phase 04 Flag、`AERIE_DISABLE_QQ=true`、`AERIE_DISABLE_MODEL_CALLS=true` 启动 `npm start -- --start-minimized`。真实窗口 renderer 已加载，健康检查返回临时 `data_path_id`，QQ disconnected；日志确认 QQ 和模型 provider 均被禁用。
- Smoke API：连续三次 `/api/chat/send` 均为 202；最终 GET status 三个 request 均 completed 并写回 legacy/canonical id。临时 DB 只读汇总：`requests=6`、`turns=6`、`messages=18`、`chat_log=18`，canonical/legacy 均为 `6 user + 12 assistant`，status 全部 completed。cancel completed 返回 200 保持 completed；retry completed 返回 409。
- 回归：关联 Python `188 passed, 4 warnings in 26.11s`；Electron Node `14 passed`；`py_compile` 与 Electron `node --check` 全部通过；完整显式 `tests` 收集 `471 passed, 6 warnings in 35.86s`。
- 范围：未连接真实 QQ，未调用真实模型 provider，未写生产 DB；未保存模型正文、附件内容、账号或凭据；生产数据一致性副本演练仍待 Task 12，因此 `rollback_ready=false`。

## Production Copy / Rollback Task 12 Evidence

- Current-state audit：默认生产库只读检查已发现 006 ledger、字段和索引均已 completed，因此原计划中“006 pending/缺列”的生产副本 Red 不再适用；未伪造 pre-006 生产副本，改为执行 idempotent/no-op rehearsal 并记录事实。
- 只读源证据：`E:\Agent_reply\data\aerie.db` 主文件 SHA-256 前后均为 `db3dfe360508e30e0da671030288d9522843cf405c00c531127e2daf9accf526`；`PRAGMA quick_check=ok`；ledger 002–006 均 completed；006 checksum 固定为 `2e649f6834695ca7b9250c3e2f7c110ab9c5b2c4ed2a230d1cd4fb5e0654ea05`。
- SQLite Backup API 副本：A/B/C 位于 `E:\Agent_reply\tmp\phase4-task12-rehearsal-20260720-233222`；A backup `0.031251s`，C restore `0.031510s`。
- Rehearsal B：dry-run pending `[]`，首次/二次 migration pending 均 `[]`；schema/count 未变化；16 个 Phase 04 列和 3 个索引存在；`completed_snapshot_non_null=0`；`foreign_key_check=0`；`quick_check=ok`。
- 恢复 C：A 与 C 的六张关键表计数和脱敏有序摘要完全一致；`chat_log=1789`、`conversations=4`、`turns=299`、`messages=1754`、`requests=299`、`migration_ledger=5`；数据损失 `0`。
- Flag 回滚矩阵：新增并通过 `test_task12_flag_rollback_matrix_reenables_queue_without_data_loss`，覆盖 queue on 完成、queue off 旧同步 200、queued 保留、依赖缺失 503、重新开启后 queued 完成。
- 回归：Phase 00–04 关联门禁 `259 passed, 4 warnings in 29.21s`；完整显式 `tests` 收集 `472 passed, 6 warnings in 36.51s`；Electron Node `14 passed`；四个 `node --check`、`py_compile` 通过。
- 范围：未直接写生产库，未保存正文/附件/账号/凭据，未提交/推送，未修改无关 `Spotlight/` 或运行态 data 文件；`rollback_ready=true`。

## 测试 Fixture Evidence

- Red：`2 errors in 0.07s`，目标缺口明确为 `phase4_db` 和 `ready_attachment` Fixture 尚未定义。
- Green：三个 Fixture 探针 `3 passed in 0.20s`；Phase 0/3/4 关联回归 `43 passed in 2.03s`；完整 Python `365 passed, 6 warnings in 14.83s`。
- 隔离合同：临时文件名 `phase4.db`、固定 UTC `2026-07-20T00:00:00+00:00`、ready 附件只含脱敏服务端元数据；异步 double 暴露 `started/release/cancel_seen`，不访问网络、QQ 或真实模型。
- `py_compile`、相关 diagnostics 与 `git diff --check` 通过；该 Fixture 批次当时尚未勾选 Service/Worker，现已由 Task 6/7 收口，完整回滚验收仍未勾选。

## 阶段门禁

- [x] 先提交并亲自观察每批目标行为缺失导致的 Red；Task 12 因当前生产库已完成 006，按 current-state audit 记录“不适用”而未伪造 Red。
- [x] 每批只写使目标测试 Green 的最小实现，再运行关联与完整回归。
- [x] Request/Turn/Message 状态和记录数守恒，无重复主键、孤立 Turn 或半完成 Request。
- [x] `chat_request_queue_v1=false` 完整恢复旧 `/api/chat/send` 同步路径且不启动 Worker、不消费 queued，同时不破坏新列、新数据或 Evidence。
- [x] 完成 Phase 04 全部验收与回滚演练前，不进入 Phase 05。

## 链接

[[Phase 04]] · [[05_Feature_Flag与回滚矩阵]] · [[90_全局验收清单]] · [[91_数据迁移核对]] · [[92_回滚演练]]
