# Changelog · Aerie · 云栖

All notable changes to this project will be documented in this file.

本文件记录本项目的所有重要变更。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

---

## [0.2.1-beta.1]

> **自 0.2.0-beta.1 以来的增量迭代 / Incremental iteration since 0.2.0-beta.1**
> 聚焦发图体验、伊塔人设重写、世界模拟迁移重庆、百度地图接入、对话知识库、身份锚定与稳定性修复。

### ✨ Features / 新功能

#### 生图与发图链路 / Image Generation & Photo Delivery

- **聊天主动触发生图链路**（`d88b5bd`）：`_resolve_chat_photo_intent` + `_deliver_chat_photo` 重构，实现「先发引导句 → 异步生图并等待送达（120s 上限，失败不阻塞文本）→ 再发剩余文本」的交互；兼容 InProcess 与 sidecar 两种 `world_port` 发布协议
- **AI 回复语义触发生图**（`199ae6b`）：意图判断升级为三层——关键词快速路径 → 用户消息 LLM 语义判断（全量交给 LLM，准确性优先）→ AI 回复疑似涉图（`_judge_reply_photo_intent`），支持"上下文驱动"发图
- **图片表达层次认知**（`657df2d`）：新增 L6 系统提示段区分"表情包=语言调味剂 / 图片=关系锚点"，新增图片意图检测（sticker/image 层级），受 `world_image_candidates_v1` 开关控制
- **同主题去重与 LLM 提示词接力**（`d41ff4f`）：`has_recent_completed` 从持久化审计存储做跨重启同视觉主题去重；`_image_prompt_for` 两步接力——基础提示词 → 轻量 LLM（`siliconflow-light`，8s 超时）选择性注入画面可见世界数据，失败退回确定性规则
- **主动发图节奏循环**（`f916a87`）：新增 `_run_proactive_photo_loop`（感知→决策→行动闭环），依据 persona 外观生成中文提示词，`_HER_HOME_OBJECTS_ZH` 物件映射
- **生图尺寸自适应**（`d11d9df`）：按 prompt_key 场景自动适配横竖构图（自拍/合影竖 9:16，环境/物件横 16:9），尺寸优先由调用方动态传入
- **生图流程异步化**：同步生图 `_run_workflow_blocking` 经 `asyncio.to_thread` 卸载到工作线程，用户请求图片改为后台异步生成（文本气泡先发、图片稍后到），不再阻塞事件循环

#### 世界模拟 / World Simulation

- **百度地图服务整合**（`f916a87`）：以 SN 校验 REST 替代 MCP（无需 IP 白名单），`weather_service.py` 接入百度天气、`world_reality.py` 用 `_baidu_search_places` 替代 MCP
- **世界模拟迁移重庆**：默认地点 济南 → 重庆（`world.location`），环境物件改为伊塔重庆复式公寓空间素材并合并附近真实 POI
- **内置地点兜底**：新增 `core/builtin_places.py`（20+ 城市地点/本地活动，零配置兜底）

#### 人设、身份与对话 / Persona, Identity & Dialogue

- **伊塔人设重写**（`13bc637`）：前地下格斗选手 → 独立设计师/工作室主理人，年龄 26→28，重写恋爱故事（重庆相识、异地、重庆复式公寓、籍贯山东），新增欲望/恐惧描述，system_prompt 整段重写
- **对话知识库接入**：新增 `tools/seed_social_knowledge.py` 的 `dialogue` 对话知识种子，主动消息生成前检索该分类作为"发起话术原则"；`kb.search()` 新增 `category` 参数并改为逐关键词匹配
- **去AI味儿·对话质感铁律**：`context_builder.py` 新增系统段（体验交换/情境缝合/禁语区/有意义沉默/主观偏见/破格条款）
- **身份锚定机制**（`00a45c7`）：启动时身份播种（`_seed_identity_memories` 写入 Chroma）、恋爱故事与时间快照固定注入 Prompt 头部防截断、新增 `memory/permanent/identity.md` 统一身份来源、`persona.relationship_story` 字段

#### 待办与日历 / Todo & Calendar

- **待办×日历双向同步**（`532e8e4`）：日历 `schedule`/`reminder` 事件合并为只读待办条目，事件在前、待办在后按时间稳定排序，前端抽屉新增事件标识样式

#### 聊天与多端体验 / Chat & Multi-client UX

- **多端交互与附件体验升级**（`2861aad`）：重做 WeChat 风格附件卡片——图片独立大缩略图气泡、非图片文件带彩色图标的横排卡片；`chat_history`/`chat_poll` 补全 `ts` 字段
- **错别字纠错**（`07fd2b2`）：新增 `core/typo_corrector.py`，用 `siliconflow-light` 轻量模型订正错别字/同音字（200 字上限、6s 超时、失败静默回退，不触碰主模型）
- **聊天滚动优化**（`07fd2b2` / `d11d9df`）：DOM 消息上限 500→200、rAF 节流 + 顶部触底分批加载，新增浮动"回到底部"按钮与未读消息角标
- **主动发图间隔配置**（`d11d9df`）：新增 `proactive.photo_min_interval_sec`（可热生效），发图调度重构为纯约束型；主动发图不再受 PushPolicy 频控与 proactive_judge 抑制（仅尊重全局静音），`local_send` 手动触发不受约束

#### Provider 与健康 / Provider & Health

- **Provider 健康/余额管理**（`f916a87`）：新增 `core/provider_health.py`——余额耗尽自动拉黑（1 小时复查窗）、限流冷却（5 分钟）、主动探测 DeepSeek/SiliconFlow 余额端点，持久化到 `data/provider_health.json`；`llm_caller` 在失败前剔除欠费账户

### 🔧 Changed / 变更

