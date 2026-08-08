﻿﻿﻿﻿﻿﻿﻿﻿# Tasks · Aerie 第三次修正计划 P1 陪伴融合与能力扩展

> 本任务列表用于执行 `execute-p1-companion-fusion`。严格度与 P0 一致：每个阶段启动前完成启动审计，完成后完成验收审计；TDD RED/GREEN；累积验证覆盖 P0+P1；决策记录随任务推进。

## 阶段 P1-A · 陪伴状态与关系面板底座

- [x] Task P1-A.1: 补全 C3.5 AI 上下文 Artifact 边界
  - [x] SubTask P1-A.1.1: 定位 context_builder 中附件进入上下文的拼接点
  - [x] SubTask P1-A.1.2: 为 PDF/Office/表格/幻灯片附件添加 trusted_boundary、part_id、page/sheet/slide/range、parser_warning
  - [x] SubTask P1-A.1.3: 增加 TDD RED 测试：多页 PDF、多 sheet 表格、解析警告场景
  - [x] SubTask P1-A.1.4: 实现 GREEN，通过 RED 测试
  - [x] SubTask P1-A.1.5: 累积回归 P0 附件邻近测试
    - 证据: [test_p1_a1_artifact_context_boundary.py](../../../tests/test_p1_a1_artifact_context_boundary.py)；5/5 通过；P0 附件 44/44 回归通过

- [x] Task P1-A.2: 实现 CompanionState 陪伴状态模型
  - [x] SubTask P1-A.2.1: 定义 CompanionState 数据结构（relationship_stage、care_followups、pending_topics、recent_pain_points、recent_joy_points）
  - [x] SubTask P1-A.2.2: 实现状态读写接口与持久化
  - [x] SubTask P1-A.2.3: 增加 TDD RED 测试：记录 pain_point、调度 care_followup、pending_topic 续接
  - [x] SubTask P1-A.2.4: 实现 GREEN
    - 证据: [companion_state.py](../../../core/companion_state.py)、[test_p1_a2_companion_state.py](../../../tests/test_p1_a2_companion_state.py)；13/13 通过`n`n- [x] Task P1-A.3: 实现共情响应策略链
  - [x] SubTask P1-A.3.1: 定义 validate_input → reflect → clarify → support → next_step 策略接口
  - [x] SubTask P1-A.3.2: 实现策略选择逻辑（基于消息情感、上下文）
  - [x] SubTask P1-A.3.3: 增加 TDD RED 测试：挫败表达、困惑表达、喜悦表达场景
  - [x] SubTask P1-A.3.4: 实现 GREEN
  - 证据: [empathy_strategy.py](../../../core/empathy_strategy.py)、[test_p1_a3_empathy_strategy.py](../../../tests/test_p1_a3_empathy_strategy.py)；25/25 通过；CompanionState 13/13 回归通过

- [x] Task P1-A.4: 扩展记忆可见性与用户控制
  - [x] SubTask P1-A.4.1: 为记忆条目添加 source_message_id、confidence、user_confirmed、expires_at、deleted_at
  - [x] SubTask P1-A.4.2: 实现记忆列表查询与删除接口
  - [x] SubTask P1-A.4.3: 增加 TDD RED 测试：查询记忆、删除记忆、过期记忆不出现
  - [x] SubTask P1-A.4.4: 实现 GREEN
  - 证据: [long_permanent.py](../../../memory/layers/long_permanent.py)、[test_p1_a4_memory_visibility.py](../../../tests/test_p1_a4_memory_visibility.py)；12/12 通过

- [x] Task P1-A.5: 实现角色配置版本化 PersonaConfig
  - [x] SubTask P1-A.5.1: 定义六类输入合并结构（identity_facts → visual_identity → background → speaking_style → active_rules → current_state）
  - [x] SubTask P1-A.5.2: 实现 revision 记录与旧 revision 失效逻辑
  - [x] SubTask P1-A.5.3: 增加 TDD RED 测试：保存新 revision、旧 revision 失效、revision 变化使旧候选失效
  - [x] SubTask P1-A.5.4: 实现 GREEN
  - 证据: [persona_config.py](../../../core/persona_config.py)、[test_p1_a5_persona_config.py](../../../tests/test_p1_a5_persona_config.py)；10/10 通过；VisualIntentRouter 16/16 回归通过

