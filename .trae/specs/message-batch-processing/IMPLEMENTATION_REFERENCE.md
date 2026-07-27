# 消息批量处理与智能回复系统 - 实现参考文档

> **文档类型**：长期维护参考文档
> **创建日期**：2026-03-26
> **最后更新**：2026-03-26
> **适用范围**：核心消息处理、批量AI识别、智能发送间隔、正文强制校验

---

## 一、系统架构概览

### 1.1 处理流程对比

| 维度 | 重构前（逐条排队） | 重构后（批量处理） |
|------|-------------------|-------------------|
| 消息收集 | 单条立即处理 | 时间窗口内聚合（默认1.5s，最多5条） |
| AI识别 | 单条prompt | 批量prompt（多条消息统一上下文） |
| 首条响应 | 排队等待 | 首条即时处理（flush立即触发） |
| 发送间隔 | 固定分段间隔 | 首条即时 + 后续按字数正比例 + persona情感因子 |
| 正文保障 | 依赖LLM自觉性 | 三级强制校验（标签过滤→LLM重生成→保底回复） |
| 可观测性 | 无批量标识 | batch_id贯穿全链路日志 |

### 1.2 核心数据流图

```
用户消息
  │
  ├─ QQ消息 ──→ companion._on_qq_message()
  │                    │
  ├─ 本地HTTP ─→ companion.process_local_message_sync()
  │                    │
  └─ 异步本地 ─→ companion.submit_local_message()
                       │
                       ▼
            ┌─────────────────────┐
            │   MessageBatcher    │  ← 按conversation_id隔离
            │  ────────────────   │     时间窗口聚合
            │  submit_message()   │     max_batch_size限制
            │  flush_all()        │
            └─────────┬───────────┘
                      │ 批次就绪回调
                      ▼
            ┌─────────────────────┐
            │  _on_message_batch_ │
            │      ready()        │
            └─────────┬───────────┘
                      │
         ┌────────────┴────────────┐
         ▼                         ▼
  启用request queue?          直接pipeline
         │                         │
         ▼                         ▼
  chat_request_service.      pipeline.handle(
    submit_batch()               messages=batch,
         │                       batch_id=bid)
         ▼                         │
  chat_request_worker        ┌─────┴──────┐
    _execute_batch()         ▼            ▼
         │            ┌──────────┐  ┌──────────┐
         └───────────→│ QQ回复   │  │ 本地回复  │
                      │SendQueue │  │emit()    │
                      │enqueue_  │  │local     │
                      │batch()   │  │pacing    │
                      └────┬─────┘  └────┬─────┘
                           │             │
                           ▼             ▼
                    ┌───────────────────────┐
                    │  首条立即发送          │
                    │  后续按字数比例间隔    │
                    │  QQ端过滤标签          │
                    │  本地端保留完整内容    │
                    └───────────────────────┘
```

---

## 二、模块详细说明

### 2.1 MessageBatcher（core/message_batcher.py）

**职责**：时间窗口内的消息聚合器，单例模式。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `window_seconds` | 1.5 | 批量收集时间窗口（秒） |
| `max_batch_size` | 5 | 单批次最大消息数 |
| `flush_first_immediately` | true | 首条消息是否立即flush（首条即时回复的关键） |

**核心方法**：

| 方法 | 说明 |
|------|------|
| `submit_message(msg)` | 提交消息，按conversation_id隔离入队 |
| `flush_all()` | 立即flush所有等待批次（用于关闭、重启等场景） |
| `register_callback(cb)` | 注册批次就绪回调 `async def callback(messages: list[IncomingMessage], batch_id: str)` |
| `get_stats()` | 获取统计信息（等待批次数、消息数、已处理批次数） |

**关键设计决策**：
- 按`conversation_id`隔离（用户ID + 来源组合），不同用户的消息不混批
- 首条消息到达时立即设置计时器（而非等待窗口满），保证响应速度
- 当某批次达到`max_batch_size`时立即触发，不等窗口结束
- 单例模式通过`MessageBatcher.get_instance()`获取，避免重复创建

### 2.2 ContentValidator（core/content_validator.py）

**职责**：正文内容强制校验，确保任何回复都包含正常自然语言正文。

**三级补救机制**：

