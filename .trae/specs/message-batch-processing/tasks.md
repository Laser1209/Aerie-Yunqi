# 消息批量处理与智能回复系统 - The Implementation Plan (Decomposed and Prioritized Task List)

## [ ] Task 1: 数据库Schema扩展 - 添加batch_id字段
- **Priority**: high
- **Depends On**: None
- **Description**: 
  - 在chat_log表中添加batch_id字段（TEXT类型，可NULL）用于关联同一批次的消息
  - 创建数据库迁移脚本，确保现有数据兼容（NULL表示历史单条消息）
  - 在ChatLog模型中添加batch_id属性
- **Acceptance Criteria Addressed**: AC-7
- **Test Requirements**:
  - `programmatic` TR-1.1: 迁移脚本执行成功，新字段添加完成
  - `programmatic` TR-1.2: 现有chat_log记录的batch_id为NULL，不影响读取
  - `programmatic` TR-1.3: 可正常插入带batch_id的新记录
- **Notes**: 使用ALTER TABLE添加字段，保持向后兼容

## [ ] Task 2: 配置项添加与热重载支持
- **Priority**: high
- **Depends On**: None
- **Description**: 
  - 在config/settings.py中添加message_batching配置段（包含enabled, window_seconds, max_batch_size, base_interval_seconds, chars_per_second, min_interval_seconds, max_interval_seconds）
  - 在settings.yaml中添加默认配置
  - 确保配置支持热重载（通过现有reload-config机制）
- **Acceptance Criteria Addressed**: AC-10
- **Test Requirements**:
  - `programmatic` TR-2.1: 默认配置值正确加载
  - `programmatic` TR-2.2: 修改配置后热重载生效
  - `programmatic` TR-2.3: enabled=false时系统回退到原有单条处理模式
- **Notes**: feature flag设计，可快速回滚

## [ ] Task 3: 批量消息收集器（MessageBatcher）实现
- **Priority**: high
- **Depends On**: Task 2
- **Description**: 
  - 创建core/message_batcher.py模块，实现MessageBatcher类
  - 实现时间窗口机制：首条消息启动定时器，窗口内消息加入批次
  - 实现最大批量限制：达到max_batch_size时立即提交
  - 实现按conversation_id隔离批次（不同用户互不影响）
  - 提供回调机制：窗口超时/批次满时触发处理
  - 生成唯一batch_id（UUID）
- **Acceptance Criteria Addressed**: AC-1, AC-8
- **Test Requirements**:
  - `programmatic` TR-3.1: 1.5秒窗口内3条消息被收集到同一批次
  - `programmatic` TR-3.2: 达到max_batch_size(5)时立即提交，不等待窗口超时
  - `programmatic` TR-3.3: 不同conversation_id的消息进入不同批次
  - `programmatic` TR-3.4: 批次提交时生成有效的batch_id
- **Notes**: 使用asyncio.Queue和asyncio.Timer实现；确保线程安全

## [ ] Task 4: Pipeline批量处理支持
- **Priority**: high
- **Depends On**: Task 1, Task 3
- **Description**: 
  - 修改Pipeline.handle()支持接收消息列表（批量模式）
  - 实现批量上下文构建：合并多条用户消息为一个上下文
  - 历史消息只加载一次，批次复用
  - 情绪更新：基于批次内所有消息综合计算
  - 修改LLM prompt，明确指示LLM为每条消息分别回复
  - 解析LLM返回的多条回复（需设计明确的分隔格式）
  - 保持单条消息处理路径作为fallback
- **Acceptance Criteria Addressed**: AC-1, AC-7
- **Test Requirements**:
  - `programmatic` TR-4.1: 批量消息一次性传入Pipeline
  - `programmatic` TR-4.2: 历史消息只加载一次（验证调用次数）
  - `programmatic` TR-4.3: LLM返回的多条回复正确解析，顺序与输入一致
  - `programmatic` TR-4.4: 每条用户消息对应一条AI回复，一对一
  - `human-judgement` TR-4.5: 批量回复的上下文连贯性良好，能看到时间窗口内所有消息
- **Notes**: prompt设计是关键，需要明确的分隔符让LLM区分多条消息并分别回复；建议使用`---msg1---`格式或编号列表

