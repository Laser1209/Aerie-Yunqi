# 内在状态接入对话 + 情绪/关系数值自然化 — 设计文档

- 日期：2026-08-09
- 状态：待用户审阅
- 范围：`core/`（对话产出链路 + 情绪/关系引擎）
- 原则：最小侵入、复用在项目已有的 provider 模式、不破坏 persona 特性

---

## 1. 背景与动机

现状梳理：

1. **内在状态（需求/疲劳/类神经化学）只被仪表盘调用**。`InternalStateEngine.compute()` 仅通过 `companion.get_internal_state()` 给 dashboard 展示，**没有进入对话产出链路**，因此不直接影响她的行为。
2. **关系判定很粗糙**。`RelationshipEngine._estimate_valence()` 只用两组硬编码关键词做 `any in text` 判断，不看强度、不看上下文（如"别"在负向，会误判"别担心"）。
3. **关系涨跌幅度固定**。正负分支都按固定 `learning_rate`（0.08）增减，不贴合真实互动强度。
4. **情绪安静时也会漂移**。`EmotionEngine.idle_tick()` 每 30 秒加 `random.gauss(0, 0.01)` 噪声，无输入时 PAD 也会随机变化。
5. **情绪爆发节奏偏突兀**。`emotion_threshold.TEXT_TRIGGERS` 部分单次 delta 很大（如"分手"→anxiety +60），容易瞬间挤到阈值触发爆发。

目标：把内在状态真正接进对话产出，并让情绪/关系数值的变化更符合直觉。

---

## 2. 目标与非目标

### 目标
- 内在状态（needs / fatigue / neurochemical）软注入对话产出，影响 LLM 行为。
- 关系正负判定更准确、涨跌更贴合互动强度。
- 情绪 PAD 无输入时不无故跳变。
- 情绪爆发节奏更渐进自然。

### 非目标
- 不改变世界模拟（phase/location/energy）逻辑。
- 不做内在状态的硬性行为规则（用户已选"软注入提示词"）。
- 不重写 persona 特性，只做克制微调。
- 不新增第三方依赖。

---

## 3. 方案 A1：内在状态接入对话产出

完全仿照现有 `self_model_snapshot_provider` 模式，新增一条 provider 链路。

### 3.1 接线链路（现状）

```
pipeline.py
  world_snapshot        = _call_optional_context_provider("world_snapshot_provider")
  relationship_snapshot = _call_optional_context_provider("relationship_snapshot_provider", user_id)
  self_model_snapshot   = _call_optional_context_provider("self_model_snapshot_provider", world, rel)
  ctx_messages = ctx_builder.build(..., world_snapshot=..., relationship_snapshot=..., self_model_snapshot=...)
```

`_call_optional_context_provider(name, *args)` 用 `getattr(self, name)` 取 provider，失败返回 `None`。

### 3.2 新增部分

新增第 4 条 provider：`internal_snapshot_provider`。

| 文件 | 改动 |
|------|------|
| `core/companion.py` | 新增方法 `_internal_snapshot_for_context(world_snapshot, relationship_snapshot)`：内部取 emotion（`self.get_primary_emotion_state()`）后调 `self.internal_state.compute(world_snapshot, emotion, relationship_snapshot)`。 |
| `core/companion.py` | 在已有 provider 注册处（约 L277-279）追加 `self.pipeline.internal_snapshot_provider = self._internal_snapshot_for_context`。 |
| `core/pipeline.py` | 在 `self_model_snapshot` 之后新增 `internal_snapshot = self._call_optional_context_provider("internal_snapshot_provider", world_snapshot, relationship_snapshot)`，并作为关键字参数传给 `ctx_builder.build(..., internal_snapshot=internal_snapshot)`。 |
| `core/context_builder.py` | `build()` 增加参数 `internal_snapshot: dict | None = None`；在 `route_mode == "FULL"` 且非空时，注入【内在状态·模拟】块（见 3.3），并附铁律提示。 |

> 说明：`InternalStateEngine.compute()` 已是确定性、source-tracked 的纯函数，接收 `world / emotion / relationship` 三元输入，天然适配 provider 模式，无需改动引擎本身。

### 3.3 注入块内容（软性）

`context_builder.py` 在 FULL 模式下、`internal_snapshot` 非空时追加：

```
【内在状态·模拟】
需求：社交 x.xx，陪伴 x.xx，探索 x.xx，休息 x.xx
疲劳：x.xx
活力 x.xx（类多巴胺），平静 x.xx（类血清素），压力 x.xx（类皮质醇）
这是计算模型，非生物测量；只用于调节语气与主动性，不得向用户报数。
```

仅作为 LLM 的自然语言背景，不产生硬性行为约束。

