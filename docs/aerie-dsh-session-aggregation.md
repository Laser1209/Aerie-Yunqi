# 会话聚合层接口定义（Session Aggregation Layer）

> 目标：让"连续发送的多条消息"被识别为同一件事，归入同一个 DSH session 持续对话，
> 而不是每条消息独立路由、独立分析、事后拼上下文。
>
> 本层位于 Aerie 路由层与 DSH session 管理模块之间，是"有引导的持续工作会话"的骨架。

---

## 1. 职责边界

| 层 | 职责 | 不负责 |
|---|---|---|
| **会话聚合层（本文档）** | 判定"连续消息是否同一件事"，给出会话归属决策 | 不执行任务、不调 DSH、不生成回复 |
| 路由层（work_mode_router） | 判定"这条消息是否工作型任务 + 哪个 preset" | 不判定跨消息的连续性 |
| DSH session 管理（dsh_cli） | 按 `preset → session_id` 复用持久化 session | 不判定消息归属 |

聚合层是**纯判定层**：输入上下文，输出决策，无副作用。

---

## 2. 时间窗口设计

核心原则：**时间窗口只做"快速候选"，最终归属由"任务状态 + 语义相关性"双重确认。**

| 参数 | 建议值 | 含义 |
|---|---|---|
| `active_window_sec` | **30** | 会话最后一次活动后 30s 内，视为"会话仍活跃" |
| `running_extend_sec` | **90** | DSH session 仍 `running` 时，补充指令窗口放宽到 90s |
| `idle_window_sec` | **60** | DSH session 已 `idle` 后，续接窗口 60s，超出强制新会话 |

**为什么是 30s 主窗口**：
- 用户"边想边说"连续发消息的典型间隔在几秒到几十秒；
- 30s 能覆盖"打完一句、补一句、再改一句"的自然节奏，又不至于把两个独立话题误合并；
- 超过 30s，用户大概率已切换关注点，交给语义判定兜底。

**任务状态对窗口的修正**（关键设计）：
- DSH session `running` → 新消息大概率是**补充指令**，即使超过 30s，放宽到 90s 直接归入（无需语义判定，节省一次 LLM 调用）；
- DSH session `idle` → 新消息需要**语义判定**：是"续接追问/修改"还是"新任务"。

**前端配置**：主窗口通过设置页「工作模式 → 会话窗口」下拉选择（15 / 30 / 60 / 90 秒），存 `settings.yaml` 的 `dsh.session_window_sec`。会话聚合层初始化时读取该值作为 `active_window_sec`，其余两个窗口按比例推导（`running_extend_sec = 3×`、`idle_window_sec = 2×`）。

---

## 3. 语义相关性模型选型

**结论：主用 `siliconflow-light`，不开新分支；百炼 `qwen3.7-flash` 作备选。**

| 角色 | 模型 | 配置来源 | 说明 |
|---|---|---|---|
| 主用 | `Qwen/Qwen3-30B-A3B-Instruct-2507` | `SILICONFLOW_LIGHT_MODEL`（`siliconflow-light` provider） | 系统既有轻量模型，定位即"快速辅助任务" |
| 备选 | `qwen3.7-flash` | `AERIE_WS_MODEL`（百炼多 Key 轮询） | `siliconflow-light` 不可用时降级 |

选型依据：
1. 语义相关性是"轻量、快速、三分类"任务，与 `siliconflow-light` 的既有用途（typo 纠错 / 生图提示词接力 / 抽屉问候语）完全同类；
2. 遵循"先翻已有依赖能做什么，再考虑加新包"——不新增 provider，零新配置；
3. 百炼三模型（`qwen3.7-flash` / `kimi-k2.7-code` / `qwen3-asr-flash`）里仅 `qwen3.7-flash` 与"通用轻量分类"匹配，作为容灾备选即可。

**三分类判定**（单次轻量 LLM 调用，超时 5s，失败降级为 `new_task`）：

```
supplement  — 补充指令（"顺便把重复的删了"）        → 归入同一 session
followup    — 续接追问/修改（"改成按日期分"）       → 归入同一 session
new_task    — 新任务（"帮我写个周报"）              → 新 session
```

---

## 4. 数据模型

### 4.1 输入：`SessionContext`

聚合层判定所需的上下文（由调用方传入）。

