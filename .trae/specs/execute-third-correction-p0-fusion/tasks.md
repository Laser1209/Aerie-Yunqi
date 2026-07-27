# Tasks · Aerie 第三次修正计划 P0 融合闭环

> 本任务列表用于执行 `execute-third-correction-p0-fusion`。无依赖任务必须优先交给 Sub-Agent 并行处理；每个阶段进入实现前必须完成启动审计，完成后必须完成验收审计。

## 阶段 1 · 信息收集与 Obsidian 知识库

- [x] Task 1.1: 研读参考文档并生成当前状态摘要
  - [x] SubTask 1.1.1: 汇总桌面完整能力修复计划中的已完成修复、审计标准、边界与遗留项
  - [x] SubTask 1.1.2: 汇总修复历史中的重复问题、已验证解决方案、未闭环风险和测试副作用
  - [x] SubTask 1.1.3: 汇总 Echo 情绪价值调研中的功能点、体验要求、产品证据与待验证边界
  - [x] SubTask 1.1.4: 汇总 Echo-Pyisland-Aerie 融合方案中的架构、模块关系、数据协议和优先级
  - 证据：[09_当前状态.md](../../../Aerie_Obsidian_Vault/09_当前状态.md)、[00_首页.md](../../../Aerie_Obsidian_Vault/00_首页.md)

- [x] Task 1.2: 创建独立 Obsidian Vault 信息总览知识库
  - [x] SubTask 1.2.1: 创建 Vault 根目录和首页索引笔记
  - [x] SubTask 1.2.2: 创建模块笔记：核心功能模块、交互模块、数据处理模块、World、附件、视觉、知识库、桌面触达
  - [x] SubTask 1.2.3: 创建技术笔记：Electron、Python 后端、SQLite/向量库、附件 worker、VLM/OCR、World sidecar、安全审计
  - [x] SubTask 1.2.4: 创建依赖笔记：内部模块依赖、外部模型/工具依赖、Pyisland/eIsland helper、QQ/NapCat、向量库候选
  - [x] SubTask 1.2.5: 建立双向链接回路，确保每个核心概念至少链接实现、依赖、验证和风险
  - 证据：[00_首页.md](../../../Aerie_Obsidian_Vault/00_首页.md)、[AttachmentEnvelope.md](../../../Aerie_Obsidian_Vault/modules/AttachmentEnvelope.md)、[ImageObservation.md](../../../Aerie_Obsidian_Vault/modules/ImageObservation.md)、[VisualIntentRouter.md](../../../Aerie_Obsidian_Vault/modules/VisualIntentRouter.md)、[DesktopSurfaceAdapter.md](../../../Aerie_Obsidian_Vault/modules/DesktopSurfaceAdapter.md)、[KnowledgeBase.md](../../../Aerie_Obsidian_Vault/modules/KnowledgeBase.md)

- [x] Task 1.3: 建立功能点与技术方案矩阵
  - [x] SubTask 1.3.1: 将 Echo 情绪价值功能映射到 Aerie 当前模块与待修复模块
  - [x] SubTask 1.3.2: 将 Pyisland/eIsland 桌面触达能力映射到 Electron/动态岛/OfficeContext
  - [x] SubTask 1.3.3: 将 P0 修复项映射到代码文件、测试入口、审计证据和交付物
  - 证据：[Function-To-Implementation.md](../../../Aerie_Obsidian_Vault/matrices/Function-To-Implementation.md)

- [x] Task 1.4: 建立知识库更新机制
  - [x] SubTask 1.4.1: 定义新增发现写入对应 Obsidian 笔记的规则
  - [x] SubTask 1.4.2: 定义计划、审计、验证、决策与知识库首页的互链规则
  - [x] SubTask 1.4.3: 记录独立 Vault 与仓库文档之间的同步边界
  - 证据：[03_第三次修正计划知识库更新机制.md](../../../documents/第三次修正计划/03_第三次修正计划知识库更新机制.md)

## 阶段 2 · 计划、决策与审计门禁体系

- [x] Task 2.1: 输出第三次修正计划文档
  - [x] SubTask 2.1.1: 编写计划版本、制定日期、负责人、变更记录
  - [x] SubTask 2.1.2: 拆分不超过四个主要阶段并写明目标、任务、资源和交付物
  - [x] SubTask 2.1.3: 为每个模块制定量化验证标准
  - [x] SubTask 2.1.4: 在计划文档与 Obsidian 知识库间建立双向链接
  - 证据：[01_第三次修正计划.md](../../../documents/第三次修正计划/01_第三次修正计划.md)、[00_首页.md](../../../Aerie_Obsidian_Vault/00_首页.md)、[08_互链地图.md](../../../Aerie_Obsidian_Vault/08_互链地图.md)