| 级别 | 触发条件 | 处理方式 |
|------|---------|---------|
| 1级 | 正文为空/只有标签 | 剥离标签，检查是否有内容 |
| 2级 | 剥离后仍无正文 | 调用LLM重新生成（重试2次） |
| 3级 | LLM重生成失败 | 使用保底回复（8种自然短句随机选择） |

**保底回复列表**：
```python
("嗯？", "在听", "怎么了？", "哦？", "继续说", "我在呢", "嗯嗯", "啊？")
```

**核心方法**：

| 方法 | 说明 |
|------|------|
| `has_meaningful_content(text)` | 检查是否包含有效正文（剥离标签后非空白） |
| `validate_and_fix(reply, llm_caller)` | 完整校验流程，返回修复后的reply |
| `get_stats()` | 获取校验统计（通过/修复/LLM重试/保底次数） |

### 2.3 SendQueue批量发送（communication/send_queue.py）

**新增方法**：`enqueue_batch(replies: list[OutgoingReply])`

**发送规则**：
1. **首条立即发送**：`sequence_index == 0`的消息立即发出，间隔0秒
2. **后续按字数间隔**：间隔 = `(字符数 / chars_per_second) + base_interval + jitter`
3. **persona情感因子叠加**：调用`compute_persona_interval`叠加情感标签影响
4. **QQ端标签过滤**：发送前调用`strip_thought_action_tags()`过滤`<thought>`和`<action>`标签
5. **按sequence_index排序**：确保消息按序发出

**间隔计算公式**：
```python
chars_per_second = 8  # 中文阅读速度约8字/秒
base_interval = 1.5   # 基础间隔
jitter = random.uniform(0, 1.0)  # 随机抖动（模拟真人不规律）

clean_content = strip_thought_action_tags(content)
char_count = len(clean_content)
interval = (char_count / chars_per_second) + base_interval + jitter
# 再叠加persona情感因子
persona_interval, _ = compute_persona_interval(...)
final_interval = max(interval, persona_interval * 0.5)
```

### 2.4 Pipeline批量处理（core/pipeline.py）

**新增参数**：`handle()`方法新增`messages`和`batch_id`参数

**批量Prompt结构**：
```
[System: persona + 屏幕隔空铁律 + 回复结构规范]
[Context: 历史消息摘要]
[Current time: 当前时间]
[Batch instructions: 以下是用户在{window_seconds}秒内发送的{N}条消息，请逐条回复]

[消息1] 用户消息（时间: xxx）
[消息2] 用户消息（时间: xxx）
...
[消息N] 用户消息（时间: xxx）

[Instructions: 
- 请按照消息顺序逐条回复，确保每条消息都有对应的正文回复
- 使用<reply index="1">...</reply>标签包裹每条回复
- 每条回复可以包含<action>、<thought>和自然语言正文
- 正文必须是正常的自然语言对话，不能只输出动作或思考
]
```

**回复解析**：从LLM输出中提取`<reply index="N">...</reply>`标签，匹配到对应消息。
- 如果解析失败或回复数不足，回退到逐条处理模式
- 每条回复创建独立的`OutgoingReply`，携带`batch_id`和`sequence_index`
- 逐条经过`ContentValidator`校验和补救

### 2.5 ChatRequest批量支持

#### Repository（core/chat_request_repository.py）
| 方法 | 说明 |
|------|------|
| `submit_batch(messages, batch_id)` | 批量提交请求，共享同一batch_id |
| `claim_remaining_batch(batch_id)` | 认领同批次中尚未被认领的请求 |
| `get_batch_requests(batch_id)` | 获取批次内所有请求 |
| `complete_batch(batch_id)` | 标记批次内所有请求为完成 |

#### Worker（core/chat_request_worker.py）
- 识别批量请求（batch_id非空且有未认领请求）
- 调用`_execute_batch()`批量处理
- 认领同批次剩余请求，避免其他slot重复处理
- 批量结果逐个发送到SendQueue

### 2.6 本地聊天Pacing（core/pipeline.py）

本地聊天通过`emit()`发送到前端event stream，也实现了批量间隔：

| 场景 | 间隔策略 |
|------|---------|
| 单条消息内分段 | 使用`compute_persona_interval`（与QQ单条一致） |
| 多条消息间（批量） | 第一条分段立即发送；消息间按字符数自适应间隔；同一消息内分段保持persona间隔 |