```python
@dataclass
class SessionContext:
    # 当前待判定的消息
    current: IncomingMessage            # 必填：当前消息（含 user_id, content, timestamp）

    # 现有活跃会话（无活跃会话时为 None）
    active_session_id: str | None       # DSH session_id（dsh_cli._sessions 里的键）
    preset: str | None                  # 场景名（file-organizer 等）
    dsh_status: str | None              # DSH session 状态："running" | "idle" | None

    # 会话时间锚点（用于时间窗口计算）
    last_activity_at: float | None      # 活跃会话的最后活动时间戳（epoch 秒）

    # 语义相关性用的历史消息（可选，供轻量模型参考）
    recent_messages: list[dict]         # 最近 N 条，[{role, content}]
```

### 4.2 输出：`AggregateDecision`

聚合层返回的归属决策（唯一输出）。

```python
@dataclass
class AggregateDecision:
    action: str                         # "continue" | "new"
    session_id: str | None              # continue 时 = 归属的 DSH session_id；new 时为 None
    preset: str | None                  # 建议的路由 preset（可复用路由层结果）
    reason: str                         # 判定依据，枚举见下
    confidence: float                   # 0.0 ~ 1.0（语义判定路径有值，规则路径恒 1.0）
```

`reason` 枚举：

| reason | 触发条件 | 含义 |
|---|---|---|
| `task_running` | DSH status == running 且在 `running_extend_sec` 内 | 任务进行中，直接续接，跳过语义判定 |
| `window_active` | 活跃窗口内 + 语义 = supplement/followup | 窗口内且语义相关，续接 |
| `semantic_new` | 语义 = new_task | 语义判定为新任务 |
| `window_expired` | 超过 `idle_window_sec` | 强制新会话 |
| `no_active_session` | 无活跃会话 | 首条消息，直接新会话 |

---

## 5. 接口签名

```python
class SessionAggregator:
    """会话聚合层：判定连续消息的会话归属（纯判定，无副作用）。"""

    def __init__(
        self,
        light_llm: LLMCaller,           # siliconflow-light（主用语义判定）
        *,
        active_window_sec: float = 30.0,
        running_extend_sec: float = 90.0,
        idle_window_sec: float = 60.0,
        classify_timeout_s: float = 5.0,
    ) -> None: ...

    async def decide(
        self,
        ctx: SessionContext,
    ) -> AggregateDecision:
        """核心接口：判定当前消息归入哪个会话。

        输入：SessionContext（当前消息 + 活跃会话状态 + 历史）
        输出：AggregateDecision（action / session_id / reason / confidence）
        无副作用：不写库、不改 DSH session、不启动进程。
        """

    async def _classify_semantic(
        self,
        current_text: str,
        recent_messages: list[dict],
    ) -> str:
        """内部：轻量模型三分类 supplement/followup/new_task（超时降级 new_task）。"""
```

---

## 6. 判定流程

```
decide(ctx)
  ├─ ctx.active_session_id 为空
  │    └─ return AggregateDecision(action="new", reason="no_active_session")
  │
  ├─ ctx.dsh_status == "running"
  │    └─ 若 now - last_activity_at ≤ running_extend_sec
  │         └─ return (action="continue", session_id=active, reason="task_running", confidence=1.0)
  │         └─ 否则落入语义判定
  │
  ├─ now - last_activity_at ≤ active_window_sec
  │    └─ 语义三分类：
  │         ├─ supplement / followup → continue（reason="window_active"）
  │         └─ new_task               → new（reason="semantic_new"）
  │
  ├─ now - last_activity_at > idle_window_sec
  │    └─ return (action="new", reason="window_expired", confidence=1.0)
  │
  └─ 兜底（语义模型失败）
       └─ return (action="new", reason="semantic_new")   # 宁可新开会话，不误合并
```

降级原则：**语义模型不可用时，宁开新会话、不误合并**（误合并会污染 DSH session 上下文，代价高于多开一个 session）。

---

## 7. 并发与排队续接（AI 输出中用户输入）

**DSH 能力边界**：DSH SDK 仅有 `initialize` / `session_prompt` / `shutdown` 三个方法，**无 `session/cancel`、无 `session/interrupt`**。因此：

- DSH 的 session 是**同步单 turn**——一个 turn 处理完才轮到下一个 turn；
- **"打断当前任务"不可行**（无 cancel），**"运行中注入补充指令"也不可行**（一个 session 同一时间只能跑一个 turn）。