- [x] Task 2.2: 创建决策记录文档
  - [x] SubTask 2.2.1: 记录已确认决策：P0 闭环优先、独立 Vault、专用向量库、阶段门禁确认
  - [x] SubTask 2.2.2: 为后续待确认事项预留决策模板
  - [x] SubTask 2.2.3: 标记需要再次确认的风险：真实模型调用、QQ扫码、外部向量库依赖、Pyisland helper 直接移植
  - 证据：[02_第三次修正计划决策记录.md](../../../documents/第三次修正计划/02_第三次修正计划决策记录.md)

- [x] Task 2.3: 创建阶段启动审计与验收审计模板
  - [x] SubTask 2.3.1: 启动审计包含任务覆盖、技术可行性、资源配置、风险点和结论
  - [x] SubTask 2.3.2: 验收审计包含代码质量、运行时调试、安全审计、Electron体验和验证证据
  - [x] SubTask 2.3.3: 为四个阶段分别创建审计记录文件
  - 证据：[阶段启动审计模板.md](./阶段启动审计模板.md)、[阶段验收审计模板.md](./阶段验收审计模板.md)、[Phase1-启动审计记录.md](./Phase1-启动审计记录.md)、[Phase1-验收审计记录.md](./Phase1-验收审计记录.md)、[Phase2-启动审计记录.md](./Phase2-启动审计记录.md)、[Phase2-验收审计记录.md](./Phase2-验收审计记录.md)、[Phase3-启动审计记录.md](./Phase3-启动审计记录.md)、[Phase3-验收审计记录.md](./Phase3-验收审计记录.md)、[Phase4-启动审计记录.md](./Phase4-启动审计记录.md)、[Phase4-验收审计记录.md](./Phase4-验收审计记录.md)

- [x] Task 2.4: 创建累积验证报告框架
  - [x] SubTask 2.4.1: 定义模块 A、A+B、A+B+C 的累积验证记录格式
  - [x] SubTask 2.4.2: 定义回退预防问题报告格式
  - [x] SubTask 2.4.3: 定义测试用例、测试数据、预期结果、实际结果和证据路径格式
  - 证据：[累积验证报告模板.md](./累积验证报告模板.md)

## 阶段 3 · P0 功能修复与融合闭环实现

- [x] Task 3.1: 修复 Electron UTF-8 chunk 解码
  - [x] SubTask 3.1.1: 定位 HTTP JSON 和 SSE 解码点
  - [x] SubTask 3.1.2: 将 JSON 响应改为 Buffer 合并后统一 UTF-8 解码
  - [x] SubTask 3.1.3: 将 SSE 流改为 StringDecoder 或等效安全解码
  - [x] SubTask 3.1.4: 增加跨 chunk 中文 JSON/SSE 回归测试
  - 证据：[main.js](../../../electron/src/main.js)、[sse-bridge.test.js](../../../electron/tests/sse-bridge.test.js)、命令 `node --test tests/sse-bridge.test.js tests/system-status.test.js` 通过 11/11

- [x] Task 3.2: 统一附件 Artifact 管线
  - [x] SubTask 3.2.1: 梳理旧 attachment_handler、新 desktop_attachments 与 worker 的职责边界
  - [x] SubTask 3.2.2: 定义 AttachmentEnvelope、DocumentArtifact、ImageObservation 兼容字段
  - [x] SubTask 3.2.3: 统一桌面上传、状态查询、历史水合和 AI context_snippets 的附件来源
  - [x] SubTask 3.2.4: 保留旧接口兼容但禁止生成分裂事实源
  - [x] SubTask 3.2.5: 增加同一文件仅一个 artifact 来源的回归测试
  - 证据：[api_server.py](../../../core/api_server.py)、[test_desktop_shared_api_contract.py](../../../tests/test_desktop_shared_api_contract.py)、[test_phase4_api.py](../../../tests/test_phase4_api.py)、命令 `python -m pytest tests/test_desktop_attachments.py tests/test_desktop_shared_api_contract.py::test_desktop_attachment_http_lifecycle_has_no_public_paths tests/test_desktop_shared_api_contract.py::test_chat_send_desktop_attachment_uses_only_attachment_id_boundary tests/test_phase4_api.py::test_api_queue_flag_on_returns_202_queued_without_waiting_pipeline tests/test_phase4_api.py::test_api_queue_flag_off_preserves_legacy_200_shape_and_empty_400 tests/test_phase4_api.py::test_api_queue_flag_off_supports_legacy_pipeline_only_companion tests/test_continuity_pipeline_integration.py -q` 通过 31/31

