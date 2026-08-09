# 内在状态接入对话 + 情绪/关系数值自然化 - Implementation Plan

> 依据：`.trae/specs/internal-state-injection-and-affect-naturalization/spec.md`
> 原则：TDD（先写失败测试 → 跑红 → 最小实现 → 跑绿 → 提交）；每任务独立可运行；不破坏 persona 特性。

## Task 1: 内在状态 provider 注册（companion）
- **Priority**: high
- **Depends On**: None
- **Files**:
  - Modify: `core/companion.py`（`_self_model_snapshot_for_context` 附近新增方法；L277-279 附近注册）
- **Description**:
  - 新增 `_internal_snapshot_for_context(world_snapshot, relationship_snapshot) -> dict | None`：取 `self.get_primary_emotion_state()` 的 pad，调 `self.internal_state.compute(world_snapshot, emotion, relationship_snapshot)` 返回快照；异常/缺省返回 None。
  - 在 provider 注册处追加 `self.pipeline.internal_snapshot_provider = self._internal_snapshot_for_context`。
- **Test Requirements**:
  - `programmatic` TR-1.1: world + emotion + relationship 输入时，返回含 `needs` / `fatigue` / `neurochemicals` 的 dict。
  - `programmatic` TR-1.2: 相同输入两次调用结果一致（确定性）。
- **Notes**: provider 签名与 `_self_model_snapshot_for_context(world, relationship)` 同构。

## Task 2: pipeline 读取 internal_snapshot 并透传
- **Priority**: high
- **Depends On**: Task 1
- **Files**:
  - Modify: `core/pipeline.py`（`_run_once` 主链路 L327-353；轻量链路 L2200-2206 可选）
- **Description**:
  - 在 `self_model_snapshot` 之后新增 `internal_snapshot = self._call_optional_context_provider("internal_snapshot_provider", world_snapshot, relationship_snapshot)`。
  - 作为关键字参数传给 `ctx_builder.build(..., internal_snapshot=internal_snapshot)`。
- **Test Requirements**:
  - `programmatic` TR-2.1: provider 未注册时返回 None，不影响构建。
  - `programmatic` TR-2.2: 注册后 internal_snapshot 被传入 build。
- **Notes**: 复用 `_call_optional_context_provider`，缺省安全。

## Task 3: context_builder 注入【内在状态·模拟】块
- **Priority**: high
- **Depends On**: Task 2
- **Files**:
  - Modify: `core/context_builder.py`（`build()` 签名 + 注入位置，参照 world_snapshot L119-132）
  - Test: `tests/test_context_builder_internal.py`
- **Description**:
  - `build()` 增加参数 `internal_snapshot: dict | None = None`。
  - `route_mode == "FULL"` 且非空时，追加：
    ```
    【内在状态·模拟】
    需求：社交 x.xx，陪伴 x.xx，探索 x.xx，休息 x.xx
    疲劳：x.xx
    活力 x.xx（类多巴胺），平静 x.xx（类血清素），压力 x.xx（类皮质醇）
    这是计算模型，非生物测量；只用于调节语气与主动性，不得向用户报数。
    ```
  - 从 `internal_snapshot["needs"]` / `["fatigue"]` / `["neurochemicals"]` 取 `value` 字段。
- **Test Requirements**:
  - `programmatic` TR-3.1: FULL 模式 + 非空快照 → 输出含"内在状态"与各数值。
  - `programmatic` TR-3.2: `internal_snapshot=None` 或非 FULL → 不注入。
- **Notes**: 软性背景，不产生硬性约束。

## Task 4: 关系判定复用情绪 P
- **Priority**: high
- **Depends On**: None
- **Files**:
  - Modify: `core/relationship_engine.py`（`observe_user_message` 签名 + valence 逻辑）
  - Modify: `core/companion.py`（`_on_qq_message` L1219-1225 传 pleasure）
  - Test: `tests/test_relationship_engine.py`（新增/更新）
- **Description**:
  - `observe_user_message(..., pleasure: float | None = None)`：
    - `pleasure is not None`：`valence = pleasure`（P>0 正、P<0 负、强度 `abs(P)`），跳过 `_estimate_valence`。
    - 否则：回退现有关键词判定。
  - `_on_qq_message` 调用处传 `pleasure=emotion_pad.get("P")`（emotion 取自 `self.get_primary_emotion_state()`）。
- **Test Requirements**:
  - `programmatic` TR-4.1: `pleasure=0.8` → 关系净增；`pleasure=-0.6` → 净减。
  - `programmatic` TR-4.2: 不传 pleasure 时走关键词回退，行为与原来一致。
- **Notes**: 事件路径（world_port 内调用）不传 P 时行为不变。

## Task 5: 涨跌强度缩放 + conflict 均衡
- **Priority**: medium
- **Depends On**: Task 4
- **Files**:
  - Modify: `core/relationship_engine.py`（`observe_user_message` 正负分支）
  - Test: `tests/test_relationship_engine.py`
- **Description**:
  - 用 `strength = min(1.0, abs(valence))` 缩放 rate：`eff_rate = learning_rate * (0.5 + 0.5 * strength)`，正负分支改用 `eff_rate`。
  - advice: 正向冲突修复 `- eff_rate*0.6`；负向冲突 `+ eff_rate*0.8`。
- **Test Requirements**:
  - `programmatic` TR-5.1: 强情感（|P| 大）比弱情感涨跌更明显。
  - `programmatic` TR-5.2: 冲突在正向互动下可被修复下降。
- **Notes**: 系数保守，以不破坏 persona 为准。

## Task 6: 情绪 idle 去噪（PAD 平滑）
- **Priority**: medium
- **Depends On**: None
- **Files**:
  - Modify: `core/emotion_engine.py`（`idle_tick` L494-507）
  - Test: `tests/test_emotion_engine.py`
- **Description**:
  - 去掉 `random.gauss(0, 0.01)` 噪声，仅保留 EMA 向基线漂移：`state[k] = 0.98 * cur + 0.02 * base`，clamp [-0.95, 0.95]。
- **Test Requirements**:
  - `programmatic` TR-6.1: 多次调用无输入时 PAD 确定性收敛基线，无随机跳变。
- **Notes**: 无输入时平滑回归基线。

## Task 7: 情绪爆发节奏渐进（削减大 delta）
- **Priority**: medium
- **Depends On**: None
- **Files**:
  - Modify: `core/emotion_threshold.py`（`TEXT_TRIGGERS` L68-123）
  - Test: `tests/test_emotion_threshold.py`
- **Description**:
  - 削减单次 delta 过大的项：
    - `(["分手","离开","结束","再见"], "anxiety", 60)` → 40
    - `(["不爱你了","不喜欢你了","喜欢别人"], "anxiety", 50)` → 35
    - `(["别找我了","不要你了"], "anxiety", 55)` → 40
    - `(["你有病","滚","滚开"], "patience", 30)` → 22
- **Test Requirements**:
  - `programmatic` TR-7.1: 削减后单条消息不再瞬间触发爆发（需叠加调用才达到阈值）。
- **Notes**: 4 槽位初值/衰减是否微调为可选，谨慎执行。

## Task 8: 全量回归验证
- **Priority**: high
- **Depends On**: Task 1-7
- **Files**:
  - Test: `tests/`（全量）
- **Description**:
  - 运行 `python -m pytest tests/ -q`，确认所有改动无回归。
  - 复跑新增用例（TR-1.1~7.1）全部通过。
- **Test Requirements**:
  - `programmatic` TR-8.1: 全量测试通过，无失败。
- **Notes**: 若因情绪 delta 削减导致既有断言失败，按新语义更新断言并记录。