- [x] Task P1-A.6: 实现关系/成长/记忆面板前端
  - [x] SubTask P1-A.6.1: 创建面板组件框架（聊天记录、成长、关系、记忆、向量星云）
  - [x] SubTask P1-A.6.2: 关系面板展示熟悉度、信任感、好感度、芥蒂感、即时情绪、今日变化
  - [x] SubTask P1-A.6.3: 记忆面板展示只读列表与删除操作
  - [x] SubTask P1-A.6.4: 成长面板展示成长事件轨迹
  - [x] SubTask P1-A.6.5: 验证面板不暴露原始模型分数或内部路径
  - [x] SubTask P1-A.6.6: 增加 TDD RED 测试：面板渲染、数据绑定、安全脱敏
  - [x] SubTask P1-A.6.7: 实现 GREEN
  - 证据: [panels.js](../../../electron/src/renderer/js/panels.js)、[panels-renderer.test.js](../../../electron/tests/panels-renderer.test.js)；11/11 通过；附件卡片 14/14 回归通过

## 阶段 P1-B · 桌面办公入口与 Pyisland/eIsland 融合

- [x] Task P1-B.1: 创建 DesktopSurfaceAdapter 与悬浮窗状态机
  - [x] SubTask P1-B.1.1: 创建 `electron/src/desktop_surface/` 模块结构
  - [x] SubTask P1-B.1.2: 实现悬浮窗状态机（collapsed → peek → expanded → tool-panel）
  - [x] SubTask P1-B.1.3: 增加 TDD RED 测试：合法转换、非法转换拒绝
  - [x] SubTask P1-B.1.4: 实现 GREEN
  - 依赖: 无
  - 证据: [state-machine.js](../../../electron/src/desktop_surface/state-machine.js)、[desktop-surface-state-machine.test.js](../../../electron/tests/desktop-surface-state-machine.test.js)；state-machine 18/18 通过

- [x] Task P1-B.2: 实现 OfficeContext 系统上下文
  - [x] SubTask P1-B.2.1: 定义 OfficeContext 数据结构（active_window、focused_task、clipboard_candidate、network_state、battery_state、calendar_due、notification_budget）
  - [x] SubTask P1-B.2.2: 实现上下文采集与更新
  - [x] SubTask P1-B.2.3: 增加 TDD RED 测试：上下文更新、过期淘汰、敏感字段脱敏
  - [x] SubTask P1-B.2.4: 实现 GREEN
  - 依赖: Task P1-B.1
  - 证据: [office_context.py](../../../core/office_context.py)、[test_p1_b2_office_context.py](../../../tests/test_p1_b2_office_context.py)；office_context 14/14 通过

- [x] Task P1-B.3: 实现 ActionRegistry 工具注册
  - [x] SubTask P1-B.3.1: 定义工具注册接口与风险级别（low/medium/high）
  - [x] SubTask P1-B.3.2: 注册低风险工具（打开 URL、显示状态、音量/亮度调整）
  - [x] SubTask P1-B.3.3: 实现危险动作二次确认机制
  - [x] SubTask P1-B.3.4: 增加 TDD RED 测试：低风险直接执行、高风险需确认、未注册工具拒绝
  - [x] SubTask P1-B.3.5: 实现 GREEN
  - 依赖: Task P1-B.1
  - 证据: [action_registry.py](../../../core/action_registry.py)、[test_p1_b3_action_registry.py](../../../tests/test_p1_b3_action_registry.py)；action_registry 12/12 通过

- [x] Task P1-B.4: 实现办公最小闭环
  - [x] SubTask P1-B.4.1: 剪贴板翻译（检测 clipboard_candidate → 翻译 → 展示）
  - [x] SubTask P1-B.4.2: 截图问图（复用 P0 ImageObservation）
  - [x] SubTask P1-B.4.3: 时间天气状态
  - [x] SubTask P1-B.4.4: 增加 TDD RED 测试：三个闭环的功能与安全边界
  - [x] SubTask P1-B.4.5: 实现 GREEN
  - 依赖: Task P1-B.2、Task P1-B.3、P0 Task 3.3
  - 证据: [office_loops.py](../../../core/office_loops.py)、[test_p1_b4_office_loops.py](../../../tests/test_p1_b4_office_loops.py)；office_loops 14/14 通过

