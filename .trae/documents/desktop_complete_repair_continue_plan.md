# Aerie 桌面端完整能力修复 - 接力实施计划

## 工作环境

- **隔离工作树**：`E:\Agent_reply-desktop-complete`
- **目标分支**：`codex/desktop-complete-repair`
- **证据目录**：`E:\Aerie_QA_Evidence\2026-07-26_full-desktop-audit`（需确认存在）
- **Python 环境**：`.venv`（项目根目录，主后端 Python 3.14）；`.venv-attachments`（附件解析 Python 3.12 独立环境）

---

## 已完成进度总结

基于 [修复_History.md](file:///e:/Agent_reply/documents/%E4%BF%AE%E5%A4%8D_History.md) 的记录，以下模块已落地：

| 阶段 | 模块 | 状态 | 关键文件 |
|------|------|------|----------|
| 1 | 隔离工作树/证据目录 | ✅ 完成 | git worktree, E:\Aerie_QA_Evidence |
| 2 | 启动契约/统一身份 | ✅ 完成 | [primary_identity.py](file:///E:/Agent_reply-desktop-complete/core/primary_identity.py), [runtime_config.py](file:///E:/Agent_reply-desktop-complete/core/runtime_config.py), [backend-health.js](file:///E:/Agent_reply-desktop-complete/electron/src/backend-health.js) |
| 3 | PAD/真实数据刷新 | ✅ 完成（双冷启动通过） | [emotion_state_store.py](file:///E:/Agent_reply-desktop-complete/core/emotion_state_store.py), [emotion-dashboard.js](file:///E:/Agent_reply-desktop-complete/electron/src/renderer/js/emotion-dashboard.js) |
| 4 | 无限历史/长对话连续性 | ✅ 完成（159项测试通过） | [conversation_continuity.py](file:///E:/Agent_reply-desktop-complete/core/conversation_continuity.py), [conversation_repository.py](file:///E:/Agent_reply-desktop-complete/core/conversation_repository.py) |
| 5 | 桌面附件架构 | ⚠️ 80% 完成（API/状态机完成，3.12环境依赖待验证） | [desktop_attachments.py](file:///E:/Agent_reply-desktop-complete/core/desktop_attachments.py), [attachment_worker_runtime.py](file:///E:/Agent_reply-desktop-complete/core/attachment_worker_runtime.py) |
| 6 | World 生命周期 | ✅ 完成 | [plugin-supervisor.js](file:///E:/Agent_reply-desktop-complete/electron/src/plugin-supervisor.js), [world-dashboard-host.js](file:///E:/Agent_reply-desktop-complete/electron/src/world-dashboard-host.js), [world_simulation.py](file:///E:/Agent_reply-desktop-complete/core/world_simulation.py) |
| - | QQ 连接安全边界 | ✅ 完成 | [napcat_launcher.py](file:///E:/Agent_reply-desktop-complete/core/napcat_launcher.py), [qq_client.py](file:///E:/Agent_reply-desktop-complete/communication/qq_client.py), [napcat-panel.js](file:///E:/Agent_reply-desktop-complete/electron/src/renderer/js/napcat-panel.js) |
| - | 数据目录隔离（desire_engine） | ✅ 已修复 | [desire_engine.py](file:///E:/Agent_reply-desktop-complete/core/desire_engine.py) |
| - | Electron 审计框架 | ⚠️ 框架已搭，全量审计待执行 | [desktop-audit.js](file:///E:/Agent_reply-desktop-complete/electron/tests/e2e/desktop-audit.js) |

**中断点记录**：最后正在处理"数据目录隔离复核又发现两处同类旧路径"——桌面附件默认目录和启动问候标记仍可能回落到仓库相对 `data/`。

---

## 剩余待完成任务清单

### 关口 1：代码收尾与数据路径全隔离（预计最先完成）

**目标**：确保所有运行时数据路径统一使用 `AERIE_DATA_DIR`，测试不污染仓库文件。

| 序号 | 任务 | 涉及文件 | 验收标准 |
|------|------|----------|----------|
| 1.1 | 修复桌面附件默认存储根路径使用统一数据目录 | [desktop_attachments.py](file:///E:/Agent_reply-desktop-complete/core/desktop_attachments.py), [paths.py](file:///E:/Agent_reply-desktop-complete/core/paths.py) | 隔离启动时不写入仓库 `data/attachments/` |
| 1.2 | 修复启动问候标记（boot_greeting_last_sent.flag）路径 | [companion.py](file:///E:/Agent_reply-desktop-complete/core/companion.py) 或启动逻辑 | 问候标记写入 `AERIE_DATA_DIR` |
| 1.3 | 全面排查其他可能硬编码 `data/` 相对路径的地方 | core/*.py, electron/*.js | `git status` 显示仓库内 `data/` 目录在测试后保持干净 |
| 1.4 | 验证 data/desire_state.json 不再被测试污染 | 运行一轮隔离启动后检查 | 该文件 `git diff` 为空 |

### 关口 2：全量测试回归通过

**目标**：Python 全量测试 + Electron 单元测试全部绿灯。

| 序号 | 任务 | 验收标准 |
|------|------|----------|
| 2.1 | 在 `.venv` 中确认依赖安装完整并运行 Python 全量测试 | `pytest tests/ -v` 全部通过（目标 ≥ 650 passed，0 failed） |
| 2.2 | 修复关口1修复后可能引入的新测试失败 | 所有 desktop_* 新增测试通过 |
| 2.3 | 运行 Electron 单元测试 | `npm test` 在 electron/ 目录全部通过 |
| 2.4 | 修复 Electron 测试中的兼容问题（若有） | 65+ 项 Electron 单元测试全部绿灯 |

### 关口 3：桌面附件独立工作进程验收

**目标**：附件解析链真实可用，Python 3.12 环境依赖完整。

| 序号 | 任务 | 涉及文件 | 验收标准 |
|------|------|----------|----------|
| 3.1 | 确认 `.venv-attachments` Python 3.12 环境存在且依赖安装完成 | `tools/attachment_worker/` 下的依赖清单 | 环境存在，`markitdown[all]`、`python-docx`、`Pillow` 等可导入 |
| 3.2 | 验证附件工作进程启动探针可正常返回能力清单 | [attachment_worker_runtime.py](file:///E:/Agent_reply-desktop-complete/core/attachment_worker_runtime.py) | 启动后通过 IPC/HTTP 返回支持的格式列表 |
| 3.3 | 使用合成测试文件（txt、md、csv、png、zip、docx）验证附件上传→排队→解析→展示完整链路 | 前端 + 后端 | 附件状态正确从 queued→processing→ready，失败项有明确原因 |
| 3.4 | 验证附件安全检查（ZIP 路径穿越、大文件限制、危险扩展名隔离） | 新增针对性测试 | 恶意文件被标记为 quarantined/failed，不会执行或逃逸 |
| 3.5 | 验证聊天气泡与数据聊天库复用同一附件组件 | [chat.js](file:///E:/Agent_reply-desktop-complete/electron/src/renderer/js/chat.js), [data-viewer.js](file:///E:/Agent_reply-desktop-complete/electron/src/renderer/js/data-viewer.js) | 重启后附件名称、大小、类型、状态、操作按钮正确显示 |

### 关口 4：前端 World 与 系统状态真实数据验证

**目标**：World 面板、系统统计、灵动岛显示真实数据而非随机/占位值。

| 序号 | 任务 | 验收标准 |
|------|------|----------|
| 4.1 | 验证 `/api/stats/system` 返回真实 CPU、内存、网络速率，且字段命名统一（含 snake_case 和 camelCase 兼容） | 接口返回 sampledAt 时间戳，数值为真实采样 |
| 4.2 | 验证灵动岛系统状态不显示随机网络值，离线时显示"不可用" | [dynamic-island.js](file:///E:/Agent_reply-desktop-complete/electron/src/renderer/js/dynamic-island.js) |
| 4.3 | 验证 World 生命周期按钮（enable/disable/start/stop/pause/resume/restart）真实生效且状态 3 秒内同步到 UI | 点击按钮后 desired/actual/revision/last-tick 正确更新 |
| 4.4 | 验证 World 默认关闭（首次启动不自动启动 Sidecar） | 全新数据目录启动后 World 状态为 disabled/stopped |

### 关口 5：Electron 逐元素/逐字符全量审计（阶段7核心）

**目标**：162+ 静态控件 + 运行时控件 100% 有交互证据，无乱码/破损/遮挡。

| 序号 | 任务 | 验收标准 |
|------|------|----------|
| 5.1 | 检查并完善 [desktop-audit.js](file:///E:/Agent_reply-desktop-complete/electron/tests/e2e/desktop-audit.js) 脚本，确保能枚举所有导航入口（11个）和主面板（10个） | 脚本可无人工干预启动 Electron 并遍历所有 tab |
| 5.2 | 逐页枚举所有可交互元素（按钮、输入框、下拉、开关、标签页）并记录定位器/角色/文本/状态/边界框 | 输出元素清单 JSON 到证据目录 |
| 5.3 | 对每个按钮执行 click 操作，验证有可见反馈（状态变化、消息、弹窗、控制台无报错） | 不允许"点了没反应"的静默控件 |
| 5.4 | 逐字符扫描所有可见文本节点、placeholder、title、aria-label、选项文本，检测：<br>- 替换字符（�）<br>- 乱码（如之前健康接口的"塅呉〺਍"）<br>- 破损 HTML 实体<br>- 异常零宽字符<br>- 截断/重叠/错误换行 | 输出字符审计报告，0个严重问题 |
| 5.5 | 覆盖所有状态：loading、empty、success、error、stale、disabled、filled | 每个状态下 UI 正常 |
| 5.6 | 验证窗口控制（最小化/最大化/关闭）、抽屉、Office 菜单、审批弹窗、附件队列、人设动态表单、灵动岛窗口 | 截图证据齐全 |
| 5.7 | 审计结束后保存截图、控制台日志、网络请求记录、元素清单到外部证据目录 | SHA-256 清单生成，不包含敏感数据 |

### 关口 6：QQ/NapCat 连接测试（阶段8，需人工参与扫码）

**目标**：验证 QQ 连接流程在"连接测试模式"下安全工作，不发送消息。

| 序号 | 任务 | 前提 | 验收标准 |
|------|------|------|----------|
| 6.1 | 设置 `AERIE_QQ_CONNECTIVITY_TEST=1` 环境变量启动 | 用户在场可扫码 | 进入连接测试模式 |
| 6.2 | 测试启动 NapCat、二维码刷新、扫码登录流程（提供5分钟窗口） | 需要手机QQ扫码 | 扫码后状态变为 connected，日志无报错 |
| 6.3 | 验证 connected 心跳正常、断线重连可触发 | 登录成功后 | 心跳持续，重连逻辑有日志 |
| 6.4 | 验证连接测试模式下：<br>- 不发送任何消息（包括启动问候）<br>- 不读取/响应私聊消息<br>- 戳一戳/撤回功能被禁用 | 登录后等待观察 | 无消息发出，私聊事件被丢弃 |
| 6.5 | 测试停止 NapCat 进程树清理 | 点击停止 | NapCat 子进程全部终止，端口释放 |
| 6.6 | 全程对 QQ 号、token、路径脱敏 | 全程 | 证据中无明文 QQ 号或 token |
| 6.7 | 恢复初始状态（若 QQ 未登录则跳过真实扫码，只做单元合同验证） | 测试结束 | 无残留 NapCat 进程 |

**注意**：若用户无法提供扫码条件，此关口可只跑单元合同测试（已通过），真实连接留作人工验收项。

### 关口 7：文档治理与风险登记（阶段9前半段）

| 序号 | 任务 | 文件 |
|------|------|------|
| 7.1 | 更新 ADR-P2-009/010/011 状态为 Accepted（World 启停纳入前端） | [二期升级/02_二期架构决策记录.md](file:///e:/Agent_reply/documents/%E4%BA%8C%E6%9C%9F%E5%8D%87%E7%BA%A7/02_%E4%BA%8C%E6%9C%9F%E6%9E%B6%E6%9E%84%E5%86%B3%E7%AD%96%E8%AE%B0%E5%BD%95.md) |
| 7.2 | 更新需求追踪矩阵，标记各需求项实现状态 | [二期升级/01_二期需求追踪矩阵.md](file:///e:/Agent_reply/documents/%E4%BA%8C%E6%9C%9F%E5%8D%87%E7%BA%A7/01_%E4%BA%8C%E6%9C%9F%E9%9C%80%E6%B1%82%E8%BF%BD%E8%B8%AA%E7%9F%A9%E9%98%B5.md) |
| 7.3 | 更新风险登记册，关闭已修复风险，记录剩余已知风险 | [二期升级/03_二期风险登记册.md](file:///e:/Agent_reply/documents/%E4%BA%8C%E6%9C%9F%E5%8D%87%E7%BA%A7/03_%E4%BA%8C%E6%9C%9F%E9%A3%8E%E9%99%A9%E7%99%BB%E8%AE%B0%E5%86%8C.md) |
| 7.4 | 更新测试证据索引，链接本次 QA 证据 | [二期升级/04_二期测试与证据索引.md](file:///e:/Agent_reply/documents/%E4%BA%8C%E6%9C%9F%E5%8D%87%E7%BA%A7/04_%E4%BA%8C%E6%9C%9F%E6%B5%8B%E8%AF%95%E4%B8%8E%E8%AF%81%E6%8D%AE%E7%B4%A2%E5%BC%95.md) |
| 7.5 | 更新任务编排状态 | [二期升级/07_二期任务编排.md](file:///e:/Agent_reply/documents/%E4%BA%8C%E6%9C%9F%E5%8D%87%E7%BA%A7/07_%E4%BA%8C%E6%9C%9F%E4%BB%BB%E5%8A%A1%E7%BC%96%E6%8E%92.md) |

### 关口 8：无损停止、提交与推送（阶段9后半段）

| 序号 | 任务 | 验收标准 |
|------|------|----------|
| 8.1 | 关闭所有本批启动的测试进程（Python、Electron、NapCat、附件worker） | `tasklist` 确认无残留 PID，无残留端口占用 |
| 8.2 | 验证正式数据库未被测试数据污染 | 隔离测试使用独立 AERIE_DATA_DIR |
| 8.3 | 恢复 QQ/World 初始状态配置 | 配置文件回到默认值 |
| 8.4 | 验证仓库 `data/` 目录无测试副作用 | `git status data/` 显示干净 |
| 8.5 | 严格按白名单暂存文件，禁止提交：Spotlight/、mobile/Android/、core/brain.py（用户未提交改动）、data/desire_state.json、.venv/、.venv-attachments/、node_modules/、外部证据目录 | 暂存文件清单经核对 |
| 8.6 | 生成符合规范的 Git commit message（中文、type/scope/subject） | 格式正确 |
| 8.7 | 普通 push 到 `origin/codex/desktop-complete-repair`，不使用 force | 推送成功，无冲突 |

---

## 文件白名单（预计提交范围）

### Python 后端
- `core/primary_identity.py`（新增）
- `core/runtime_config.py`（新增）
- `core/conversation_continuity.py`（新增）
- `core/desktop_attachments.py`（新增）
- `core/attachment_worker_runtime.py`（新增）
- `core/api_server.py`（修改）
- `core/companion.py`（修改）
- `core/conversation_repository.py`（修改）
- `core/database.py`（修改）
- `core/desire_engine.py`（修改）
- `core/emotion_state_store.py`（修改）
- `core/feature_flags.py`（修改）
- `core/identity/resolver.py`（修改）
- `core/migrations/__init__.py`（修改）
- `core/napcat_launcher.py`（修改）
- `core/pipeline.py`（修改）
- `core/paths.py`（修改，如需要）
- `core/world_adapters/remote.py`（修改）
- `core/world_port.py`（修改）
- `core/world_simulation.py`（修改）
- `communication/qq_client.py`（修改）
- `config/settings.yaml`（修改：默认启用3个开关）
- `main.py`（修改）
- `world_service/main.py`（修改）
- `world_service/storage/sqlite_store.py`（修改）

### Electron 前端
- `electron/src/main.js`（修改）
- `electron/src/preload.js`（修改）
- `electron/src/plugin-supervisor.js`（修改）
- `electron/src/backend-health.js`（新增）
- `electron/src/world-dashboard-host.js`（修改）
- `electron/src/capability-broker.js`（修改，如有）
- `electron/src/renderer/index.html`（修改）
- `electron/src/renderer/js/chat.js`（修改）
- `electron/src/renderer/js/chat-uploader.js`（修改）
- `electron/src/renderer/js/calendar-panel.js`（修改）
- `electron/src/renderer/js/data-viewer.js`（修改）
- `electron/src/renderer/js/dynamic-island.js`（修改）
- `electron/src/renderer/js/emotion-dashboard.js`（修改）
- `electron/src/renderer/js/emotion-history.js`（修改）
- `electron/src/renderer/js/napcat-panel.js`（修改）
- `electron/src/renderer/js/world-dashboard.js`（修改）
- `electron/src/renderer/styles/main.css`（修改）
- `electron/src/renderer/styles/world-dashboard.css`（修改）
- `electron/package.json`（修改：新增 playwright-core 等依赖）
- `electron/package-lock.json`（修改）

### 测试
- `tests/test_primary_identity.py`（新增）
- `tests/test_desktop_attachments.py`（新增）
- `tests/test_desktop_attachment_offline_acceptance.py`（新增）
- `tests/test_desktop_chat_continuity.py`（新增）
- `tests/test_desktop_chat_continuity_acceptance.py`（新增）
- `tests/test_desktop_shared_api_contract.py`（新增）
- `tests/test_emotion_state_freshness.py`（新增）
- `tests/test_continuity_pipeline_integration.py`（新增）
- `tests/test_napcat_launcher_lifecycle.py`（新增）
- `tests/test_qq_connectivity_mode.py`（新增）
- `tests/test_world_runtime_lifecycle.py`（新增）
- `tests/test_companion_data_path.py`（新增）
- `tests/test_desire_engine_data_path.py`（新增）
- `tests/test_desktop_qa_index.py`（新增）
- `tests/test_api.py`（修改）
- `tests/test_phase2_identity.py`（修改）
- `tests/test_phase4_chat_request_service.py`（修改）
- `tests/test_phase15_world_dashboard_api.py`（修改）
- `electron/tests/desktop-audit-script.test.js`（新增）
- `electron/tests/emotion-calendar-renderer.test.js`（新增）
- `electron/tests/napcat-panel.test.js`（新增）
- `electron/tests/plugin-supervisor-lifecycle.test.js`（新增）
- `electron/tests/system-status.test.js`（新增）
- `electron/tests/e2e/README.md`（新增）
- `electron/tests/e2e/WORLD_LIFECYCLE.md`（新增）
- `electron/tests/e2e/desktop-audit.js`（新增）
- `electron/tests/e2e/world-lifecycle.js`（新增）
- `electron/tests/chat-request-queue.test.js`（修改）
- `tools/generate_desktop_qa_index.py`（新增）
- `tools/attachment_worker/`（新增目录）
- `.gitignore`（修改：忽略 .venv-attachments 等）

### 明确排除（不提交）
- `Spotlight/` 目录（用户已有暂存改动，不在本批范围）
- `mobile/` 或 Android 相关文件（不存在于本工作树，继续保持）
- `core/brain.py`（用户未提交改动，本批不修改）
- `data/desire_state.json`（测试副作用，已恢复/不纳入）
- `.venv/`、`.venv-attachments/`、`node_modules/`（虚拟环境和依赖）
- `E:\Aerie_QA_Evidence\`（外部证据目录）
- 任何真实数据库、QQ 聊天记录、密钥 token

---

## 风险与注意事项

1. **Python 版本问题**：附件工作进程需要 Python 3.12，但系统 `python` 命令可能指向 3.14。需确认 `.venv-attachments` 使用正确的 3.12 可执行文件创建。

2. **Electron 审计阻塞**：Playwright 驱动真实 Electron 需要窗口处于前台，审计期间不能有其他操作遮挡窗口。

3. **QQ 扫码依赖人工**：关口 6 需要用户在场用手机 QQ 扫码，若无人在场可降级为只跑单元合同，真实连接测试标记为"待人工验收"。

4. **数据隔离验证必须在最前**：关口 1 不通过，后续所有测试都可能污染仓库数据，必须先确保路径全部正确。

5. **不修改 core/brain.py**：计划明确规定本批不改动该文件，连续性/上下文等功能通过外围服务接入。

6. **真实模型调用限制**：最多 10 次真实模型调用，仅用于附件/长对话哨兵验证，其他测试全部使用 mock/synth 数据。

---

## 执行顺序（工作流）

1. **切换到隔离工作树**：`E:\Agent_reply-desktop-complete`
2. **关口 1**：数据路径全隔离（最快完成，先做）
3. **关口 2**：全量 Python + Electron 测试回归绿灯
4. **关口 3**：附件独立环境与全链验收
5. **关口 4**：World/系统状态真实数据验证
6. **关口 5**：Electron 逐元素/逐字符全量审计（耗时最长）
7. **关口 6**：QQ 真实连接测试（需要用户配合）
8. **关口 7**：文档治理更新
9. **关口 8**：无损停止、Git 白名单提交、普通推送