## [ ] Task 5: 正文内容强制校验模块实现
- **Priority**: high
- **Depends On**: None
- **Description**: 
  - 在core/创建content_validator.py模块
  - 实现正文存在性检查：过滤thought/action标签后检查是否有非空白内容
  - 实现补救流程：
    - 第一次失败：调用LLM重新生成（prompt："请只输出自然语言对话正文，不要只输出动作或思考标签"）
    - 第二次仍失败：使用保底回复（随机选择："嗯？"、"在听"、"怎么了？"、"哦？"、"继续说"）
  - 记录WARN日志和metrics
  - 集成到现有输出校验链（screen_action_sanitizer → output_self_check → content_validator → response_validator）
- **Acceptance Criteria Addressed**: AC-5, AC-6
- **Test Requirements**:
  - `programmatic` TR-5.1: 只有标签无正文的回复被正确识别
  - `programmatic` TR-5.2: 第一次失败触发重新生成
  - `programmatic` TR-5.3: 重新生成仍失败时使用保底回复
  - `programmatic` TR-5.4: 最终发送的消息过滤标签后非空
  - `programmatic` TR-5.5: QQ端标签正确过滤，只显示正文
- **Notes**: 保底回复至少5个，随机选择避免重复感

## [ ] Task 6: SendQueue批量发送与字数间隔实现
- **Priority**: high
- **Depends On**: Task 2, Task 5
- **Description**: 
  - 修改communication/send_queue.py支持批量入队（多条回复带batch_id）
  - 修改_worker循环：识别批次首条，立即发送（间隔0）
  - 实现字数比例间隔计算：interval = base_interval + (char_count / chars_per_second)
  - 字数计算基于过滤标签后的纯正文长度
  - 间隔叠加persona_pacing情感因素（±30%）
  - 间隔钳制在[min_interval, max_interval]范围内
  - 空正文补救回复使用min_interval
  - 确保批次内回复严格按时间顺序发送
- **Acceptance Criteria Addressed**: AC-2, AC-3, AC-4
- **Test Requirements**:
  - `programmatic` TR-6.1: 批次首条回复在处理完成后100ms内发送
  - `programmatic` TR-6.2: 50字回复间隔 ≈ 0.5 + 50/4 = 1.0-1.5秒（含情感浮动）
  - `programmatic` TR-6.3: 150字回复间隔 ≈ 0.5 + 150/4 = 3.0-4.5秒（含情感浮动）
  - `programmatic` TR-6.4: 长回复间隔 > 短回复间隔（正比例）
  - `programmatic` TR-6.5: 发送顺序与消息接收顺序一致
  - `programmatic` TR-6.6: 间隔在[0.3, 5.0]秒范围内
- **Notes**: 与现有persona_pacing模块集成；字数计算使用strip_thought_action_tags后的文本长度

## [ ] Task 7: ChatRequestWorker与Repository适配
- **Priority**: high
- **Depends On**: Task 3, Task 4
- **Description**: 
  - 修改ChatRequestRepository：支持批量创建请求记录（多条消息共享batch_id）
  - 修改claim_next逻辑：保持同一conversation_id串行处理（现有逻辑已支持）
  - 修改ChatRequestWorker._slot_loop：识别批量请求，调用Pipeline批量处理
  - 处理批量请求的取消机制：取消整个批次
  - 处理批量请求的cognition trace：标记batch_id
- **Acceptance Criteria Addressed**: AC-7, AC-8
- **Test Requirements**:
  - `programmatic` TR-7.1: 批量请求正确入库，共享batch_id
  - `programmatic` TR-7.2: 同一conversation_id的多个批次不会并发处理
  - `programmatic` TR-7.3: 取消操作能终止整个批次处理
  - `programmatic` TR-7.4: cognition trace中记录batch_id
- **Notes**: 利用现有claim_next的串行保证，无需修改其核心逻辑

## [ ] Task 8: QQ客户端与本地聊天双路适配
- **Priority**: high
- **Depends On**: Task 3, Task 6
- **Description**: 
  - 修改qq_client.py的消息接收逻辑：新消息先进入MessageBatcher而非直接入队
  - 修改本地聊天（direct chat）的消息接收逻辑：同样进入MessageBatcher
  - 确保QQ端标签过滤（strip_thought_action_tags）在字数计算之前执行
  - 确保两路聊天都支持批量发送和首条即时回复
