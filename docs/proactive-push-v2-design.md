# 主动消息系统 v2 设计方案（Proactive Push v2）

> 状态：待评审 · 日期：2026-08-19 · 范围：内容生成层 + 调度层重构

## 1. 背景与目标

### 1.1 现存问题

1. **两套提示词漂移**：日常对话走 PersonaHub（`data/personas/*.json` + `context_builder` 分层组装），主动消息在 `core/llm_caller.py::generate_push` 内联硬编码人设。两处「屏幕隔空铁律 / 禁语区 / 破格条款」文字各写一份、互不同步，风格必然不一致。
2. **开场框架写死**：提示词强制「好的开场 = 一个小分享 + 一个轻量开放式问题」。真人的开场是开放的、由当下状态生发的，不是套公式。
3. **与状态/记忆脱节**：主动消息看不到世界快照、PAD 情绪、作息窗口、旧事记忆，生成的内容像「背台词」而非「由心而发」。
4. **调度机制死板**：只靠 proactive.yaml 的 cron 时刻表，不感知用户活跃度、情绪、已消耗额度；不会随作息自动调整。

### 1.2 目标

1. 两套系统共用**同一副嘴巴**（共享人设组装器）。
2. 主动消息内容 = **状态化开放生成**：人设 × 情绪状态（PAD)×世界环境 × 话题状态 × 记忆唤起，无固定结构。
3. 调度 = **整点滚动自检 + 软预算 + 作息学习**，像真人一样「看状态决定聊不聊、聊几句」。
4. 全程考虑与其他模块的适配性（见 §9 适配矩阵）。

## 2. 已收敛的边界决策（用户确认记录）

| # | 边界 | 决策 |
|---|------|------|
| 1 | 生成机制 | 状态注入 + 小候选池（2～3 条，一次调用） |
| 2 | 候选挑选 | LLM 按贴合度排序输出，**直接取第一条** |
| 3 | 情绪输入 | **档位 + 原始 PAD 数值双通道**（Pleasure/Arousal/Dominance，来自 emotion_engine） |
| 4 | 档位映射维护层 | **代码预定义规则表**（`pad_tone_rules`），可调试可维护 |
| 5 | 旧事召回 | v1 就接分层记忆（`LayeredMemory` + `KnowledgeBase`） |
| 6 | 提示词统一 | 从 `context_builder` 抽取**共享组装器**，日常对话 + 主动推送共用 |
| 7 | 调度触发 | **整点滚动自检**：每小时推算下一小时发送计划，可修正后续安排 |
| 8 | 每日额度 | `max_per_day` 变**软预算** + **硬顶保险丝** |
| 9 | 决策输入 | 用户在线状态、人设状态（PAD/欲望）、环境与时段、已消耗额度与冷却（全量取） |
| 10 | cron 场景 | **保留为保底锚点** + 作息学习（近 7 天滚动推算起床/睡觉，搬移推送窗口） |
| 11 | 交付 | 先出方案文档，评审通过后按阶段开工 |
| 12 | 兼容策略 | 不保留向后兼容（项目硬约束），旧路径直接删；失败兜底保留（防线上事故） |

## 3. 现状资产与缺口

### 3.1 已有可复用能力（不需重复造轮子）