- [x] Task 3.3: 接入结构化图片识别与 ImageObservation
  - [x] SubTask 3.3.1: 梳理 image_service、multimodal_input、brain 现有视觉入口
  - [x] SubTask 3.3.2: 设计并实现 ImageObservation 输出结构
  - [x] SubTask 3.3.3: 接入 VLM/OCR provider 边界或可替代适配层
  - [x] SubTask 3.3.4: 确保图片观察默认不进入长期记忆
  - [x] SubTask 3.3.5: 增加中文截图、实物图、低置信度不确定性测试
  - 证据：[image_service.py](../../../core/image_service.py)、[test_phase10_image_workflow.py](../../../tests/test_phase10_image_workflow.py)、命令 `python -m pytest tests/test_phase10_image_workflow.py -q` 通过 13/13；Task 3.1/3.2 累积回归 `node --test .\tests\sse-bridge.test.js .\tests\system-status.test.js` 通过 11/11，附件邻近回归通过 28/28

- [x] Task 3.4: 实现 VisualIntentRouter 主动图片路由
  - [x] SubTask 3.4.1: 定义 role_selfie、role_in_scene、couple_photo、environment_object、document_snapshot、meme_sticker 意图
  - [x] SubTask 3.4.2: 接入 PersonaConfig.visual_identity revision 冻结规则
  - [x] SubTask 3.4.3: 接入 WorldSnapshot 与 OfficeContext 环境图来源
  - [x] SubTask 3.4.4: 确保 environment_object 的 reference_assets 必须为空
  - [x] SubTask 3.4.5: 增加角色自拍、环境图、置信度不足回退测试
  - 证据：[image_service.py](../../../core/image_service.py)、[test_phase10_image_workflow.py](../../../tests/test_phase10_image_workflow.py)、命令 `python -m pytest tests/test_phase10_image_workflow.py -q` 通过 16/16；累积回归 Electron 11/11、附件邻近 28/28

- [x] Task 3.5: 补齐前端附件预览与安全动作
  - [x] SubTask 3.5.1: 聊天气泡与历史库共用附件渲染状态
  - [x] SubTask 3.5.2: 展示图片、文本/Markdown、表格、PDF/PPT/Office 投影的可读预览入口
  - [x] SubTask 3.5.3: 实现 ready/failed/quarantined/unsupported 等状态的明确文案和操作
  - [x] SubTask 3.5.4: 验证 UI 不暴露本机绝对路径、令牌或扫描细节
  - 证据：[chat.js](../../../electron/src/renderer/js/chat.js)、[attachment-card-renderer.test.js](../../../electron/tests/attachment-card-renderer.test.js)、命令 `node --test electron\tests\attachment-card-renderer.test.js` 通过 14/14；累积回归 Electron 11/11、图片工作流 16/16、附件邻近 25/25

- [x] Task 3.6: 尝试连接专用向量知识库
  - [x] SubTask 3.6.1: 探测现有 knowledge 模块、embedding 模块和配置中是否存在可用向量实现
  - [x] SubTask 3.6.2: 若存在可用实现，将 Obsidian 总览摘要写入索引并执行语义检索测试
  - [x] SubTask 3.6.3: 若不存在可用实现，记录缺失接口、推荐专用向量库边界和阻塞证据
  - [x] SubTask 3.6.4: 将结果写入累积验证报告和知识库相关笔记
  - 证据：[Task3.6-向量知识库连接尝试报告.md](./Task3.6-向量知识库连接尝试报告.md)、[KnowledgeBase.md](../../../Aerie_Obsidian_Vault/modules/KnowledgeBase.md)；结论：阻塞——ChromaDB 依赖未安装、Embedding API 未配置、生产代码未接入 LayeredMemory

## 阶段 4 · 累积验证、双自审计与交付收口

