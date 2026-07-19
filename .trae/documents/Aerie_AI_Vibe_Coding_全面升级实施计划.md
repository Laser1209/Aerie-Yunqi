# Aerie AI Vibe Coding 全面升级实施计划

执行纪律：每个编码批次开始前必须重读 E:\Agent_reply\documents\Level_up\实施计划.md 和本计划。先测试后实现，逐批验收，失败即停止后续批次。

目标：保留现有 Pipeline、QQ、Electron、Persona Hub、情绪、工具和主动消息基础设施，渐进完成规范化对话、连续输入与拟人流式、主动闭环、图片资产、24 小时世界及 Sidecar。

架构：Core 以 Conversation、Turn、Message、Request 为聊天真源。桌面和 QQ 短期会话隔离，经 Actor 共享长期记忆。世界只通过 WorldPort 接入，先 InProcess Adapter，后独立 world.db 的 Remote Sidecar。Electron Main 监管进程和权限，Renderer 不直连 Sidecar。

## 1. 权威裁决

- v14 是主路线。不受限制对话是正确性验收。拟人化是流式和 Renderer 子计划。
- 主动消息专项细化 P0 与 P1，不新建第二套调度器。
- 图片资产、生成、审核、发送归 Core。世界只产生 ImageCandidate。
- 2026-07-20 世界方案覆盖旧的直挂 Companion、写 aerie.db、Renderer 直连方案。
- 演进 core/pipeline.py 和 core/context_builder.py，复用 SemanticMessageSplitter，不长期并存 v2 副本。
- 文档中的疑似凭据不得进入代码、日志、测试或新文档。实施前应轮换并检查历史。

## 2. 当前状态

- 默认入口仍是 core/pipeline.py。core/agent.py 是双轨实验路径。
- chat_log 按行存储。Pipeline 按 user_id 读 20 行，ContextBuilder 再截 8、5、3 行。assistant 分段污染轮次。
- chat send API 同步阻塞且拒绝纯附件。chat.js 全局 loading 阻止连续输入。
- chat event 缺 event、request、conversation、turn、message、group、sequence 标识。stderr、SSE、poll 无统一去重。
- PushScheduler 外层只有 trigger，但调用方使用 trigger_scene。Companion.desire 与 Judge.desire_engine 错配。PushEventEngine 未启停。主动投递仅 QQ。proactive.yaml 重复 idle_care 覆盖 desire dispatcher。
- IncomingMessage 只有 user_id 和 source。桌面以 QQ 号作本地身份，短期历史混用。长期记忆按 user_id 可共享，但未注入主 ContextBuilder。
- 上传缺魔数、EXIF、哈希、所有权、缩略图和 GC。上传器绕过已有 preload IPC。
- WorldPort、世界领域、world.db、Outbox、Sidecar 与插件监管尚未实现。

## 3. 已锁定决策

1. 新建 Conversation、Turn、Message、Request 四表，保留 chat_log 一个可观测兼容周期。
2. 桌面与 QQ 短期 Conversation 隔离。绑定 Actor 后长期记忆共享。
3. WorldPort 加 InProcess Adapter 先行，稳定后迁移 Remote Sidecar。
4. Core UI 用 SSE。Sidecar 用独立可靠协议。
5. Persona Hub 为目标唯一真源。旧 YAML 只作兼容投影。

## 4. 全局纪律与开关

开关：migration_framework_v1、proactive_delivery_v2、identity_contract_v1、conversation_model_v1、chat_request_queue_v1、chat_stream_v1、context_budget_v1、persona_hub_source_v1、image_assets_v1、world_inprocess_v1、world_sidecar_v1、world_image_candidates_v1。迁移先备份，支持 dry run、cursor、幂等和校验。只改源码，不改构建产物。

## 5. 分阶段计划

### Phase 0 迁移器与标识合同