| 能力 | 位置 | 说明 |
|------|------|------|
| 话题生命周期与续接 | `core/topic_tracker.py` | `active/closed/paused` 三态、`continuation_plan()` 返回 `new/continue/revive`、`REVIVE_WINDOW_HOURS` 再造窗口、收尾词表 |
| 情绪 PAD | `core/emotion_engine.py` | P/A/D 三轴 [-1,1]，5 类基本情绪，状态快照可调 |
| 主动消息生成 | `core/llm_caller.py::generate_push` | 已支持 `topic_mode/tone_hint/judge_context/knowledge_fragment/dialogue_context` |
| 主动消息分发 | `core/companion.py::_dispatch_push` | 已组装 judge_context、dialogue 话术知识、话题续接、最近对话素材 |
| 调度与额度 | `core/push_scheduler.py` | `PushPolicy`（max_per_day / min_interval_min / can_push / record / postpone / mute）、`CronScheduler`（proactive.yaml cron 解析） |
| 情绪→tone 映射 | `core/proactive_judge.py` | `TONE_BY_DOMINANT` + `TONE_PROMPTS` 12 段语气 |
| 分层记忆 | `memory/layers/layered_memory.py` | `memory_search(query, top_k, user_id)` 跨层检索 |
| 话术知识库 | `knowledge/kb.py` | `search(query, limit, category)`，已有 `dialogue` 品类 |
| 世界快照 | `core/world_simulation.py` | WorldSnapshot（时间/天气/地点/视觉主题） |
| 决策埋点 | `core/decision_log.py` + `companion._build_motive_candidates` | 主动消息动机落盘 |

### 3.2 缺口清单（本次设计补上）

| 缺口 | 对应设计 |
|------|----------|
| 主动消息人设不读 PersonaHub | §5.1 共享组装器 |
| 开场框架写死 | §5.2 状态化开放生成 |
| 无 PAD 细粒度输入 | §5.3 PAD 档位规则表（双通道） |
| 生成无候选池与自选 | §5.4 候选池（排序取首条） |
| 不能翻分层记忆中的旧事 | §5.5 记忆唤起 |
| 无计划性调度 | §6.1 整点滚动自检 PulsePlanner |
| max_per_day 硬限额 | §6.2 软预算 + 硬顶 |
| 无作息感知 | §6.4 RoutineLearner（近 7 天学习） |
| 无自适应频率模型 | §6.3 决策模型（状态→每小时配额） |

## 4. 总体架构

```
┌────────────────────────────────────────────────────────────┐
│  调度层（PulseScheduler）                                    │
│  Cron 锚点场景(cron 定时) + PulsePlanner(整点自检) + Policy  │
│  RoutineLearner(作息窗口) → 生成 下一小时 Plan 队列            │
└───────────────────────────┬────────────────────────────────┘
                            │ 触发 计划项(trigger_at, shape, ctx)
┌───────────────────────────▼────────────────────────────────┐
│  决策层（ProactiveJudge + _dispatch_push）                    │
│  状态快照：PAD/情绪档位 · 欲望分 · 用户活跃 · 话题 plan ·      │
│            已耗额度/冷却 · 世界快照 · 作息窗口 · 记忆唤起      │
└───────────────────────────┬────────────────────────────────┘
                            │ Decision(score, tone) + 上下文包
┌───────────────────────────▼────────────────────────────────┐
│  生成层（generate_push v2）                                  │
│  共享人设组装器(PersonaAssembler) + 发起者强化段 +               │
│  PAD 档位片段 + 记忆唤起片段 + 候选池(JSON排序取首条)             │
└───────────────────────────┬────────────────────────────────┘
                            │ 正文
┌───────────────────────────▼────────────────────────────────┐
│  投递层（现网络成 maintained）：send_message → QQ/桌面       │
└────────────────────────────────────────────────────────────┘
```

分层原则（对齐项目惯例）：
- 调度层只回答「**发不发、几点发、发几条**」；
- 决策层把调度意图翻译成「**动机、语气、情绪上下文**」；
- 生成层只回答「**这句话怎么说**」；
- 投递层不动。

## 5. 内容生成层设计（Phase 1）

### 5.1 共享人设组装器（PersonaAssembler）

**目标**：让主动推送与日常对话长在同一副嘴巴。

**做法**：
- 从 `core/context_builder.py::_build_system_prompt` 中抽出与「人设基础身份 L1 / 语言铁律 L4 / 表达自由 L4.5 / 屏幕铁律 / 禁语区 / 破格条款」对应的组装函数，落新模块 `core/persona_assembler.py`。
- 暴露统一入口：

```
build_persona_block(persona: dict, mode: "chat" | "push", **ctx) -> str
```

