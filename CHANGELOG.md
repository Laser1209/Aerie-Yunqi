# Changelog · Aerie · 云栖

All notable changes to this project will be documented in this file.

本文件记录本项目的所有重要变更。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

---

## [Unreleased] - 2026-07-21

> **文档同步 / Documentation Sync**
> 根据当前仓库结构、运行入口、Spotlight 官网、World Service 与 Phase 测试状态，同步根文档说明。

### 📝 Documentation / 文档
- **README.md 当前状态更新**：补充 Electron 桌面端、Python 后端、NapCat、Spotlight 官网、World Service、Phase 0-15 测试与发布资源状态
- **线上官网地址同步**：在当前状态、快速开始、发布资源与文档索引中补充 `https://laser1209.github.io/Aerie_Spotlight/`
- **运行说明校准**：按当前源码结构整理 Python 后端、NapCat、Electron 与 Spotlight 的启动流程
- **验证命令校准**：保留 `pytest tests`、重点 Phase 测试、Electron `check:all` 与 Spotlight 构建命令，移除未在 `electron/package.json` 暴露的 `npm test` 指引
- **项目结构更新**：新增 `world_service/`、`Spotlight/`、`docs/`、`.trae/documents/` 等当前实际目录说明
- **配置与排障更新**：补充配置热加载、运行数据、日志、官网构建与发布资源说明

### Fixed / 修复
- **灵动岛原生置顶**：Windows 使用保留 `WS_EX_TOPMOST` 的窗口层级，并在主窗口显示、聚焦、最大化、还原和全屏切换后重新确认置顶
- **窗口生命周期**：二次启动统一唤回现有窗口；只有托盘或可见灵动岛可恢复窗口时才执行“关闭即隐藏”
- **导航时序**：主窗口加载完成前缓存 tab/日报导航，修正灵动岛日报入口与通知日历入口的目标协议
- **打包托盘图标**：打包态改用实际进入 `app.asar` 的 `builder/icon.ico`
- **API 路由与日报问候**：限制 self-evolve 详情路由为整数，并将日报日期传入问候生成合同
- **渲染安全**：恢复 Electron 默认 renderer sandbox，保持 `contextIsolation` 与禁用 `nodeIntegration`

### Performance / 性能
- **首屏初始化**：隐藏面板改为首次进入时初始化，全局控制器延后到首帧之后启动
- **日报合成**：收敛为单层背景模糊，移除嵌套 filter、位移动画和会触发 sibling layer 丢失的 hover transform
- **灵动岛空闲负载**：移除常驻粒子循环；媒体状态查询改为单飞、带超时的自适应轮询，隐藏时暂停

### Tests / 测试
- 新增日报 compositor、renderer 性能、窗口生命周期、导航队列、媒体轮询与原生置顶合同测试
- 新增 self-evolve 静态路由与日报日期传递回归测试

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

## [9.0.0] - 2026-07-16

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

## [8.0.0] - 2026-07-15

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

## [7.0.0] - 2026-07-15

> 多模型选型锁定 + 文档结构升级 v6.0 → v7.0
> Multi-model selection locked + document structure upgrade

### ✨ Added

- 5 个补充文档（PartA-PartE）
- v7.0 补充索引（§13），含 mermaid 图 + 章节表 + 核心伪代码 + 公式 + 阅读建议
- 核心约束：使用 Qwen2.5-72B（主）+ DeepSeek-V3（备）+ Gemini-2.0-Flash（专）

---

## [6.0.0] - 2026-07-16

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