**本地端特性**：
- **不过滤标签**：前端UI可以展示thought/action或自行处理
- **SSE事件流**：每个分段作为独立`assistant`事件emit
- **用户消息也emit**：批量中的用户消息也会emit到前端，保证对话历史完整

---

## 三、配置项（config/settings.yaml）

```yaml
message_batching:
  # 是否启用消息批量处理（false时回退到逐条处理模式）
  enabled: true
  
  # 批量收集时间窗口（秒），推荐1.0-3.0
  window_seconds: 1.5
  
  # 单批次最大消息数，超出立即触发处理
  max_batch_size: 5
  
  # 首条消息是否立即flush（true=首条即时回复，false=等待窗口）
  flush_first_immediately: true
  
  # 批量发送时每秒处理字符数（控制字数→间隔换算）
  chars_per_second: 8
  
  # 批量消息间基础间隔（秒）
  base_interval: 1.5
  
  # 发送间隔随机抖动（0-1秒），模拟真人不规律性
  jitter_max: 1.0
  
  # 是否启用正文强制校验（建议始终启用）
  content_validation_enabled: true
  
  # LLM重生成最大重试次数
  max_regen_attempts: 2
```

**热重载**：修改配置后无需重启，`persona_loader.py`自动检测文件变化并更新配置。

**访问API**：
```python
from config.persona_loader import (
    get_message_batching_config,
    is_message_batching_enabled,
)
cfg = get_message_batching_config()
if is_message_batching_enabled():
    window = cfg["window_seconds"]
```

---

## 四、数据库Schema

### chat_log表新增字段
```sql
ALTER TABLE chat_log ADD COLUMN batch_id TEXT;
CREATE INDEX IF NOT EXISTS idx_chat_batch ON chat_log(batch_id);
```

### requests表新增字段
```sql
ALTER TABLE requests ADD COLUMN batch_id TEXT;
CREATE INDEX IF NOT EXISTS idx_requests_batch ON requests(batch_id);
```

> **注意**：首次启动时`Database`类的`_ensure_schema()`方法会自动执行迁移（检查字段是否存在，不存在则添加）。无需手动执行SQL。

---

## 五、回复发送规则详解

### 5.1 首条即时回复
- MessageBatcher收到首条消息后立即触发回调（不等时间窗口）
- 如果启用了request queue，首条消息作为独立请求提交，立即被worker认领处理
- 如果直接走pipeline，立即调用`pipeline.handle()`
- 首条回复入SendQueue后，`_compute_batch_interval`返回0，立即发送

### 5.2 后续消息字数比例间隔
- 同一批次内`sequence_index > 0`的消息，在入队时计算延迟
- 间隔与字符数成正比（字数越多，阅读/输入时间越长）
- 基准速度：8字符/秒（中文平均阅读/输入速度）
- 叠加1.5秒基础间隔 + 0-1秒随机抖动
- 再叠加persona情感因子（如激动时间隔短，思考时间隔长）

### 5.3 正文内容强制要求
**核心原则**：任何回复必须包含正常自然语言正文，不允许只输出`<action>`或`<thought>`。

**标签规范**（来自《处理AI回答问题时的规范文件》）：
- `<action>...</action>`：屏幕那端的动作（如`看着手机`、`打字`、`笑了一下`）
- `<thought>...</thought>`：内心想法
- 动作和心理各自独立一个标签，不混用
- 标签内不包含markdown、不带引号、纯自然语言
- **屏幕隔空铁律**：动作必须是"屏幕那端"的（看手机、靠椅背等），禁止"在场动作"（伸手、拥抱等）
- 正文内容在标签之外，用自然语言对话

**示例**：
```
<action>指尖在屏幕上停了一下</action>
<thought>他怎么突然问这个</thought>
你说的那个项目，我下午看了一下文档，有些地方想跟你确认。
<action>轻轻咬了咬嘴唇</action>
主要是数据接口那块，文档里写的是v2，但实际线上跑的好像还是v1？
```

---

## 六、关键文件索引