- `mode="chat"` 走现有分层（L0.5/L1.5/L2/L6 等仍留在 context_builder 内层拼接，保证日常行为不变）；
- `mode="push"` 取人设基础段 + 发起者强化段（见 §5.2），不拼入对话系上下文。
- `generate_push` 删除内联「你是伊塔（Ita）」硬编码，改从此入口获得人设；人设数据源 = PersonaHub（`persona_manager`）当前激活人设，与日常对话同一份。

**验收**：`generate_push` 系统提示词中 `你是伊塔` 段落与 PersonaHub JSON 内容一致；改一份人设两份同时生效。

### 5.2 拆除固定开场框架，改为状态化开放生成

**删除**：提示词中「好的开场 = 一个小分享 + 一个轻量开放问题」的结构指令以及类似「必须」推销。

**替换为**：注入「结构化状态的软指导」，只给方向、不给结构：

```
此刻状态（供你选择开口的方式，不要逐一复述）：
- 情绪：{PAD 三值 + 情绪档位描述} → 你此刻更想说哪类话
- 环境：{time/天气/季节} —— 此刻的世界是什么样的
- 关系/记忆：{最近话题状态 / 一段用户提过的旧事（若有）}
- 时刻：{现在几点，用户作息窗口}
```

**拟定原则片段**（作为软的言语风格参考，可被破格条款打破）：
- 开场不一定要问句；可以是观察、回忆、感叹、行动邀约、叨叨一句废话
- 没有观点就分享一个当下感官真实
- 承接旧话题的优先级（当 topic_mode=continue/revive 时）> 旧事重提 > 新话题

### 5.3 PAD → 档位规则表（双通道）

新模块 `core/pad_tone_rules.py`（纯函数，无 IO）：

- 输入：`PAD {pleasure, arousal, dominance}`（emotion_engine 状态，[-1,1]）
- 输出：`(band_label: str, expression_fragment: str)`

档位映射（每轴三分）：

| 轴 | 区间 | 档 | 表达倾向 |
|----|------|----|------|
| P(愉悦) | >0.33 | 高 | 满足/分享欲/主动邀约 |
| P | -0.33~0.33 | 中 | 安需求、有话聊 |
| P | <-0.33 | 低 | 想念/被需要/求安慰 |
| A(唤醒) | >0.33 | 高 | 活泼、话多、想行动 |
| A | 中 | 常态 | 谦和 |
| A | <—0.33 | 低 | 慵懒、想被拥抱 |
| D(主导) | >0.33 | 高 | 占有/主动出击 |
| D | 中 | 平衡 | 平铺 |
| D | <—0.33 | 低 | 依赖/靠住 |

- **组合规则**：9～12 个高频组合（如 P高+A高+D高=「兴冲冲邀约型」，P低+A高+D低=「想你但软弱型」，P中+A低+D中=「慵懒分享型」…），各带 1 句「此状态想说的话」风格片段 → 注入提示词。
- **原值通道**：`pl=0.58 ar=0.20 do=0.41` 原样注入，让模型感知细微差异。
- **数据源**：`companion.get_primary_emotion_state()` / emotion_engine snapshot；不用额外缓存，推送时实时拉取。
- 维护层：代码内（可加单元测试逐一验证每个组合）。

**验收**：同 PAD 注入，主动消息风格明显随情绪档位变化；单元测试覆盖 12 组合。

### 5.4 候选池（一次生成，排序取首条）

`generate_push` v2 调用方式改为：

```
prompt: 「基于以上状态，自然地列出 2-3 条你会在这时候发的话（可用 JSON 数组），
        按你认为最自然的那条排在第 1 位。」
resp: json array[2-3 条] → 取 arr[0] 作为最终正文
```

- 一次 `chat` 调用完成，不加第二次请求。
- 兜底链：JSON 解析失败→ 若无 `resp.text`，退回第一候选的纯文本 →仍失败退回原 template 填充兜底。
- JSON 模式仅提示词引导；若模型返回非 JSON 纯文本，直接视为单条并按原文使用。
- 说明：候选池是上一条调用内的一次生成，因此可 60 字等约束保留在提示词内。

