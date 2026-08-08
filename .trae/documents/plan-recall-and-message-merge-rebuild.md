---
title: Aerie 三端撤回与消息合并重构计划
date: 2026-08-09
tags:
  - plan
  - recall
  - message-merge
  - multi-channel
status: draft
---

# Aerie 三端撤回与消息合并重构计划

> [!abstract] 一句话
> 把当初设计得不成熟的「撤回」和「消息批量处理」重写为：**按端口(QQ/本地/未来微信)解耦的撤回系统 + LLM 主动撤回指令 + 首条立即/动态合并的消息编排**，全程带 Gate 门锁与量化达标标准。

> [!warning] 三个必须遵守的工程原则
> 1. **三端必须解耦，禁止混在一起** —— 撤回能力按 `channel` 分派，绝不共用单一 `user_id` 记录。
> 2. **改动必须可回滚** —— 每一 Gate 都有 feature flag 兜底，任何一步不达标即可整体回退到上一门锁。
> 3. **先冻结基线再动手** —— 用现有测试跑出基线，避免重构引发隐性回归。

> [!success] 当前落地状态（2026-08-09 复核）
> - ✅ **Gate 1 三端撤回抽象层 —— 已落地**：`communication/recall/` 五文件就位，`RecallManager` 已按 `(channel, account)` 解耦。
> - ✅ **Gate 2 LLM 主动撤回指令 —— 已落地**：`core/recall_instruction.py` + pipeline `_handle_recall_instruction` 接入。
> - ✅ **Gate 3 本地端撤回补全 —— 已落地**：`companion.recall_message` 通用化。
> - ✅ **Gate 4 消息合并重构 —— 已落地**：`message_batcher.py` 首条立即 + 动态缓冲；**但 5 个旧测试需更新**（见 §6.4）。
> - ⏳ **Gate 5 撤回判断联动 —— 未实现**：`message_orchestrator.py` / `RecallJudge` 尚不存在。
> - ⏳ **Gate 6 微信调研归档 —— 未实现**：调研文档未创建。

---

## 0. 现状分析（Phase 1 探索结论）

### 0.1 撤回现状 —— 三端情况

