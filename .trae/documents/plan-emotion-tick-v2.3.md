# 情绪仪表盘 · 实时仿真 + PAD 流通量条形图（Plan v2.3）

> 用户最新反馈："情绪仪表盘里当前情绪是 neutral，月度没显示唤醒度/支配度，隐藏槽位四个栏都没动，情绪历史曲线没跟随时间实时位移"
>
> 用户决策（2026-07-17）：
> 1. **后台 tick 仿真**：加 background tick，让 emotion engine 周期性衰减 + 扰动
> 2. **阈值按 YAML 走同比例**：daily_decay 同比缩到 hourly
> 3. **PAD 可视化**：环下加原始数值行 + **右侧加一个条形图实时展示流通量**（dP/dt, dA/dt, dD/dt）

---

## 0. 根因复盘

- [core/emotion_engine.py L88-L119](file:///e:/Agent_reply/core/emotion_engine.py#L88-L119)：`EmotionEngine.__init__` 只设 baseline，没有 background tick
- `update_trajectory_async` 是**唯一**改 `_state` 的入口，**只在 chat 消息时触发**
- [core/emotion_threshold.py L238-L246](file:///e:/Agent_reply/core/emotion_threshold.py#L238-L246)：`daily_decay` 也只被 chat 流程触发
- [core/companion.py L160](file:///e:/Agent_reply/core/companion.py#L160)：启动时只创建 `_daily_decay_task`（按天），没有 sub-day tick
- 实测：24h 58 条 snapshot 中最后 30+ 条都是 P=0.001 的"占位"行，曲线视觉上"不动"
- PAD 后端值 P=0.01 / A=-0.015 / D=0.091 接近 0 → 前端环比例 50% 偏 1px，用户视觉上"没显示"

---

## 1. 设计要点

### 1.1 后端 background tick（每 10s 一次）
- `core/emotion_engine.py`：加 `idle_tick()` 方法
  - 读取 `_state` 当前 P/A/D
  - 走 EMA 向 baseline 缓慢回归（系数 0.02/tick）
  - 加微小随机扰动（±0.01，种子用 time.time）
  - 更新 `_state` 内存
  - 不写 snapshot（写频率会爆炸）
- `core/emotion_threshold.py`：加 `hourly_decay()`（daily_decay ÷ 24）
- `core/companion.py`：新增 `_emotion_tick_task`，10s 周期
  - 调 `self.emotion.idle_tick()` + `self.emotion.threshold_engine.hourly_decay()`
  - 每 60s（每 6 个 tick）调一次 `state_store.snapshot(..., trigger_event="idle_tick")` 给 history 曲线喂点
  - 失败不抛、不影响主流程
- `core/api_server.py`：`/api/emotion/state` 已经能返回最新 `_state`，前端 3s 轮询能自动看到新数据

### 1.2 前端：PAD 三卡原始数值行 + 流通量条形图
- [electron/src/renderer/styles/main.css](file:///e:/Agent_reply/electron/src/renderer/styles/main.css)：新增 `.pad-card-raw` 样式（小号灰色，环下方）
- [electron/src/renderer/js/emotion-dashboard.js](file:///e:/Agent_reply/electron/src/renderer/js/emotion-dashboard.js)：
  - `_setPADCard()` 新增写 `.pad-card-raw` 元素，3 位小数
  - 新增内部字段 `_prevPad`（上次 tick 的 P/A/D）
  - 新增 `_setFlowBars()` 方法：3 个水平条，正绿负红，长度 = |delta| × 500
  - 在 `_render()` 末尾调 `_setFlowBars()` 后再更新 `_prevPad`
- [electron/src/renderer/index.html](file:///e:/Agent_reply/electron/src/renderer/index.html)：在 `#panel-emotion` 的 `.pad-row` 后加 `#emotion-flow-bars` 容器
- 历史曲线因为 idle_tick 写新数据点 → 24h/7d 窗口会自动出现新点

### 1.3 不动的部分
- 不改 `update_trajectory_async` 路径（保持 LLM 情绪推理的语义）
- 不改 LLM/emotion_state_store 现有 schema
- 不动 SSE（轮询足够，10s tick + 3s 轮询 = 1 帧延迟）
- 不动 `e2e_narration.py` / `verify_zero_regression.py` / 零回归套件

---

## 2. 改动清单

### 2.1 [core/emotion_engine.py](file:///e:/Agent_reply/core/emotion_engine.py) — 新增 `idle_tick()`

```python
# 加在 get_state() 之后，import 头部加 random + math

def idle_tick(self) -> dict:
    """R7.5: periodic background tick for dashboard liveness.

    - EMA: 0.98 * current + 0.02 * baseline   (gentle pull toward neutral)
    - plus tiny Gaussian noise (sigma=0.01) so the dashboard never
      looks frozen.
    - No LLM call, no DB write here (caller decides when to snapshot).
    Returns the new state for inspection.
    """
    import random
    import math
    for k in ("P", "A", "D"):
        cur = float(self._state.get(k, 0.0))
        base = float(self._baseline.get(k, 0.0))
        ema = 0.98 * cur + 0.02 * base
        noise = random.gauss(0.0, 0.01)
        self._state[k] = max(-0.95, min(0.95, ema + noise))
    return dict(self._state)
```

### 2.2 [core/emotion_threshold.py](file:///e:/Agent_reply/core/emotion_threshold.py) — 新增 `hourly_decay()`

```python
def hourly_decay(self) -> None:
    """R7.5: hourly equivalent of daily_decay (decay_per_day / 24)."""
    for slot in self.slots.values():
        decay = slot.decay_per_day / 24.0
        slot.value = max(0, slot.value - decay)
```

### 2.3 [core/companion.py](file:///e:/Agent_reply/core/companion.py) — 加 `_emotion_tick_task`

```python
# 在 _daily_decay_task 旁边
self._emotion_tick_task: asyncio.Task | None = None

# start() 里
self._emotion_tick_task = asyncio.create_task(self._emotion_tick_loop())

# 新方法
async def _emotion_tick_loop(self) -> None:
    """R7.5: 10s tick for emotion state + hourly decay.
    Every 6th tick (60s) writes a snapshot so the history curve stays alive.
    """
    n = 0
    try:
        while True:
            await asyncio.sleep(10)
            try:
                self.emotion.idle_tick()
                self.emotion.threshold_engine.hourly_decay()
                n += 1
                if n % 6 == 0:
                    from core.emotion_state_store import EmotionStateStore
                    state = self.emotion.get_state(0)
                    EmotionStateStore(self.db).snapshot(
                        0,
                        {"label": state.get("label"), "pad": state.get("pad")},
                        state.get("thresholds", {}),
                        trigger_event="idle_tick",
                    )
            except Exception as e:
                logger.debug("emotion tick loop error: %s", e)
    except asyncio.CancelledError:
        return

# shutdown() 里 cancel
if self._emotion_tick_task:
    self._emotion_tick_task.cancel()
    try: await self._emotion_tick_task
    except asyncio.CancelledError: pass
```

### 2.4 [electron/src/renderer/index.html](file:///e:/Agent_reply/electron/src/renderer/index.html) — PAD 环 + 流通量容器

在 `.pad-row` 后插入：
```html
<div class="emotion-flow-bars" id="emotion-flow-bars">
  <div class="emotion-flow-row" data-flow="P">
    <span class="emotion-flow-label">dP/dt</span>
    <div class="emotion-flow-track">
      <div class="emotion-flow-center"></div>
      <div class="emotion-flow-fill emotion-flow-fill--pos"></div>
    </div>
  </div>
  <!-- 同样 dA/dt, dD/dt -->
</div>
```

### 2.5 [electron/src/renderer/styles/main.css](file:///e:/Agent_reply/electron/src/renderer/styles/main.css) — PAD 原始值 + 流通量样式

```css
.pad-card-raw {
  font-size: 10px;
  color: var(--color-text-muted);
  font-family: var(--font-mono);
  text-align: center;
  margin-top: -8px;
}
.emotion-flow-bars { ... 水平条 ... }
.emotion-flow-fill--pos { background: var(--success); }
.emotion-flow-fill--neg { background: var(--danger); }
```

### 2.6 [electron/src/renderer/js/emotion-dashboard.js](file:///e:/Agent_reply/electron/src/renderer/js/emotion-dashboard.js) — 渲染逻辑

- `_setPADCard()` 末尾加 `pad-raw` 写入
- 新增 `_setFlowBars(P, A, D)` 比较上次和本次的 delta
- `_render()` 末尾调 `_setFlowBars(P, A, D)`
- `init()` 初始化 `_prevPad = null`

---

## 3. 验证

```bash
# 后端冒烟
curl http://127.0.0.1:7890/api/emotion/state   # 10s 内 P/A/D 应有微小变化
curl "http://127.0.0.1:7890/api/emotion/history?window=1h"  # 60s 后应出现 trigger_event=idle_tick 的新点

# 回归
python verify_zero_regression.py   # 14/14
python e2e_pacing.py               # 96/96
python e2e_self_evolve.py          # 20/20

# 前端自检
npm run check:emojis; npm run check:forbidden; npm run check:tokens
```

---

## 4. 风险

- idle_tick 与 daily_decay 同跑可能冲突：daily_decay 是按天一次性扣减，hourly_decay 是按时持续扣减。两者**不会**冲突（hourly_decay 不会改 last_decay_date 字段），但需要确保 daily_decay 不在 tick 循环里被触发。
- 写入频率：60s 一次 snapshot = 1440/天 = 60 KB/天，可接受
- idle_tick 写 snapshot 失败要 swallow，不能挂主流程