### 5.5 记忆唤起（v1）

**触发时机**：主动推送时，在 `new/continue/revive` 之后新增一种动机来源 `memory_pick`。

**召回链路**（`_dispatch_push` 内新增）：
1. 规则预筛：`continuation_plan()` 结果非 continue/revive 且距上次 memory 唤起 ≥ 2h、且当日旧事唤起未超次（默认 ≤2 次/天）→ 进入召回；
2. `LayeredMemory.memory_search(query=当前时刻+关系上下文, top_k=3, user_id=master)` + `KnowledgeBase.search(category="user")` 融合去重；
3. **去重**：与 `topic_tracker` 当前 active/closed stub 不出现重复主题（通过 topic 关键词交集判断，交 2 个以上词则放弃该条，换下一条）；
4. LLM 裁决阶段：把「旧事内容 + 上次提及时间」注入 `generate_push`，由模型自行判断「现在提合不合适」，模型选择不写旧事（输出内容不含旧事）即自然放弃；
5. 成功落内容 → `memory_evoke` 计数 +1 并落 decision_log。

**目的**：不是「每次捧个旧事」，而是给伊塔「记性」——低频、自然、不刻意。

## 6. 调度层设计（Phase 2）

### 6.1 整点滚动自检（PulsePlanner）

新模块 `core/proactive_planner.py`：

```
class PlannedPulse:
    at: datetime          # 期望触发时刻
    shape: str            # "anchor" | "state_based"（cron锚点/状态态计算）
    scene: str | None     # anchor 场景名（来自 proactive.yaml）
    payload: dict         # 传来内容的上下文（可选）

class PulsePlanner:
    async def plan_next_hour(self, now, state: PushStateSnapshot) -> list[PlannedPulse]
    async def replan_after(self, now, event: str) -> None   # 事件插队（Phase 3 可选）
```

**心跳流程**（整点）：
1. 今天已发额度 hard 统计；昨日是否不足/超额 → 参与系数
2. 读 4 组状态源 → 计算下一小时配数 budget_hour
3. 把 second-hour 计划（可 0-N 条）写入 `PushPolicy` 的 pending 队列（新字段 `pending_plans`）；后续整点重算时覆盖该队列（最近一次重算为准）
4. cron 锚点场景照常进入 pending，并在新调度失效时由 PulsePlanner 补位（锚点挪移规则见 §6.4）

### 6.2 决策模型（状态→每小时配额）

```
hour_coefficient = Σ w_i * factor_i    # 所有 factor ∈ [0,1]

factor_active:  用户近 30 分钟是否在线/刚发过消息       权重 0.30
factor_window:  当前是否在作息活跃窗口内               权重 0.20
factor_window:  越接近最近一次交互（>6h）越高           权重 0.15
factor_mood:    PAD->需要度（P低/A高/或 label∈焦虑/想念）权重 0.20
factor_desire:  desire_engine 场景分(0~1)              权重 0.15

budget_hour = round(HOURLY_BASE * hour_coefficient)     # HOURLY_BASE 约 0.75~1.0/min
budget_hour = min(budget_hour, soft_remaining_today)     # 后续小时可用预算
```

- **软预算**：`soft_budget_today = max_per_day × budget_modifier`，其中 modifier 由昨日实际、今日状态波动：`clamp(0.6~1.6)`。
- **硬顶保险丝**：`HARD_CAP = max(原 max_per_day ×1.5, 20)`，每日无条件超不过；到达硬顶后，之后每次触发全部转静默（保留 `mute()` 语义）。
- **冷却保留**：`min_interval_min`（默认 15 分钟）依然生效，计划出时间需避开「上一滞后」。
- 手机优先：计划项触发时若仍在静默时段（用户作息睡眠窗口），整体压下补齐再发。

### 6.3 cron 锚点保留 + 作息学习器（RoutineLearner）

新模块 `core/routine_learner.py`：

