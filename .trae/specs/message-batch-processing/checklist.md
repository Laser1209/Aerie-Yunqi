# 消息批量处理与智能回复系统 - Verification Checklist

## 数据库与配置
- [ ] Checkpoint 1: chat_log表已添加batch_id字段，现有数据batch_id为NULL
- [ ] Checkpoint 2: 迁移脚本可重复执行（幂等性）
- [ ] Checkpoint 3: settings.yaml包含message_batching配置段，默认值正确
- [ ] Checkpoint 4: 配置支持热重载（POST /api/system/reload-config生效）
- [ ] Checkpoint 5: enabled=false时系统完全回退到原有单条处理模式

## 批量消息收集器
- [ ] Checkpoint 6: MessageBatcher按conversation_id隔离批次，不同用户互不干扰
- [ ] Checkpoint 7: 首条消息到达后启动1.5秒窗口计时器
- [ ] Checkpoint 8: 窗口内（0.5秒间隔）连发3条消息被收集到同一批次
- [ ] Checkpoint 9: 达到max_batch_size(5条)时立即提交，不等待窗口超时
- [ ] Checkpoint 10: 窗口超时后批次正确提交，生成唯一UUID batch_id
- [ ] Checkpoint 11: 系统正在处理上一批次时，新消息进入下一批次等待（不并发）

## Pipeline批量处理
- [ ] Checkpoint 12: Pipeline.handle()支持接收消息列表（批量模式）
- [ ] Checkpoint 13: 批量处理时历史消息只加载一次（通过日志/调用计数验证）
- [ ] Checkpoint 14: 情绪更新基于批次内所有消息综合计算
- [ ] Checkpoint 15: LLM prompt明确指示为每条消息分别回复
- [ ] Checkpoint 16: LLM返回的多条回复正确解析，顺序与输入消息一致
- [ ] Checkpoint 17: 每条用户消息对应恰好一条AI回复（一对一）
- [ ] Checkpoint 18: 批量回复上下文连贯，能看到时间窗口内所有消息内容

## 回复发送规则
- [ ] Checkpoint 19: 批次首条回复在处理完成后100ms内发送（即时回复）
- [ ] Checkpoint 20: 首条回复发送不等待后续回复准备完成
- [ ] Checkpoint 21: 后续回复间隔按字数正比例计算（50字≈1-1.5秒，150字≈3-4.5秒）
- [ ] Checkpoint 22: 间隔计算公式：interval = base_interval + (char_count / chars_per_second)
- [ ] Checkpoint 23: 字数计算基于过滤<thought>/<action>标签后的纯正文长度
- [ ] Checkpoint 24: 间隔叠加persona_pacing情感因素（±30%浮动）
- [ ] Checkpoint 25: 间隔钳制在[0.3秒, 5.0秒]范围内（不超出上下限）
- [ ] Checkpoint 26: 回复严格按消息接收的时间顺序发送
- [ ] Checkpoint 27: 空正文补救回复使用最小间隔0.3秒

## 正文内容强制校验
- [ ] Checkpoint 28: 正文存在性检查在标签过滤后执行
- [ ] Checkpoint 29: 只有<thought>/<action>标签无正文的回复被正确识别
- [ ] Checkpoint 30: 第一次正文缺失触发LLM重新生成（提示只输出正文）
- [ ] Checkpoint 31: 重新生成仍失败时使用保底回复（至少5个短句随机选择）
- [ ] Checkpoint 32: 最终发送的消息过滤标签后一定有非空白内容（无空消息）
- [ ] Checkpoint 33: 正文校验失败记录WARN级别日志
- [ ] Checkpoint 34: 正文校验集成在screen_action_sanitizer和output_self_check之后

## QQ端与本地聊天
- [ ] Checkpoint 35: QQ新消息先进入MessageBatcher而非直接入队
- [ ] Checkpoint 36: 本地聊天新消息同样进入MessageBatcher
- [ ] Checkpoint 37: QQ端<thought>/<action>标签正确过滤，只显示正文
- [ ] Checkpoint 38: QQ发送前is_logged_in检查和wait_for_login逻辑保持正常
- [ ] Checkpoint 39: 本地聊天和QQ聊天批量回复体验一致（首条即时、后续按间隔）