| 文件 | 职责 | 修改程度 |
|------|------|---------|
| [core/message_batcher.py](file:///e:/Agent_reply/core/message_batcher.py) | 批量消息收集器 | **新增** |
| [core/content_validator.py](file:///e:/Agent_reply/core/content_validator.py) | 正文强制校验模块 | **新增** |
| [core/database.py](file:///e:/Agent_reply/core/database.py) | 数据库Schema迁移 | 修改（添加batch_id字段+索引） |
| [config/settings.yaml](file:///e:/Agent_reply/config/settings.yaml) | 批量处理配置项 | 修改（添加message_batching段） |
| [config/persona_loader.py](file:///e:/Agent_reply/config/persona_loader.py) | 配置访问API | 修改（添加批量配置读取+热重载） |
| [communication/message.py](file:///e:/Agent_reply/communication/message.py) | 消息数据模型 | 修改（OutgoingReply添加batch_id、sequence_index） |
| [communication/send_queue.py](file:///e:/Agent_reply/communication/send_queue.py) | 发送队列 | 修改（添加enqueue_batch、字数间隔计算） |
| [core/pipeline.py](file:///e:/Agent_reply/core/pipeline.py) | 处理核心管道 | 修改（批量处理模式、批量prompt、本地pacing） |
| [core/chat_request_repository.py](file:///e:/Agent_reply/core/chat_request_repository.py) | 请求仓储 | 修改（批量submit/claim/complete方法） |
| [core/chat_request_worker.py](file:///e:/Agent_reply/core/chat_request_worker.py) | 请求工作器 | 修改（添加_execute_batch批量处理） |
| [core/chat_request_service.py](file:///e:/Agent_reply/core/chat_request_service.py) | 请求服务 | 修改（添加submit_batch方法） |
| [core/companion.py](file:///e:/Agent_reply/core/companion.py) | 系统入口 | 修改（集成MessageBatcher、双路适配） |
| [core/api_server.py](file:///e:/Agent_reply/core/api_server.py) | HTTP API | 修改（本地消息入口适配） |
| [communication/qq_client.py](file:///e:/Agent_reply/communication/qq_client.py) | QQ客户端 | 未修改（标签过滤已存在，发送前自动执行） |

---

## 七、日志与可观测性

### 7.1 关键日志标记

| 日志前缀 | 含义 |
|---------|------|
| `[MessageBatcher]` | 批量收集器事件（入队、触发、flush） |
| `[batch:<id>]` | 贯穿全链路的批次标识 |
| `[ContentValidator]` | 正文校验事件（通过/修复/重试/保底） |
| `[SendQueue] batch enqueue` | 批量入队事件（含size、首条/后续间隔） |
| `[Pipeline] batch handling` | Pipeline批量处理开始/结束 |

### 7.2 示例日志
```
[MessageBatcher] Batch ready: conv=qq:123456, size=3, bid=b0ea4fd7..., window=1.5s
[Pipeline] batch handling: bid=b0ea4fd7..., messages=3
[ContentValidator] Reply 0 passed validation (content length=42)
[ContentValidator] Reply 1 had only tags, fixed by stripping (content length=28)
[SendQueue] batch enqueue: bid=b0ea4fd7..., size=3
[SendQueue] batch reply seq=0 (first, send immediately), chars=42
[SendQueue] batch reply seq=1, chars=85, interval=12.1s
[SendQueue] batch reply seq=2, chars=31, interval=5.4s
```

---

## 八、回退与降级策略

### 8.1 批量处理关闭
设置`message_batching.enabled: false`可完全回退到原逐条处理模式：
- MessageBatcher收到消息后立即触发回调（窗口=0效果）
- Pipeline以单条模式处理
- SendQueue使用原有单条enqueue逻辑

### 8.2 批量解析失败
- 如果LLM返回的`<reply>`标签解析失败
- 或解析出的回复数与消息数不匹配
- Pipeline自动回退到逐条处理模式

### 8.3 正文校验极端情况
- LLM连续2次重生成仍无有效正文
- 使用保底回复（自然短句），保证不会发空消息或纯标签消息

---

## 九、测试与验证

### 9.1 已验证项（2026-03-26）
- ✅ 所有模块Python语法编译通过
- ✅ 所有模块可正常导入（无ImportError）
- ✅ 数据库自动迁移成功（batch_id字段+索引）
- ✅ MessageBatcher单例创建、消息入队、窗口触发、按conversation_id隔离
- ✅ ContentValidator正文检测正确（纯标签→False，混合内容→True）
- ✅ ContentValidator保底回复加载（8种自然短句）
- ✅ OutgoingReply模型支持batch_id和sequence_index字段
- ✅ SendQueue存在enqueue_batch和_compute_batch_interval方法
- ✅ 配置正确加载（enabled=True, window=1.5s, max_batch=5）

### 9.2 建议手动测试场景

| 场景 | 预期结果 |
|------|---------|
| 发送单条QQ消息 | 立即收到回复，无明显延迟 |
| 1.5秒内快速发3条QQ消息 | 首条立即回复，第2、3条按字数间隔依次回复 |
| 回复中只有`<action>`标签 | 自动修复，追加保底回复或重新生成正文 |
| 通过本地UI发送消息 | 收到带thought/action的完整回复（不过滤标签） |
| 修改配置禁用batching | 回退到逐条处理模式 |
| 发送超长消息（>200字） | 回复间隔较长（字数比例），分段发送自然 |

---

## 十、后续维护指南

### 10.1 调整批量参数
修改`config/settings.yaml`中`message_batching`段，热重载自动生效。

**调参建议**：
- 响应太快/AI经常漏看后续消息 → 增大`window_seconds`（如2.0-3.0）
- 响应太慢/等待过久 → 减小`window_seconds`（如1.0）
- 批量太多导致回复质量下降 → 减小`max_batch_size`（如3）
- 发送间隔太短/不像真人 → 增大`base_interval`或减小`chars_per_second`

### 10.2 添加新的消息来源
1. 在`companion.py`中创建入口方法
2. 调用`self._submit_incoming_message(msg)`提交到MessageBatcher
3. 确保消息正确设置`conversation_id`（用于隔离批次）
4. 在Pipeline的发送路由中添加对应source的处理（如非QQ、非本地，需扩展emit逻辑）

### 10.3 修改正文校验规则
编辑`core/content_validator.py`：
- 修改`has_meaningful_content()`调整有效内容判定逻辑
- 修改`FALLBACK_REPLIES`添加/修改保底回复
- 在`validate_and_fix()`中添加新的补救级别

### 10.4 修改发送间隔算法
编辑`communication/send_queue.py`的`_compute_batch_interval()`方法，或调整参数配置。

---

## 十一、规范摘要（AI回复内容规则）

### 11.1 屏幕隔空铁律
**白名单**（屏幕那端的动作）：
- 看手机、盯着屏幕、打字、滑动、停顿
- 靠在椅背上、歪头、皱眉、笑了一下
- 咬嘴唇、叹气、深呼吸、闭上眼睛想了想
- 拿起水杯喝了一口、伸了个懒腰

**黑名单**（在场动作，禁止）：
- 伸手、拥抱、拍肩、摸头
- 走到身边、坐在旁边
- 递东西、牵手
- 任何需要"在你身边"才能做的动作

### 11.2 消息结构
- `<action>`和`<thought>`独立标签，不嵌套、不混用
- 标签内纯自然语言，无markdown、无引号、无换行
- 正文在标签之外，正常自然语言对话
- 交错穿插，按出现顺序排列

### 11.3 核心原则
- **首条即时回复**：不让用户等待
- **字数比例间隔**：字数多→间隔长，模拟真实输入
- **正文必须存在**：不允许只输出动作/思考
- **标签只出现在标签内**：正文文本中不出现`<action>`字面量

---

## 十二、决策记录

| 决策 | 理由 | 替代方案 |
|------|------|---------|
| 时间窗口1.5秒 | 平衡响应速度和批量合并率 | 固定N条（死板）、2s+（等待久） |
| 首条立即flush | 保证用户感知"秒回" | 等窗口结束（延迟明显） |
| 按conversation_id隔离 | 不同用户消息不混批 | 全局队列（会串上下文） |
| 三级校验机制 | 确保极端情况也有正文 | 依赖LLM自觉（不可靠） |
| 字数比例间隔 | 模拟真人阅读/输入节奏 | 固定间隔（机械感） |
| QQ端过滤标签 | QQ是纯文本聊天 | 发送标签（用户看到XML标签） |
| 本地端保留标签 | UI可渲染thought/action | 过滤（前端无法展示动作/想法） |
| 保底回复用短句 | 避免长文本不自然 | 长段道歉（不像真人） |

---

*本文档为长期维护参考，每周迭代时同步更新。如有架构变更或新的决策，请追加到对应章节。*
