# 消息批量处理与智能回复系统 - Product Requirement Document

## Overview
- **Summary**: 将现有逐条排队的消息处理机制重构为时间窗口内的批量处理模式，同时增强回复发送规则（首条即时回复、后续消息按字数比例间隔发送）和正文内容强制校验（包含标签时必须有自然语言正文）。
- **Purpose**: 解决短时间多条消息导致的遗忘、回复延迟累积、上下文不连贯问题；提升回复的自然度和及时性；确保AI回复始终包含可阅读的正文内容。
- **Target Users**: 云栖(Aerie)桌面端用户，通过QQ或桌面聊天窗口与AI伴侣交互的用户。

## Goals
- **G1**: 实现可配置时间窗口内的消息批量合并处理机制，替代逐条排队模式
- **G2**: 时间窗口内首条消息即时回复，确保响应及时性
- **G3**: 批次内后续回复按字数正比例计算发送间隔，严格按时间顺序发送
- **G4**: 强制要求任何包含<thought>/<action>标签的回复必须同时有自然语言正文
- **G5**: 保持与现有系统的兼容性（持久化、cognition trace、取消机制、本地/QQ双路发送）
- **G6**: 建立可长期维护的参考文档，支持后续迭代更新

## Non-Goals (Out of Scope)
- 不修改LLM模型本身或更换AI服务提供商
- 不重构UI界面（除必要的配置项暴露）
- 不改变现有情绪引擎、人设系统的核心逻辑
- 不实现消息已读回执或 typing indicator 等新功能
- 不支持群聊消息的批量处理（仅针对私聊）
- 不修改现有的工具调用(tool use)机制

## Background & Context

### 现有系统问题
1. **逐条排队延迟累积**：用户快速连发N条消息，每条独立走完整pipeline（2-5秒/条），总延迟N倍增长
2. **上下文不连贯/遗忘**：前两条消息处理时，第三条还未进入上下文，导致回复遗漏后续内容
3. **计算资源浪费**：每条消息重复加载历史、构建上下文、情绪更新
4. **正文缺失风险**：LLM可能只输出<thought>/<action>标签而无实际对话内容，QQ端过滤标签后出现空消息

### 现有架构基础
- ChatRequestRepository + ChatRequestWorker 已实现请求排队和多slot并发
- claim_next SQL已保证同一conversation_id串行处理（不能并发）
- Pipeline.handle() 已实现完整的9阶段处理流程
- SendQueue + persona_pacing 已实现拟人化分段发送
- screen_action_sanitizer + output_self_check + response_validator 已实现多层输出校验

### 关键约束
- 同一对话(conversation_id)必须保持串行处理，不能并发
- 必须兼容chat_log表的单条消息存储格式
- 必须支持本地聊天和QQ聊天双路发送
- 不能破坏现有的取消、心跳、重试机制
- 人设规范（屏幕隔空铁律、消息结构）必须严格遵守

## Functional Requirements

### FR-1: 批量消息收集与时间窗口
- **FR-1.1**: 系统应提供可配置的批量时间窗口参数（默认：1.5秒）
- **FR-1.2**: 当收到第一条消息时，启动时间窗口计时器
- **FR-1.3**: 在窗口时间内到达的同一用户消息应被收集到同一批次
- **FR-1.4**: 窗口超时后，将收集到的所有消息作为一个批次提交处理
- **FR-1.5**: 如果窗口内消息数达到最大批量上限（默认：5条），应提前关闭窗口并立即处理
- **FR-1.6**: 如果系统正在处理上一批次，新到消息应进入下一批次等待（不破坏串行保证）

### FR-2: 批量AI识别与处理
- **FR-2.1**: Pipeline应支持一次性处理批次内多条消息
- **FR-2.2**: 批量消息应合并构建上下文，让LLM能看到时间窗口内的所有消息
- **FR-2.3**: LLM应为批次内每条消息生成对应的回复（一对一）
- **FR-2.4**: 情绪更新应基于批次内所有消息综合计算，避免抖动
- **FR-2.5**: 历史消息加载只进行一次，供整个批次复用

### FR-3: 首条即时回复
- **FR-3.1**: 批次处理完成后，第一条回复必须立即发送（间隔=0）
- **FR-3.2**: 第一条回复发送不应等待后续回复准备完成
- **FR-3.3**: 即时回复保证用户感知的响应时间 ≤ 单条消息处理时间（相对现有系统不退化）

