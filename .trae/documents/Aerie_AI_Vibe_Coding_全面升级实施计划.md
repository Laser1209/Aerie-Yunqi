# Aerie AI Vibe Coding 全面升级实施计划

## Summary

本计划将六份升级方案合并为一条可执行主路线：保留现有 Pipeline、QQ、Electron、Persona Hub、情绪、工具和主动消息基础设施，渐进完成规范化对话、连续输入与拟人流式、主动消息闭环、图片资产、24 小时世界模拟及 Remote Sidecar。

每个编码批次开始前必须重读本计划与对应的 AI Vibe Coding 阶段笔记；先测试后实现，逐批验收，当前批次失败即停止后续批次。执行时只修改源码与显式生成的文档，不编辑构建产物。

目标架构：Core 以 Conversation、Turn、Message、Request 为聊天真源；桌面与 QQ 的短期会话隔离，经 Actor 共享长期记忆；世界系统只通过 WorldPort 接入，先 InProcess Adapter，稳定后迁移至独立 `world.db` 的 Remote Sidecar；Electron Main 监管进程和权限，Renderer 不直连 Sidecar。

## Current State Analysis

### 方案权威关系与冲突裁决

- `Aerie_v14_对话系统全面升级方案.md` 是对话升级主路线。
- `Aerie_不受限制对话模式二次开发方案.md` 作为上下文正确性、连续输入和长对话验收专项，不代表绕过安全策略或工具权限。
- `Aerie_拟人化对话模式研究与优化方案.md` 作为流式输出、Typing、多气泡和 Pacing 专项。
- `Aerie_Agent主动发消息方案.md` 细化主动消息 P0/P1，不新建第二套调度器。
- `Aerie_图片上传与管理完整解决方案.md` 约束 Core 图片资产、理解、生成、审核与投递；世界系统只能产生 `ImageCandidate`，不得直接执行图片副作用。
- `2026-07-20_Agent_24小时世界模拟与人格图片系统实施计划.md` 是世界与插件架构的最新权威方案，覆盖旧的“直接挂 Companion、写入 `aerie.db`、Renderer 直连世界服务”设想。
- 演进现有 `core/pipeline.py` 和 `core/context_builder.py`，复用 `SemanticMessageSplitter` 与现有 Persona Pacing，不长期维护平行的 v2 实现。
- 六份文档中的疑似凭据不得复制进代码、日志、测试、截图、Evidence 或新文档；实施前必须确认并轮换真实凭据，随后检查 Git 历史。

### 当前代码现状

