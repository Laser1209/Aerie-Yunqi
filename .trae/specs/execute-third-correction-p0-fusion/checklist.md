# Checklist · Aerie 第三次修正计划 P0 融合闭环

> 每项检查必须有实际证据路径、命令输出、截图、日志、文档链接或审计结论。仅凭静态推断不得勾选。

## §1 · 信息收集与 Obsidian 知识库

- [x] C1.1 已读取并归纳四份输入文档的核心信息
  - 验证: 知识库首页包含桌面修复计划、修复历史、Echo 调研、统一融合方案四个来源链接与摘要
  - 证据: [00_首页.md](../../../Aerie_Obsidian_Vault/00_首页.md)、[09_当前状态.md](../../../Aerie_Obsidian_Vault/09_当前状态.md)
- [x] C1.2 当前系统状态已明确
  - 验证: 当前状态笔记列出已修复功能、遗留问题、技术债务、测试副作用和禁止触碰边界
  - 证据: [09_当前状态.md](../../../Aerie_Obsidian_Vault/09_当前状态.md)
- [x] C1.3 Obsidian Vault 为独立目录
  - 验证: Vault 不与 `.trae/specs` 混用，并包含首页、模块、技术、依赖、决策、审计、验证笔记
  - 证据: [00_首页.md](../../../Aerie_Obsidian_Vault/00_首页.md)、[01_模块总览.md](../../../Aerie_Obsidian_Vault/01_模块总览.md)、[02_技术总览.md](../../../Aerie_Obsidian_Vault/02_技术总览.md)、[03_依赖清单.md](../../../Aerie_Obsidian_Vault/03_依赖清单.md)、[04_决策记录.md](../../../Aerie_Obsidian_Vault/04_决策记录.md)、[05_审计报告.md](../../../Aerie_Obsidian_Vault/05_审计报告.md)、[06_验证索引.md](../../../Aerie_Obsidian_Vault/06_验证索引.md)
- [x] C1.4 每个核心概念有双向链接回路
  - 验证: 抽查 Echo 情绪价值、AttachmentEnvelope、ImageObservation、VisualIntentRouter、DesktopSurfaceAdapter、向量知识库至少各有 4 类链接
  - 证据: [Echo-Emotional-Value.md](../../../Aerie_Obsidian_Vault/dependencies/Echo-Emotional-Value.md)、[AttachmentEnvelope.md](../../../Aerie_Obsidian_Vault/modules/AttachmentEnvelope.md)、[ImageObservation.md](../../../Aerie_Obsidian_Vault/modules/ImageObservation.md)、[VisualIntentRouter.md](../../../Aerie_Obsidian_Vault/modules/VisualIntentRouter.md)、[DesktopSurfaceAdapter.md](../../../Aerie_Obsidian_Vault/modules/DesktopSurfaceAdapter.md)、[KnowledgeBase.md](../../../Aerie_Obsidian_Vault/modules/KnowledgeBase.md)、[08_互链地图.md](../../../Aerie_Obsidian_Vault/08_互链地图.md)
- [x] C1.5 功能点与技术方案矩阵完整
  - 验证: 矩阵覆盖 Echo、Pyisland/eIsland、Aerie 当前模块、P0 修复项、代码文件、测试入口和风险
  - 证据: [Function-To-Implementation.md](../../../Aerie_Obsidian_Vault/matrices/Function-To-Implementation.md)
- [x] C1.6 知识库更新机制存在
  - 验证: 有明确规则说明新发现写入何处、如何互链、如何与修正计划同步
  - 证据: [03_第三次修正计划知识库更新机制.md](../../../documents/第三次修正计划/03_第三次修正计划知识库更新机制.md)

## §2 · 计划、决策与审计门禁

- [x] C2.1 第三次修正计划文档存在
  - 验证: 文档包含版本号、制定日期、负责人、变更记录、阶段、任务、资源、交付物和验证标准
  - 证据: [01_第三次修正计划.md](../../../documents/第三次修正计划/01_第三次修正计划.md)