- [x] Task P1-B.5: 实现 companion_mode 与 office_mode 模式切换
  - [x] SubTask P1-B.5.1: 实现模式切换接口与 trace 记录
  - [x] SubTask P1-B.5.2: 增加 TDD RED 测试：模式切换、模式不串场、trace 写入
  - [x] SubTask P1-B.5.3: 实现 GREEN
  - 依赖: Task P1-B.1
  - 证据: [mode_switch.py](../../../core/mode_switch.py)、[test_p1_b5_mode_switch.py](../../../tests/test_p1_b5_mode_switch.py)；mode_switch 12/12 通过；P1-B 后端累计 78/78、前端 54/54 通过

## 阶段 P1-C · 主动消息升级与世界模拟联动

- [x] Task P1-C.1: 实现 WorldSimulation tick 与 WorldSnapshot
  - [x] SubTask P1-C.1.1: 定义 WorldSnapshot 结构（phase、location、activity、energy、social、nearby_objects、available_visual_topics）
  - [x] SubTask P1-C.1.2: 实现 tick 调度与快照生成
  - [x] SubTask P1-C.1.3: 增加 TDD RED 测试：tick 生成快照、快照字段完整、同一 tick 不重复
  - [x] SubTask P1-C.1.4: 实现 GREEN
  - 依赖: 无
  - 证据: WorldSimulation 与 WorldSnapshot 已完成；指定验证 10/10 通过，额外回归 41 项通过

- [x] Task P1-C.2: 实现主动候选意图与打分
  - [x] SubTask P1-C.2.1: 定义候选意图类型（life_share、care_followup、unfinished_topic、mood_shift、attention_ack）
  - [x] SubTask P1-C.2.2: 实现打分逻辑（世界新鲜度、关系相关性、情绪变化、用户偏好、最近重复度）
  - [x] SubTask P1-C.2.3: 增加 TDD RED 测试：候选生成、打分排序、低分过滤
  - [x] SubTask P1-C.2.4: 实现 GREEN
  - 依赖: Task P1-C.1、Task P1-A.2
  - 证据: 主动候选意图与打分链路已完成；指定验证 19/19 通过

- [x] Task P1-C.3: 实现主动关怀治理
  - [x] SubTask P1-C.3.1: 实现挂心事项到期回访
  - [x] SubTask P1-C.3.2: 实现未完话题续接
  - [x] SubTask P1-C.3.3: 实现沉默问候（每日上限、最小间隔、退避）
  - [x] SubTask P1-C.3.4: 增加 TDD RED 测试：回访触发、续接触发、退避递增、每日上限
  - [x] SubTask P1-C.3.5: 实现 GREEN
  - 依赖: Task P1-C.2、Task P1-A.2
  - 证据: 主动关怀治理已完成；指定验证 18/18 通过

- [x] Task P1-C.4: 实现主动消息 + 主动图片联合调度
  - [x] SubTask P1-C.4.1: 将主动候选意图与 VisualIntentRouter 联合调度
  - [x] SubTask P1-C.4.2: 确保同一 world_snapshot_id 不重复生成主动候选
  - [x] SubTask P1-C.4.3: 增加 TDD RED 测试：联合调度、去重、用户忽略后退避
  - [x] SubTask P1-C.4.4: 实现 GREEN
  - 证据: P1-C 阶段审计 accepted；proactive_visual_scheduler.py 指定验证 31/31 通过
  - 依赖: Task P1-C.2、P0 Task 3.4

## 阶段 P1-D · 语音、表情包与通道扩展

- [x] Task P1-D.1: 实现语音 ASR/TTS 三服务边界
  - [x] SubTask P1-D.1.1: 定义 VoiceProfile、SpeechMarkup、VoiceDeliveryPolicy 三个服务接口
  - [x] SubTask P1-D.1.2: 实现 ASR 转写与 TTS 合成适配层
  - [x] SubTask P1-D.1.3: 实现语音开关与审计
  - [x] SubTask P1-D.1.4: 增加 TDD RED 测试：转写、合成、开关关闭不调用、审计记录
  - [x] SubTask P1-D.1.5: 实现 GREEN
  - 证据: P1-D 阶段审计 accepted；voice_service.py 15/15 通过
  - 依赖: 无