- [pipeline.py](file:///E:/Agent_reply/core/pipeline.py) 是生产聊天主链，已承载路由、认知、情绪、工具、验证、语义拆分、持久化、自进化和 Pacing，不适合整体重写。
- 当前 `chat_log` 按消息行存储；Pipeline 按 `user_id` 读取 20 行，[context_builder.py](file:///E:/Agent_reply/core/context_builder.py) 再按路由截取 8/5/3 行，assistant 多分段会挤掉对应 user 输入并破坏完整 Turn。
- [api_server.py](file:///E:/Agent_reply/core/api_server.py) 的聊天发送仍以同步 `/api/chat/send` 为主；[chat.js](file:///E:/Agent_reply/electron/src/renderer/js/chat.js) 使用全局 `_loading`，阻止连续输入。
- 现有 stderr、SSE、IPC、poll 事件缺少统一的 `event_id`、`request_id`、`conversation_id`、`turn_id`、`message_id`、`response_group_id` 和 `sequence`，存在重复气泡和乱序风险。
- [push_scheduler.py](file:///E:/Agent_reply/core/push_scheduler.py) 的公共接口是 `trigger()`，多个调用方使用不存在的 `trigger_scene()`；[companion.py](file:///E:/Agent_reply/core/companion.py) 保存 `self.desire`，而 [proactive_judge.py](file:///E:/Agent_reply/core/proactive_judge.py) 查找 `desire_engine`；[push_event_engine.py](file:///E:/Agent_reply/core/push_event_engine.py) 尚未接入 Companion 生命周期；主动投递主要覆盖 QQ；[proactive.yaml](file:///E:/Agent_reply/config/proactive.yaml) 存在重复 `idle_care`。
- `IncomingMessage` 主要以 `user_id` 和 `source` 标识身份，桌面复用 QQ 号，短期历史可能混用；长期记忆具备存储基础，但尚未完整注入 Context Builder 主链。
- 图片上传已有通用附件基础，但缺少魔数校验、EXIF/GPS 清理、内容哈希、所有权、缩略图、引用管理和 GC；[chat-uploader.js](file:///E:/Agent_reply/electron/src/renderer/js/chat-uploader.js) 与后端格式、纯附件和 URL 合同不统一。
- WorldPort、确定性世界领域、`world.db`、Outbox、Sidecar、插件监管与 Capability Broker 尚未实现。

## Assumptions & Decisions

### 已由用户确认

1. 新建 Conversation、Turn、Message、Request 四张规范化表；`chat_log` 保留一个可观测兼容周期。
2. 桌面与 QQ 使用隔离的短期 Conversation；绑定同一 Actor 后共享长期记忆。
3. 世界系统先实现 `WorldPort + InProcessWorldAdapter`，领域稳定后迁移 `RemoteWorldAdapter + Sidecar`。

### 为保证计划决策完备而固定的默认值

- Core UI 事件使用 SSE；Sidecar 使用独立、可确认、可续传的可靠协议。
- Persona Hub 是目标唯一真源；旧 Persona YAML 只作为兼容投影，迁移期只读。
- 主动消息默认同时尝试桌面气泡和 QQ；系统通知默认开启但允许关闭；QQ 离线消息不跨重启补发。
- 图片支持 PNG、JPEG、WEBP、GIF，单文件上限 20MB；只保存清洗和规范化后的资产，不保留带 EXIF 的原图；生成图保留至用户主动删除；本地 Provider 可用时优先本地，否则使用远程 Provider。
- 关系系统默认只向用户展示自然语言摘要，允许重置，不同 Persona 的关系相互隔离。
- Feature Flags：`migration_framework_v1`、`proactive_delivery_v2`、`identity_contract_v1`、`conversation_model_v1`、`chat_request_queue_v1`、`chat_stream_v1`、`context_budget_v1`、`persona_hub_source_v1`、`image_assets_v1`、`world_inprocess_v1`、`world_sidecar_v1`、`world_image_candidates_v1`。
- 数据迁移必须支持 backup、dry-run、checksum、幂等、cursor、断点续跑和守恒校验；回滚优先关闭 Feature Flag，不删除旧表和旧文件。

## Proposed Changes

### Phase 0：安全基线、迁移器与标识合同

**涉及文件**

- 修改：[database.py](file:///E:/Agent_reply/core/database.py)、[settings.yaml](file:///E:/Agent_reply/config/settings.yaml)、[chat_events.py](file:///E:/Agent_reply/core/chat_events.py)
- 新增：`core/migrations/`、`core/feature_flags.py`、`core/ids.py`、`core/event_contracts.py`、迁移 CLI 与对应测试

**实施方式**

- 先确认六号方案文档中的疑似凭据是否真实；真实则轮换/吊销，并规划历史清理，任何输出都不得回显值。
- 建立迁移账本，记录版本、checksum、状态、开始/完成时间、错误与 backfill cursor。
- 定义统一 `EventEnvelope`，至少包含 event、request、conversation、turn、message、group、sequence、channel 标识和时间戳。
- 建立 Feature Flag 读取和审计机制。

**门槛与回滚**

- 空库、现有库、重复运行、中断续跑均通过。
- 回滚只关闭开关并恢复数据库备份，不删除旧表。

### Phase 1：主动消息 P0 修复

**涉及文件**

- 修改：[push_scheduler.py](file:///E:/Agent_reply/core/push_scheduler.py)、[desire_engine.py](file:///E:/Agent_reply/core/desire_engine.py)、[push_event_engine.py](file:///E:/Agent_reply/core/push_event_engine.py)、[proactive_judge.py](file:///E:/Agent_reply/core/proactive_judge.py)、[companion.py](file:///E:/Agent_reply/core/companion.py)、[api_server.py](file:///E:/Agent_reply/core/api_server.py)、[proactive.yaml](file:///E:/Agent_reply/config/proactive.yaml)、[main.js](file:///E:/Agent_reply/electron/src/main.js)
- 新增：Scheduler、Event、Delivery、Config 测试

**实施方式**

- 全部调用统一为 `await push_scheduler.trigger(scene_name)`；内部事件统一通过一个 `emit_and_route` 入口。
- Companion 构造、启动、停止 `PushEventEngine`，用户消息到达时记录活动。
- 统一 Desire 属性名，修复 Judge 状态读取。
- 删除重复 YAML 键并保留完整 dispatcher 配置。
- 主动内容只生成一次，QQ、桌面气泡、系统通知各自记录独立 Delivery 结果。

**门槛与回滚**

- 验证 Cron、手动、Desire、Idle、QQ 断线、quiet、exempt、force。
- 可回滚为 QQ-only，但保留接口、生命周期和 YAML 修复。

### Phase 2：Actor、Channel 与 Persona 真源

**涉及文件**

- 新增：`core/identity/models.py`、`repository.py`、`resolver.py`、身份迁移与测试
- 修改：消息模型、[api_server.py](file:///E:/Agent_reply/core/api_server.py)、QQ Client、[chat.js](file:///E:/Agent_reply/electron/src/renderer/js/chat.js)、[context_builder.py](file:///E:/Agent_reply/core/context_builder.py)、Persona Manager、Persona Loader

**实施方式**

- `IncomingMessage` 增加 `actor_id`、`channel`、`channel_account_id`，兼容期保留 `user_id`。
- 一个 Actor 可绑定 desktop 与 QQ；短期对话按 Channel 隔离，长期记忆归 Actor。
- Persona Hub 成为写入真源，旧 YAML 仅提供兼容读取投影。

**门槛与回滚**

- 同一 Actor 跨 Channel 共享长期记忆但不共享短期 Turn；不同 Actor 不串线。
- 可切回 legacy `user_id` 解析。

### Phase 3：Conversation / Turn / Message / Request 四表与回填

**涉及文件**

- 新增：`core/conversation/models.py`、`repository.py`、`service.py`、迁移、backfill 脚本与测试
- 修改：[database.py](file:///E:/Agent_reply/core/database.py)、[pipeline.py](file:///E:/Agent_reply/core/pipeline.py)、[api_server.py](file:///E:/Agent_reply/core/api_server.py)

**实施方式**

- Conversation 记录 Actor、Persona、Channel；Turn 表示一轮；Message 表示可展示气泡；同一回答的分段共享 `response_group_id` 并以 `sequence` 排序；Request 使用完整状态机。
- QQ 与 local 分开回填；未知来源进入 `legacy_unknown`；连续 assistant 行在可证明时组合为一个 group；保存 legacy 映射和 cursor。
- 兼容期双写新表与 `chat_log`，读路径由 Feature Flag 切换。

**门槛与回滚**

- 记录数、附件数、角色顺序和 Channel 守恒；回填幂等且可续跑。
- 回滚新表读路径，继续使用 `chat_log`，不删除新表。

### Phase 4：Request 队列、取消、重试与纯附件

**涉及文件**

- 新增：`core/conversation/request_queue.py`、`request_state.py`、`cancellation.py` 与测试
- 修改：[api_server.py](file:///E:/Agent_reply/core/api_server.py)、[pipeline.py](file:///E:/Agent_reply/core/pipeline.py)、[companion.py](file:///E:/Agent_reply/core/companion.py)、[chat.js](file:///E:/Agent_reply/electron/src/renderer/js/chat.js)

**实施方式**

- 新增 Request 创建、状态、取消、重试 API；旧 `/api/chat/send` 走兼容适配器。
- 同一 Conversation 串行，不同 Conversation 并行；生成开始前的连续输入可按固定窗口合并，生成开始后排队。
- 取消必须落为 `cancelled` 或 `interrupted`，不得误记 `completed`。
- 统一纯附件消息合同。

**门槛与回滚**

- 连续快速发送三条消息不丢失；跨 Channel 并发互不阻塞；取消、重试、纯附件均通过。
- Renderer 可临时切回旧 send。

### Phase 5：事件统一、SSE 恢复与 Renderer 去重

**涉及文件**

- 修改：[chat_events.py](file:///E:/Agent_reply/core/chat_events.py)、[event_stream.py](file:///E:/Agent_reply/core/event_stream.py)、[api_server.py](file:///E:/Agent_reply/core/api_server.py)、[main.js](file:///E:/Agent_reply/electron/src/main.js)、[preload.js](file:///E:/Agent_reply/electron/src/preload.js)、[chat.js](file:///E:/Agent_reply/electron/src/renderer/js/chat.js)
- 新增：Stream、Reconnect、乱序与幂等测试

**实施方式**

- SSE 提供 `id` 和有限恢复窗口；Renderer 按 `event_id` 去重，按 `request_id + sequence` 排序，按 `message_id` 幂等更新。
- Electron 使用指数退避和游标续连。
- poll 保留一个兼容周期，但与 SSE 共用事件 ID，避免重复渲染。

**门槛与回滚**

- stderr、IPC、SSE、poll 不产生重复气泡；断线续连、乱序重排和 completed 顺序正确。
- 可关闭新 SSE 路径并保留 poll。

### Phase 6：完整 Turn Context、Token Budget、摘要与长期记忆

**涉及文件**

- 新增：`core/context/sections.py`、`token_budget.py`、`retrievers.py`、`audit.py`、`core/conversation/summarizer.py` 与相关测试
- 修改：[context_builder.py](file:///E:/Agent_reply/core/context_builder.py)、[pipeline.py](file:///E:/Agent_reply/core/pipeline.py)、Memory Store、Knowledge Base 接线

**实施方式**

- Context 预算顺序固定为：系统安全规则、Persona、滚动摘要、Actor 长期记忆、知识检索、最近完整 Turns、当前消息与附件。
- 禁止截断半个 Turn；展示层多个 assistant 气泡在模型上下文中合并为一条 assistant 响应。
- 记录 token 使用、裁剪原因、检索命中和注入来源。

**门槛与回滚**

- 单轮十个 assistant 气泡仍作为一个完整历史响应；短期上下文不跨 Channel；Actor 长期记忆可跨 Channel 命中。
- Feature Flag 可切回旧 Builder 路径。

### Phase 7：拟人化流式、Typing、多气泡与 Pacing

**涉及文件**

- 新增：`core/chat/streaming.py`、`pacing.py`、`topic_tracker.py`、`ending_detector.py` 与测试
- 修改：Brain Provider 接口、[pipeline.py](file:///E:/Agent_reply/core/pipeline.py)、[chat.js](file:///E:/Agent_reply/electron/src/renderer/js/chat.js) 与相关样式

**实施方式**

- Provider 支持时输出 delta，不支持时使用完整响应降级。
- delta 仅更新临时气泡；最终文本仍经现有 `SemanticMessageSplitter` 分段持久化，并写入 group 与 sequence。
- 打字指示器、情绪优先停顿、Persona-aware Pacing、自然结束检测和 reduced-motion 设置统一由状态机控制。
- 用户取消后保留已输出内容并标记 `interrupted`，不撤回已说内容。

**门槛与回滚**

- Typing 在 100ms 内可见；模拟 Provider 首 delta 目标 1s 内；取消确认目标 500ms 内；多气泡严格有序。
- 可关闭流式并使用完整响应。

### Phase 8：主动反馈、频控与用户设置

**涉及文件**

- 新增：主动反馈模型、迁移、Repository 与测试
- 修改：Scheduler、Judge、API、Electron 设置页

**实施方式**

- 持久化 per-scene cooldown、daily state、positive/negative feedback、mute 和 postpone。
- 提供总开关、系统通知、场景静音、频率、主动图片设置。
- 所有 Cron、Desire、Idle、World Candidate 均经过相同 Judge 和组合限流。

**门槛与回滚**

- 配置和频控跨重启生效；负反馈触发自适应降频。
- 可回滚为静态 policy，但保留反馈记录。

### Phase 9：Core 图片资产

**涉及文件**

- 新增：`core/images/models.py`、`repository.py`、`validator.py`、`processor.py`、`storage.py`、`service.py`、图片迁移、backfill 和测试
- 修改：[api_server.py](file:///E:/Agent_reply/core/api_server.py)、[attachment_handler.py](file:///E:/Agent_reply/core/attachment_handler.py)、[chat-uploader.js](file:///E:/Agent_reply/electron/src/renderer/js/chat-uploader.js)、[chat.js](file:///E:/Agent_reply/electron/src/renderer/js/chat.js)、[preload.js](file:///E:/Agent_reply/electron/src/preload.js)

**实施方式**

- 固定处理链：大小限制、魔数与 MIME 交叉验证、解码尺寸限制、EXIF/GPS 清理、规范化重压缩、SHA-256 去重、缩略图、元数据事务、Message 引用。
- 上传器通过 Preload 白名单 IPC/API，不在 `file://` Renderer 中手工拼接 `/uploads/` URL。
- 旧 uploads 目录只读保留，完成 backfill 后才允许 GC 无引用资产。

**门槛与回滚**

- 验证伪扩展名、超大像素、路径穿越、重复图、EXIF、引用删除、孤儿 GC。
- 回滚新资产读路径，保留旧 uploads，不删除新资产元数据。

### Phase 10：图片理解、生成、审核与投递

**涉及文件**

- 新增：`core/images/vision_provider.py`、`generation_provider.py`、`moderation.py`、`delivery.py` 与测试
- 修改：Brain、[pipeline.py](file:///E:/Agent_reply/core/pipeline.py)、QQ 与桌面投递接线

**实施方式**

- 替换 Vision/Image Generation Stub 为 Provider 抽象。
- 图片理解结果进入附件 Context Section；生成、审核、资产持久化和投递分离。
- QQ 与桌面复用同一 Asset，但分别保存 Delivery 状态。

**门槛与回滚**

- Provider 超时、生成失败、审核拒绝时不得产生外部副作用或重复发送。
- Vision 和 Generation 可独立关闭。

### Phase 11：Plugin Host、WorldPort 与 InProcess Adapter

**涉及文件**

- 新增：`core/world/contracts.py`、`port.py`、`inprocess_adapter.py`、`null_adapter.py`、`core/plugins/manifest.py`、`capabilities.py`、契约测试、[preload-world.js](file:///E:/Agent_reply/electron/src/preload-world.js)
- 修改：[companion.py](file:///E:/Agent_reply/core/companion.py)、[context_builder.py](file:///E:/Agent_reply/core/context_builder.py)、[main.js](file:///E:/Agent_reply/electron/src/main.js)

**实施方式**

- WorldPort 最小接口固定为 `get_snapshot`、`record_interaction`、`list_candidates`、`ack_candidate`、`health`，仅返回版本化 DTO，不暴露数据库对象。
- `NullWorldAdapter` 保证世界停用时聊天完整可用。
- Electron Renderer 仅获得白名单 IPC，不获得任意 Sidecar 网络地址或凭据。

**门槛与回滚**

- Contract tests 对 Null 与 InProcess Adapter 同时通过；禁用世界不影响聊天。
- 回滚为 `NullWorldAdapter`。

### Phase 12：确定性世界、关系与 SelfModel

**涉及文件**

- 新增：`world/domain/clock.py`、`actions.py`、`simulation.py`、`relationship.py`、`self_model.py`、`regulator.py`、`world/application/service.py` 与测试

**实施方式**

- Tick 不调用 LLM；动作来自有限 Action Registry；时钟与随机种子可注入。
- 关系变化双向、有界、可解释，并按 Persona 隔离。
- SelfModel 只描述世界内自我状态，不成为第二 Persona 真源；类神经化学变量必须标记为计算模型。
- 离线推进通过确定性事件重放完成。

**门槛与回滚**

- 同输入、同 seed、同时钟得到同快照；非法动作拒绝；数值极值受控；离线推进可重放。
- 可停止 InProcess 世界任务并切回 Null Adapter。

### Phase 13：`world.db`、Outbox 与 Remote Sidecar

**涉及文件**

- 新增：`world/storage/database.py`、迁移器、`outbox.py`、`world/server/main.py`、`protocol.py`、`core/world/remote_adapter.py`、`electron/src/plugin-supervisor.js`、`capability-broker.js`、`event-router.js` 与协议/恢复测试

**实施方式**

- `aerie.db` 仅 Core 写，`world.db` 仅 Sidecar 写，禁止跨库直接读写、JOIN 或双写。
- 协议包含版本、能力协商、`event_id`、单调 `seq`、ACK cursor、checkpoint、heartbeat 和幂等键。
- Electron Main 负责启动、健康检查、崩溃退避和关闭 Sidecar；Core 通过 Remote Adapter 访问。

**门槛与回滚**

- 杀死 Sidecar 后聊天继续；重启后从 cursor 续传；重复事件不产生重复副作用；版本不兼容时降级。
- 回滚至 InProcess Adapter。

### Phase 14：世界图片候选与主动消息审批闭环

**涉及文件**

- 新增：`world/domain/image_decision.py`、`core/world/candidate_consumer.py` 与候选/投递测试
- 修改：WorldPort DTO、ProactiveJudge、Core Image Service 接线

**实施方式**

- World 只输出含原因、快照引用、Persona、建议 Prompt、优先级、过期时间和幂等键的 `ImageCandidate`。
- Core 按顺序执行 ProactiveJudge、用户设置、生成、审核、资产持久化、Delivery，最后 ACK。
- 世界插件不得持有 QQ 凭据或图片 Provider 密钥。

**门槛与回滚**

- 重复、过期、静音、审核拒绝、生成失败、QQ 离线均不得产生重复副作用。
- 关闭 Candidate Consumer 即可回滚。

### Phase 15：World Dashboard、Creative Workshop 与发布

**涉及文件**

- 修改 Electron Renderer 页面、[main.js](file:///E:/Agent_reply/electron/src/main.js)、[preload-world.js](file:///E:/Agent_reply/electron/src/preload-world.js)
- 新增世界仪表盘、候选审批、插件健康、创意工坊及 UI 测试

**实施方式**

- UI 覆盖 loading、empty、error、disconnected、version mismatch、recovering、permission denied。
- 关系默认显示自然语言摘要；提供显式重置。
- Sidecar 崩溃和升级不阻断聊天主链。
- 旧 `chat_log` 写入、poll 和 Persona 投影只在完整可观测周期后另开清理批次，本计划不提前删除。

**门槛与回滚**

- 完成 Python 全测、Node 检查、Electron 启动烟测、离线重启、Sidecar 崩溃恢复、升级回滚、数据库恢复和旧 API 观测。
- UI 功能可按插件 Feature Flag 整体隐藏，聊天仍可发布。

## 依赖与并行限制

- Phase 0 先于所有业务改造。
- Phase 1 与 Phase 2 可独立开发，但合并前必须统一 Actor 与 Event 合同。
- Phase 2 先于 Phase 3；Phase 3 先于 Phase 4、Phase 6、Phase 9。
- Phase 4 先于 Phase 5；Phase 5 先于 Phase 7。
- Phase 9 先于 Phase 10。
- Phase 11 先于 Phase 12；领域稳定后才进入 Phase 13。
- Phase 14 依赖 Phase 1、Phase 8、Phase 10、Phase 13。
- Phase 15 最后执行。

## AI Vibe Coding Obsidian 文档包

计划获批后的首个执行批次只创建 `E:\Agent_reply\documents\Level_up\AI_Vibe_Coding\` 文档包，不修改业务代码。

### 主控笔记

- `00_Aerie_全面升级主控计划.md`
- `01_六方案冲突裁决.md`
- `02_术语与核心合同.md`
- `03_数据所有权与迁移纪律.md`
- `04_API与事件协议.md`
- `05_Feature_Flag与回滚矩阵.md`
- `06_AI_Vibe_Coding批次规约.md`
- `07_风险登记册.md`
- `90_全局验收清单.md`
- `91_数据迁移核对.md`
- `92_回滚演练.md`
- `93_性能与可靠性基线.md`
- `94_发布与安全检查.md`

### 阶段笔记与 ADR

- `phases/` 下创建 Phase 00 至 Phase 15；每篇固定包含：目标、非目标、依赖、当前证据、文件范围、数据/API 合同、TDD 步骤、验收、回滚、指标、提交边界和 Evidence。
- `decisions/` 下创建 ADR：规范化四表、桌面/QQ 短期隔离长期共享、WorldPort 渐进 Sidecar、Core SSE 与 World 可靠协议分离、Persona Hub 唯一真源、图片副作用归 Core。
- 使用 Obsidian YAML Frontmatter、Wikilinks、Callouts、Mermaid 和任务清单；不得在 Frontmatter 中放复杂对象或敏感值。

### Bases 看板

创建 `Aerie升级任务.base`，仅索引 `tasks/` 下 `kind: task` 的笔记。任务 Frontmatter 固定字段：

- `title`、`tags`、`kind`、`task_id`、`phase`、`subsystem`
- `status`、`priority`、`dependencies`、`risk`、`decision_required`
- `feature_flag`、`migration`、`files`、`acceptance_ids`
- `rollback_ready`、`owner`、`evidence`

视图固定为：按阶段、P0 与阻塞、迁移与高风险、待决策、待验收、世界与图片、回滚未就绪。公式提供阶段标签、阻塞状态、文件年龄和回滚状态。创建后必须解析 YAML，并通过 Electron Skill 启动/连接 Obsidian，验证 Base、Wikilink、Mermaid 和筛选视图。

## Verification Steps

### 每阶段通用验证

1. 先新增失败测试，再实现最小变更使其通过。
2. 运行受影响模块测试和完整回归测试。
3. 检查数据库迁移 dry-run、幂等、cursor 续跑、守恒和回滚。
4. 验证 Feature Flag 关闭时恢复旧路径且不丢新数据。
5. 检查日志、Fixture、截图和 Evidence 不包含凭据、消息正文或不必要的个人数据。
6. 只提交当前阶段相关文件，不混入格式化或无关重构。

### 全局验收

- 数据回填守恒、幂等、可续跑；桌面与 QQ 短期隔离；Actor 长期记忆共享。
- 连续三条输入不丢失；完整 Turn 上下文；取消、重试、失败状态正确。
- `event_id` 去重、`sequence` 有序、断线恢复不重复。
- Typing、首 delta、多气泡、打断和 reduced-motion 可验证。
- Cron、Desire、Idle、World Candidate 全部经过 Judge；各通道结果独立；用户可静音和降频。
- 图片具备魔数、EXIF 清理、哈希去重、所有权、引用、审核和 GC；World 不直接生成或发送。
- 世界可确定性重放；数据库保持单一所有者；Sidecar 崩溃时聊天降级；Outbox 幂等续传。
- Renderer 无通用 Sidecar 网络能力；世界 IPC 白名单化；系统通知不重复聊天消息。
- Electron Skill 完成 Obsidian 文档验证、Aerie 连续输入、取消、流式、多气泡、上传、主动消息和 Sidecar 崩溃恢复烟测。
- 疑似凭据不进入提交、日志、Fixture、截图或 Evidence。