- [x] C2.2 阶段数量不超过四个
  - 验证: 计划文档只包含信息知识库、计划门禁、P0实现、验证收口四类主阶段或等价结构
  - 证据: [01_第三次修正计划.md](../../../documents/第三次修正计划/01_第三次修正计划.md#L60-L293)
- [x] C2.3 每个阶段有可测量验证标准
  - 验证: 每个阶段至少包含文档完整性、测试命令、审计结论、截图/日志/报告路径中的一类量化证据
  - 证据: [01_第三次修正计划.md](../../../documents/第三次修正计划/01_第三次修正计划.md#L104-L293)
- [x] C2.4 决策记录已写入已确认四项决策
  - 验证: 记录包含 P0 闭环优先、独立 Vault、专用向量库、阶段门禁确认
  - 证据: [02_第三次修正计划决策记录.md](../../../documents/第三次修正计划/02_第三次修正计划决策记录.md)
- [x] C2.5 待确认高风险事项已列出
  - 验证: 记录包含真实模型调用、QQ扫码、外部向量依赖、Pyisland helper 直接移植等待确认项
  - 证据: [02_第三次修正计划决策记录.md](../../../documents/第三次修正计划/02_第三次修正计划决策记录.md)
- [x] C2.6 启动审计模板完整
  - 验证: 模板包含计划覆盖、技术可行性、资源配置、风险点、问题、措施和结论
  - 证据: [阶段启动审计模板.md](./阶段启动审计模板.md)
- [x] C2.7 验收审计模板完整
  - 验证: 模板包含代码质量、调试证据、安全扫描、Electron体验、验证结果和整改项
  - 证据: [阶段验收审计模板.md](./阶段验收审计模板.md)
- [x] C2.8 累积验证报告框架完整
  - 验证: 报告框架支持模块 A、A+B、A+B+C 验证和回退预防问题报告
  - 证据: [累积验证报告模板.md](./累积验证报告模板.md)

## §3 · P0 功能修复

- [x] C3.1 Electron JSON 解码无 UTF-8 乱码
  - 验证: 人为跨 chunk 切分中文 JSON 后，前端接收文本不包含 `�`
  - 证据: [sse-bridge.test.js](../../../electron/tests/sse-bridge.test.js)、[main.js](../../../electron/src/main.js)、命令 `node --test tests/sse-bridge.test.js tests/system-status.test.js` 通过 11/11
- [x] C3.2 Electron SSE 解码无 UTF-8 乱码
  - 验证: 人为跨 chunk 切分中文 SSE frame 后，frame 顺序、内容和边界正确
  - 证据: [sse-bridge.test.js](../../../electron/tests/sse-bridge.test.js)、[main.js](../../../electron/src/main.js)、命令 `node --test tests/sse-bridge.test.js tests/system-status.test.js` 通过 11/11
- [x] C3.3 附件管线只有一个事实源
  - 验证: 同一合成文件上传后只产生一个 attachment id 和一个 artifact 来源
  - 证据: [api_server.py](../../../core/api_server.py)、[test_desktop_shared_api_contract.py](../../../tests/test_desktop_shared_api_contract.py)、命令 `python -m pytest tests/test_desktop_shared_api_contract.py::test_chat_send_desktop_attachment_uses_only_attachment_id_boundary -q` 通过
- [x] C3.4 附件状态兼容且可解释
  - 验证: queued、processing、ready、failed、quarantined、unsupported 均有明确 API payload 和前端文案
  - 证据: [test_desktop_attachments.py](../../../tests/test_desktop_attachments.py)、[test_desktop_shared_api_contract.py](../../../tests/test_desktop_shared_api_contract.py)、附件/API/pipeline 回归 31/31 通过
- [ ] C3.5 AI 上下文使用 Artifact 边界
  - 验证: 附件进入上下文时包含 trusted boundary、part id、页码/sheet/slide/range、parser warning
- [x] C3.6 ImageObservation 结构完整
  - 验证: 图片识别结果包含 scene、objects、ocr_text、relations、uncertainties、provider metadata、memory eligibility
  - 证据: [image_service.py](../../../core/image_service.py)、[test_phase10_image_workflow.py](../../../tests/test_phase10_image_workflow.py)、命令 `python -m pytest tests/test_phase10_image_workflow.py -q` 通过 13/13
- [x] C3.7 图片观察不默认污染长期记忆
  - 验证: 上传图片并识别后，长期记忆未新增未经准入的图片事实
  - 证据: `ImageObservation.memory_eligibility.eligible=false` 默认写入结果；`core/image_service.py` 未新增 `LongTermMemory`、`LayeredMemory` 或 `.store()` 记忆写入调用；`test_phase10_image_workflow.py` 覆盖中文截图、实物图、低置信度和异常 confidence
- [x] C3.8 VisualIntentRouter 环境图不挂角色参考图
  - 验证: environment_object 请求的 reference_assets 为空
  - 证据: [image_service.py](../../../core/image_service.py)、[test_phase10_image_workflow.py](../../../tests/test_phase10_image_workflow.py)、命令 `python -m pytest tests/test_phase10_image_workflow.py::test_generation_environment_object_routes_without_reference_assets -q` 通过
- [x] C3.9 VisualIntentRouter 自拍冻结身份版本
  - 验证: role_selfie 或 role_in_scene 请求包含 PersonaConfig visual identity revision
  - 证据: [image_service.py](../../../core/image_service.py)、[test_phase10_image_workflow.py](../../../tests/test_phase10_image_workflow.py)、命令 `python -m pytest tests/test_phase10_image_workflow.py::test_generation_role_selfie_freezes_visual_identity_revision -q` 通过
- [x] C3.10 主动图片置信度不足可回退
  - 验证: 低置信度分类不直接调用生图 provider，产生询问或文字回退
  - 证据: [image_service.py](../../../core/image_service.py)、[test_phase10_image_workflow.py](../../../tests/test_phase10_image_workflow.py)、命令 `python -m pytest tests/test_phase10_image_workflow.py::test_generation_low_confidence_visual_intent_does_not_call_provider -q` 通过
- [x] C3.11 前端附件预览可读
  - 验证: 图片、文本/Markdown、表格、PDF/PPT/Office 投影均有可读预览或明确降级状态
  - 证据: [chat.js](../../../electron/src/renderer/js/chat.js)、[attachment-card-renderer.test.js](../../../electron/tests/attachment-card-renderer.test.js)、命令 `node --test electron\tests\attachment-card-renderer.test.js` 通过 14/14；所有 category 类型均有对应图标和 ready 状态打开入口
- [x] C3.12 前端不泄露本机路径
  - 验证: Renderer DOM、状态 payload、截图和日志中不包含附件本机绝对路径或内部扫描令牌
  - 证据: [chat.js _redactSensitive](../../../electron/src/renderer/js/chat.js)、[attachment-card-renderer.test.js](../../../electron/tests/attachment-card-renderer.test.js) `test_attachment_card_does_not_expose_local_absolute_paths` 和 `test_attachment_card_does_not_expose_tokens_or_credentials_in_error_messages` 通过
- [x] C3.13 专用向量知识库连接尝试完成
  - 验证: 若成功，至少 3 个融合概念可语义检索；若失败，报告包含能力探测、缺失接口、阻塞原因和后续设计
  - 证据: [Task3.6-向量知识库连接尝试报告.md](./Task3.6-向量知识库连接尝试报告.md)；结论：阻塞——ChromaDB 依赖未安装、Embedding API 未配置、生产代码未接入 LayeredMemory；报告包含能力探测、缺失接口清单、阻塞原因、推荐方案 A/B/C 和后续设计建议

## §4 · 审计与累积验证

- [ ] C4.1 每个阶段都有启动审计记录
  - 验证: 阶段启动记录结论为通过，且风险项已处理或已确认
  - 可证明部分: Phase1-4 启动审计记录文件已创建；Phase3/4 当前为未开始门禁，不满足完整勾选条件
  - 证据: [Phase1-启动审计记录.md](./Phase1-启动审计记录.md)、[Phase2-启动审计记录.md](./Phase2-启动审计记录.md)、[Phase3-启动审计记录.md](./Phase3-启动审计记录.md)、[Phase4-启动审计记录.md](./Phase4-启动审计记录.md)
- [ ] C4.2 每个阶段都有验收审计记录
  - 验证: 阶段验收记录包含证据路径、结论和整改状态
  - 可证明部分: Phase1-4 验收审计记录文件已创建；Phase3/4 当前为未开始门禁，不满足完整勾选条件
  - 证据: [Phase1-验收审计记录.md](./Phase1-验收审计记录.md)、[Phase2-验收审计记录.md](./Phase2-验收审计记录.md)、[Phase3-验收审计记录.md](./Phase3-验收审计记录.md)、[Phase4-验收审计记录.md](./Phase4-验收审计记录.md)
- [ ] C4.3 后端代码质量审计已完成
  - 验证: 代码审查报告列出范围、意图、发现或无问题结论
- [ ] C4.4 运行时调试验证已完成
  - 验证: 对无法静态确认的问题有运行时日志、复现步骤、分析和前后对比证据
- [ ] C4.5 安全审计已完成
  - 验证: 安全审计覆盖输入处理、文件边界、路径、权限、敏感信息、Renderer 暴露和本轮差异
- [ ] C4.6 Electron 真实体验审计已完成
  - 验证: 有真实窗口启动记录、控制台、网络、截图、元素状态和字符清单
- [ ] C4.7 累积验证未发现已通过模块回退
  - 验证: 验证报告包含知识库、计划审计、P0 修复、集成链路的累积结果
- [ ] C4.8 失败项全部转化为整改任务
  - 验证: 所有失败检查点均在 tasks.md 或后续整改计划中有对应任务
- [ ] C4.9 最终交付物索引完整
  - 验证: 索引包含信息总览知识库、第三次修正计划、审计记录、累积验证报告、决策记录、向量连接尝试结果
- [ ] C4.10 无损停止和边界确认完成
  - 验证: 本批测试进程已关闭，正式数据未污染，用户未提交改动未被回滚或纳入无关提交