| 端口 | 真实撤回能力 | 触发方式 | 现状代码 |
|---|---|---|---|
| **QQ 端** | ✅ 有（NapCat `delete_msg`） | 用户负面话自动 / 手动按钮 | [qq_client.py](file:///e:/Agent_reply/communication/qq_client.py#L474) `recall_message` |
| **本地/桌面端** | ⚠️ 只能标记，无真实删除 | 手动按钮 | [chat.js](file:///e:/Agent_reply/electron/src/renderer/js/chat.js#L1353) `_recallMessage` |
| **微信端** | ❌ 无（仅 `clawbot` 桩） | — | [companion_channel.py](file:///e:/Agent_reply/core/companion_channel.py#L138) `ClawBotChannelAdapter` |

### 0.2 关键缺陷（本轮要修的）

> [!bug] 缺陷清单
> - **D1｜AI 主动撤回根本不存在**：`config/persona.yaml` 的 `recall.triggers: [send_after_thinking, regret_correction]` 是**死配置**，全仓库无任何代码消费。你从未见过 AI 主动撤回——因为它确实从未实现过。
> - **D2｜三端绑定在一起**：`RecallManager` 按单一 `user_id` 记录（[recall_manager.py](file:///e:/Agent_reply/communication/recall_manager.py#L92-L94)），未区分 channel；`pipeline.py` 硬编码 `source == "qq"`（[pipeline.py](file:///e:/Agent_reply/core/pipeline.py#L235)）。
> - **D3｜本地端撤回是坏的**：撤回 API 强制要求 `qq_message_id`（[companion.py](file:///e:/Agent_reply/core/companion.py#L1026)），纯本地消息会返回 `no_qq_message_id` 错误。
> - **D4｜`<action>` 不是可执行指令**：它只是人设动作描写（纯文本），发送时被 `re.sub(r'<action>.*?</action>', '', text)` 过滤（[pipeline.py](file:///e:/Agent_reply/core/pipeline.py#L2652)），框架不执行它。所以不能直接把撤回挂进 `<action>`。
> - **D5｜消息合并是"固定窗口"**：`MessageBatcher` 首条也要等 1.5s 窗口（[message_batcher.py](file:///e:/Agent_reply/core/message_batcher.py#L157-L168)），与你"首条立即"的构想冲突。

### 0.3 微信端行业调研结论（供后续调取）

> [!tip] 微信端结论（2026-08-09 实测调研）
> 腾讯 **2026-03 官方开放「微信 ClawBot」**（OpenClaw 平台，底层 **iLink 协议**，接入域名 `ilinkai.weixin.qq.com`），对应代码 `CHANNEL_CLAWBOT`。
>
> **⚠️ 撤回能力关键结论**：iLink 协议 `WeixinMessage` 结构含 `delete_time_ms`（删除时间戳）字段，但**协议层无独立的 revoke/撤回端点**（仅 getupdates / sendmessage / sendtyping / getconfig / upload 等）。因此 **ClawBot 官方通道当前无法可靠撤回自己消息**。
>
> 撤回能力替代结论：
> - **WeChatFerry（wcf）**：Windows DLL 注入，`revoke_msg` 明确支持撤回自己消息，但需特定微信版本、有封号风险（非官方）。
> - **Wechaty + PadLocal**：iPad 协议，商业 token，撤回能力需按方案确认。
>
> 本轮**只做架构预留 + 调研归档，不接真实微信**。当 ClawBot 官方暴露 revoke 端点后再接。详细调研见 [[Aerie_微信接入调研与方案]]。

### 0.4 现有批处理链路（合并重构的落点）

```
MessageBatcher(1.5s窗口)
  → companion._on_message_batch_ready
  → chat_request_service.submit_batch(messages, batch_id)
  → repository.submit_batch（每条一个 request，共享 batch_id）
  → worker._notify_worker
  → worker.claim_next + claim_remaining_batch(batch_id)
  → pipeline.handle(..., batch_id=...)
```

---

## 1. 目标架构总览

> [!info] 目标状态机（每个 conversation）
> ```
> IDLE --收到首条--> START(立即提交首条)
>   ├─ 处理中收到新消息 --> PENDING_BUFFER(不打断,缓冲)
>   │     └─ 当前完成后 --> 新消息作为新批次
>   └─ 首条已发出,又收到新消息 --> RECALL_JUDGE(撤回判断)
>         ├─ 需撤回 --> recall(按端口) + 新消息合并重算
>         └─ 不需撤回 --> 新消息作为新批次
> ```

### 1.1 新增/重构的核心组件

| 组件 | 类型 | 职责 | 位置 |
|---|---|---|---|
| `RecallAdapter` 协议 + 三端实现 | 新增 | 统一撤回接口，按端口分派 | `communication/recall/` |
| `RecallManager` | 重构 | 按 `(channel, account)` 记录 + 通过 Adapter 执行 | `communication/recall_manager.py` |
| `recall_instruction.py` | 新增 | 解析并执行 LLM 的 `<recall>` 指令 | `core/recall_instruction.py` |
| `MessageOrchestrator` | 新增 | 首条立即 + 缓冲 + 撤回判断联动 | `core/message_orchestrator.py` |
| 微信调研文档 | 新增 | 归档行业做法，供后续调取 | `documents/Agent_v/微信接入调研与方案.md` |

---

## 2. Gate 0 —— 基线冻结（进入条件）

> [!todo] 产出
> 1. 运行现有测试基线：`python -m pytest tests/test_recall.py tests/test_communication.py tests/test_pipeline.py tests/test_message_batcher.py -q`
> 2. 记录：`_pytest_gate0_baseline.txt` 存当前 pass/fail 数。

> [!success] 门锁 Gate0 达标标准
> - [ ] 基线测试命令可运行，失败数记录在案
> - [ ] 确认 `recall.triggers` 无消费方（用 `grep -rn "regret_correction" --include=*.py` 应只命中配置/测试，无业务调用）
> - [ ] 确认本地端撤回 `no_qq_message_id` 缺陷可复现

**回滚**：不涉及代码改动，无回滚风险。

---

## 3. Gate 1 —— 端口撤回抽象层（三端解耦）

> [!note] 目标
> 建立 `RecallAdapter` 抽象，把"撤回"从单一 `user_id` 绑定中拆出来，按 `channel` 分派。这是后续一切撤回功能的地基。

### 3.1 新增 `communication/recall/` 包

**`communication/recall/__init__.py`** —— 导出工厂 `get_recall_adapter(channel)`。

**`communication/recall/base.py`** —— 定义协议：

```python
class RecallOutcome:  # dataclass
    channel: str
    recalled: bool          # 平台侧是否真的撤回了
    reason: str             # "ok" / "unsupported" / "no_msg_id" / "window_expired"
    msg_id: int = 0
    remote_message_id: str | None = None

class RecallAdapter(Protocol):
    channel: str
    def can_recall(self, record) -> tuple[bool, str]: ...
    async def recall(self, record) -> RecallOutcome: ...
    def local_mark_only(self) -> bool: ...  # True=仅本地标记, 无真实平台撤回
```

**`communication/recall/qq.py`** —— `QQRecallAdapter`：`recall()` 调 `qq_client.recall_message(record.qq_message_id)`，无 `qq_message_id` 时返回 `no_msg_id`。

**`communication/recall/local.py`** —— `LocalRecallAdapter`：`local_mark_only()=True`，`recall()` 直接返回 `recalled=True, reason="local_mark"`（本地撤回 = DB 标记 + 前端事件，见 Gate 3）。

**`communication/recall/wechat_stub.py`** —— `WeChatClawbotAdapter`：**仅桩**，`can_recall` 恒 `(False, "not_implemented")`，`recall()` 返回 `unsupported`。预留 `channel="clawbot"`。

**`communication/recall/factory.py`** —— 按 channel 返回对应 Adapter，未知 channel 回退 `LocalRecallAdapter`。

### 3.2 重构 `communication/recall_manager.py`

> [!warning] 改动点
> - `_last_sent: dict[int, SentRecord]` → `dict[tuple[str, str], SentRecord]`，key = `(channel, channel_account_id)`。
> - `SentRecord` 增加 `channel: str`、`channel_account_id: str` 字段。
> - `record_sent`、`try_recall`、`can_recall`、`handle_user_negative`、`reset_session` 全部改为接收 `channel` 参数。
> - `try_recall` 内部：用 `get_recall_adapter(record.channel)` 分派真实撤回；无论平台是否撤回，都做 DB 标记 + emit `recall` 事件。
> - 保留 `qq_message_id`（QQ 专用）与 `msg_id`（chat_log.id，全端通用）两个字段。

**改动文件**：`communication/recall_manager.py`

### 3.3 门锁 Gate1 达标标准

> [!success] 达标标准（全部可单测验证）
> - [ ] `communication/recall/` 五个文件就位，无循环依赖
> - [ ] 新增 `tests/test_recall_adapters.py`：QQ 有 id 可撤 / QQ 无 id 返回 no_msg_id / 本地 local_mark / 微信 unsupported，4 类断言全过
> - [ ] 既有 `tests/test_recall.py` 全部通过（兼容签名改造）
> - [ ] 同一 `user_id` 在 qq 与 local 两个 channel 互不干扰（隔离单测）

**回滚**：feature flag `recall.channel_adapter_enabled` 默认 true；置 false 时 `get_recall_adapter` 回退到旧的单 user 逻辑（保留旧路径到 Gate 2 结束再删）。

---

## 4. Gate 2 —— LLM 主动撤回指令

> [!note] 目标
> 让 AI 能通过**输出撤回指令**主动撤回自己上一条已发消息。这是本次最核心的新能力。

### 4.1 新指令格式（与 `<action>` 严格区分）

> [!important] 指令设计
> 新增 `<recall>` 可执行指令，**与现有 `<action>`（人设动作描写·纯文本）完全分离**：
> ```xml
> <recall reason="说错话了">这条我撤回</recall>
> ```
> - `<action>` → 人设描写，发送时被过滤，**不执行**
> - `<recall>` → 框架指令，**执行撤回**，且从正文中剔除

### 4.2 新增 `core/recall_instruction.py`

**职责**：在 pipeline 阶段 7（sanitize 之后）解析 LLM 原始输出。

```python
RECALL_RE = re.compile(r"<recall[^>]*>(.*?)</recall>", re.DOTALL)

def extract_recall_instruction(raw: str) -> RecallInstruction | None
    # 返回 {reason, raw_tag}，或 None

async def execute_recall_instruction(recall_manager, channel, account, reason) -> RecallOutcome
    # 校验 can_recall → 调 recall_manager.try_recall(channel, account, reason="llm_instruction")
    # 成功后 emit("recall", ...) 供前端呈现
```

### 4.3 修改 `core/pipeline.py`

**改动点**（在 `_handle_batch` / 单条路径的阶段 7 处理处，即现有 `sanitize` 调用点附近）：
1. 拿到 LLM 原始回复后，先调 `extract_recall_instruction(raw)`。
2. 若存在指令：
   - 用当前 request 的 `channel`/`channel_account_id` 调 `execute_recall_instruction(...)` 撤回上一条 AI 消息。
   - 日志记录 `reason`。
3. 把 `<recall>...</recall>` 标签从正文中剔除（`re.sub(RECALL_RE, "", raw)`），确保撤回指令不发送给用户。
4. 其余正文正常走 sanitize → output_self_check → emit。

**改动文件**：`core/pipeline.py`（阶段7处理处）、`core/recall_instruction.py`（新增）

### 4.4 修改 `core/brain.py` / prompt

> [!note] Prompt 引导
> 在系统 prompt 中告知 AI：当你想表达"说完就后悔/这句不该说/想收回"时，可在回复中附带 `<recall reason="原因">`，框架会自动撤回你上一条已发送的消息。**不承诺每次都撤回**，避免 AI 滥用。
> 同时在 `config/persona.yaml` 的 `recall.triggers` 下**激活** `send_after_thinking` / `regret_correction`，作为 LLM 使用该指令的行为提示（不再是死配置）。

**改动文件**：`core/brain.py`（prompt 组装）、`config/persona.yaml`、`core/persona_pacing.py`（如需人设节奏关联）

### 4.5 门锁 Gate2 达标标准

> [!success] 达标标准
> - [x] `tests/test_recall_instruction.py`：提取/剔除/无指令三种情况单测通过
> - [x] 集成测试：模拟 LLM 输出含 `<recall>` → 断言 `try_recall` 被调、上一条 DB 标记 `is_recalled=1`、正文不含 `<recall>` 标签
> - [ ] E2E（手动/脚本）：在 QQ 端让 AI 输出撤回指令，观测 NapCat 收到 `delete_msg`，前端气泡变"（消息已撤回）"
> - [x] `regret_correction` 从死配置变为有消费方（`grep` 能命中 pipeline 调用链）

**回滚**：feature flag `recall.llm_instruction_enabled`；置 false 则 `extract_recall_instruction` 恒返回 None（零行为变化）。

---

## 5. Gate 3 —— 客户端（本地端）撤回补全

> [!note] 目标
> 修复 D3：让**纯本地消息**也能撤回（本地撤回 = DB 标记 `is_recalled=1` + 前端呈现"已撤回"），不再报 `no_qq_message_id`。

### 5.1 修改 `core/api_server.py`

**`POST /api/chat/recall/{msg_id}`**（现 [api_server.py](file:///e:/Agent_reply/core/api_server.py#L2051)）：
- 改为通过 `get_recall_adapter(msg.channel)` 分派，而不是写死 QQ。
- 本地消息：走 `LocalRecallAdapter` → DB 标记 + emit 事件，`qq_recalled=false`。
- QQ 消息：走 `QQRecallAdapter` → 真实 delete_msg + DB 标记。
- 移除对 `qq_message_id` 的强制要求（改为：有则调 QQ，无则本地标记）。

### 5.2 修改 `core/companion.py`

**`recall_qq_message`**（[companion.py](file:///e:/Agent_reply/core/companion.py#L1015)）：
- 改名/改造为通用 `recall_message`，经 adapter 分派，去掉 `only_assistant...no_qq_message_id` 的写死限制。
- `chat_log` 需保证含 `channel` 字段（Gate 5 前确认 schema；若缺，从 row 推断或补 migration）。

### 5.3 前端（已有基础，仅核对）

`electron/src/renderer/js/chat.js` 的撤回 UI（`_recallMessage`）已存在，本地撤回会经 `emit("recall")` 把气泡变"（消息已撤回）"（[chat.js](file:///e:/Agent_reply/electron/src/renderer/js/chat.js#L381)）。本轮只需确保本地撤回事件能触发该渲染。

**改动文件**：`core/api_server.py`、`core/companion.py`（+ 可能的 migration）

### 5.4 门锁 Gate3 达标标准

> [!success] 达标标准
> - [x] 纯本地消息通过 `/api/chat/recall/{id}` 成功标记，返回 `qq_recalled=false`，不再报错
> - [x] 前端气泡显示"（消息已撤回）"
> - [x] `tests/test_desktop_shared_api_contract.py` 及撤回相关测试通过

**回滚**：flag `recall.local_recall_enabled`；置 false 恢复旧写死逻辑。

---

## 6. Gate 4 —— 消息合并重构（首条立即 + 动态缓冲）

> [!note] 目标
> 修复 D5：首条消息**立即提交处理**（不再等 1.5s 窗口）；处理期间到达的新消息进入**待并入缓冲**，当前批完成后作为新批处理。

### 6.1 修改 `core/message_batcher.py`

**核心改造**：
1. 新增 `_pending_buffer: dict[conversation_id, list[IncomingMessage]]`：首条提交后，后续消息先进缓冲，**不阻塞首条**。
2. `submit_message`：首条 → 立即 `_dispatch_batch([msg], new_batch_id)`（不再等窗口）；后续 → 进缓冲。
3. 监听当前批完成信号（`_on_batch_completed`，由 worker/pipeline 完成事件驱动）：完成时若有缓冲消息 → 把它们作为新批次 dispatch。
4. 保留 `max_batch_size`、`window_seconds` 作为缓冲批次的封顶参数（缓冲满了/超窗才提前 dispatch）。

**改动文件**：`core/message_batcher.py`

### 6.2 修改 `core/chat_request_worker.py`

- 在批次完成处（`_execute_batch_claimed` 的 finally）广播 `batch_completed` 事件（含 conversation_id），供 `MessageBatcher` 消费以触发缓冲批次 dispatch。
- 或在 `companion._on_message_batch_ready` 回调链中追加完成回调。

**改动文件**：`core/chat_request_worker.py`、`core/companion.py`

### 6.4 待更新测试（Gate 4 已落地，5 个旧测试断言旧"固定窗口"语义）

> [!warning] 必须处理的回归
> 重构后 `tests/test_message_batcher.py` 有 5 个用例仍断言旧语义（首条也要等窗口），现全部失败：
> - `test_time_window_collects_multiple_messages`：旧期望 0→1 批；新语义应为 **首条立即 1 批 + 缓冲合并 1 批 = 2 批**。
> - `test_max_batch_size_triggers_immediate_dispatch`：旧期望窗口内 0 批；新语义首条立即 dispatch。
> - `test_conversation_isolation`：旧期望 `[2,2]`；新语义应为 `[1,1,1,1]` 或按完成钩子合并。
> - `test_flush_all_dispatches_all_active_batches`：旧期望 pending 未 dispatch；新语义首条已立即 dispatch。
> - `test_max_size_then_next_message_starts_new_batch`：首条立即后，后续缓冲合并语义变化。

> [!success] 达标标准
> - [x] 单条消息：首条请求**立即**进入 `running`（日志时间差 < 200ms），不再有 1.5s 窗口延迟
> - [x] 连发 3 条：首条立即处理，后 2 条缓冲后作为一批处理，总请求数 ≤ 2 批
> - [ ] **5 个旧测试更新为新语义后全部通过**（新增用例：首条立即 dispatch 单条批 + on_batch_completed 触发缓冲批）
> - [ ] `tests/test_message_batcher.py` 全绿（10 通过 + 5 修正）
> - [ ] 同 conversation 串行保证不被破坏（新缓冲批次在前批完成后才 claim）

**回滚**：flag `merge.first_immediate_enabled`；置 false 恢复旧固定窗口。

---

## 7. Gate 5 —— 撤回判断联动（合并 × 撤回）

> [!note] 目标
> 把 Gate 2（撤回）与 Gate 4（合并）联动：**首条已发出后**又收到新消息时，决策"是否需要撤回首条再合并重算"，而不是无脑撤回或重复回复。

### 7.1 新增 `core/message_orchestrator.py` —— `RecallJudge`

```python
@dataclass
class RecallDecision:
    recall: bool          # 是否需撤回首条
    reason: str           # "user_correction" / "no_op" / "budget_exhausted" / "window_expired"
    prev_reply: str = ""
    new_msg: str = ""

class RecallJudge:
    def __init__(self, recall_manager, *, window_seconds: int = 120) -> None: ...
    def should_recall_prev(self, *, prev_reply, new_msg, channel) -> RecallDecision: ...
```

**判断规则（初版，可配置，`recall.correction_keywords`）**：
1. **用户修正**：上一条 AI 回复刚发出（< `recall.window_seconds`）**且** 新消息命中修正关键词（`不对/不是/说错了/撤回/我改口/换个说法/重说`）→ `recall=True, reason="user_correction"`。
2. **预算兜底**：`recall_manager.can_recall(channel,...)` 返回 false（window_expired/cooldown/session_limit）→ `recall=False, reason=<对应原因>`（新消息作为新批，不撤回首条）。
3. **否则** → `recall=False, reason="no_op"`（新消息作为新批，不误撤）。

> [!warning] 克制原则
> 撤回是重武器，只应在"语义明显冲突/用户明显修正"时触发，避免频繁撤回造成体验降级（QQ 有 120s 窗口 + 冷却 + 预算硬限制）。默认 `correction_keywords` 保守，宁可不撤不误撤。

### 7.2 接入点（精确）

在 `companion._on_message_batch_ready`（[companion.py](file:///e:/Agent_reply/core/companion.py#L1155)）**已有批次路径**中，于真正提交处理前插入判断：
- 条件：该 conversation 的**上一批已产出**（`recall_manager` 存在最近记录）**且** 新批非首条。
- 命中 `recall=True` → 先 `recall_manager.try_recall(channel, channel_account_id, user_id, reason="recall_judge")`，再走 Gate 4 合并重算。
- 未命中 → 仅走 Gate 4 合并，不撤回。

**改动文件**：`core/message_orchestrator.py`（新增）、`core/companion.py`（`_on_message_batch_ready` 内插桩）、`config/persona.yaml`（新增 `recall.correction_keywords`）

### 7.3 门锁 Gate5 达标标准

> [!success] 达标标准
> - [ ] 修正性新消息 → `RecallDecision.recall=True` 且 `try_recall` 被调、前批合并重算（单测）
> - [ ] 普通新消息 → `recall=False`，仅作为新批（不误撤，单测）
> - [ ] 预算用尽/超窗 → `recall=False` 且原因正确，正常走新批（兜底单测）
> - [ ] `tests/test_message_orchestrator.py` 覆盖三分支，全部通过

**回滚**：flag `merge.recall_judge_enabled`；置 false 则 `should_recall_prev` 恒 false（退化为 Gate4 纯合并）。

---

## 8. Gate 6 —— 微信端架构预留 + 调研归档

> [!note] 目标
> 不接真实微信，但把行业做法查清归档，并预留可扩展的撤回接口。

### 8.1 创建 `documents/Agent_v/微信接入调研与方案.md` → 实际落地于 `documents/Aerie_微信接入调研与方案.md`

> [!todo] 文档内容（已调研，直接落档）
> - **官方方案（最相关）**：腾讯 OpenClaw「微信 ClawBot」，iLink 协议，域名 `ilinkai.weixin.qq.com`；参考 GitHub `SiverKing/weixin-ClawBot-API`。与代码 `CHANNEL_CLAWBOT` 对应。
> - **⚠️ 撤回能力结论**：iLink 协议 **暂无独立 revoke 端点**（仅收发/输入状态/配置），ClawBot 官方当前**无法可靠撤回自己消息**。`<recall>` 指令在微信端自动降级为仅本地标记。
> - **WeChatFerry（wcf）**：Windows DLL 注入，`revoke_msg` 支持撤回自己消息，但需特定微信版本、封号风险高。
> - **Wechaty + PadLocal**：iPad 协议，商业 token，风控较低，撤回能力需确认。
> - **接入时机建议**：待 ClawBot 官方暴露 revoke 端点后再接；否则维持本地标记降级。

### 8.2 代码侧预留

- `WeChatClawbotAdapter`（Gate1 已建桩）保持 `channel="clawbot"` 不变。
- `communication/router.py`、`companion_channel.py` 的 `CHANNEL_CLAWBOT` 常量保留，不删。
- 不新增微信业务代码。

### 8.3 门锁 Gate6 达标标准

> [!success] 达标标准
> - [ ] 调研文档落地，含方案对比 + 撤回能力 + 风险
> - [ ] `get_recall_adapter("clawbot")` 返回桩且不抛错
> - [ ] 全量测试回归通过

**回滚**：纯新增文档 + 桩，无风险。

---

## 9. 总体验收与回归

> [!success] 剩余待办收口（Gate 1-4 已落地）
> ### 9.1 剩余代码工作
> - [ ] **Gate 4 测试修复**：`tests/test_message_batcher.py` 5 个旧测试更新为新"首条立即"语义，全绿
> - [ ] **Gate 5**：新增 `core/message_orchestrator.py`（`RecallJudge`）+ `companion._on_message_batch_ready` 插桩 + `config/persona.yaml` 新增 `recall.correction_keywords` + `tests/test_message_orchestrator.py`
> - [ ] **Gate 6**：调研文档已归档（✅），验证 `get_recall_adapter("clawbot")` 返回桩
>
> ### 9.2 全量门锁收口
> - [ ] `python -m pytest tests/ -q` 全量通过（基线对比 Gate0）
> - [ ] 手动 E2E：QQ 端 AI 主动撤回 / 本地撤回 / 连发首条即时 / 撤回判断联动，4 项逐一验证
> - [ ] 三端配置项齐全且默认值保守（不误撤、不刷屏）
> - [ ] CHANGELOG 记录本次重构

---

## 10. 风险登记

| 风险 | 等级 | 缓解 |
|---|---|---|
| LLM 滥用 `<recall>` 频繁撤回 | 中 | prompt 引导 + 预算硬限制（window/cooldown/session） |
| 本地撤回 schema 缺 `channel` 字段 | 中 | Gate5 前置确认 + 补 migration |
| 消息合并改造破坏串行保证 | 高 | Gate4 单测 + flag 回滚 |
| 微信 ClawBot 官方能力未稳定 | 低 | 本轮仅桩 + 调研归档 |

---

## 11. 执行顺序速查

```
Gate0 基线冻结
  ↓
Gate1 端口撤回抽象层
  ↓
Gate2 LLM 主动撤回指令
  ↓
Gate3 本地端撤回补全
  ↓
Gate4 消息合并(首条立即+缓冲)
  ↓
Gate5 撤回判断联动
  ↓
Gate6 微信预留+调研归档
  ↓
全量回归收口
```