- [x] Task P1-D.2: 实现表情包入口
  - [x] SubTask P1-D.2.1: 定义表情包数据结构与情绪/场景标签
  - [x] SubTask P1-D.2.2: 实现标签检索与发送审计
  - [x] SubTask P1-D.2.3: 实现用户关闭开关
  - [x] SubTask P1-D.2.4: 增加 TDD RED 测试：检索、发送审计、关闭后不可用
  - [x] SubTask P1-D.2.5: 实现 GREEN
  - 证据: P1-D 阶段审计 accepted；sticker_gate.py 16/16 通过
  - 依赖: 无

- [x] Task P1-D.3: 实现克隆音色高敏感评审
  - [x] SubTask P1-D.3.1: 定义克隆音色上传/试听/授权/撤销/删除/审计流程
  - [x] SubTask P1-D.3.2: 实现授权令牌与过期机制
  - [x] SubTask P1-D.3.3: 增加安全审查：生物特征数据不写入长期记忆、不暴露到 Renderer
  - [x] SubTask P1-D.3.4: 增加 TDD RED 测试：上传授权、撤销失效、删除清理、审计完整
  - [x] SubTask P1-D.3.5: 实现 GREEN
  - 证据: P1-D 阶段审计 accepted；clone_voice_service.py 16/16 通过
  - 依赖: Task P1-D.1

- [x] Task P1-D.4: 实现 CompanionChannel 通道抽象
  - [x] SubTask P1-D.4.1: 定义 CompanionChannel 接口（health、echo、send、receive）
  - [x] SubTask P1-D.4.2: 实现 QQ 适配器健康检查与回显
  - [x] SubTask P1-D.4.3: 实现 ClawBot 适配器健康检查与回显
  - [x] SubTask P1-D.4.4: 增加 TDD RED 测试：健康检查、断线真实状态、回显验证
  - [x] SubTask P1-D.4.5: 实现 GREEN
  - 证据: P1-D 阶段审计 accepted；companion_channel.py 15/15 通过
  - 依赖: 无

- [x] Task P1-D.5: 激活专用向量知识库
  - [x] SubTask P1-D.5.1: 安装 ChromaDB 依赖（取消 requirements.txt 注释）
    - 证据: requirements.txt 第 118 行 `chromadb>=1.5.9` 已启用；`.venv` 内 `import chromadb` → v1.5.9（2026-08-09 00:50 核验）
  - [x] SubTask P1-D.5.2: 配置 Embedding API 环境变量并暴露到 .env.example
    - 证据: `.env` 新增 `AERIE_EMBEDDING_PROVIDER=chromadb_local`（Key 留空走本地 ONNX）、`AERIE_CHROMA_DIR`、`AERIE_KNOWLEDGE_COLLECTION`；`.env.example` 已有完整模板
  - [x] SubTask P1-D.5.3: 切换生产代码到 LayeredMemory 并传入 embedding_fn
    - 证据: `core/companion.py` 用 `LayeredMemory(db, chroma_persist_dir, embedding_fn=resolve_embedding_fn())` 替换 `LongTermMemory`；新增 `memory/layers/sync_adapter.py` 桥接旧同步接口；`tests/test_p1_d5_3_layered_adapter.py` 4 passed（含运行中事件循环场景）
  - [x] SubTask P1-D.5.4: 将 Obsidian 总览摘要写入向量索引
    - 证据: `scripts/p1d5_activate_knowledge.py` 写入 6 块（kb_companion/kb_vector/kb_world/kb_channels/kb_empathy/kb_persona），持久化于 `data/chroma`
  - [x] SubTask P1-D.5.5: 执行语义检索测试，至少 3 个融合概念可检索
    - 证据: 语义检索命中 4 个 distinct topic（channels/companion/empathy/world）≥3 ✅
  - [x] SubTask P1-D.5.6: 增加 TDD RED 测试：写入、检索、去重、失败降级
    - 证据: `tests/test_p1_d5_knowledge_indexer.py` 6 用例
  - [x] SubTask P1-D.5.7: 实现 GREEN
    - 证据: `pytest tests/test_p1_d5_knowledge_indexer.py -q` → 6 passed（2026-08-09 00:51）
  - 依赖: P0 Task 3.6

