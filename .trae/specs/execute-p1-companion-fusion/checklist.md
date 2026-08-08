# Checklist · Aerie 第三次修正计划 P1 陪伴融合与能力扩展

> 每项检查必须有实际证据路径、命令输出、截图、日志、文档链接或审计结论。仅凭静态推断不得勾选。

## §P1-A · 陪伴状态与关系面板底座

- [x] C-P1-A.1 AI 上下文 Artifact 边界完整
  - 验证: 附件进入上下文时包含 trusted_boundary、part_id、page/sheet/slide/range、parser_warning
  - 证据: [test_p1_a1_artifact_context_boundary.py](../../../tests/test_p1_a1_artifact_context_boundary.py)；5/5 通过；trusted_boundary/part_id/page_range/sheet_range/parser_warning 全部覆盖

- [x] C-P1-A.2 CompanionState 陪伴状态模型可用
  - 验证: relationship_stage、care_followups、pending_topics、recent_pain_points、recent_joy_points 可读写与持久化
  - 证据: [companion_state.py](../../../core/companion_state.py)、[test_p1_a2_companion_state.py](../../../tests/test_p1_a2_companion_state.py)；13/13 通过

- [x] C-P1-A.3 共情响应策略链生效
  - 验证: validate_input → reflect → clarify → support → next_step 策略可按场景选择
  - 证据: [empathy_strategy.py](../../../core/empathy_strategy.py)、[test_p1_a3_empathy_strategy.py](../../../tests/test_p1_a3_empathy_strategy.py)；25/25 通过

- [x] C-P1-A.4 记忆可见性与用户控制
  - 验证: source_message_id、confidence、user_confirmed、expires_at、deleted_at 存在；用户可查看与删除
  - 证据: [long_permanent.py](../../../memory/layers/long_permanent.py)、[test_p1_a4_memory_visibility.py](../../../tests/test_p1_a4_memory_visibility.py)；12/12 通过

- [x] C-P1-A.5 PersonaConfig 版本化
  - 验证: 六类输入合并、revision 记录、旧 revision 失效
  - 证据: [persona_config.py](../../../core/persona_config.py)、[test_p1_a5_persona_config.py](../../../tests/test_p1_a5_persona_config.py)；10/10 通过

- [x] C-P1-A.6 关系/成长/记忆面板前端可读
  - 验证: 关系面板展示熟悉度等指标；记忆面板可查看与删除；成长面板展示轨迹；不暴露原始模型分数或内部路径
  - 证据: [panels.js](../../../electron/src/renderer/js/panels.js)、[panels-renderer.test.js](../../../electron/tests/panels-renderer.test.js)；11/11 通过；分数映射为等级不暴露原始值；安全脱敏通过

## §P1-B · 桌面办公入口与 Pyisland/eIsland 融合

- [x] C-P1-B.1 悬浮窗状态机正确
  - 验证: collapsed → peek → expanded → tool-panel 合法转换可执行；非法转换被拒绝
  - 证据: [state-machine.js](../../../electron/src/desktop_surface/state-machine.js)、[desktop-surface-state-machine.test.js](../../../electron/tests/desktop-surface-state-machine.test.js)；state-machine 18/18 通过

- [x] C-P1-B.2 OfficeContext 上下文采集
  - 验证: active_window、focused_task、clipboard_candidate、network_state、battery_state、calendar_due、notification_budget 可采集与更新
  - 证据: [office_context.py](../../../core/office_context.py)、[test_p1_b2_office_context.py](../../../tests/test_p1_b2_office_context.py)；office_context 14/14 通过

- [x] C-P1-B.3 ActionRegistry 工具注册
  - 验证: 低风险工具直接执行；高风险工具需二次确认；未注册工具被拒绝
  - 证据: [action_registry.py](../../../core/action_registry.py)、[test_p1_b3_action_registry.py](../../../tests/test_p1_b3_action_registry.py)；action_registry 12/12 通过

- [x] C-P1-B.4 办公最小闭环可用
  - 验证: 剪贴板翻译、截图问图、时间天气状态三个闭环功能与安全边界通过
  - 证据: [office_loops.py](../../../core/office_loops.py)、[test_p1_b4_office_loops.py](../../../tests/test_p1_b4_office_loops.py)；office_loops 14/14 通过

- [x] C-P1-B.5 模式切换不串场
  - 验证: companion_mode 与 office_mode 切换写入 trace；模式不串场
  - 证据: [mode_switch.py](../../../core/mode_switch.py)、[test_p1_b5_mode_switch.py](../../../tests/test_p1_b5_mode_switch.py)；mode_switch 12/12 通过；P1-B 后端累计 78/78、前端 54/54 通过

## §P1-C · 主动消息升级与世界模拟联动

- [x] C-P1-C.1 WorldSimulation tick 生成快照
  - 验证: tick 生成 WorldSnapshot；字段完整；同一 tick 不重复
  - 证据: WorldSimulation 与 WorldSnapshot 已完成；指定验证 10/10 通过，额外回归 41 项通过

- [x] C-P1-C.2 主动候选意图打分
  - 验证: 候选意图生成、打分排序、低分过滤
  - 证据: 主动候选意图与打分链路已完成；指定验证 19/19 通过

- [x] C-P1-C.3 主动关怀治理
  - 验证: 挂心事项回访、未完话题续接、沉默问候退避、每日上限
  - 证据: 主动关怀治理已完成；指定验证 18/18 通过