修改 database.py、settings.yaml、chat_events.py。新增 migrations runner 与账本迁移、feature_flags.py、ids.py、event_contracts.py、db_migrate.py 及测试。账本记录版本、checksum、状态、时间、错误、backfill cursor。EventEnvelope 含 event、request、conversation、turn、message、group、sequence、channel 标识。验证空库、现有库、重复运行、中断续跑。回滚只关开关，不删旧表。

### Phase 1 主动消息 P0

修改 push_scheduler.py、desire_engine.py、push_event_engine.py、proactive_judge.py、companion.py、api_server.py、proactive.yaml、Electron main.js，新增 scheduler、event、delivery、config 测试。统一 await trigger 与 emit_and_route；Companion 启停事件引擎并记录用户活动；内容只生成一次，QQ、本地气泡、系统通知分别记 delivery。验证 Cron、手动、Desire、Idle、QQ 断线、quiet、exempt、force。回滚 QQ only，但保留接口与 YAML 修复。

### Phase 2 Actor、Channel 与 Persona

新增 core/identity 的 models、repository、resolver、0002_identity 迁移及测试。修改 message.py、api_server.py、qq_client.py、chat.js、context_builder.py、persona_manager.py、persona_loader.py。IncomingMessage 增加 actor_id、channel、channel_account_id，保留 user_id。一个 Actor 绑定 desktop 与 QQ，长期记忆归 Actor。Persona Hub 为主真源，旧 YAML 只读投影。验证不串线与 Persona 一致性；回滚 legacy user_id。

### Phase 3 对话四表与回填

新增 core/conversation 的 models、repository、service、0003_conversations、backfill 脚本及测试。修改 database.py、pipeline.py、api_server.py。Conversation 记录 Actor、Persona、Channel；Turn 表示一轮；Message 为气泡，共享 response_group_id 与 sequence；Request 使用完整状态机。QQ 与 local 分开回填，未知来源进 legacy_unknown，连续 assistant 行组成一个 group，保存 legacy 映射与 cursor。验证计数、附件守恒与 Channel 隔离。双写期不删 chat_log。

### Phase 4 Request 队列、取消与重试

新增 request_queue.py、request_state.py、cancellation.py 及测试。修改 api_server.py、pipeline.py、companion.py、chat.js。新增创建 Request、取消、重试、状态查询 API，旧 send 走适配器。同 Conversation 串行，不同 Conversation 并行；未生成输入可按时间窗合并，生成后排队。验证三条快速输入、跨 Channel 并发、取消不完成、纯附件。回滚 Renderer 使用旧 send。

### Phase 5 事件统一与 Renderer 去重

修改 chat_events.py、event_stream.py、api_server.py、Electron main.js、preload.js、chat.js，新增 stream 与 reconnect 测试。SSE 支持 id 与有限恢复窗口；Renderer 按 event_id 去重，按 request_id 和 sequence 排序，按 message_id 幂等更新；Electron 指数退避与游标续连。验证 stderr 与 SSE 不重复、乱序重排、completed 顺序。保留 poll 一个周期。

### Phase 6 完整 Turn Context 与记忆

新增 context/sections.py、token_budget.py、retrievers.py、audit.py、conversation/summarizer.py 及预算、轮次、跨 Channel 记忆测试。修改 context_builder.py、pipeline.py、memory_store.py。预算顺序为 system safety、persona、summary、Actor memory、knowledge、recent complete turns、current message 与附件。不得拆半 Turn，记录 token 与裁剪原因。验证十段 assistant 仍是一条历史响应，短期不跨 Channel，长期记忆共享。回滚旧 Builder 路径。

### Phase 7 流式、Typing、多气泡与 Pacing

新增 streaming.py、pacing.py、topic_tracker.py、ending_detector.py 及测试。修改 brain.py、pipeline.py、chat.js 与样式。Provider 支持时输出 delta，否则完整响应；delta 只更新临时气泡，最终仍用 SemanticMessageSplitter 持久化；取消内容标记 interrupted。验证 Typing 100ms、模拟首 delta 1s、取消 500ms、sequence 有序。回滚完整响应。