**正确形态：排队续接**，而非并发注入：

```
用户发消息A → DSH turn 1 执行中（推进度）
   ↓ 用户又发消息B
   ↓ B 进入队列（不丢失）
   ↓ turn 1 完成
   ↓ 会话聚合层判定 B 是否同一件事
   ├─ 同一件事 → B 作为同一 session 的 turn 2 续接（DSH 带着 turn 1 上下文继续）
   └─ 新话题   → 新 session
```

**两个体验补丁**（排队续接的体验空洞）：

1. **进度反馈**：执行 A 时实时推送进度（对接"进度人格化"），让用户知道在忙、不是卡死；
2. **快速确认**：用户发 B 后，立即回一句轻量确认（"收到，我先把手头这件做完，马上继续"），而不是沉默到 turn 1 结束。

**职责划分**：聚合层保持**纯判定、无副作用**——"是否排队"由上游 pipeline 依据 `dsh_status == "running"` 自行判断，不放入聚合层输出。聚合层的 `reason` 里 `task_running` 已隐含"当前有任务在跑"这一信号，pipeline 可据此决定排队。

---

## 8. 与 DSH session 管理模块的对接

聚合层**只输出决策**，由上游（pipeline）执行决策：

```python
# pipeline 侧对接伪代码
decision = await aggregator.decide(ctx)

if decision.action == "continue":
    # 复用现有 session，DSH 带着前文继续
    result = await dsh_cli.delegate(
        text, preset=decision.preset,
        session_id=decision.session_id,      # ← 关键：显式续接，而非 preset 默认复用
    )
else:
    # 新 session：dsh_cli 内部为 preset 生成新 session_id
    result = await dsh_cli.delegate(text, preset=decision.preset)
```

**对 dsh_cli 的一个增量要求**：`delegate()` 目前靠 `preset → session_id` 字典复用 session；聚合层需要**显式指定 `session_id`**（续接某次历史对话），因此建议给 `delegate()` 增加可选参数：

```python
async def delegate(self, task, *, preset, session_id: str | None = None, ...):
    # session_id 为 None 时保持现状（preset 默认复用/新建）
    # session_id 非 None 时，显式续接该 session
```

---

## 9. 待确认项（对接前需拍板）

1. ~~**时间窗口前端设置**~~ ✅ 已完成：设置页「工作模式 → 会话窗口」下拉（15/30/60/90 秒），存 `dsh.session_window_sec`；
2. ~~**`IncomingMessage` 的时间戳来源**~~ ✅ 已完成：新增独立 `timestamp` 字段（`from_onebot_event` 取 `event.time`、`from_local` 取 `time.time()`、pipeline 恢复时保留）；
3. ~~**`session_id` 显式续接**~~ ✅ 已完成：`dsh_cli.delegate` 新增 `session_id` 参数，显式续接历史会话；
4. ~~**语义判定 prompt 措辞**~~ ✅ 已拍板：保持通用技术措辞，不做人设微调。

---

## 附：模型配置对照

| 用途 | 模型 | 环境变量 |
|---|---|---|
| 语义相关联性（主） | `qwen3.7-flash`（轻量） | `SILICONFLOW_LIGHT_MODEL` |
| 语义相关性（备） | `deepseek-v4-flash-0731`（备） | `DEEPSEEK_MODEL` |

> 说明：实现采用 `siliconflow-light` 主用，失败降级 `qwen3.7-flash`，兜底新开会话，避免误合并。

---

## 10. 实现落地状态