### FR-4: 字数比例发送间隔
- **FR-4.1**: 批次内第2条及以后的回复，发送间隔与回复字数正比例计算
- **FR-4.2**: 间隔计算公式：`interval = base_interval + (char_count / chars_per_second)`
- **FR-4.3**: base_interval默认0.5秒，chars_per_second默认4字/秒（均可配置）
- **FR-4.4**: 间隔应设置上下限：最小0.3秒，最大5.0秒
- **FR-4.5**: 间隔应在字数比例基础上叠加persona_pacing的情感因素（±30%浮动）
- **FR-4.6**: 必须严格按照消息接收的时间顺序发送回复
- **FR-4.7**: 间隔计算应在过滤<thought>/<action>标签之后，基于纯正文长度计算（标签内容不计入字数）
- **FR-4.8**: 如果某条回复过滤标签后正文为空（触发正文校验补救），该条使用最小间隔0.3秒发送
### FR-5: 正文内容强制校验
- **FR-5.1**: 任何回复在发送前必须经过"正文存在性检查"
- **FR-5.2**: 如果回复包含<thought>或<action>标签，过滤标签后必须有非空白的自然语言正文
- **FR-5.3**: 如果正文为空，必须触发补救流程：
  - FR-5.3.1: 第一次尝试：提示LLM重新生成（只输出对话正文）
  - FR-5.3.2: 如果重新生成仍然失败：使用保底回复（如"嗯？"、"在听"）
- **FR-5.4**: 正文校验失败必须记录WARN级别日志
- **FR-5.5**: 正文校验必须在screen_action_sanitizer和output_self_check之后执行

### FR-6: 持久化与兼容性
- **FR-6.1**: 批次内每条用户消息仍单独存储为chat_log记录
- **FR-6.2**: 批次内每条AI回复仍单独存储为chat_log记录
- **FR-6.3**: 同一批次的消息/回复应通过batch_id关联
- **FR-6.4**: 必须保持cognition trace记录完整性
- **FR-6.5**: 必须支持请求取消机制（取消整个批次）
- **FR-6.6**: 本地聊天和QQ聊天都必须适配批量处理
- **FR-6.7**: SendQueue应支持批量多条回复按序发送

### FR-7: 配置项
- **FR-7.1**: 在settings.yaml中添加批量处理配置段：
  ```yaml
  message_batching:
    enabled: true
    window_seconds: 1.5
    max_batch_size: 5
    base_interval_seconds: 0.5
    chars_per_second: 4
    min_interval_seconds: 0.3
    max_interval_seconds: 5.0
  ```
- **FR-7.2**: 配置项应支持热重载（通过POST /api/system/reload-config）

## Non-Functional Requirements

### NFR-1: 性能
- **NFR-1.1**: 首条消息响应时间相对现有系统不应退化（应略有改善）
- **NFR-1.2**: 3条消息批量处理总时间应 ≤ 单条处理时间 × 2（相比逐条的×3有提升）
- **NFR-1.3**: 内存占用增量不应超过20MB（批次缓冲）

### NFR-2: 可靠性
- **NFR-2.1**: 批量处理失败不应导致消息丢失
- **NFR-2.2**: 系统重启后应能恢复未完成批次的状态（可选，最终一致性可接受）
- **NFR-2.3**: 正文校验失败率应 < 1%（通过prompt优化保证）
- **NFR-2.4**: 保底回复机制必须100%可用，不能出现空消息

### NFR-3: 可维护性
- **NFR-3.1**: 批量处理逻辑应模块化，与现有Pipeline解耦
- **NFR-3.2**: 所有关键决策和参数必须记录在长期参考文档中
- **NFR-3.3**: 必须保留单条处理路径作为fallback（可通过feature flag切换）

### NFR-4: 可观测性
- **NFR-4.1**: 必须记录批量处理相关metrics（批次大小、窗口等待时间、总处理时间）
- **NFR-4.2**: 必须记录正文校验触发次数和补救结果
- **NFR-4.3**: cognition trace应标记哪些消息/回复属于同一批次

## Constraints

### Technical
- 语言：Python 3.10+（后端），JavaScript（前端）
- 框架：asyncio（异步），现有Koa/Electron架构
- 数据库：SQLite（必须兼容现有schema）
- 不能引入新的重量级依赖
- 必须兼容Windows环境

### Business
- 不破坏现有用户体验，首条回复必须即时
- 人设表现不能退化（屏幕隔空铁律等必须遵守）
- 改动必须可回滚（通过feature flag）

### Dependencies
- 依赖现有ChatRequestRepository的conversation串行保证
- 依赖现有LLM brain.chat()接口（需要支持批量消息输入）
- 依赖现有SendQueue和persona_pacing（需要扩展支持字数比例间隔）
- 依赖现有output_self_check和screen_action_sanitizer

## Assumptions

- **A1**: LLM能够理解"多条用户消息+分别回复"的prompt格式，为每条消息生成对应回复
- **A2**: 1.5秒的时间窗口足以捕捉大多数"连发"场景，又不会让单条消息用户感到明显延迟
- **A3**: 同一用户不会同时从多个channel（QQ+本地）发消息（如果发生，按现有conversation机制处理）
- **A4**: 字数比例间隔对用户感知是自然的（类似真人阅读+输入时间）
- **A5**: 保底回复（如"嗯？"）在极端情况下是可接受的降级方案