### Phase 8 主动反馈与频控

新增 proactive_feedback.py、0004_proactive_feedback 迁移及测试。修改 scheduler、judge、API 与 Electron 设置。持久化 per scene cooldown、daily state、positive、negative、mute；提供总开关、通知、场景静音、频率、主动图片设置。验证跨重启和组合限流。回滚静态 policy，保留记录。

### Phase 9 Core 图片资产

新增 core/images 的 models、repository、validator、processor、storage、service，0005_image_assets 迁移、backfill 脚本及验证、资产、GC 测试。修改 api_server.py、attachment_handler.py、chat-uploader.js、chat.js。处理链为大小、魔数与 MIME、解码尺寸、EXIF GPS 清理、规范化重压缩、SHA256 去重、缩略图、元数据事务、Message 引用。上传器改用 preload IPC，URL 不由 file 页面拼接。验证伪扩展名、超大像素、路径穿越、重复图、EXIF、引用删除和孤儿 GC。旧 uploads 只读保留。

### Phase 10 图片理解、生成与审核

新增 vision_provider.py、generation_provider.py、moderation.py、delivery.py 及 Provider、Delivery 测试。修改 brain.py 与 pipeline.py，把 stub 替换为抽象 Provider，理解结果进入附件 context section，QQ 与桌面共用 asset 与 delivery。验证超时、失败、审核拒绝无副作用。可分别关闭 vision 与 generation。

### Phase 11 WorldPort 与 InProcess Adapter

新增 core/world 的 contracts.py、port.py、inprocess_adapter.py、null_adapter.py，core/plugins 的 manifest.py、capabilities.py，契约与降级测试，electron/src/preload-world.js。修改 companion.py、context_builder.py、Electron main.js。WorldPort 最小接口为 get_snapshot、record_interaction、list_candidates、ack_candidate、health，返回版本化 DTO，不暴露数据库。Null adapter 时聊天正常，Renderer 不可访问任意 Sidecar 地址。回滚 NullWorldAdapter。

### Phase 12 确定性世界、关系与 SelfModel

新增 world/domain 的 clock.py、actions.py、simulation.py、relationship.py、self_model.py、regulator.py，world/application/service.py 及确定性、关系、SelfModel 测试。Tick 不调用 LLM；动作来自有限 Registry；随机性由 seed 驱动；关系双向有界；SelfModel 不是第二 Persona 真源。验证同输入同快照、离线推进可重放、非法动作拒绝、极值受控。回滚停用 InProcess 任务。

### Phase 13 world.db、Outbox 与 Remote Sidecar

新增 world/storage 的 database.py、migrations runner、outbox.py，world/server 的 main.py、protocol.py，core/world/remote_adapter.py，Electron plugin-supervisor.js、capability-broker.js、event-router.js 及协议、Outbox、恢复测试。aerie.db 仅 Core 写，world.db 仅 Sidecar 写，禁止跨库 JOIN。协议包含版本、event_id、单调 seq、ACK cursor、checkpoint、heartbeat、幂等键。验证杀死 Sidecar 后聊天继续、重启续传、重复事件不重复、协议不兼容降级。回滚 InProcess。

### Phase 14 世界图片候选闭环

新增 world/domain/image_decision.py、core/world/candidate_consumer.py 及候选和投递测试。World 只输出含原因、快照引用、Persona、建议 Prompt、优先级、过期时间、幂等键的 ImageCandidate。Core 依次经过 ProactiveJudge、用户设置、生成、审核、资产持久化、Delivery，再 ACK。验证重复、过期、静音、审核拒绝、生成失败和 QQ 离线无重复副作用。回滚关闭 consumer。

### Phase 15 Dashboard、Creative Workshop 与发布