```
@dataclass
class RoutineWindow:
    wake_time: time      # 平均首条消息时刻
    sleep_time: time     # 平均末条消息时刻
    active_peak: list[(start, end)]  # 午间/晚间活跃峰（按速度在历史看）
    silent_start: time   # sleep_time + 1h 视为静默开始
    enabled: bool

class RoutineLearner:
    async def on_user_message(self, ts_local) -> None   # 由消息接收处 hook
    def window(self) -> RoutineWindow                    # 近7天滚动统计
    def reload_state(self) / save_state()                # 持久化 jsonl → 存储文件
```

**学习逻辑**：
- 数据源：chat 表本地时间戳中**用户发起的消息**（排除 AI 主动、系统）。
- 每天记「首条时刻 / 末条时刻 /净活跃时长」；剔除异常日（当日消息<3 条、首末差<8h 视为噪音跳过）。
- 7 天滑动平均得 `wake_time` / `sleep_time`，直接过期旧值（无保留）。
- **锚点搬移规则**：cron 场景按语义映射到作息窗口——
  - `boot_greeting` → wake_time ≈ ±15min；`morning_brief` → wake+30~60min；
  - 晚间场景（如睡前）→ sleep_time −30~60min；
  - 场景的 `force:true` 与 `custom_dispatcher` 属性继承。
- 持久化：`09_STATE/routine_state.json`（对齐 `monitor_state.json` 惯例），小时级频率更新。

### 6.4 触发链路整合

- 心跳：`push_scheduler` 增加每小时 `asyncio.Task`（整点对齐），运行 `plan_next_hour`。
- 事件：用户消息触发 `RoutineLearner.on_user_message`（仅更新作息，不做重算，重算留给整点 —— 避免高成本事件风暴）。
- 手动/设置页：暂停、静默、推迟、硬顶告警展示（Phase 3）。

## 7. 接口契约

### 7.1 generate_push（改造）

```python
async def generate_push(
    template: str,
    mood: str = "neutral",
    *,
    tone_hint: str | None = None,
    judge_context: dict | None = None,
    knowledge_fragment: str = "",
    dialogue_context: str = "",
    topic_mode: str = "new",
    # —— v2 新增 ——
    pad: dict[str, float] | None = None,          # {"pleasure":..,"arousal":..,"dominance":..}
    pad_band: str | None = None,                 # 档位表命中标签（P高/A低/D中 之类）
    memory_fragment: str = "",                    # 被想起的一件旧事（≤120 字）
    world_fragment: str = "",                     # 世界快照的影像相关片段（≤60 字）
    trigger_shape: str = "anchor|adaptive",       # 调度来源标记
    candidates: bool = True,                      # 候选池开关（默认开）
    temperature: float | None = None,
    **kwargs,
) -> TextOrCandidates   # 返回候选或单条标题（v2 统一走候选池）
```

### 7.2 新模块清单

| 文件 | 职责 | 依赖 |
|------|------|------|
| `core/persona_assembler.py` | 人设组装器（chat/push 两模式） | persona_hub |
| `core/pad_tone_rules.py` | PAD 档位规则表（纯函数） | — |
| `core/proactive_planner.py` | 整点滚动规划（PulsePlanner） | state snapshot /PushPolicy |
| `core/routine_learner.py` | 7 天作息学习 | chat 数据表 |

### 7.3 改动清单（现有）

| 位置 | 改动 | 类型 |
|------|------|------|
| `core/llm_caller.py::generate_push` | 人设走 Assembler；结构开放段；PAD 双通道；记忆唤起；候选池 | 扩展+替换 |
| `core/context_builder.py` | 抽出共享片段 → 新模块（不改变对话行为） | 重构 |
| `core/companion.py::_dispatch_push` | 组裝 PAD/记忆/世界/作息 → 新签名调用；record 计入软预算 | 扩展 |
| `core/push_scheduler.py::PushPolicy` | `max_per_day` 语义变软预算；加 HARD_CAP；pending 队列 | 改造 |
| `core/push_scheduler.py::CronScheduler` | 锚点窗口搬移（作息）；整点 PulsePlanner 任务 | 改造 |
| `core/proactive_judge.py` | 可选传入 PAD 作为更精确 tone 输入（保留原有 tone 表） | 微扩展 |
| `config/proactive.yaml` | 新增以下二级节（不破坏现有场景）：`budget/soft_coefficient`、`candidate.enabled`、`routine.enabled` | 配置扩展 |