- **全局 LLM 温度**：默认 `0.7 → 0.85`（`LLM_TEMPERATURE`）；`generate_push()` 重构为"主动发起方"定位，`TONE_PROMPTS` 改为主动分享式措辞
- **LLM provider 超时**：默认 `60s → 180s`（`AERIE_VISION_PROVIDER_TIMEOUT_SECONDS`）
- **新增轻量 Provider** `siliconflow-light`：用于错别字纠错、快捷问候语、生图提示词接力等快速辅助任务，不触碰主模型
- **图片视觉意图关键词**大幅扩充（自拍/拍照/发照片等）；`local_send` 手动请求的图片不占主动推送频控与每日额度

### 🐛 Fixed / 修复

- **消息撤回本地临时 ID 报 422**（`d9c2807`）：撤回前校验真实 `msg_id`，未同步消息直接提示拦截；`chat_log` 新增 `qq_message_id` 字段
- **心跳续租误杀已完成请求**（`f916a87`）：终态请求的续租失败不再触发取消（`is_terminated()` 判断）
- **sidecar 发布协议误判 rejected**（`d88b5bd`）：兼容 InProcess `{"status":"accepted"}` 与 sidecar `{"seq":...}` 两种返回
- **`long_term_memory` 主键类型不匹配**（`00a45c7`）：`id` 由 INTEGER 改为 TEXT(uuid)，修复与 ChromaDB 写入 datatype mismatch，自动重建迁移
- **裸 HH:MM 待办按天查不到**（`532e8e4`）：`_normalize_due_time()` 自动补当天日期，空值落到 `T23:59:59`
- **冷启动后端未就绪各面板永久横幅**（`2861aad`）：preload 新增 `withBackendWait`，IPC 层对 `ECONNREFUSED` 自动重试（15s 上限、500ms 步进）
- **轮询接口附件渲染为空**（`2861aad`）：聊天轮询附件 JSON 解析 + `_hydrate_desktop_attachment_records`
- **Electron 重启失败**（`13bc637`）：`restart.bat` 改直接启动 `electron.exe` 二进制（`start` 无法启动 `electron.cmd` 垫片）
- **知识库 tags 搜索匹配失败**（`13bc637`）：改为逐关键词匹配
- **RAR 安全**：拦截无有效成员的垃圾 RAR 附件

### Performance / 性能

- **生图异步化**：`asyncio.to_thread` 卸载阻塞式生图，避免冻结事件循环
- **用户请求图片后台异步生成**：不阻塞主回复
- **Provider 健康过滤**：欠费账户在请求失败前即被剔除轮询
- **聊天渲染**：DOM 消息上限 500→200、历史消息 rAF 节流分批加载
- **回复侧保留模糊信号闸门**：避免对每条回复都发起额外 LLM 调用

### 🔌 API 接口新增 / New API Endpoints

- `GET/POST /api/env/baidu-map` 百度地图 AK/SK 读取与保存（密钥脱敏）
- `POST /api/brief/greeting` 轻量模型快捷刷新简报问候语（4s 硬上限，失败回退缓存）

### ⚙️ 配置与开关 / Config & Feature Flags

- **`config/settings.yaml`**：
  - `world.location`：济南 → 重庆
  - `proactive.image_max_per_day`：20 → 0（0=不限制，纯约束型由 Agent 自决）
  - 新增 `proactive.photo_min_interval_sec`：主动发图最小间隔（秒，0=无间隔，默认 0；对应前端分钟下拉）
- **`config/persona.yaml`**：伊塔人设重写（独立设计师/28 岁）、新增 `relationship_story`、`body_type` 文案微调
- **新增环境变量**：`BAIDU_MAP_AK` / `BAIDU_MAP_SK`、`AERIE_DISABLED_PROVIDERS`（手动禁用 provider）、`SILICONFLOW_LIGHT_MODEL`（轻量辅助模型）；`IMAGE_GEN_*` 扩展支持（API_KEY/BASE_URL/MODEL + 幂等键）
- **数据库**：`chat_log` 新增 `qq_message_id`；`long_term_memory.id` 改为 TEXT(uuid) 并新增多维字段

### 🧪 Tests / 测试

- 新增 `test_phase14_world_image_candidates.py`（跨重启同主题去重、窗口过期与 failed 过滤）
- 更新 `test_context_builder.py`（图片能力注入/意图识别/开关控制）、`test_todo_manager.py`（日历事件合并、时间归一化）

---

## [0.2.0-beta.1] - 2026-08-10

> **能力大版本升级 / Major Beta Release**
> 从 0.1.0-beta.1 基线以来，完成 P1 陪伴融合、世界模拟、三端撤回、多模态生图、向量知识库与移动端网关等系统性能力实装。
> 按 Keep a Changelog 规范将此前若干 Unreleased 段合并为本版本，并明确标注为 `0.2.0-beta.1`。

### ✨ Features / 新功能

#### 陪伴融合 (P1) / Companion Fusion

- **内在状态接入**：`core/internal_state.py` + `emotion_state_store.py` 落地，情绪/关系自然化全量实现，PAD 情绪、欲望引擎、关系建模与拟人化节奏统一接入
- **同理心策略**：`core/empathy_strategy.py`（`test_p1_a3`），根据对话情境自适应同理心表达
- **记忆可见性**：LayeredMemory 生产记忆切换（见下方"向量知识库"），P1 记忆可见性合同落地
- **人设配置**：`persona_config.py` / `persona_behavior.yaml` 行为与表达节奏配置化
- **通道抽象**：`core/companion_channel.py` 多通道抽象 + 3 层适配器（`test_p1_d4` / `test_p1_d5`）

#### 三端撤回 + 消息合并重构 / Multi-channel Recall & Message Merge

