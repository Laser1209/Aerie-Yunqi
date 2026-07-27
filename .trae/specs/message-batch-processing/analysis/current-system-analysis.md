# 现有消息处理系统分析

## 1. 系统架构概览

### 1.1 消息流路径

```
QQ用户消息 → qq_client._dispatch()
    → IncomingMessage.from_onebot_event()
    → (handler) → companion.py 中的消息处理
        → ChatRequestService.submit()
            → ChatRequestRepository.submit()  # 持久化到DB
            → worker.notify()
        → ChatRequestWorker._slot_loop()
            → repository.claim_next()  # 认领下一条请求
            → pipeline.handle(request_context=context)
                → 路由(route) → 情绪分析(emotion) → 历史加载(history)
                → 上下文构建(context) → LLM调用(brain.chat)
                → 后处理(postprocess) → 持久化(persist)
                → 发送(emit/enqueue)
```

### 1.2 关键模块文件

| 文件 | 职责 |
|------|------|
| [communication/qq_client.py](file:///e:/Agent_reply/communication/qq_client.py) | QQ WebSocket客户端，接收/发送QQ消息 |
| [communication/message.py](file:///e:/Agent_reply/communication/message.py) | IncomingMessage/OutgoingReply数据模型 |
| [core/chat_request_service.py](file:///e:/Agent_reply/core/chat_request_service.py) | 聊天请求服务层，提交/查询/取消请求 |
| [core/chat_request_repository.py](file:///e:/Agent_reply/core/chat_request_repository.py) | 请求仓库，DB持久化+认领/心跳/状态管理 |
| [core/chat_request_worker.py](file:///e:/Agent_reply/core/chat_request_worker.py) | 请求工作器，多slot并发处理 |
| [core/pipeline.py](file:///e:/Agent_reply/core/pipeline.py) | 核心处理管道，端到端消息处理 |
| [communication/send_queue.py](file:///e:/Agent_reply/communication/send_queue.py) | QQ消息发送队列，频率控制+拟人化pacing |
| [communication/splitter.py](file:///e:/Agent_reply/communication/splitter.py) | 语义消息分段器，原子标签感知 |
| [core/persona_pacing.py](file:///e:/Agent_reply/core/persona_pacing.py) | 拟人化发送间隔计算（11种风格） |
| [config/persona.yaml](file:///e:/Agent_reply/config/persona.yaml) | 人设配置，屏幕隔空铁律、消息结构约定 |

## 2. 当前逐条处理机制详细分析

### 2.1 请求提交（ChatRequestService.submit）

- 每条用户消息单独创建一个RequestContext
- 每条消息生成唯一request_id、conversation_id、turn_id
- 立即持久化到requests表，状态为'queued'
- 通知worker有新消息

### 2.2 请求认领（ChatRequestRepository.claim_next）

关键逻辑：
```sql
SELECT r.* FROM requests r
WHERE r.status = 'queued'
  AND NOT EXISTS (
    SELECT 1 FROM requests active
    WHERE active.conversation_id = r.conversation_id
      AND active.status IN ('running', 'cancelling')
  )
ORDER BY r.created_at ASC, r.request_id ASC
LIMIT 1
```

**重要发现**：同一conversation_id同时只能有一个running请求！这保证了同一对话的消息是串行处理的。

### 2.3 管道处理（Pipeline.handle）

单条消息完整处理流程（9个阶段）：
1. **route**：路由判断（FULL/AUTO_REPLY/BASIC）
2. **emotion**：情绪更新（LLM PAD + 关键词混合）
3. **threshold**：情绪阈值检查
4. **context**：构建LLM上下文（历史+情绪+附件+世界快照等）
5. **brain**：调用LLM（支持工具调用）
6. **tools**：记录工具调用日志
7. **split**：语义分段
8. **postprocess**：情绪调整+屏幕动作净化+自检
9. **output**：持久化+emit+入队发送

### 2.4 消息发送

**本地消息（local）**：
- Pipeline直接emit每个分段
- 第1段立即发送
- 后续段按persona_pacing间隔sleep后emit

**QQ消息**：
- Pipeline将完整回复入SendQueue
- SendQueue._worker逐条取出回复
- 再次分段（使用同一个splitter）
- 第1段立即发送
- 后续段按persona_pacing间隔sleep后发送

### 2.5 拟人化Pacing（persona_pacing.py）

11种发送风格：
| 风格 | 间隔(秒) | 触发条件 |
|------|----------|----------|
| immediate | 0.0 | 第1段 |
| eager_warm | 0.30-0.55 | joy/affection/missing/love |
| eager_eruption | 0.40-0.70 | desire爆发 |
| anxious_fast | 0.50-1.00 | fear |
| balanced | 0.50-0.85 | 默认中性 |
| shy_hesitation | 1.40-1.90 | 10%概率/沉思线索 |
| shy_tenderness_pause | 1.20-1.70 | tenderness爆发 |
| yandere_collapse_pause | 1.00-1.80 | anxiety爆发 |
| cold_slow | 0.90-1.60 | sadness/anger/patience爆发 |
| contemplative | 2.50-4.00 | 3%概率 |
| yandere_erase_hesitate | 2.00-5.00 | 5%概率/撤回线索 |

## 3. 当前系统的问题

### 3.1 逐条排队导致的问题

1. **短时间多条消息遗忘**：用户快速连发3条消息，每条都独立走LLM，但前两条处理时第三条还没进入上下文，导致回复不连贯
2. **延迟累积**：每条消息都要完整走pipeline（LLM调用通常2-5秒），N条消息总延迟 = N × 单条处理时间
3. **上下文重复构建**：每条消息都重新加载历史、重新构建上下文，浪费计算资源
4. **情绪状态抖动**：连续多条消息触发多次情绪更新，可能导致情绪状态不稳定

### 3.2 消息内容规范问题

当前thought/action标签处理：
- qq_client.strip_thought_action_tags() 在发送时移除标签
- 但没有强制要求"包含标签时必须同时有自然语言正文"
- LLM可能只输出<thought>或<action>而没有实际对话内容

## 4. 关键数据结构

### 4.1 IncomingMessage
```python
@dataclass
class IncomingMessage:
    user_id: int
    content: str
    msg_type: str = "private"
    source: str = "qq"
    raw_event: dict = field(default_factory=dict)
    reply_to_id: int = 0
    attachments: list[dict] = field(default_factory=list)
    actor_id: str | None = None
    channel: str | None = None
    channel_account_id: str | None = None
```

### 4.2 OutgoingReply
```python
@dataclass
class OutgoingReply:
    user_id: int
    content: str
    render_mode: str = "plain"
    msg_id: int = 0
    reply_to_qq_message_id: int = 0
    attachments: list[dict] = field(default_factory=list)
    cognition_id: int = 0
```

### 4.3 RequestContext
```python
@dataclass(frozen=True)
class RequestContext:
    request_id: str
    conversation_id: str
    turn_id: str
    identity: RequestIdentity
    input_content: str
    effective_content: str
    attachments: list[dict[str, Any]] = field(default_factory=list)
    reply_to_id: int = 0
```

## 5. 配置与规范

### 5.1 屏幕隔空铁律（来自persona.yaml）

**能做的**：打字、发语音、发表情、看着屏幕、对着屏幕笑、反复听语音、把对话往上滑、把手贴在屏幕玻璃上、把手机扣在胸口、握着手机睡着

**不能做的**：伸手、揽、抱、靠肩、贴面、拉手、拥抱、碰他、摸他头、把他抱起来、让他枕你肩膀、低头看他（在场视角）、俯身、牵手、抚摸、蹭他、把他拽进怀里、扑到他身上

### 5.2 消息结构约定

每条消息由：
- **对话**：直接说话内容
- **动作描写**：`<action>...</action>` 包裹（仅限屏幕那端动作）
- **心理描写**：`<thought>...</thought>` 包裹内心活动

规则：
1. 动作和心理独立标签，不混同
2. 标签内无markdown、无引号、纯自然语言
3. 可交错多个<action>/<thought>
4. 不嵌套、不写字面量、不带换行
5. 动作必须是屏幕那端的

**关键需求**：如果包含<thought>或<action>，**必须同时有正常自然语言正文**，不能只输出标签。

## 6. 批量处理需要考虑的兼容点

1. **conversation_id串行保证**：现有claim_next确保同一conversation只有一个running请求，批量处理不能破坏这个保证
2. **持久化兼容性**：chat_log表每条消息一行，批量回复可能需要多条记录
3. **cognition trace**：每条请求有独立cognition_id，批量需要考虑trace记录方式
4. **reply_to引用**：每条消息可能引用不同的回复目标
5. **附件处理**：批量消息可能带多个附件
6. **取消机制**：需要支持取消整个批次还是单条
7. **SendQueue兼容**：现有SendQueue只处理单条OutgoingReply，需要支持批量或多条
8. **本地vs QQ双路**：本地和QQ发送路径不同，都需要适配