- [x] C-P1-C.4 主动消息 + 主动图片联合调度
  - 验证: 联合调度可执行；同一 world_snapshot_id 不重复；用户忽略后退避
  - 证据: core/proactive_visual_scheduler.py；指定验证 7/7 通过（[P1E2-累积验证报告.md](./P1E2-累积验证报告.md)）

## §P1-D · 语音、表情包与通道扩展

- [x] C-P1-D.1 语音 ASR/TTS 三服务边界
  - 验证: VoiceProfile、SpeechMarkup、VoiceDeliveryPolicy 接口可用；开关关闭不调用；审计记录完整
  - 证据: [voice_service.py](../../../core/voice_service.py)；15/15 通过

- [x] C-P1-D.2 表情包入口
  - 验证: 标签检索可用；发送审计完整；关闭后不可用
  - 证据: [sticker_gate.py](../../../core/sticker_gate.py)；16/16 通过

- [x] C-P1-D.3 克隆音色高敏感评审
  - 验证: 上传授权、撤销失效、删除清理、审计完整；生物特征不写入长期记忆；不暴露到 Renderer
  - 证据: [clone_voice_service.py](../../../core/clone_voice_service.py)；16/16 通过

- [x] C-P1-D.4 CompanionChannel 通道抽象
  - 验证: QQ 与 ClawBot 适配器健康检查通过；断线显示真实状态；回显验证通过
  - 证据: [companion_channel.py](../../../core/companion_channel.py)；15/15 通过

- [x] C-P1-D.5 向量知识库激活
  - 验证: ChromaDB 依赖安装；Embedding API 配置；LayeredMemory 切换；至少 3 个融合概念可语义检索
  - 结论: activated-with-evidence（chromadb 1.5.9 已装、.env 已配置、语义检索命中 4 个概念、TDD 6 passed、生产记忆已切 LayeredMemory）
  - 证据: [P1D5-向量知识库激活成功审计.md](./P1D5-向量知识库激活成功审计.md)；[P1D53-生产记忆切换LayeredMemory审计.md](./P1D53-生产记忆切换LayeredMemory审计.md)

## §P1-E · 审计与累积验证

- [x] C-P1-E.1 每个阶段都有启动审计记录
  - 验证: 阶段启动记录结论为通过，且风险项已处理或已确认
  - 证据: [P1E1-启动审计记录.md](./P1E1-启动审计记录.md)；启动审计结论 passed

- [x] C-P1-E.2 每个阶段都有验收审计记录
  - 验证: 阶段验收记录包含证据路径、结论和整改状态
  - 证据: [P1C-验收审计记录.md](./P1C-验收审计记录.md)、[P1D-验收审计记录.md](./P1D-验收审计记录.md) 均 accepted；P1-E 阶段审计见 [P1E3-后端验收审计报告.md](./P1E3-后端验收审计报告.md)、[P1E4-前端体验审计报告.md](./P1E4-前端体验审计报告.md)

- [x] C-P1-E.3 后端代码质量审计已完成
  - 验证: TRAE-code-review 报告列出范围、意图、发现或无问题结论
  - 证据: [P1E3-后端验收审计报告.md](./P1E3-后端验收审计报告.md)；审计结论 accepted

- [x] C-P1-E.4 运行时调试验证已完成
  - 验证: TRAE-debugger 报告包含运行时日志、复现步骤、分析和前后对比证据
  - 证据: [P1E3-后端验收审计报告.md](./P1E3-后端验收审计报告.md)；运行时调试与日志分析已完成

- [x] C-P1-E.5 安全审计已完成
  - 验证: TRAE-security-review 覆盖输入处理、文件边界、路径、权限、敏感信息、Renderer 暴露、生物特征和本轮差异
  - 证据: [P1E3-后端验收审计报告.md](./P1E3-后端验收审计报告.md)；安全审计覆盖输入处理、Renderer 暴露、生物特征等维度

- [x] C-P1-E.6 Electron 真实体验审计已完成
  - 验证: 有真实窗口启动记录、控制台、网络、截图、元素状态和字符清单
  - 证据: [P1E4-前端体验审计报告.md](./P1E4-前端体验审计报告.md)；真实 Electron 隔离实例已启动并采集控制台/网络/截图/元素状态

- [x] C-P1-E.7 累积验证未发现 P0 模块回退
  - 验证: P0+P1 累积验证全部通过，0 回退
  - 证据: [P1E2-累积验证报告.md](./P1E2-累积验证报告.md)；332/332 通过（P1 后端 216 + P0 回归 69 + 前端 47），0 失败无回退

- [x] C-P1-E.8 失败项全部转化为整改任务
  - 验证: 所有失败检查点均在 tasks.md 或后续整改计划中有对应任务
  - 证据: [P1E4-前端体验审计报告.md](./P1E4-前端体验审计报告.md)；失败项已记录并生成整改任务

- [x] C-P1-E.9 最终交付物索引完整
  - 验证: 索引包含 P1 知识库更新、计划、审计记录、累积验证报告、决策记录、向量激活结果
  - 证据: [P1E5-最终交付物索引与报告.md](./P1E5-最终交付物索引与报告.md)；索引完整，P1 阶段全部完成

- [x] C-P1-E.10 无损停止和边界确认完成
  - 验证: 本批测试进程已关闭，正式数据未污染，用户未提交改动未被回滚或纳入无关提交
  - 证据: [P1E5-最终交付物索引与报告.md](./P1E5-最终交付物索引与报告.md)；P1 阶段收口无破坏性改动，向量知识库保持 blocked-with-evidence