## 持久化与兼容性
- [ ] Checkpoint 40: 批次内每条用户消息单独存储为chat_log记录
- [ ] Checkpoint 41: 批次内每条AI回复单独存储为chat_log记录
- [ ] Checkpoint 42: 同一批次记录通过batch_id可关联查询
- [ ] Checkpoint 43: cognition trace记录完整且标记batch_id
- [ ] Checkpoint 44: 请求取消机制可取消整个批次
- [ ] Checkpoint 45: SendQueue支持批量多条回复按序入队和发送
- [ ] Checkpoint 46: 不破坏现有心跳、重试、错误处理机制

## 可观测性
- [ ] Checkpoint 47: 日志包含batch_id、batch_size、window_wait_ms等批次信息
- [ ] Checkpoint 48: 记录批次大小分布、窗口等待时间、总处理时间metrics
- [ ] Checkpoint 49: 记录正文校验触发次数、重新生成成功次数、保底回复使用次数
- [ ] Checkpoint 50: 记录实际发送间隔值，可验证字数-间隔对应关系

## 性能指标
- [ ] Checkpoint 51: 首条消息响应时间相对现有系统不退化（甚至略有改善）
- [ ] Checkpoint 52: 3条消息批量处理总时间 ≤ 单条处理时间 × 2
- [ ] Checkpoint 53: 内存占用增量不超过20MB（批次缓冲）
- [ ] Checkpoint 54: 正文校验失败率 < 1%

## 人设规范遵守
- [ ] Checkpoint 55: 批量回复遵守屏幕隔空铁律（动作仅限屏幕那端，无在场动作）
- [ ] Checkpoint 56: thought/action标签正确使用，不嵌套、无markdown、纯自然语言
- [ ] Checkpoint 57: 同一段对话可交错多个action/thought标签
- [ ] Checkpoint 58: 标签内不带换行
- [ ] Checkpoint 59: 人设表现与单条处理时一致，无退化

## 端到端场景验证
- [ ] Checkpoint 60: 场景1 - 单发1条消息：正常回复，无不必要延迟（作为对照）
- [ ] Checkpoint 61: 场景2 - 连发2条消息（间隔0.5秒）：合并为一批，首条即时，第2条按字数间隔
- [ ] Checkpoint 62: 场景3 - 连发5条消息（间隔0.3秒）：达到max_batch_size立即处理
- [ ] Checkpoint 63: 场景4 - 连发6条消息（间隔0.3秒）：前5条一批，第6条进入下一批
- [ ] Checkpoint 64: 场景5 - 慢速发消息（间隔3秒）：每条独立成批（等同于原有模式）
- [ ] Checkpoint 65: 场景6 - LLM返回只有标签无正文：触发补救，最终有内容发送
- [ ] Checkpoint 66: 场景7 - feature flag关闭：完全回退到原有逐条处理模式
- [ ] Checkpoint 67: 场景8 - 两个不同用户同时发消息：批次隔离，互不影响
- [ ] Checkpoint 68: 场景9 - 处理中用户取消：整个批次取消，不发送部分回复
- [ ] Checkpoint 69: 场景10 - 重启应用：无数据损坏，历史记录可正常读取

## 长期参考文档
- [ ] Checkpoint 70: reference.md文档已创建，结构清晰
- [ ] Checkpoint 71: 包含系统架构概览和批量处理流程图
- [ ] Checkpoint 72: 包含关键模块说明和配置项说明
- [ ] Checkpoint 73: 包含回复发送规则详解和正文校验规则
- [ ] Checkpoint 74: 包含故障排查指南
- [ ] Checkpoint 75: 包含维护日志模板，支持每周迭代更新
- [ ] Checkpoint 76: 包含回滚指南（如何快速切换回单条模式）

## 代码质量
- [ ] Checkpoint 77: 批量处理逻辑模块化，与现有Pipeline解耦
- [ ] Checkpoint 78: 单条处理路径保留作为fallback，代码不冗余
- [ ] Checkpoint 79: 所有新增代码有适当的日志记录
- [ ] Checkpoint 80: 无硬编码魔法值，所有参数通过配置控制