- [x] Task 4.1: 执行阶段启动审计和风险门禁
  - [x] SubTask 4.1.1: 对每个阶段执行启动前四问审计
  - [x] SubTask 4.1.2: 对发现的高风险事项发起确认并记录决策
  - [x] SubTask 4.1.3: 启动审计结论为通过后才执行对应阶段
  - 证据：[Phase4-启动审计记录.md](./Phase4-启动审计记录.md)；结论：有条件通过；四问全部通过；3 项待办问题（I-P4-01/02/03）已记录

- [x] Task 4.2: 执行累积验证
  - [x] SubTask 4.2.1: 验证知识库文档完整性与链接回路
  - [x] SubTask 4.2.2: 验证文档+计划+审计体系集成一致性
  - [x] SubTask 4.2.3: 验证 P0 修复项独立功能
  - [x] SubTask 4.2.4: 验证 P0 修复项与既有桌面端、附件、World、聊天历史集成
  - 证据：[Phase4-验收审计记录.md](./Phase4-验收审计记录.md)、[累积验证报告模板.md](./累积验证报告模板.md)；累积验证 69/69 全部通过（Electron 11/11、图片 workflow 16/16、前端卡片 14/14、附件邻近 28/28）；3 项严重不一致已修复（C3.13 状态、Phase4 验收状态、累积验证报告版本）；知识库断链已修复（ADR-0002/0003 创建、R-TC-004 添加）

- [x] Task 4.3: 执行后端验收审计
  - [x] SubTask 4.3.1: 对本轮代码差异执行代码质量审查
  - [x] SubTask 4.3.2: 对无法静态确认的问题执行运行时调试与证据采集
  - [x] SubTask 4.3.3: 对本轮新增/修改输入边界、文件处理、权限控制和数据暴露执行安全审查
  - 证据：[Task4.3-后端验收审计报告.md](./Task4.3-后端验收审计报告.md)；TRAE-code-review accepted（0阻塞+1低级别观察）、TRAE-debugger accepted（69/69通过+诊断空）、TRAE-security-review accepted（9项专项检查全部pass）

- [x] Task 4.4: 执行前端真实体验审计
  - [x] SubTask 4.4.1: 使用真实 Electron 窗口启动隔离实例
  - [x] SubTask 4.4.2: 枚举聊天、附件、动态岛、World、知识相关可交互元素
  - [x] SubTask 4.4.3: 采集控制台、网络、截图、元素状态和字符清单
  - [x] SubTask 4.4.4: 记录所有失败项并生成整改任务
  - 证据：[Task4.4-前端体验审计报告.md](./Task4.4-前端体验审计报告.md)、[screenshot-1785182695633.png](./evidence/screenshot-1785182695633.png)；真实 Electron 窗口启动成功，25 个可交互元素全部可见，中文字符完整性通过，控制台无错误，DOM 状态正确

- [x] Task 4.5: 完成交付物索引与最终报告
  - [x] SubTask 4.5.1: 汇总信息总览知识库路径
  - [x] SubTask 4.5.2: 汇总第三次修正计划文档路径
  - [x] SubTask 4.5.3: 汇总阶段启动/验收审计记录路径
  - [x] SubTask 4.5.4: 汇总累积验证报告路径
  - [x] SubTask 4.5.5: 汇总决策记录路径
  - [x] SubTask 4.5.6: 汇总向量知识库连接尝试结果
  - 证据：[Task4.5-最终交付物索引与报告.md](./Task4.5-最终交付物索引与报告.md)；26 个知识库笔记、6 份计划文档、13 份审计记录、1 份累积验证报告、5 份决策记录、3 份向量知识库连接尝试文档；71/71 累积验证全部通过

# Task Dependencies

- Task 1.2 depends on Task 1.1.
- Task 1.3 depends on Task 1.1 and Task 1.2.
- Task 2.1 depends on Task 1.2 and Task 1.3.
- Task 2.2 depends on current confirmed decisions and continues throughout all phases.
- Task 2.3 and Task 2.4 depend on Task 2.1.
- Task 3.1, Task 3.2, Task 3.3, Task 3.4, Task 3.5, Task 3.6 depend on successful Phase 3 start audit.
- Task 3.4 depends on Task 3.3 for ImageObservation semantics and on WorldSnapshot/PersonaConfig discovery.
- Task 3.5 depends on Task 3.2 and Task 3.3.
- Task 4.2 depends on completed Phase 1-3 work.
- Task 4.3 and Task 4.4 depend on completed P0 implementation and available audit evidence.
- Task 4.5 depends on all previous tasks and all checklist items passing.