### 7.4 存储

- `storage/output/routine_profile.json` — 作息快照 + 学习日期
- `storage/output/pulse_state.json`（若与现有 push_state 分离则新建） — pending 计划
- `LLM_STATE/push_state.json` 保持多级现场（现有持久化不动）

## 8. 与既有模块的适配矩阵

| 模块 | 现状接口 | 改动类型 | 风险 | 对策 |
|------|---------|---------|------|------|
| emotion_engine | `get_primary_emotion_state()` | 只读 | 低 | 无 |
| desire_engine | 场景分读 | 只读 | 低 | 无 |
| topic_tracker | `continuation_plan()` | 复用 + 记忆 dedup | 中（重复旧事） | §5.5 步骤2 去重 |
| context_builder | 组装逻辑 | 抽出共享 | 中（行为回归） | Phase 1 的回归测试对比 |
| knowledge/kb dialogue | 检索 | 复用 | 低 | 无 |
| pipeline（日常对话） | 不变 | 只读 | 低 | 回归测试 |
| decision_log | 动机候选点 | 扩展字段（memory/pad 来源） | 低 | 追加 |
| settings.yaml / PUT /api/settings | 热更新预算参数 | 扩展 | 低 | 兼容现有写入 |
| 前端设置页 | 展示软预算/作息/今日已发 | **Phase 3 评估，不扩充不异步** | 中 | 需先做「前端改动前置分析」再动 |
| 24h 监听 | 无关 | — | — | — |
| 世界发图 | 只读世界快照 | 低 | — | — |

> 关联前端改动（若有）必须先完成「后端路由/数据契约/preload/事件链路」前置分析后执行（项目硬约束）。

## 9. 阶段划分与验收

### Phase 0 — 契约与底座（无行为变化）
- [ ] 新增 `pad_tone_rules`、`persona_assembler`（纯函数/纯抽取，等于不改对话行为）
- [ ] `routine_profile.json` 骨架 + `RoutineLearner` 采集逻辑（只采集，不搬锚点）
- 验收：单测通过；`context_builder` 行为零变化（对比测试基线通过）。

### Phase 1 — 内容层最小闭环（运行在现有 cron 触发上）
- [ ] generate_push v2：装 Audverter 人设 + 拆固定框架 + PAD 双通道 + 候选池
- [ ] `_dispatch_push` 注入 pad/world/memory；记忆唤起落地
- [ ] 局域网直接观察：连续触发 3-5 次推送，内容风格与日常对话一致，情绪档位有区分
- 验收：e2e 脚本断言 `generate_push` 输出来源 PersonaHub 人设词汇相关性；≥3 条不同情绪档输出有差异。

### Phase 2 — 调度层
- [ ] PushPolicy 软预算+硬顶，`PulsePlanner` 整点任务
- [ ] RoutineLearner 接入锚点搬移
- [ ] 用历史聊天数据离线回放：对比新旧调度「每小时计划曲线」合理性
- 验收：24h 监听日志中每日实际发送满足 `≤HARD_CAP`；软预算目标偏差 ≤30%（离线回放）。

### Phase 3 — 配置/API/收尾
- [ ] proactive.yaml 预算参数热更新（PUT /api/settings）
- [ ] 前端设置页预算展示（先做前置分析，后实施）
- [ ] decision_log 字段闭环、验证文档
- 验收：完整手动探查清单跑通。

## 10. 风险与开放决策