- **三端撤回解耦**：新增 `communication/recall/` 包（`RecallAdapter` 协议 + QQ/Local/WeChatClawbot 三端实现），`RecallManager` 改为按 `(channel, channel_account_id)` 记录与预算，撤回能力经适配器按端口分派
- **LLM 主动撤回指令**：新增 `core/recall_instruction.py`，解析并执行 AI 输出的 `<recall reason="...">` 指令（与纯文本 `<action>` 严格分离），执行后从正文剔除并撤回上一条已发消息；`config/persona.yaml` 的 `recall.triggers` 从死配置变为有消费方
- **本地端撤回补全**：`companion.recall_message` 通用化，纯本地消息可撤回（DB 标记 + 前端"已撤回"呈现），不再报 `no_qq_message_id`
- **消息合并重构**：`MessageBatcher` 首条立即提交、后续消息动态缓冲，当前批完成后作为新批处理，不再等固定窗口
- **撤回判断联动**：新增 `core/message_orchestrator.py`（`RecallJudge`），新批到达且上一批已产出时决策是否撤回首条再合并重算
- **QQ 端**：NapCat `delete_msg` 真实撤回；**本地/桌面端**：DB 标记 + 前端事件；**微信端**：架构预留桩（`channel="clawbot"`），iLink 协议暂无可调用撤回端点，`<recall>` 自动降级为仅本地标记

#### 多模态生图与视觉 / Multimodal Image & Vision

- **三视图生图辅助**：人设面板可上传正/侧/背三视图参考图（`GET/POST/DELETE /api/persona/three-view/...`），经 `three_view:front` token 锁定角色外观；超限自动压缩，大小经 `AERIE_THREE_VIEW_MAX_BYTES` 配置（默认 8MB）
- **图片候选人生成推送**：`world_image_candidates_v1` 开关 + `POST /api/world/image-candidates/publish`，支持 `qq` / `local_chat` 双通道交付；本地聊天以绝对 URL + `.chat-bubble img` 样式渲染
- **QQ 发图**：`QQClient.send_image()` 以 OneBot11 图片段发送图片到 QQ
- **主动发图预算管控**：`core/image_budget.py` + `proactive.image_max_per_day`（默认 20）限制每日主动发图量
- **图生图能力 (img2img)**：`core/image_service.py` 支持基于参考图生成
- **SiliconFlow 视觉技能**：新增 `skills/local/siliconflow-vision/`，复用 `SILICONFLOW_API_KEY`，让纯文本 LLM 具备图片识别/描述能力

#### 世界模拟 / World Simulation (Phase 11-15)

- **世界端口与领域**：`world_port.py` / `world_simulation.py`，`world_inprocess_v1`（默认开）与 `world_sidecar_v1` 双模式
- **世界现实与天气**：`world_reality.py` + `weather_service.py`，真实数据同步，`world.location=济南`
- **世界仪表盘**：`/world/dashboard`、`/world/snapshot` API + Electron `world-dashboard-host.js`，新增世界位置配置与真实数据同步
- **WorldSnapshot**：确定性计算，`world.random_events_per_day` / `world.reality_refresh_sec` / `world.tick_interval_sec` 可配置
- **Sidecar**：`world_service/main.py` + SQLite 存储（`world_service/storage/sqlite_store.py`）

#### 向量知识库与记忆 / Vector KB & Memory

- **专用向量知识库激活**：`core/knowledge_indexer.py` 将桌面附件分块索引进独立 Chroma 库（`data/chroma_attachments`），检索命中注入上下文
- **生产记忆切换 LayeredMemory**：`memory/layers/` 分层记忆（transient/short/long/permanent），`scripts/migrate_long_term_memory.py` 迁移旧数据
- **知识库写入工具**：新增知识库写入工具并启用全局工具支持（`tools` 全量接入 Function Calling）

#### 移动端网关 / Mobile Gateway

- **Android 移动网关**：`core/mobile_gateway.py` + `mobile_chat.py` + `mobile_files.py` + `mobile_identity.py`，多端会话、文件能力与账号鉴权（`mobile_gateway_v1` 开关）
- **重启可观测**：backend restart helper 改为 project-root 安全、可观测执行
- **消息顺序保序**：移动端消息段顺序保留，历史游标 honor camel-case

#### 简报与资讯 / Brief & News

- **分层混合爬虫**：`brief_fetcher.py` 按 `SECTIONS_PRIORITY` 逐层尝试（hn → crawl → aggregator → hot → bocha），Hacker News 与百度热搜无需 API Key
- **GitHub Trending 订阅**：`brief_subscriptions.sources.github_trending` 可订阅热门仓库（`min_stars=200`）
- **全屏天气预报**：brief-drawer 新增全屏天气展示与抽屉样式优化

#### 办公与文档 / Office & Docs

- **文档写作工具链**：`core/doc_writer.py` 文档写作工具（报告/规格/研究等）
- **文件整理增强**：`file_organizer.py` 文件整理、去重与过期清理
- **办公模式匹配**：`office_mode.py` 办公模式关键词匹配与徽标显示控制
- **LLMCaller 命名收敛**：核心模块从 `Brain` 收敛到 `core/llm_caller.py`（`test_llm_caller` 全链路测试）

### 🔧 Changed / 变更

- **版本号**：0.1.0-beta.1 → 0.2.0-beta.1
- **LLM 时间感知修正**：修复 LLM 时间感知偏差，优化对话历史与时间展示；输出端剥离 `[MM-DD HH:MM]` 时间戳标记（`pipeline._strip_leading_timestamp`），系统提示新增"时间戳铁律"防止模型模仿历史格式
- **开机问候升级**：`boot_greeting` 支持动态上下文生成，`_boot_greeting_fired` 守卫避免开场双消息
- **多平台通用搜索工具**：`tools/social_search.py` 等，世界仪表盘与天气功能同步优化
- **每日简报缓存**：修复 todo 数据过时问题，移除自动生成示例待办逻辑
- **Electron 动态岛**：修复环境变量开关逻辑位置；灵动岛原生置顶、窗口生命周期、导航时序、打包托盘图标、渲染安全（sandbox + contextIsolation）等多项修复

### 🐛 Fixed / 修复

- **Electron 渲染层**：灵动岛原生置顶（`WS_EX_TOPMOST` 保留）、窗口二次启动唤回、导航缓存时序、打包托盘图标、renderer sandbox 恢复
- **移动端**：消息段顺序保序、历史游标 camel-case、backend restart project-root 安全与可观测
- **简报**：缓存 todo 数据过时、移除自动示例待办
- **时间戳**：LLM 输出残留 `[MM-DD HH:MM]` 标记剥离

### Performance / 性能