| 项 | 状态 | 位置 |
|---|---|---|
| `SessionContext` / `AggregateDecision` 数据类 | ✅ 已实现 | `core/session_aggregator.py` |
| `SessionAggregator.decide()` 5 条判定路径 | ✅ 已实现 | `core/session_aggregator.py` |
| 聚合单元测试（8 条路径） | ✅ 已通过 | `tests/test_session_aggregator.py` |
| `dsh_cli.delegate` 增加 `session_id` 显式续接 | ✅ 已实现 | `core/dsh_cli.py` |
| `IncomingMessage.timestamp` 字段 | ✅ 已实现 | `communication/message.py` |
| **串入 `pipeline._try_delegate_to_dsh`** | ✅ 已就位 | `core/pipeline.py` §见下 |
| 委托链路单元测试（8 条） | ✅ 已通过 | `tests/test_pipeline_dsh_delegate.py` |
| **工作区管理器**（预设目录 + 对话临时目录 + 文件树 + 缩略图 + 打开 + 操作日志） | ✅ 已实现 | `core/workspace.py` |
| **人格化翻译层**（DSH 机械结果 → 伊塔口吻，失败降级） | ✅ 已实现 | `core/work_persona.py` |
| 工作区 + 翻译层单元测试（20 条） | ✅ 已通过 | `tests/test_workspace.py` |
| 工作区管理 API | ✅ 已实现 | `core/api_server.py` `/api/workspace/*` |
| 前端工作区侧边栏（文件/图片/日志三视图） | ✅ 已实现 | `electron/src/renderer/js/workspace-panel.js` |

**pipeline 串接点**（`core/pipeline.py` `_try_delegate_to_dsh`，委托前）：

```python
state = self._dsh_session_state.get(preset)
agg_ctx = SessionContext(
    current=msg,
    active_session_id=state.get("session_id") if state else None,
    preset=preset,
    dsh_status="idle",              # L1：delegate 同步阻塞，处理新消息时上轮必已完成
    last_activity_at=state.get("last_activity_at") if state else None,
)
agg_decision = await self._dsh_aggregator.decide(agg_ctx)
if agg_decision.action == "continue":
    session_id = agg_decision.session_id
# 委托成功后按 preset 记录本轮 session
self._dsh_session_state[preset] = {
    "session_id": result.session_id or session_id,
    "last_activity_at": time.time(),
}
```

> ⚠️ **`dsh_status` 硬编码 `"idle"` 说明**：L1 是同步阻塞委托，处理新消息时上一轮必已完成，故恒为 `"idle"`。聚合层的 `task_running`（DSH running 且窗口内）快捷路径**不会被 pipeline 触发**，仅在聚合类单测里被直接覆盖。若改为**异步排队模式**，需由 pipeline 依据真实 DSH 状态回填 `dsh_status`，见 §11。

---

## 11. 异步排队模式改造点（pipeline 侧）

当改为"用户消息进入队列、DSH turn 异步执行"（解决 AI 输出中用户再输入），`core/pipeline.py` 需调整：

1. **废除 `dsh_status="idle"` 硬编码**：由 pipeline 维护每个 preset 的实时 DSH 状态（`running` / `idle`），在发起委托前读取并回填 `agg_ctx.dsh_status`，让聚合层的 `task_running` 窗口路径真正生效（DSH 运行中、90s 内补充指令直接续接，跳过语义判定，省一次 LLM 调用）。
2. **新增"运行中补充消息"队列**：`_try_delegate_to_dsh` 命中 delegate 且该 preset 当前 running 时，不立刻 `delegate()`（会与 running turn 冲突），而是入队 `deque[(msg, preset)]`；当前 turn 完成后再 `drain` 队列，逐条续接。
3. **快速确认 + 进度反馈**：入队时立即回一条轻量确认（"收到，先把手头这件做完，马上继续"）；执行中回调 `on_notice` 实时推送 `step/ tool/ subagent/` 进度，避免排队空洞。
4. **状态记录时机**：`last_activity_at` 应在 turn 真正开始时更新，而非入队时，否则排队期间会被误判为 idle 而开新会话。

代码骨架建议：

```python
async def _try_delegate_to_dsh(self, text, msg):
    ...
    preset = decision.preset or "default"
    state = self._dsh_session_state.get(preset, {})
    agg_ctx = SessionContext(
        current=msg,
        active_session_id=state.get("session_id"),
        preset=preset,
        dsh_status=await self._dsh_real_status(preset),  # running/idle
        last_activity_at=state.get("last_activity_at"),
    )
    decision = await self._dsh_aggregator.decide(agg_ctx)

    if decision.action == "continue" and decision.session_id:
        # 显式续接历史会话
        return await self._delegate_now(preset, decision.session_id, text)
    if decision.action == "new":
        return await self._delegate_now(preset, None, text)
    ...
```

> 解析：本层目标"continue"语义与 DSH 无 cancel 约束是自洽的——aggregator 只在事件窗口内选"续接"，不会"躲开正在运行的任务"。异步模式下，真实 running 状态由 pipeline 回填，聚合层保持纯判定不变。