| 风险 | 等级 | 对策 |
|------|------|------|
| 候选池 JSON 解析失败 | 低 | 三级兜底：组数减为一个→纯文本→template 填充 |
| 记忆唤起重复提旧话 | 中 | topic 去重 + 时段限次(2 条/天) + LLM 自裁 |
| 软预算「话痨失控上不封顶」 | 中 | 硬顶保险丝 HARD_CAP + mute 语义保留 |
| RoutineLearner 数据噪声 | 低 | 异常日剔除、7天滚动均值 |
| context_builder 重构回归 | 中 | Phase 1 单独回归测试对照 |

开放决策（需在开工时敲定，相关方确认即可）：
- `HOURLY_BASE` 与权重初始值作为配置项暴露（先保守取值，后续调）；
- 前端是否展示「常态作息窗口」建议（>Phase 3 决策）。

---

## 11. 实施记录（v2 已落地 · 2026-08-19）

### 11.1 落地清单

**新增模块**
- `core/persona_assembler.py` — 共享人设组装入口（L1/L2/L4/L4.5 薄委托 ContextBuilder，对话行为字节零变化）
- `core/pad_tone_rules.py` — PAD 档位规则表：三轴分档 + 15 组高频组合 + 逐轴兜底拼接（`classify()`）
- `core/proactive_planner.py` — PulsePlanner 整点滚动规划（决策系数模型 + `PlannedPulse`）
- `core/routine_learner.py` — RoutineLearner 近 7 天作息学习（噪音日过滤 + JSON 持久化）

**改造**
- `core/llm_caller.py::generate_push` — v2：人设改为共享组装；拆除"小分享+轻量问题"固定框架；PAD 档位+原值双通道；注入世界/记忆阑色；候选池排序取首条（三级兜底）
- `core/companion.py` — `_dispatch_push` 注入 PAD/世界/记忆唤起并透传 `trigger_shape`；`_pulse_state_snapshot` 整点状态快照；`_apply_proactive_overlay` 支持软预算/硬顶热更新；decision_log 动机字段补齐
- `core/push_scheduler.py` — PushPolicy 软预算+硬顶保险丝+pending 计划队列；CronScheduler 新增整点自检任务、pending 处理器、作息锚点搬运（wake/sleep）
- `config/proactive.yaml` — 新增 v2 配置节（soft_budget/hard_cap/candidate_pool/routine）；`morning_brief` 标注 `anchor: wake`，`goodnight` 标注 `anchor: sleep`

**测试**：`tests/test_pad_tone_rules.py`（6 项）、`tests/test_proactive_scheduler_v2.py`（22 项：PulsePlanner/RoutineLearner/PushPolicy）

### 11.2 验证结果

- 相关回归套件 **141 passed**；ContextBuilder 行为零变化（字节级）
- mock-LLM 端到端冒烟：人设同源 / 旧框架删除 / PAD 双通道 / 世界·记忆注入 / 候选取首条 全部命中
- 全量非 e2e：1637 passed / 32 failed —— 32 项均为测试环境顺序污染（独立重跑全部通过），与本改动无关

### 11.3 前端展示前置分析（本轮未动前端，后续评估）

若要设置页展示"软预算/硬顶/作息窗口/今日已发"：
- 后端契约已就绪：settings.yaml proactive 节可存取 soft_budget/hard_cap；`PushPolicy.snapshot()` 现成
- 影响面：`electron/renderer/js/settings.js`（proactive 区渲染 + PUT 合并）、`core/api_server`（透传 settings 已是√）
- 观察期替代：日志/decision_log 即可观测，无需改前端

### 11.4 运行注意事项

1. **软预算语义**：`max_per_day` 不再硬停，由 `HARD_CAP`（默认 max*1.5、最低 20）兜底；要严格上限请在设置中显式 `hard_cap = max_per_day`
2. **记忆唤起额度**：当前为进程内存态（冷却 2h / 当日 ≤2 次，重启归零），下个迭代持久化到 `routine_profile.json`
3. **作息学习**：首次需积累近 7 天有效数据（每日 ≥3 条且跨度 ≥8h）才产出窗口，状态落 `data/routine_profile.json`
4. **锚点搬移**：仅 `anchor` 标注的场景跟随作息；其余 cron 场景保持原时刻
