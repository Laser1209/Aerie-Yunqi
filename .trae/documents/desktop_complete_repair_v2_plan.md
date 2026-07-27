# Aerie 桌面端完整能力修复 - 接力实施计划（v2 更新版）

## 工作环境与信息存档约定

- **主工作目录**：`E:\Agent_reply-desktop-complete`（隔离工作树，分支 `codex/desktop-complete-repair`）
- **原主仓库**：`e:\Agent_reply`（不直接修改，仅作参考对比）
- **证据目录**：`E:\Aerie_QA_Evidence\2026-07-26_full-desktop-audit`
- **Python 环境**：`.venv`（主后端 Python 3.14）；`.venv-attachments`（附件解析 Python 3.12 独立环境）
- **⚡ 信息存档**：每一步操作的进展、发现、验证结果都必须存入 `work_progress/` 文件夹（Markdown 格式），防止对话历史压缩丢失信息。

---

## 当前进度盘点（2026-07-26）

### 隔离工作树中已完成（上一轮agent工作）

| 模块 | 状态 | 关键文件 |
|------|------|----------|
| 隔离工作树/证据目录 | ✅ 完成 | git worktree 创建完成 |
| 启动契约/统一身份/实例ID | ✅ 完成 | primary_identity.py, runtime_config.py, backend-health.js |
| PAD情绪/真实数据刷新/双冷启动 | ✅ 完成 | emotion_state_store.py, emotion-dashboard.js |
| 无限历史/长对话连续性 | ✅ 完成（159项测试通过） | conversation_continuity.py, conversation_repository.py |
| World 生命周期（Supervisor/Sidecar） | ✅ 完成 | plugin-supervisor.js, world-dashboard-host.js |
| QQ连接测试模式/安全边界 | ✅ 完成 | napcat_launcher.py, qq_client.py, napcat-panel.js |
| desire_engine数据目录隔离修复 | ✅ 完成 | desire_engine.py |
| 桌面附件API/状态机骨架 | ⚠️ 80% 完成 | desktop_attachments.py, attachment_worker_runtime.py |
| Electron审计框架 | ⚠️ 框架已搭，全量审计待执行 | desktop-audit.js |

### 本轮新发现/已就绪（无需重复实现）

| 模块 | 状态 | 位置 |
|------|------|------|
| 主动消息三通道投递（QQ/Desktop/System Notification） | ✅ 后端代码已完整 | companion.py _dispatch_push |
| PushEventEngine事件总线 | ✅ 已实现并在companion.start()启动 | push_event_engine.py |
| 图片服务（生成/理解/安全审核/幂等） | ✅ 已完整实现 | image_service.py ImageWorkflow |
| 附件图片上传（格式校验/去重/缩略图） | ✅ 已完整实现 | attachment_handler.py process_image_upload |
| 图片API端点 | ✅ 已完整实现 | api_server.py: /api/upload, /api/images/generate, /api/images/vision |
| 情绪感知打字节奏引擎 | ✅ 已完整实现 | message_pacing.py compute_interval() |

### 本轮新增（主目录已写，待同步到隔离工作树）

| 新增内容 | 文件 | 说明 |
|---------|------|------|
| **per-scene频控** | push_scheduler.py | PushPolicy新增scene_last_sent记录，同一场景默认最小间隔60分钟，跨天重置 |
| **MessageChunker语义分块器** | core/message_chunker.py（新文件） | 段落→句子→软分隔→连接词多层智能分割，ack/normal/complex/emotional分类，结合情绪分配打字延迟 |
| **功能开关启用** | config/settings.yaml | proactive_delivery_v2, image_assets_v1, conversation_model_v1等设为true |
| **work_progress/信息存档文件夹** | work_progress/ | 已在主目录创建，需同步到隔离树 |

### 上一轮中断点

修复_History.md最后记录：**"数据目录隔离复核又发现两处同类旧路径"**——桌面附件默认目录和启动问候标记仍可能回落到仓库相对 `data/`。

---

## 剩余待完成任务（按执行顺序）

### 关口 0：同步本轮新增修改 + 工作信息目录初始化 ⚡

**目标**：把主目录已做好的改进同步到隔离工作树，建立 work_progress 存档机制。