- **Electron 首屏初始化**：隐藏面板延迟初始化，全局控制器延后启动
- **日报合成**：收敛单层背景模糊，移除嵌套 filter 与触发 sibling layer 丢失的 transform
- **灵动岛空闲负载**：移除常驻粒子循环，媒体状态单飞自适应轮询，隐藏时暂停

### 🔌 API 接口新增 / New API Endpoints

- `POST /api/world/image-candidates/publish` 图片候选人发布（channel: `qq` / `local_chat`）
- `GET/POST/DELETE /api/persona/three-view/{persona_id}/{view}` 三视图参考图管理

### 🧪 Tests / 测试

- **Python 单测**：107 个 `test_*.py` 文件覆盖 Phase 0-15、P1 陪伴融合、v13.9、E2E 与验证脚本
- 新增 `test_recall_adapters.py`、`test_recall_instruction.py`、`test_message_orchestrator.py`、`test_persona_three_view.py`、`test_desktop_attachment_vector_index.py`、`test_llm_caller.py` 等
- 更新 `test_message_batcher.py` 为新"首条立即"语义（15 用例全绿）
- **Electron**：16 个 `.test.js` 文件覆盖窗口生命周期、日报、napcat、persona-hub、chat-store、panels、system-status 等

### 📝 Documentation / 文档

- 同步 README 当前状态（版本、能力、启动流程、验证命令、项目结构、配置与排障）
- 补充线上官网地址 `https://laser1209.github.io/Aerie_Spotlight/`、World Service、Phase 0-15 测试与发布资源说明

---

## [0.1.0-beta.1] - 2026-07-19

> **内测基准版本 / Internal Beta Baseline**
> 从 v13.9.8 重置版本号，确立内测阶段第一个稳定基线，后续严格按内测规范迭代

### 🔄 Changed / 变更

- **版本号重置**：13.9.8 → 0.1.0-beta.1，正式进入内测阶段
- **版本策略调整**：放弃跳跃式大版本号，采用 beta 迭代渐进收敛

---

## [13.9.8] - 2026-07-19

> **v13.9 收尾版本 / Final v13.9 Release**
> 全项目综合修复方案就绪，15 个 Bug 确认待修复（5 Critical + 6 High + 4 Medium）

### 🐛 发现问题 / Issues Identified

#### Critical — 运行时崩溃

- **pipeline.py** `history_msgs` NameError：校验链路完全失效
- **computer_control.py** 4 处方法名错误：`key_type`→`type_text` / `run_shell`→`shell_execute` / `uia_action` 缺失 / `focus_window` 参数类型错误

#### High — 功能静默失效

- **companion.py** Brain/EmotionStateStore 重复实例化
- **persona_loader.py** YAMLError 未捕获，损坏文件导致启动崩溃
- **context_builder.py** 除零错误
- **approval-modal.js / office-mode.js** SSE 回调未 JSON.parse，推送完全失效

#### Medium — 技术债务

- **computer_control.py** 协程泄漏（`_cleanup` 未启动）
- **companion.py** AsyncTaskManager 未显式启动

---

## [13.9.4] - 2026-07-19

> **办公模式增强 / Office Mode Enhancement**
> 文件保存目录可配置化，QQ 客户端重构优化

### ✨ Added / 新增

#### 办公文件保存目录配置

- **settings.yaml 新增 `office.dir` 字段**：用户可自定义办公文件保存路径
- **设置面板 UI**：前端新增办公目录选择器，支持浏览文件夹
- **API 端点**：`GET/PUT /api/settings/office-dir` 读写办公目录配置
- **动态目录支持**：`get_office_dir()` 每次从 settings 重新读取，配置变更即时生效

### 🔧 Changed / 变更

#### QQ 客户端重构

- **`_rpc_call` 方法统一**：`_learn_self_id` / `recall_message` / `send_poke` / `send_message_with_segments` 全部使用 `_rpc_call` 进行 echo 匹配和生命周期/心跳帧过滤
- **`is_logged_in` 替代 `is_connected`**：QQ 消息发送就绪判断改用 WS 层 + QQ 账号双重登录状态

---

## [13.9.3] - 2026-07-19

> **桌面应用功能迭代 / Desktop App Feature Iteration**
> 灵动岛媒体控制完善、办公模式交互优化、SMTC 中文编码修复

### ✨ Added / 新增

#### 灵动岛增强

- **媒体缩略图支持**：SMTC 曲目封面提取并在灵动岛展示
- **媒体状态扩展**：新增 `thumbnail` 字段和 `_lastThumbnailPath` 缓存

#### 办公模式优化

- **下拉菜单智能定位**：根据视口空间自动翻转方向（上方/下方），`transform-origin` 动态调整
- **键盘无障碍**：Enter/Space 触发、Esc 关闭，`aria-haspopup` / `aria-expanded` ARIA 属性
- **菜单挂载优化**：追加到 `document.body` 避免 overflow 裁剪，`position: fixed` + `z-index: 9999`

### 🐛 Fixed / 修复

#### SMTC 中文乱码

- **PowerShell UTF-8 强制编码**：在 SMTC 查询脚本开头添加 `$OutputEncoding` / `[Console]::OutputEncoding` / `chcp 65001`，解决中文歌曲标题/艺术家在 Node.js stdout 读取时变成乱码的问题

### 🔧 Changed / 变更

- **灵动岛**：样式优化 + 组件配置加载逻辑修正（仅完整数组通过校验）
- **办公模式 CSS**：重构样式表，改进菜单交互与视觉

---

## [13.9.2] - 2026-07-18

> **v13.9 第三批升级 / Batch 3: 权限体系 + 工具矩阵 + 任务执行 + 异步调度**
> 四大核心模块全部落地，从办公助手升级为自主办事 Agent

### ✨ Added / 新增

#### 权限体系重做（对标豆包双层授权）