在 Electron renderer 增加世界仪表盘、候选审批、插件健康和创意工坊；修改 main.js 与 preload-world.js。UI 覆盖 loading、empty、error、disconnected、version mismatch、recovering、permission denied。关系默认自然语言摘要。Sidecar 崩溃不阻断聊天。发布前执行 Python 全测、Node 检查、Electron 开发启动、离线重启、升级回滚、数据库恢复、旧 API 观测。旧 chat_log 写、poll、Persona 投影只在一个版本周期后另开清理批次。

## 6. 依赖与并行限制

Phase 0 先于所有改造。Phase 1 与 Phase 2 可分支并行，但合并前统一 Actor 与 Event。Phase 2 先于 Phase 3。Phase 3 先于 Phase 4、6、9。Phase 4 先于 Phase 5，Phase 5 先于 Phase 7。Phase 9 先于 Phase 10。Phase 11 先于 Phase 12，领域稳定后才做 Phase 13。Phase 14 依赖 Phase 1、8、10、13。Phase 15 最后。

## 7. Obsidian AI Vibe Coding 文档包

获批后的首个执行批次只创建 E:\Agent_reply\documents\Level_up\AI_Vibe_Coding，不改业务代码。

主控笔记：00 全面升级主控、01 冲突裁决、02 术语与合同、03 数据所有权与迁移、04 API 与事件、05 Feature Flag 与回滚、06 AI 批次规约、07 风险登记、90 全局验收、91 数据迁移核对、92 回滚演练、93 性能可靠性基线、94 发布安全检查。

阶段笔记：phases 目录创建 Phase 00 至 Phase 15。每篇包含目标、非目标、依赖、当前证据、文件清单、数据与 API 合同、TDD 步骤、验收、回滚、指标、提交边界和证据。

ADR：规范化四表、桌面 QQ 短期隔离长期共享、WorldPort 渐进 Sidecar、Core SSE 与 World 可靠协议分离、Persona Hub 唯一真源、图片副作用归 Core。

任务 frontmatter：title、tags、kind、task_id、phase、subsystem、status、priority、dependencies、risk、decision_required、feature_flag、migration、files、acceptance_ids、rollback_ready、owner、evidence。

Aerie升级任务.base 过滤 tasks 目录与 kind task。视图：按阶段、P0 与阻塞、迁移与高风险、待验收、世界与图片。公式：阶段标签、阻塞、文件年龄、回滚状态。创建后做 YAML 解析并在 Obsidian 检查视图与链接。

## 8. 全局验收

- 数据回填守恒、幂等、可续跑；桌面 QQ 短期隔离；Actor 长期记忆共享。
- 连续三条输入不丢；完整 Turn 上下文；取消、重试、失败状态正确。
- event_id 去重、sequence 有序、断线恢复不重复。
- Typing、首 delta、逐气泡、打断、reduced motion 可验证。
- Cron、Desire、Idle、World Candidate 都经过 Judge；各通道结果独立；用户可静音。
- 图片具备魔数、EXIF、去重、所有权、引用、审核、GC；World 不直接生成或发送。
- 世界确定性重放；数据库单一所有者；Sidecar 崩溃时聊天降级；Outbox 幂等续传。
- Renderer 无通用 Sidecar 网络能力；世界 IPC 白名单化；系统通知不重复聊天消息。
- 疑似凭据不得进入提交、日志、fixture、截图或 evidence。

## 9. 待用户确认的产品默认值

这些不改变三项已锁定架构，但会改变默认行为：

1. 主动消息：QQ 与桌面气泡是否同时尝试；系统通知默认是否开启；QQ 离线是否跨重启排队。
2. 图片：允许格式与上限；是否保存原图；EXIF；生成图保留期；本地与远程 Provider 优先级。
3. 关系：显示数值或摘要；是否可重置；Persona 切换时关系共享或隔离。

推荐默认：气泡与 QQ 同时尝试；通知默认开启但可关；QQ 离线不跨重启排队。图片支持 PNG、JPEG、WEBP、GIF 和 20MB；保存清洗后的规范图，不保存带 EXIF 原文件；生成图保留到用户删除；本地可用时本地优先。关系只显示摘要，可重置，按 Persona 隔离。