## Acceptance Criteria

### AC-1: 时间窗口消息收集
- **Given**: 用户快速连发3条消息（间隔0.5秒）
- **When**: 第一条消息到达，1.5秒窗口启动
- **Then**: 3条消息应被收集到同一批次，窗口超时后一次性提交处理
- **Verification**: `programmatic`
- **Notes**: 可通过日志验证batch_id和batch_size

### AC-2: 首条即时回复
- **Given**: 批次处理完成，包含3条回复
- **When**: 开始发送回复
- **Then**: 第1条回复应立即发送（从处理完成到首条emit ≤ 100ms）
- **Verification**: `programmatic`
- **Notes**: 对比现有系统首条回复延迟不增加

### AC-3: 字数比例间隔
- **Given**: 批次内第2条回复50字，第3条回复150字
- **When**: 计算发送间隔
- **Then**: 第2条间隔 ≈ 0.5 + 50/4 = 13.75秒（实际在1.0-1.5秒范围，叠加情感后），第3条间隔 ≈ 0.5 + 150/4 = 38秒（实际在3.0-4.5秒范围）
- **Then**: 第3条间隔必须 > 第2条间隔（字数多→间隔长）
- **Verification**: `programmatic`

### AC-4: 回复顺序保证
- **Given**: 批次内消息按时间顺序 M1 → M2 → M3 到达
- **When**: 发送回复 R1, R2, R3
- **Then**: 发送顺序必须是 R1 → R2 → R3（与接收顺序一致）
- **Verification**: `programmatic`

### AC-5: 正文强制存在
- **Given**: LLM返回只有`<action>看着屏幕笑。</action>`无正文
- **When**: 正文校验执行
- **Then**: 应触发补救流程，重新生成或使用保底回复
- **Then**: 最终发送的消息过滤标签后有非空白内容
- **Verification**: `programmatic`

### AC-6: 标签仍正确过滤（QQ端）
- **Given**: 回复包含`"在干嘛。"<action>看着屏幕。</action>`
- **When**: 发送到QQ
- **Then**: QQ端只收到"在干嘛。"，action标签被移除
- **Verification**: `programmatic`

### AC-7: 持久化完整性
- **Given**: 批次包含2条用户消息和2条AI回复
- **When**: 处理完成
- **Then**: chat_log表应有4条新记录（2 user + 2 assistant），可通过batch_id关联
- **Verification**: `programmatic`

### AC-8: 串行处理保证不破坏
- **Given**: 用户A有正在处理的批次，用户A又发新消息
- **When**: claim_next执行
- **Then**: 新消息必须等待前一批次完成后才被认领（不并发）
- **Verification**: `programmatic`

### AC-9: 本地聊天兼容
- **Given**: 通过桌面聊天窗口发送消息
- **When**: 批量处理和发送
- **Then**: 本地聊天也应正确收到批量回复（首条即时、后续按间隔）
- **Verification**: `human-judgment` + `programmatic`

### AC-10: 可配置性
- **Given**: 修改settings.yaml中window_seconds为3.0
- **When**: 热重载配置
- **Then**: 系统应使用3.0秒的新窗口值，无需重启
- **Verification**: `programmatic`

### AC-11: 自然对话体验
- **Given**: 用户正常使用聊天功能
- **When**: 批量回复发送
- **Then**: 整体对话体验应自然，间隔符合真人聊天节奏，无不自然停顿
- **Verification**: `human-judgment`

### AC-12: 人设规范遵守
- **Given**: 所有批量生成的回复
- **When**: 经过screen_action_sanitizer
- **Then**: 不应出现在场视角动作（伸手、拥抱等），动作仅限屏幕那端
- **Verification**: `programmatic` + `human-judgment`

## Open Questions

- [ ] **Q1**: LLM批量prompt格式需要确认——是用"[消息1]\n[消息2]"格式还是其他格式让LLM明确区分多条消息并分别回复？
- [ ] **Q2**: 如果批次内某条消息需要工具调用（tool use），是阻塞整个批次还是让其他消息先回复？建议：工具调用期间后续消息等待，保持顺序。
- [ ] **Q3**: 批量处理时情绪更新是基于每条消息增量更新还是基于整个批次文本一次性更新？建议：一次性综合更新，避免抖动。
- [ ] **Q4**: 时间窗口计时器精度问题——是否需要高分辨率定时器，1.5秒窗口允许±多少误差？建议：±200ms可接受。
- [ ] **Q5**: 保底回复文案需要确定——除了"嗯？"、"在听"，是否需要更多选项？建议：至少5个短句随机选择。
- [ ] **Q6**: 是否需要在UI上显示"正在输入批量处理中"状态？建议：复用现有typing状态即可，不新增UI。