## 阶段 P1-E · 累积验证、审计与交付收口

- [x] Task P1-E.1: 执行阶段启动审计和风险门禁
  - [x] SubTask P1-E.1.1: 对 P1 每个阶段执行启动前四问审计
  - [x] SubTask P1-E.1.2: 对高风险事项发起确认并记录决策
  - [x] SubTask P1-E.1.3: 启动审计结论为通过后才执行对应阶段
  - 证据: [P1E1-启动审计记录.md](./P1E1-启动审计记录.md)；启动审计结论 passed

- [x] Task P1-E.2: 执行累积验证
  - [x] SubTask P1-E.2.1: 验证 P0 模块无回退
  - [x] SubTask P1-E.2.2: 验证 P1 模块独立功能
  - [x] SubTask P1-E.2.3: 验证 P0+P1 集成功能
  - [x] SubTask P1-E.2.4: 更新累积验证报告
  - 证据: [P1E2-累积验证报告.md](./P1E2-累积验证报告.md)；332/332 通过（P1 后端 216 + P0 回归 69 + 前端 47），0 失败无回退

- [x] Task P1-E.3: 执行后端验收审计
  - [x] SubTask P1-E.3.1: 使用 TRAE-code-review 进行代码质量审查
  - [x] SubTask P1-E.3.2: 使用 TRAE-debugger 进行运行时调试
  - [x] SubTask P1-E.3.3: 使用 TRAE-security-review 进行安全审计
  - 证据: [P1E3-后端验收审计报告.md](./P1E3-后端验收审计报告.md)；审计结论 accepted

- [x] Task P1-E.4: 执行前端真实体验审计
  - [x] SubTask P1-E.4.1: 使用真实 Electron 窗口启动隔离实例
  - [x] SubTask P1-E.4.2: 枚举面板、悬浮窗、办公入口、语音、表情包可交互元素
  - [x] SubTask P1-E.4.3: 采集控制台、网络、截图、元素状态
  - [x] SubTask P1-E.4.4: 记录失败项并生成整改任务
  - 证据: [P1E4-前端体验审计报告.md](./P1E4-前端体验审计报告.md)；审计结论 accepted

- [x] Task P1-E.5: 完成交付物索引与最终报告
  - [x] SubTask P1-E.5.1: 汇总 P1 知识库更新
  - [x] SubTask P1-E.5.2: 汇总 P1 计划与审计记录
  - [x] SubTask P1-E.5.3: 汇总 P1 累积验证报告
  - [x] SubTask P1-E.5.4: 汇总 P1 决策记录
  - [x] SubTask P1-E.5.5: 汇总向量知识库激活结果
  - 证据: [P1E5-最终交付物索引与报告.md](./P1E5-最终交付物索引与报告.md)；交付索引完整，P1 阶段全部完成

# Task Dependencies

- Task P1-A.3 depends on Task P1-A.2.
- Task P1-A.6 depends on Task P1-A.2 and Task P1-A.4.
- Task P1-B.2 depends on Task P1-B.1.
- Task P1-B.3 depends on Task P1-B.1.
- Task P1-B.4 depends on Task P1-B.2, Task P1-B.3, and P0 Task 3.3.
- Task P1-B.5 depends on Task P1-B.1.
- Task P1-C.2 depends on Task P1-C.1 and Task P1-A.2.
- Task P1-C.3 depends on Task P1-C.2 and Task P1-A.2.
- Task P1-C.4 depends on Task P1-C.2 and P0 Task 3.4.
- Task P1-D.3 depends on Task P1-D.1.
- Task P1-D.5 depends on P0 Task 3.6.
- Task P1-E.2 depends on all P1-A through P1-D tasks.
- Task P1-E.3 and Task P1-E.4 depend on completed P1 implementation.
- Task P1-E.5 depends on all previous tasks and all checklist items passing.