### 3.4 错误处理
- provider 缺省（未注册/异常）时 `_call_optional_context_provider` 返回 `None`，注入块自动跳过，与现有 world/relationship 行为一致。

---

## 4. 情绪/关系数值自然化

四个调整点，均按"保守微调 + 测试验证"执行，不破坏 persona 特性。

### 4.1 关系判定更准确（复用情绪 P）

- `core/relationship_engine.py`：`observe_user_message()` 增加可选参数 `pleasure: float | None = None`。
  - 若 `pleasure is not None`：以 P 值作为 valence（P>0 正、P<0 负、强度 `|P|`），跳过粗糙的关键词判定。
  - 否则：回退现有 `_estimate_valence()`，保证事件路径（`world_port` 内调用）不传 P 时行为不变。
- `core/companion.py` `_on_qq_message()`（约 L1219-1225）：调用 `observe_user_message` 时传入 `pleasure=emotion_pad.get("P")`（取自 `self.get_primary_emotion_state()`）。
- 效果：关系判定与情绪引擎天然一致，"超级爱你"→P 高→关系涨得多；"别管我"→P 低→掉得多。

### 4.2 涨跌更符合直觉（强度缩放 + conflict 均衡）

- `core/relationship_engine.py`：
  - 正负分支中，用 `strength = min(1.0, abs(valence))` 缩放 rate（如 `rate * (0.5 + 0.5 * strength)`），让强情感涨跌更明显、弱情感更平缓。
  - 均衡 conflict：正向修复冲突上调（如 `- rate*0.6`），负向累积冲突下调一点（如 `+ rate*0.8`），避免冲突只增难消。
- 具体系数在实现时以不破坏 persona 为前提确定，并纳入测试。

### 4.3 情绪更平滑不跳变（idle 去噪）

- `core/emotion_engine.py` `idle_tick()`（约 L494-507）：**去掉 `random.gauss` 随机噪声**，只保留 EMA 向基线漂移（`0.98*cur + 0.02*base`）。
- 效果：无输入时 PAD 平滑缓慢回归基线，不再随机跳动、情绪标签不再无故变化。

### 4.4 情绪爆发节奏更渐进（削减单次大 delta）

- `core/emotion_threshold.py` `TEXT_TRIGGERS`：削减单次 delta 过大的项，降低"瞬间挤爆阈值"。
  - 示例：`(["分手","离开","结束","再见"], "anxiety", 60)` → 40；`(["不爱你了","不喜欢你了","喜欢别人"], "anxiety", 50)` → 35；`(["你有病","滚","滚开"], "patience", 30)` → 22。
- 同时 4 个槽位初值/衰减是否微调，作为可选步骤，以"更渐进、不突兀"为准，保守执行。

---

## 5. 数据流（改动后）

```
用户消息
  └─► emotion_engine.update_trajectory_async()  ──► PAD / 4 槽位
  └─► relationship_engine.observe_user_message(pleasure=P)  ──► 关系 8 维
  └─► world_port 世界快照
        └─► internal_state.compute(world, emotion, relationship)  ──► 内在状态
              └─► pipeline 读取 internal_snapshot_provider
                    └─► context_builder 注入【世界】【关系】【情绪】【内在状态】
                          └─► LLM 生成回复
```

三套原有注入 + 新增【内在状态】共同作用于回复的语气、主动性与边界。

---

## 6. 错误处理
- 所有 provider 均经 `_call_optional_context_provider`，缺省/异常安全返回 `None`。
- `relationship_engine.observe_user_message` 新增的 `pleasure` 为可选参数，回退路径保持原行为。
- `context_builder` 注入块仅在 FULL 模式且快照非空时追加。

---

## 7. 测试
- 新增/更新 `tests/` 下 pytest 用例：
  1. `companion._internal_snapshot_for_context`：输入 world+emotion+relationship，输出含 needs/fatigue/neurochemical，且确定性可复现。
  2. `context_builder` FULL 模式：`internal_snapshot` 非空时注入块存在；`None` 或非 FULL 时不注入。
  3. `relationship_engine.observe_user_message(pleasure=…)`：P 高则关系净增、P 低则净减，且强度缩放生效；不传 pleasure 时走关键词回退且行为不变。
  4. `emotion_engine.idle_tick`：多次调用无输入时 PAD 无随机跳变（确定性收敛基线）。
  5. `emotion_threshold.scan_text`：大 delta 削减后，单条消息不再瞬间触发爆发。
- 运行：项目 pytest 全量（`python -m pytest tests/`）确保无回归。

---

## 8. 涉及文件清单
- `core/companion.py`
- `core/pipeline.py`
- `core/context_builder.py`
- `core/relationship_engine.py`
- `core/emotion_engine.py`
- `core/emotion_threshold.py`
- `config/persona_behavior.yaml`（可选：阈值初值/衰减微调）
- `tests/`（新增用例）