- **细粒度权限管理器** ([permission_manager.py](file:///e:/Agent_reply/core/permission_manager.py))
  - 5 大类权限：文件读取 / 文件写入 / 文件删除 / 界面控制 / 系统操作
  - 目录级白名单：默认授权文档/下载/桌面/AerieOffice 四个目录
  - 系统路径自动拦截：Windows / Program Files / 注册表等永久禁止
  - 高危操作二次确认：删除、批量操作、shell 命令均需用户确认
  - 信任模式：可跳过二次确认（带风险提示）
  - 一键撤销：立即关闭所有非必要权限
  - 完整审计日志：500 条操作记录可追溯
  - 旧版兼容：三档权限（view_only/standard/full）仍可使用

#### 办公工具矩阵扩充（7 → 26 个）

- **文件管理类**：目录遍历、文件复制、文件移动、文件重命名、创建目录
- **文档处理类**：Word 文档生成、CSV 表格生成、文档格式转换
- **系统操作类**：系统信息查询、进程列表、打开应用
- **数据分析类**：数据统计、数据过滤、数据排序、SVG 图表生成（柱状/折线/饼图）
- **网络工具类**：网页抓取、天气查询、多语言翻译、GitHub 代码搜索
- 所有工具均带 OpenAI Function Calling Schema，可直接被 LLM 调用

#### 任务执行引擎

- **TaskExecutor 任务执行器** ([task_executor.py](file:///e:/Agent_reply/core/task_executor.py))
  - 步骤级执行：按顺序执行 TaskPlanner 规划的每一步
  - 失败自动重试：单步最多重试 3 次，逐步增加等待时间
  - 进度实时追踪：每步状态、耗时、结果完整记录
  - 执行结果汇总：自动生成执行总结报告
  - 可扩展处理器：支持注册自定义 step handler

#### 异步任务系统

- **AsyncTaskManager 异步任务管理器** ([async_task_manager.py](file:///e:/Agent_reply/core/async_task_manager.py))
  - 任务队列：基于 asyncio 的调度队列，支持优先级（高/中/低）
  - 并发控制：默认同时最多 3 个任务
  - 实时进度：进度百分比 + 当前步骤 + 已用时间 + 预计剩余
  - 任务管理：运行中/历史记录/取消/重试，完整生命周期管理
  - WebSocket 事件：task_submitted / task_cancelled / 进度更新
  - 进度回调机制：支持注册多个进度监听器
  - 历史记录：最多保留 100 条任务记录

### 🔌 API 接口

#### 权限管理 API

- `GET /api/permissions/config` 获取权限配置
- `PUT /api/permissions/config` 更新权限配置
- `GET /api/permissions/dirs` 列出授权目录
- `POST /api/permissions/dirs` 添加授权目录
- `DELETE /api/permissions/dirs` 移除授权目录
- `POST /api/permissions/check` 权限检查
- `GET /api/permissions/audit` 审计日志
- `POST /api/permissions/revoke_all` 一键撤销所有权限

#### 异步任务 API

- `GET /api/tasks` 任务列表（支持状态过滤）
- `GET /api/tasks/stats` 任务统计
- `GET /api/tasks/{id}` 任务详情
- `POST /api/tasks` 提交任务
- `POST /api/tasks/{id}/cancel` 取消任务
- `POST /api/tasks/{id}/retry` 重试任务
- `GET /api/tasks/{id}/progress` 进度历史

### 🧪 Testing / 测试

- 综合测试套件：7 大类测试全部通过
- 权限管理器：9 项测试（默认配置/目录授权/系统拦截/二次确认/一键撤销等）
- 办公工具：26 个工具全部注册成功，OpenAI Schema 完整
- 任务规划：7 项测试（触发判断/分类/创建/进度/动态调整）
- 任务执行：步骤级执行 + 重试 + 结果汇总全部正常
- 异步任务：提交/执行/取消/列表，全流程通过
- 数据分析：统计/过滤/排序/图表，4 项工具验证通过
- 文件管理：列目录/创建/复制/重命名，全部正常

---

## [13.9.1] - 2026-07-18

> **v13.9 第二批升级 / Batch 2: 全图标矢量化 + 任务规划引擎 + 文件整理模板**
> 完成 emoji 全面替换，新增任务规划引擎和文件整理预设模板，完善回复校验集成

### ✨ Added / 新增

#### 图标系统

- **全项目 emoji 矢量图标替换**：新增 30+ 个 SVG sprite 图标，覆盖所有 UI 场景
  - UI 基础类：home / heart / brain / dna / mouse / shield / folder / file-text / calendar / message
  - 媒体类：image / video / package / lightbulb / list / trash / refresh / eye / hand
  - 功能类：sparkles / flower / briefcase / microscope / bar-chart / book / globe / thought / target / check
  - 文档类：book-open (PDF) / book-blue (Word)
- **替换范围**：HTML 页面 37 处 + JS 动态渲染 7 处，全部使用矢量图标替代 emoji

#### 任务规划引擎

- **TaskPlanner 任务规划引擎** (`core/task_planner.py`)：办公模式下复杂任务自动拆解
  - 6 种任务类型识别：doc_write / data_analysis / file_organize / research / code_task / simple
  - 5 步标准流程模板：需求分析 → 方案设计 → 核心执行 → 测试验证 → 优化交付
  - 动态调整：根据用户关键词（简单/详细）自动增减步骤和复杂度
  - 进度追踪：每步状态管理 + 进度百分比 + 结构化输出
  - 最大步数限制：默认 10 步，防止 Token 过度消耗

#### 文件整理模板

- **4 个预设整理模板** (`core/file_organizer.py`)
  - 下载文件夹整理：按文件类型（图片/文档/视频/音频/压缩包/安装包/其他）分类
  - 桌面整理：按用途（工作文档/图片素材/视频/压缩文件/其他）分类
  - 照片按日期整理：按月归档照片
  - 工作文档整理：按项目和年份分类工作文档
- **模板 API**：`list_organize_templates()` / `get_organize_template()`

### 🔧 Changed / 变更

#### QQ 消息优化

- **thought/action 标签过滤**：QQ 发送消息前自动移除 `<thought>` 和 `<action>` 标签
  - 支持跨行匹配、大小写不敏感
  - 自动清理多余空行，只输出纯对话文本
  - 集成到 `send_message` 和 `send_message_with_segments` 两个发送入口

#### 回复校验完善

- **Pipeline 集成**：FULL 模式和 BASIC 模式均接入回复校验
  - FULL 模式：完整 Guard + Judge 双层校验，结果写入认知 trace
  - BASIC 模式：轻量校验，不影响响应速度
  - best-effort 模式：校验失败不影响主流程

### 🛡️ Security / 安全

- **回复校验 Accuracy Guard**：敏感内容检测（赌博/毒品/自伤/暴力），自动拦截
- **文件整理路径安全**：所有移动操作基于预览计划生成，支持 7 天撤销

---

## [13.0.0] - 2026-07-18

> **v13 大版本发布 / Major release: 办公模式 + 回复校验 + 事件驱动推送**
> 三大核心能力落地：办公模式（豆包优先 + 7大办公工具 + 设备识别）、双层回复校验、事件驱动主动推送
> 基础设施工具化：Persona Hub 人设基础设施（可自定义人设模板）

### ✨ Added / 新增

#### 办公模式

- **办公模式核心架构**：三档切换（自动识别 / 聊天模式 / 办公模式），智能检测关键词 + 上下文启发式判断，8 类任务分类（文档/表格/PPT/邮件/日程/代码/搜索/分析）
- **办公场景工具集（7个）**：document_create / document_read / spreadsheet_analyze / file_search / text_summary / calendar_list / calendar_create
- **模型路由优化**：办公模式自动优先豆包 Seed 2.1 Turbo，provider 重排序机制
- **设备识别能力**：User-Agent 解析，自动识别 PC/手机/平板，区分操作系统和浏览器
- **前端办公模式入口**：输入框左侧工具栏按钮，下拉菜单切换模式，状态指示器

#### 回复校验机制

- **双层校验架构**：Accuracy Guard（准确性闸门） + Quality Judge（质量评判）
- **Guard 层**：敏感内容检测 / 专业领域免责声明检查 / 自相矛盾检测 / 数字夸大检测
- **Judge 层**：长度评估 / 切题度评分 / 语气一致性 / 情绪价值评估，四维综合评分
- **Pipeline 集成**：LLM 生成后、用户收到前的校验环节，结果写入认知链路 trace
- **API 接口**：POST /api/validation/check + GET /api/validation/config

#### 主动推送增强

- **事件驱动推送引擎**：EventBus 发布/订阅模式，19 种事件类型（用户行为 / 时间日期 / 环境 / 系统 / 待办）
- **三类触发源**：Cron 定时（已有） + 情绪触发（ProactiveJudge 综合判定） + 事件触发（新增）
- **空闲监控**：用户长时间未互动检测，自动触发关怀消息
- **前端管理面板**：状态总览 / 场景列表 / 事件历史 / 一键触发，5 个 API 端点

#### Persona Hub 人设基础设施

- **人设管理器**：人设模板化，支持自定义创建、加载、切换
- **预设模板**：默认伊塔模板，可扩展多套人设
- **前端人设面板**：人设选择、参数配置、实时预览

### 🔧 Changed / 变更

- 版本号：12.1.0 → 13.0.0（MAJOR 升级，新增三大核心能力）
- Pipeline 新增回复校验环节，不影响原有流程（best-effort 模式）
- 主动推送从纯定时升级为「定时 + 情绪 + 事件」三维触发

### 🛡️ Security / 安全

- 回复校验 Guard 层拦截违规内容，确保输出安全合规
- 办公工具文件系统访问受限，防止越权操作
- 事件引擎用户活动监控仅本地运行，无数据泄露风险

---

## [12.1.0] - 2026-07-18

> **桌面灵动岛重磅登场 / Minor release: Dynamic Island**
> 删除悬浮球，全面升级为桌面顶部灵动岛，组件化架构，多主题多形态，弹性果冻感动画
> 新增：Kimi WebBridge 浏览器操控 + douyin-mcp 抖音数据采集

### ✨ Added / 新增

- 桌面灵动岛（Dynamic Island）替代原悬浮球，四种形态：胶囊态 / 通知态 / 工具栏态 / 展开态
- 三套主题可切换：深色毛玻璃 / 恋粉治愈 / 浅白清新
- 组件化架构，用户可自由配置显示内容和顺序
- 四种交互方式可配置：点击 / 悬停 / 两级 / 长按
- 弹性果冻感动画 + 粒子特效系统
- Kimi WebBridge 浏览器操作工具集（13个工具，可对话调用）
- douyin-mcp 抖音创作者数据工具集（13个工具，可对话调用）

### 🔄 Changed / 变更

- 移除旧版悬浮球全部代码
- 版本号：12.0.1 → 12.1.0

### 🎨 UI/UX

- 灵动岛视觉设计：呼吸光晕、粒子散出、弹性过渡
- 设置页新增「灵动岛」配置面板，实时预览

---

## [12.0.1] - 2026-07-18

> **v12 大版本发布 / Major release: v12**
> 外部单 Agent + 内部准多 Agent 架构，能力全面爆发
> 核心跃升：自进化 L4 · 电脑操控 · 文件整理 · 文档写作 · 自主 Skill · QQ 深耕 · Cognition Panel v2

### ✨ Added / 新增

#### 架构升级

- **Agent 抽象 (S1)**：显式 Agent 类，六步主循环（Perceive→Reason→Decide→Act→Reflect→Express），异步 Reflect 队列
- **Provider 智能路由 (S2)**：5 维复杂度评估，动态路由 + 全局预算跟踪，混合模式（规则为主 + LLM 仲裁）
- **四层记忆 + 安全 (S3)**：transient/working/long-term/permanent 四层记忆架构，工具调用隔离，10 类 Prompt Injection 防御
- **多模态 + 自进化 L1-L3 (S4)**：图片输入、TTS 语音输出，梦境整理 / 会话复盘 / 主动沉淀三级自进化

#### S5 能力大爆发

- **🧬 自进化 L4**：代码自修改引擎，4 道生存闸门（安全审查 / 语法检查 / 测试验证 / 回滚准备），白名单控制，24h 回滚窗口，完整审计日志
- **🖱️ 电脑操控**：3 级权限（VIEW_ONLY / STANDARD / FULL），键鼠控制 + 截图 + UIA 自动化 + 受限 Shell，危险命令黑名单，操作审计日志
- **📁 文件整理**：目录扫描 + AI 智能分类 + 预览执行 + 一键移动/重命名，7 天撤销日志，大文件/近期文件标记
- **📝 文档写作**：5 类模板（日记/报告/规格/研究/简历），4 种导出格式（Markdown/HTML/PDF/Word），3 种 HTML 样式
- **🔧 自主 Skill 创建**：5 类模板（utility/text_processing/data_query/transform/custom），安全沙箱验证，命名空间隔离，自动注册加载
- **💬 QQ 深耕**：语音优化（Silk 编码 + 缓存），视频管理（缩略图 + 压缩），大文件传输（分块 + MD5 校验），主动消息 v2（4 级优先级 + 定时 + 速率限制）

#### S6 集成发布

- **🧠 Cognition Panel v2**：5 Tab 导航（大脑中枢 / 自进化 / 电脑操控 / 文件整理 / 文档写作），渐变玻璃风，完整响应式，原有功能完整保留
- **📦 便携版打包**：Windows x64 portable ZIP，即下即用，无需安装

### 🔧 Changed / 变更

- Electron 版本号：9.0.0 → 12.0.1
- Cognition Panel 全面升级为 v2 多 Tab 架构

### 🛡️ Security / 安全

- L4 自进化：白名单 + 4 道闸门 + 24h 回滚窗口，确保代码修改安全可控
- 电脑操控：3 级权限 + 危险命令黑名单 + 审计日志，防止误操作
- 文件整理：预览二次确认 + 7 天撤销日志，数据可恢复
- Prompt Injection：10 类攻击向量全绿，工具调用隔离生效

---

## [9.0.0][9.0.0] - 2026-07-16

> **首个可分发的完整版本 / First distributable complete release**
> 完整对齐 `OpenCloud_Companion_System_Features.md` v9.0 与 `Ita.md` v3.1
> Fully aligned with `OpenCloud_Companion_System_Features.md` v9.0 and `Ita.md` v3.1

### ✨ Added / 新增

#### Desktop Shell (Electron 28)

- `electron/src/main.js` 主进程：单实例锁 + Python 后端 spawn + 主窗口 + 悬浮球 + 托盘
- `electron/src/preload.js` `contextBridge` 暴露 IPC API（安全基线：nodeIntegration=false / contextIsolation=true / sandbox）
- `electron/src/renderer/index.html` 渲染层骨架 + 严格 CSP
- `electron/src/renderer/floating-ball.html` 悬浮球：拖拽 + 智能靠边 + 单击展开 + 双击最大化 + 5s 半透明
- `electron/src/renderer/js/chat.js` 聊天面板：发送 + 历史 + 5s 轮询新消息
- `electron/src/renderer/js/sidebar.js` 侧边栏 5 Tab：情绪 / 纪念 / 系统 / 其他 / 数据
- `electron/src/renderer/js/status.js` 状态面板：5s 刷新 Token / 模型 / 内核 / Provider
- `electron/src/renderer/js/theme-switcher.js` 5 主题切换（伊塔粉 / 深夜紫 / 樱白 / 海蓝 / 森绿）
- `electron/src/renderer/js/app.js` 主应用协调
- `electron/src/renderer/js/api.js` IPC 客户端
- `electron/builder/installer.nsh` NSIS 安装器脚本
- `electron/builder/icon.ico` 多尺寸应用图标（16/32/48/64/128/256）
- `electron/electron-builder.yml` 打包配置（`requestedExecutionLevel: requireAdministrator`）

#### Python Backend (3.12+)

- `main.py` Python 后端入口（SIGTERM 优雅关闭 + 启动序列编排）
- `core/companion.py` Companion 主类，编排所有后端模块
- `core/brain.py` 多 Provider AI 调度（Fallback 链 Qwen → DeepSeek → Gemini）
- `core/providers/base.py` Provider 抽象基类
- `core/providers/qwen.py` Qwen (DashScope OpenAI 兼容)
- `core/providers/deepseek.py` DeepSeek
- `core/providers/gemini.py` Gemini (OpenAI 兼容端点)
- `core/token_tracker.py` Token 消耗统计
- `core/emotion_engine.py` PAD 三维情感引擎（5 类基本情绪）
- `core/emotion_threshold.py` 累积阈值引擎（4 槽位：忍耐 / 不安 / 渴望 / 温柔透支）
- `core/context_builder.py` 上下文构建（System Prompt + 长期记忆 Top 5 + 知识库 Top 3 + 最近 8 条历史）
- `core/database.py` SQLite 单例 + 8 张业务表
- `core/pipeline.py` 5 阶段消息处理管线
- `core/api_server.py` aiohttp 22+ 端点 HTTP API
- `core/backup.py` 自动 + 手动 zip 备份 + 一键迁移
- `core/elevator.py` UAC 静默提权
- `core/task_scheduler.py` Windows 任务计划包装
- `core/system_monitor.py` CPU / 内存 / 磁盘 / 网络
- `core/self_healing.py` 14 类故障自动恢复
- `core/tool_registry.py` 工具注册表
- `core/function_calling.py` OpenAI Function Calling 适配

#### Communication Layer

- `communication/qq_client.py` NapCat OneBot11 WebSocket 客户端
- `communication/router.py` 三级路由（FULL / AUTO / BASIC）
- `communication/message.py` IncomingMessage / OutgoingReply DTO
- `communication/splitter.py` 语义分段器（8 种分割模式）
- `communication/send_queue.py` 拟人化发送队列（5 类间隔范围）
- `communication/recall_manager.py` 撤回机制（闷骚型特有）

#### Proactive Messenger (auto-wake ⭐)

- `scheduler/cron.py` APScheduler 包装 + 9 个 Cron 任务
- `proactive/messenger.py` 主动消息器
- `proactive/policy.py` 频控策略（5 重检查 + 暂停）
- `proactive/scenes/` 9 个场景模块（morning_brief / weather_push / lunch_remind / evening_check / goodnight / todo_remind / anniversary / idle_care / emotion_comfort）
- `config/proactive.yaml` 9 场景配置 + 静默时段 + 频控参数

#### Persona Engine

- `persona/decision.py` 4 级决策权重（L1 0.5 / L2 0.3 / L3 0.15 / L4 0.05）
- `persona/brain_random.py` Markov 转移矩阵
- `config/persona.yaml` 伊塔完整人设（22 岁女 · 四爱 · 闷骚+病娇 · ISTP · 大五人格 O:0.70/C:0.85/E:0.45/A:0.70/N:0.45）

#### Memory & Knowledge

- `memory/short_term.py` 短期记忆（最近 8 条）
- `memory/memory_store.py` 长期记忆（SQLite + 关键词检索）
- `knowledge/kb.py` 知识库（4 类目：persona / user / world / task）

#### Tool System (14+ Tools)

- `tools/__init__.py` 14 个工具模块：
  - `query_knowledge` / `add_todo` / `list_todos` / `mark_todo_done`
  - `search_music` / `play_local_music` / `set_reminder` / `get_weather`
  - `search_web` / `open_application` / `close_application` / `screenshot`
  - `get_system_status` / `send_proactive_msg`

#### Config

- `config/settings.yaml` 主配置（self_qq / http_api / theme / window / startup）
- `config/persona.yaml` 伊塔人设
- `config/proactive.yaml` 主动推送配置
- `.env.example` 模板（API 密钥 + 端口 + 时区）
- `requirements.txt` Python 依赖（aiohttp / websockets / loguru / psutil / pyyaml / apscheduler / openai / requests / pywin32 / python-dotenv）

### 🛠 Changed / 变更

- **运行时零窗口** / Zero console windows at runtime:
  - 使用 `pythonw.exe` 替代 `python.exe`
  - Electron spawn 配置 `windowsHide: true` + `stdio: 'ignore'`
  - `app.disableHardwareAcceleration()` 减少内存
- **消息规范强化** / Message spec hardening (v8.0 → v9.0):
  - 输入消息 ≤ 2000 字符（截断 + `parse_error=true`）
  - 输出消息 ≤ 2000 字符（超长分段）
  - 推送消息 ≤ 2000 字符
  - 知识库内容 ≤ 8000 字符
  - Emoji 频率 5-10%（`persona.yaml` 可配置）
- **命名规范** / Naming convention:
  - 用户面向（UI / 文档）：中英双语
  - 代码层（变量 / 函数 / 注释 / 日志 / SQL / API / 包名 / 路径 / 环境变量）：纯英文

### 🐛 Fixed / 修复

- 7-Zip 符号链接提取错误（在 Windows 上构建时缺少 `SeCreateSymbolicLinkPrivilege`）
  → 实现 `7za.cmd` → `7za-shim.js` → `7za-original.exe` shim 链，注入 `-snh -snt -snl` 标志
- `builder-util` 的 `chmod` 错误处理
- PyQt6 stylesheet ID 选择器在子控件上静默失败（不影响 v9.0，文档已记录）
- `os.startfile` 不解析 PATH 环境变量（v8.0 经验，已记录）

### 🗑 Removed / 移除

- 所有 v5-v6 早期未实现模块
- 所有 "主人" 措辞（v8.0 起），保留 "主人哲学" 作为产品概念名
- 旧 v5-v6 设计文档归档至 `documents/archive/`

### 📊 Stats

- **代码规模** / Code size: ~14,000 行 Python + ~2,000 行 JS
- **数据库表** / DB tables: 8 业务表 + 1 系统表
- **API 端点** / API endpoints: 22
- **工具数量** / Tools: 14
- **主动场景** / Proactive scenes: 9
- **主题** / Themes: 5
- **可执行文件** / Executable size: 176 MB
- **便携包** / Portable package: 82 MB

---

## [8.0.0][8.0.0] - 2026-07-15

> 引入伊塔人设（22 岁女 · 闷骚+病娇 · 四爱）+ 移除"主人"措辞
> Introduced Yita persona and removed "主人" wording

### ✨ Added

- 伊塔完整人设（v8.0 final）
- 累积情感阈值系统（忍耐 / 不安 / 渴望 / 温柔透支）
- 撤回机制（闷骚型特有表达真意的方式）
- 大五人格参数校准

### 🗑 Removed

- 移除所有 "主人" 措辞，改用 "你"
- 移除 "GPT-4 / Character.AI" 实际集成（仅作理论参考）

---

## [7.0.0][7.0.0] - 2026-07-15

> 多模型选型锁定 + 文档结构升级 v6.0 → v7.0
> Multi-model selection locked + document structure upgrade

### ✨ Added

- 5 个补充文档（PartA-PartE）
- v7.0 补充索引（§13），含 mermaid 图 + 章节表 + 核心伪代码 + 公式 + 阅读建议
- 核心约束：使用 Qwen2.5-72B（主）+ DeepSeek-V3（备）+ Gemini-2.0-Flash（专）

---

## [6.0.0][6.0.0] - 2026-07-16

> 系统设计文档 v6.0（12 章节 + 5 附录）
> System design document v6.0

### ✨ Added

- TL;DR 摘要
- 核心用户哲学规则
- 3 个时序图
- 情感引擎
- 多模态扩展
- 主题切换
- 数据备份 / 迁移
- 持续进化机制
- 反馈学习
- 故障自愈
- 测试策略

---

## 历史 / Legacy

* **v5.0**：单文件 Python QQBot（无桌面壳）
* **v1.0-v4.0**：早期原型（已归档）

---

[9.0.0]: #900---2026-07-16
[8.0.0]: #800---2026-07-15
[7.0.0]: #700---2026-07-15
[6.0.0]: #600---2026-07-16