| 序号 | 任务 | 涉及文件 | 验收标准 |
|------|------|----------|----------|
| 0.1 | 在隔离工作树创建 `work_progress/` 文件夹 | E:\Agent_reply-desktop-complete\work_progress\ | 文件夹存在 |
| 0.2 | 把主目录的 `core/message_chunker.py` 复制到隔离工作树 | core/message_chunker.py | 文件存在且语法正确 |
| 0.3 | 把主目录的 per-scene 频控修改（scene_last_sent）同步到隔离树的 push_scheduler.py | core/push_scheduler.py | 与主目录逻辑一致 |
| 0.4 | 确认/更新隔离树 config/settings.yaml 功能开关（proactive_delivery_v2, image_assets_v1等为true） | config/settings.yaml | 关键开关已启用 |
| 0.5 | 在 work_progress/ 中创建起始进度文档 | work_progress/00_起始状态.md | 记录当前git状态、已完成项清单 |

### 关口 1：数据路径全隔离收尾（接上次中断点）

**目标**：确保所有运行时数据路径统一使用 `AERIE_DATA_DIR`，测试不污染仓库文件。

| 序号 | 任务 | 涉及文件 | 验收标准 |
|------|------|----------|----------|
| 1.1 | 修复桌面附件默认存储根路径使用统一数据目录 | desktop_attachments.py, paths.py | 隔离启动时不写入仓库 data/attachments/ |
| 1.2 | 修复启动问候标记（boot_greeting_last_sent.flag）路径 | companion.py | 问候标记写入 AERIE_DATA_DIR |
| 1.3 | 全面排查其他硬编码 `data/` 相对路径 | core/*.py, electron/*.js | grep "data/" 确认无遗漏硬编码 |
| 1.4 | 运行一轮隔离启动验证 data/desire_state.json 不再被污染 | 回归测试 | 该文件 git diff 为空 |
| 1.5 | 更新 work_progress 记录关口1结果 | work_progress/01_数据路径隔离.md | 存档验证证据 |

### 关口 2：MessageChunker 集成到流式响应（拟人化对话Phase1）

**目标**：把已创建的 message_chunker.py 接入聊天流式响应流水线，实现真人分段打字效果。

| 序号 | 任务 | 涉及文件 | 验收标准 |
|------|------|----------|----------|
| 2.1 | 分析现有聊天流式响应的发送入口（chat_request_worker/pipeline） | chat_request_worker.py, pipeline.py | 找到SSE/流式输出的消息发送点 |
| 2.2 | 在流式响应完成后（或流中）对完整回复调用 chunk_message() 分块 | chat_request_worker.py 或 companion.py | 消息被正确分割为语义块 |
| 2.3 | 新增SSE事件类型 `chunk` 用于分段发送，携带 delay_before 字段 | api_server.py / event_stream.py | 前端可接收分块和延迟信息 |
| 2.4 | 前端 chat.js 处理 chunk 事件：按 delay_before 等待后逐块追加消息 | electron/src/renderer/js/chat.js | 逐字/逐块显示效果，模拟真人打字分段 |
| 2.5 | 首块快速显示（ack块0.2s），后续块按情绪和长度动态延迟 | 前端+后端 | 短回复不分块，长回复自然分段 |
| 2.6 | 更新 work_progress 记录 | work_progress/02_拟人化分块集成.md | 存档集成说明和测试结果 |

### 关口 3：全量测试回归通过

**目标**：Python 全量测试 + Electron 单元测试全部绿灯。

| 序号 | 任务 | 验收标准 |
|------|------|----------|
| 3.1 | 在 .venv 中确认依赖安装完整并运行 Python 全量测试 | pytest tests/ -v 全部通过（目标≥697 passed，0 failed） |
| 3.2 | 为新增 message_chunker.py 写单元测试（分块逻辑、分类、延迟计算） | tests/test_message_chunker.py（新增）| 覆盖ack/normal/complex/emotional、短消息、段落分割等场景 |
| 3.3 | 修复关口0/1/2引入的新测试失败 | 所有 desktop_* 新增测试通过 |
| 3.4 | 运行 Electron 单元测试 | cd electron && npm test 全部通过（65+项） |
| 3.5 | 更新 work_progress 记录 | work_progress/03_全量测试回归.md | 存档测试结果和修复记录 |

### 关口 4：桌面附件独立工作进程验收

**目标**：附件解析链真实可用，Python 3.12 环境依赖完整。

| 序号 | 任务 | 涉及文件 | 验收标准 |
|------|------|----------|----------|
| 4.1 | 确认 .venv-attachments Python 3.12 环境依赖安装完成 | tools/attachment_worker/ | markitdown[all]、Pillow 等可导入 |
| 4.2 | 验证附件工作进程启动探针可返回能力清单 | attachment_worker_runtime.py | 启动后返回支持格式列表 |
| 4.3 | 用合成测试文件验证上传→排队→解析→展示全链路 | 前后端 | 状态正确从 queued→processing→ready |
| 4.4 | 验证附件安全检查（ZIP穿越、大文件、危险扩展名） | 针对性测试 | 恶意文件被隔离/拒绝 |
| 4.5 | 验证聊天气泡与数据聊天库复用同一附件组件 | chat.js, data-viewer.js | 重启后附件信息正确显示 |
| 4.6 | 更新 work_progress 记录 | work_progress/04_附件验收.md | 存档 |

### 关口 5：前端 World 与系统状态真实数据验证

| 序号 | 任务 | 验收标准 |
|------|------|----------|
| 5.1 | 验证 /api/stats/system 返回真实 CPU/内存/网络，字段命名兼容snake_case/camelCase | sampledAt时间戳真实，数值非随机 |
| 5.2 | 验证灵动岛不显示随机网络值，离线时显示"不可用" | dynamic-island.js |
| 5.3 | 验证 World 生命周期按钮真实生效，状态3秒内同步 | desired/actual/revision正确更新 |
| 5.4 | 验证 World 默认关闭（首次启动不自动启动Sidecar） | 全新数据目录启动后状态为disabled/stopped |
| 5.5 | 更新 work_progress 记录 | work_progress/05_World与系统状态.md |

### 关口 6：Electron 逐元素/逐字符全量审计（阶段7核心）

**目标**：162+ 静态控件 + 运行时控件 100% 有交互证据，无乱码/破损/遮挡。
**使用插件技能**：`trae-remote-official:build-web-apps:frontend-testing-debugging`

| 序号 | 任务 | 验收标准 |
|------|------|----------|
| 6.1 | 检查完善 desktop-audit.js，确保能枚举所有导航入口（11个）和主面板（10个） | 脚本可无人工干预启动Electron遍历所有tab |
| 6.2 | 逐页枚举所有可交互元素并记录定位器/角色/文本/状态/边界框 | 输出元素清单JSON到证据目录 |
| 6.3 | 对每个按钮执行click，验证有可见反馈（状态变化/消息/弹窗，控制台无报错） | 无"点了没反应"的静默控件 |
| 6.4 | 逐字符扫描所有可见文本，检测乱码/破损实体/零宽字符/截断/重叠 | 输出字符审计报告，0个严重问题 |
| 6.5 | 覆盖loading/empty/success/error/stale/disabled/filled所有状态 | 每个状态UI正常 |
| 6.6 | 验证窗口控制/抽屉/Office菜单/审批弹窗/附件队列/人设表单/灵动岛 | 截图证据齐全 |
| 6.7 | 保存截图/控制台/网络/元素清单到外部证据目录，生成SHA-256清单 | 不含敏感数据 |
| 6.8 | 更新 work_progress 记录 | work_progress/06_Electron审计.md |

### 关口 7：QQ/NapCat 连接测试（需人工扫码，可降级）

**前提**：用户在场可提供手机QQ扫码。若无法扫码，只跑单元合同。

| 序号 | 任务 | 验收标准 |
|------|------|----------|
| 7.1 | 设置 AERIE_QQ_CONNECTIVITY_TEST=1 启动 | 进入连接测试模式 |
| 7.2 | 测试启动/二维码刷新/扫码登录（提供5分钟窗口） | 扫码后状态connected |
| 7.3 | 验证心跳正常/断线重连可触发 | 日志有心跳记录 |
| 7.4 | 验证连接测试模式：不发消息/不读私聊/戳一戳撤回禁用 | 无消息发出，私聊被丢弃 |
| 7.5 | 测试停止NapCat进程树清理 | 子进程全部终止，端口释放 |
| 7.6 | 全程QQ号/token/路径脱敏 | 证据无明文敏感信息 |
| 7.7 | 更新 work_progress 记录 | work_progress/07_QQ连接测试.md |

### 关口 8：主动消息三通道端到端验证（P0最终验收）

**目标**：验证主动消息（事件触发+cron定时）三通道（QQ/桌面气泡/系统通知）真实工作。

| 序号 | 任务 | 验收标准 |
|------|------|----------|
| 8.1 | 验证 PushEventEngine 启动并绑定事件源（用户idle/情绪波动） | companion.start()后事件引擎运行 |
| 8.2 | 手动触发 idle_care 场景验证三通道投递 | 桌面气泡+系统通知出现，QQ在线则收到消息 |
| 8.3 | 验证 per-scene 频控生效：同一场景60分钟内不重复推送 | 第二次触发返回 scene_interval 拒绝 |
| 8.4 | 验证 quiet_period（免打扰时段）、max_per_day（每日上限）生效 | 策略正确拦截 |
| 8.5 | 更新 work_progress 记录 | work_progress/08_主动消息验证.md |

### 关口 9：文档治理与最终提交

| 序号 | 任务 |
|------|------|
| 9.1 | 更新 work_progress/09_最终总结.md |
| 9.2 | 关闭所有测试进程，确认无残留PID/端口/文件锁 |
| 9.3 | 验证正式数据库未被污染（测试使用独立AERIE_DATA_DIR） |
| 9.4 | 验证仓库 data/ 目录无测试副作用 |
| 9.5 | 严格按白名单暂存文件（禁止提交Spotlight/、core/brain.py、data/desire_state.json、.venv*、node_modules、证据目录） |
| 9.6 | 生成规范Git commit message（type(scope): subject 中文格式） |
| 9.7 | 普通push到 origin/codex/desktop-complete-repair（不force） |

---

## 文件变更白名单（预计提交范围）

### Python 后端（新增+修改）
- `core/message_chunker.py`（**本轮新增** - 语义分块器）
- `core/primary_identity.py`（新增）
- `core/runtime_config.py`（新增）
- `core/conversation_continuity.py`（新增）
- `core/desktop_attachments.py`（新增）
- `core/attachment_worker_runtime.py`（新增）
- `core/push_scheduler.py`（**本轮修改** - 加per-scene频控）
- `core/api_server.py`（修改：加chunk事件）
- `core/companion.py`（修改：问候路径+三通道+chunker集成）
- `core/conversation_repository.py`（修改）
- `core/database.py`（修改）
- `core/desire_engine.py`（修改）
- `core/emotion_state_store.py`（修改）
- `core/feature_flags.py`（修改）
- `core/napcat_launcher.py`（修改）
- `core/pipeline.py`（修改：chunker集成点）
- `core/paths.py`（修改：附件路径）
- `config/settings.yaml`（**本轮修改** - 启用开关）
- 其他上一轮已修改文件...

### Electron 前端（新增+修改）
- `electron/src/backend-health.js`（新增）
- `electron/src/renderer/js/chat.js`（**本轮修改** - 处理chunk事件）
- `electron/src/preload.js`（修改）
- `electron/src/main.js`（修改）
- 其他上一轮已修改文件...

### 测试
- `tests/test_message_chunker.py`（**本轮新增** - chunker单元测试）
- 其他上一轮已新增测试文件...

### 明确排除（不提交）
- `Spotlight/` 目录（用户暂存改动）
- `core/brain.py`（用户未提交改动，本批不修改）
- `data/desire_state.json`（测试副作用，恢复/不纳入）
- `.venv/`、`.venv-attachments/`、`node_modules/`
- `E:\Aerie_QA_Evidence\`（外部证据）
- 真实数据库、QQ聊天记录、密钥token
- `work_progress/` 文件夹（本地工作记录，不提交）

---

## 关键原则与约束

1. **每步存档**：work_progress/ 中每个关口完成后写一个 Markdown 记录，包含做了什么、修改了哪些文件、验证结果、遇到的问题。
2. **使用frontend-testing-debugging技能**：关口6 Electron审计使用该技能流程做真实窗口验证。
3. **不修改core/brain.py**：本批明确不改动该文件，拟人化/连续性通过外围服务接入。
4. **数据隔离优先**：关口1不通过不继续后续测试，避免污染仓库。
5. **真实模型最多10次**：仅用于附件/长对话/主动消息哨兵验证，其他测试用mock/synth数据。
6. **QQ不强制扫码**：关口7若用户无法扫码，降级为单元合同验证。
7. **普通push，不用force**：最终提交用普通推送。
8. **工作目录始终是隔离树**：所有代码修改在 `E:\Agent_reply-desktop-complete` 进行。