- **Acceptance Criteria Addressed**: AC-6, AC-9
- **Test Requirements**:
  - `programmatic` TR-8.1: QQ消息进入MessageBatcher
  - `programmatic` TR-8.2: 本地聊天消息进入MessageBatcher
  - `programmatic` TR-8.3: QQ端收到的消息标签正确过滤
  - `human-judgement` TR-8.4: 本地聊天和QQ聊天体验一致
- **Notes**: 保持现有is_logged_in检查和wait_for_login逻辑

## [ ] Task 9: Metrics与可观测性
- **Priority**: medium
- **Depends On**: Task 3, Task 5, Task 6
- **Description**: 
  - 添加批量处理metrics：批次大小分布、窗口等待时间、总处理时间
  - 添加正文校验metrics：触发次数、重新生成成功次数、保底回复使用次数
  - 添加发送间隔metrics：实际间隔值、字数-间隔对应关系
  - 在cognition trace中标记batch_id和批次序号
  - 在日志中明确记录批次相关信息（batch_id, batch_size, window_wait_ms）
- **Acceptance Criteria Addressed**: AC-7, NFR-4
- **Test Requirements**:
  - `programmatic` TR-9.1: 日志中包含batch_id和batch_size
  - `programmatic` TR-9.2: metrics正确记录批次大小和处理时间
  - `programmatic` TR-9.3: 正文校验失败事件被记录
- **Notes**: 使用现有日志系统，不引入新依赖

## [ ] Task 10: 集成测试与端到端验证
- **Priority**: high
- **Depends On**: Task 4, Task 5, Task 6, Task 7, Task 8
- **Description**: 
  - 编写集成测试脚本：模拟连发3条消息，验证批量处理流程
  - 验证首条即时回复（时间测量）
  - 验证后续回复间隔与字数比例
  - 验证回复顺序正确性
  - 验证正文为空时的补救流程
  - 验证feature flag关闭时回退到单条模式
  - 验证本地聊天和QQ聊天双路正常
- **Acceptance Criteria Addressed**: AC-1, AC-2, AC-3, AC-4, AC-5, AC-10
- **Test Requirements**:
  - `programmatic` TR-10.1: 3条连发消息被合并为一批
  - `programmatic` TR-10.2: 首条回复延迟 ≤ 单条处理时间
  - `programmatic` TR-10.3: 后续回复间隔符合字数比例
  - `programmatic` TR-10.4: 回复顺序与消息顺序一致
  - `programmatic` TR-10.5: 空正文触发补救，最终有内容
  - `programmatic` TR-10.6: feature flag关闭后使用原有单条处理
- **Notes**: 创建e2e测试脚本，可重复运行验证

## [ ] Task 11: 长期参考文档编写
- **Priority**: medium
- **Depends On**: Task 10
- **Description**: 
  - 在.trae/specs/message-batch-processing/下创建长期维护文档reference.md
  - 包含：系统架构概览、批量处理流程图、关键模块说明、配置项说明、回复发送规则详解、正文校验规则、故障排查指南、维护日志模板
  - 包含与现有系统的兼容性说明和回滚指南
  - 文档结构设计为可持续更新（每周迭代维护）
- **Acceptance Criteria Addressed**: G6
- **Test Requirements**:
  - `human-judgement` TR-11.1: 文档结构清晰，易于查找信息
  - `human-judgement` TR-11.2: 包含所有关键决策和设计理由
  - `human-judgement` TR-11.3: 有明确的维护更新指南
- **Notes**: 这是用户要求的核心交付物之一，需重点完成

## [ ] Task 12: 人设规范回归验证
- **Priority**: medium
- **Depends On**: Task 4, Task 5
- **Description**: 
  - 验证批量生成的回复仍遵守屏幕隔空铁律（动作仅限屏幕那端）
  - 验证消息结构规范（thought/action标签正确使用，不嵌套）
  - 验证标签内无markdown、无引号、纯自然语言
  - 验证同一段对话可以交错多个action/thought标签
- **Acceptance Criteria Addressed**: AC-12
- **Test Requirements**:
  - `programmatic` TR-12.1: screen_action_sanitizer正确过滤违规动作
  - `human-judgement` TR-12.2: 批量回复的人设表现与单条处理一致
  - `human-judgement` TR-12.3: 无在场视角动作（伸手、拥抱等）
- **Notes**: 利用现有screen_action_sanitizer和output_self_check
