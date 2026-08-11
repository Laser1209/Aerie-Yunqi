# 世界·生图·情绪·推送 串导卡死修正计划

> **For agentic workers:** REQUIRED SUB-SKILL: 按任务逐条执行。步骤用 `- [ ]` 复选框跟踪。

**Goal:** 修复「世界推进停摆 → 时段卡死 → 主动发图去重空转」与「生图候选发布但不落盘/不生成」，让世界/生图/情绪/推送正确互相贴合、串导，不再卡死。

**Architecture:** 三层兜底——① `WorldSimulation.get_snapshot()` 加"新鲜度校验"（缓存过期强制 `tick()` 重算时段/话题），从读快照方根治"旧时段/旧话题"；② 修正 `tick()` 对 naive 时钟的时区归一化，杜绝"本地 16:48 被误判成 morning"；③ 世界循环加自愈 + 生图候选消费链路兜底落盘，保证"发布了就一定被消费并落盘终态"。

**Tech Stack:** Python asyncio / pytest / 现有 WorldSimulation / WorldImageCandidateConsumer / companion.py。

---

## 一、问题汇总（来自本次对话排查，含证据等级）

### P0 已证实（日志 + 代码双重确认）

| # | 问题 | 现象 | 根因 | 证据 |
|---|---|---|---|---|
| P0-1 | **世界时段间歇性卡死** | 16:48~18:32 世界快照 phase 停在 `morning`，视觉话题只有 `morning_plan`，被 4h 去重窗口挡住，主动发图每分钟空转一次（`skip duplicate visual topic=morning_plan within 14400s`） | `get_snapshot()` 只返回缓存 `_snapshot` 不重算（[world_simulation.py#L494-L497](file:///e:/Agent_reply/core/world_simulation.py#L494-L497)）；时段推进完全依赖 `_run_world_loop` 每 300s `wp.tick()`；16:48 本地应属 `afternoon`(14-19) 却判 `morning`，疑似 `tick()` 对 naive 时钟时区误判 | [backend.stderr.2026-08-11T08-47-50.raw.log#L84-L120](file:///e:/Agent_reply/logs/backend.stderr.2026-08-11T08-47-50.raw.log) |
| P0-2 | **生图候选发布但不落盘/不生成** | 18:33/18:34 发布 `deep_focus` 候选后无生成/交付/失败日志，`world_image_candidates.json` 最新一条仍停在 16:43 的 `morning_plan`(completed) | `process_event()` 有多个分支（`disabled`/`offline`/`expired`）直接 return 不写 store（[world_image_candidates.py#L288-L351](file:///e:/Agent_reply/core/world_image_candidates.py#L288-L351)）；消费驱动链无持续运行日志 | [backend.stderr.2026-08-11T08-47-50.raw.log#L503-L506](file:///e:/Agent_reply/logs/backend.stderr.2026-08-11T08-47-50.raw.log) |
| P0-3 | **生图决策依赖"缓存且不重算"的快照 → 旧时段/旧话题** | 主动发图循环取 `_world_snapshot_for_context()` → `get_world_snapshot()` → `get_snapshot()` 返回缓存 | 与 P0-1 同源；主动发图 [companion.py#L2166-L2172](file:///e:/Agent_reply/core/companion.py#L2166-L2172) 读取的正是这份缓存 | 代码确认 |
| P0-4 | **主动推送与主动发图频控不共享（错频）** | 文字推送 `PushPolicy.max_per_day=10 / min_interval_min=15`；主动发图 `image_max_per_day=0(无限) / photo_min_interval_sec=0(无间隔)` + 主题 4h 去重。`max_per_day` 完全管不住发图 | 两套独立频控，主动发图循环不读 `PushPolicy`（[companion.py#L2133-L2199](file:///e:/Agent_reply/core/companion.py#L2133-L2199)） | 代码确认 |

### P1 未证实（子 Agent 推理，需观察/低危）

| # | 问题 | 说明 |
|---|---|---|
| P1-1 | **"陈旧情绪"误判** | 情绪经 `CompanionState.load()` 持久化，生图读 `state._emotion_change`，但情绪更新与生图决策无强同步；无日志证据，低危 |
| P1-2 | **时钟源未统一** | 世界模块归一化 `LOCAL_TZ`；情绪/欲望/推送直接 `datetime.now()`(naive)。同机同区一致，低危 |

### 已修复（上下文，非本次，勿重复）
太阳方位角、月相分类、视觉判重模板、主动发图话题轮换、世界时钟 UTC→本地归一化（已有部分处理）。

---

## 二、修复策略

- **必做（根治 P0）**：Task 1（根因审计）→ Task 2（时区归一化）→ Task 3（快照新鲜度校验）→ Task 4（主动发图接入新鲜快照 + 世界循环自愈/日志）。
- **加固**：Task 5（生图候选消费兜底落盘）。
- **决策项**：Task D（主动发图额度并入 `max_per_day`，需用户确认）。
- **可选/低危**：Task E（陈旧情绪加固 / 时钟源统一）。

---

## Task 1: 根因审计——复现"16:48 本地被误判 morning"

**Files:**
- Modify: `e:\Agent_reply\core\world_simulation.py`（仅阅读确认）
- Test: `e:\Agent_reply\tests\test_p1_c1_world_simulation.py`

- [ ] **Step 1: 先跑现有测试确认 phase 语义基线**

Run:
```bash
cd e:\Agent_reply
.venv\Scripts\python.exe -m pytest tests/test_p1_c1_world_simulation.py -v
```
Expected: 现有用例全部 PASS。**重点看 `test_phase_mapping_by_hour` 的 expected**——它决定"clock 返回的 hour 被当成本地小时还是 UTC 小时"。记录结果供 Task 2 决策。

- [ ] **Step 2: 写复现测试（临时，确认后保留为回归）**

在 `tests/test_p1_c1_world_simulation.py` 末尾追加：

```python
def test_16_48_local_should_be_afternoon():
    """本地 16:48 应判 afternoon(14-19)，绝不能是 morning。"""
    from datetime import datetime, timezone
    from core.world_simulation import WorldSimulation

    # 方式A：clock 返回 aware 本地时间（正确约定）
    aware_local = datetime(2026, 8, 11, 16, 48, tzinfo=timezone.utc).astimezone()
    sim = WorldSimulation(clock=lambda: aware_local)
    assert sim.tick().phase == "afternoon"
```

- [ ] **Step 3: 跑测试验证行为**

Run:
```bash
.venv\Scripts\python.exe -m pytest tests/test_p1_c1_world_simulation.py::test_16_48_local_should_be_afternoon -v
```
Expected: **PASS** → 说明 aware 本地时钟下判定正确，根因在"运行时 clock 实为 naive UTC"；**若 FAIL** → 记录实际 phase，直接定位到 `tick()` 归一化。

- [ ] **Step 4: 审计运行时 clock 来源**

Grep 确认 `WorldSimulation` 与 `InProcessWorldAdapter` 构造时是否传了 clock：
- `core/world_port.py` `InProcessWorldAdapter.__init__` 里 `WorldSimulation()`（默认 `datetime.now(LOCAL_TZ)` aware）还是有外部注入。
- `core/companion.py` 创建 world_port 处是否覆盖 clock。
记录结论到本计划"Task 1 结论"注释。

- [ ] **Step 5: 提交（根因审计结论入库）**

```bash
git add tests/test_p1_c1_world_simulation.py
git commit -m "test(world): 钉住本地16:48应判afternoon的回归用例"
```

> Task 1 结论（执行后填写）: ____

---

## Task 2: 修正 `tick()` 对 naive 时钟的时区归一化

**Files:**
- Modify: `e:\Agent_reply\core\world_simulation.py`（`tick()` 归一化段，约 L398-L404）
- Test: `e:\Agent_reply\tests\test_p1_c1_world_simulation.py`

- [ ] **Step 1: 写失败测试（naive UTC 输入）**

```python
def test_naive_utc_clock_maps_to_local_phase():
    """clock 返回 naive UTC（如 08:47 UTC=本地16:47）应判 afternoon 而非 morning。"""
    from datetime import datetime
    from core.world_simulation import WorldSimulation

    naive_utc = datetime(2026, 8, 11, 8, 47)  # 无 tzinfo，代表 UTC
    sim = WorldSimulation(clock=lambda: naive_utc)
    assert sim.tick().phase == "afternoon"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_p1_c1_world_simulation.py::test_naive_utc_clock_maps_to_local_phase -v`
Expected: FAIL（当前 `now.replace(tzinfo=LOCAL_TZ)` 把 08:47 当本地 → morning）。

- [ ] **Step 3: 修改归一化——naive 一律先假定 UTC 再转本地**

在 `world_simulation.py` `tick()` 内：

```python
now = self.clock()
# 时区归一化：naive 一律视为 UTC 再转本地；aware 直接转本地。
# 绝不能用 replace(tzinfo=LOCAL_TZ) 把 naive 当作本地——否则 UTC 8 点会被误判成
# 本地 8 点(morning)，而正确应是本地 16 点(afternoon)，导致时段整体偏移 8h。
if now.tzinfo is None:
    now = now.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)
else:
    now = now.astimezone(LOCAL_TZ)
ts = int(now.timestamp())
```

- [ ] **Step 4: 跑测试确认通过 + 无回归**

Run:
```bash
.venv\Scripts\python.exe -m pytest tests/test_p1_c1_world_simulation.py -v
```
Expected: `test_naive_utc_clock_maps_to_local_phase` PASS；原有用例（尤其 `test_phase_mapping_by_hour`）若原本把 aware UTC hour 当本地小时，可能因语义变化而 FAIL——**若 FAIL，与 Task 1 结论对照，统一 clock 约定为"clock 恒返回 aware 本地时间"**，并同步修正相关测试的构造，保证语义一致。

- [ ] **Step 5: 提交**

```bash
git add core/world_simulation.py tests/test_p1_c1_world_simulation.py
git commit -m "fix(world): 修正 naive 时钟时区归一化,避免时段偏移8小时误判morning"
```

---

## Task 3: `get_snapshot()` 加新鲜度校验（根治"旧时段/旧话题"）

**Files:**
- Modify: `e:\Agent_reply\core\world_simulation.py`（`get_snapshot`，L494-L497）
- Test: `e:\Agent_reply\tests\test_p1_c1_world_simulation.py`

- [ ] **Step 1: 写失败测试**

```python
def test_get_snapshot_refreshes_when_stale():
    """缓存超过 max_age_sec 未更新时, get_snapshot 强制随真实时钟重算时段。"""
    from datetime import datetime, timezone
    from core.world_simulation import WorldSimulation

    def later_clock():
        return datetime(2026, 7, 28, 15, 0, tzinfo=timezone.utc).astimezone()

    sim = WorldSimulation(clock=lambda: datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc).astimezone())
    sim.tick()  # morning 缓存
    cached = sim.get_snapshot()
    assert cached.phase == "morning"

    sim.clock = later_clock  # 推进到 15:00 本地，但缓存未刷新
    # 默认 None：仍返回旧缓存（保持兼容）
    assert sim.get_snapshot().phase == "morning"
    # 传入 max_age_sec：过期 → 强制刷新 → 不再是 morning
    assert sim.get_snapshot(max_age_sec=300).phase != "morning"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_p1_c1_world_simulation.py::test_get_snapshot_refreshes_when_stale -v`
Expected: FAIL（当前 `get_snapshot` 忽略 max_age_sec，恒返回 morning）。

- [ ] **Step 3: 实现新鲜度校验**

```python
def get_snapshot(self, *, max_age_sec: float | None = None) -> WorldSnapshot:
    """返回当前世界快照。

    传 ``max_age_sec`` 时，若缓存快照超过该秒数未刷新，则强制调用
    ``tick()`` 随真实时钟重算时段/话题——保证世界循环停摆时，
    主动发图等读快照方仍能拿到"当前时段"，杜绝旧时段/旧话题导致的去重空转。
    """
    if self._snapshot is None:
        return self.tick()
    if max_age_sec is None:
        return self._snapshot
    try:
        current = int(self.clock().timestamp())
    except Exception:
        return self._snapshot
    if self._cached_second is not None and (current - self._cached_second) > max_age_sec:
        return self.tick()
    return self._snapshot
```

- [ ] **Step 4: 跑测试确认通过 + 无回归**

Run: `pytest tests/test_p1_c1_world_simulation.py -v`
Expected: 新用例 PASS，其余无回归。

- [ ] **Step 5: 提交**

```bash
git add core/world_simulation.py tests/test_p1_c1_world_simulation.py
git commit -m "feat(world): get_snapshot 支持新鲜度校验, 缓存过期强制重算时段"
```

---

## Task 4: 主动发图接入新鲜快照 + 世界循环自愈/日志

**Files:**
- Modify: `e:\Agent_reply\core\world_port.py`（`InProcessWorldAdapter.get_world_snapshot`，L529-L530）
- Modify: `e:\Agent_reply\core\companion.py`（`_world_snapshot_for_context` L1034；`_run_proactive_photo_loop` L2166；`_run_world_loop` L2007-L2043）
- Test: `e:\Agent_reply\tests\test_phase11_world_port.py`

- [ ] **Step 1: 写失败测试（world_port 透传新鲜度参数）**

在 `tests/test_phase11_world_port.py` 追加：

```python
def test_get_world_snapshot_passes_max_age():
    """InProcessWorldAdapter.get_world_snapshot 应透传 max_age_sec 到 world.get_snapshot。"""
    from core.world_port import InProcessWorldAdapter
    from core.world_simulation import WorldSimulation

    calls = []
    class SpyWorld(WorldSimulation):
        def get_snapshot(self, *, max_age_sec=None):
            calls.append(max_age_sec)
            return super().get_snapshot(max_age_sec=max_age_sec)

    adapter = InProcessWorldAdapter(world=SpyWorld())
    adapter.get_world_snapshot(max_age_sec=60)
    assert calls == [60]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_phase11_world_port.py::test_get_world_snapshot_passes_max_age -v`
Expected: FAIL（当前签名无 `max_age_sec` 参数）。

- [ ] **Step 3: world_port 透传**

```python
def get_world_snapshot(self, *, max_age_sec: float | None = None) -> dict[str, Any] | None:
    return dict(self.world.get_snapshot(max_age_sec=max_age_sec))
```

- [ ] **Step 4: companion 读快照方支持新鲜度，主动发图强制新鲜**

`_world_snapshot_for_context` 增加透传并容错：

```python
def _world_snapshot_for_context(self, *, max_age_sec: float | None = None) -> dict | None:
    provider = getattr(self.world_port, "get_world_snapshot", None)
    if not callable(provider):
        return None
    try:
        if max_age_sec is None:
            return provider()
        try:
            return provider(max_age_sec=max_age_sec)
        except TypeError:  # 旧/无参适配器
            return provider()
    except Exception:
        logger.debug("world snapshot unavailable", exc_info=True)
        return None
```

`_run_proactive_photo_loop` L2166 改为强制新鲜（60s 兜底，覆盖世界循环停摆）：

```python
raw_snapshot = self._world_snapshot_for_context(max_age_sec=60)
```

- [ ] **Step 5: 世界循环自愈 + 关键日志**

在 `_run_world_loop` 内 `wp.tick()` 后记录 phase 变化（DEBUG 级，量小）：

```python
try:
    snap = wp.tick()
    phase = str(getattr(snap, "phase", "") or "")
    if phase != getattr(self, "_last_world_phase", None):
        logger.info("[WorldLoop] phase=%s", phase)
        self._last_world_phase = phase
except Exception:
    logger.warning("[WorldLoop] tick failed", exc_info=True)
```

新增自愈监控：`asyncio.create_task(self._run_world_loop())` 处（companion L581）改为包一层看门狗，任务异常结束后自动重建：

```python
async def _supervise_world_loop(self) -> None:
    while True:
        task = asyncio.create_task(self._run_world_loop())
        try:
            await task
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error("[WorldLoop] task died, restarting", exc_info=True)
        await asyncio.sleep(5)
```

并替换 L581 为 `self._world_loop_task = asyncio.create_task(self._supervise_world_loop())`。

- [ ] **Step 6: 跑测试确认通过 + 无回归**

Run: `pytest tests/test_phase11_world_port.py tests/test_p1_c1_world_simulation.py -v`
Expected: 新用例 PASS，其余无回归。

- [ ] **Step 7: 提交**

```bash
git add core/world_port.py core/companion.py tests/test_phase11_world_port.py
git commit -m "fix(world): 主动发图强制新鲜快照, 世界循环自愈并记录phase日志"
```

---

## Task 5: 生图候选消费链路兜底落盘

**Files:**
- Modify: `e:\Agent_reply\core\world_image_candidates.py`（`process_event` L288-L351）
- Modify: `e:\Agent_reply\core\companion.py`（消费驱动确认）
- Test: `e:\Agent_reply\tests\test_phase10_image_workflow.py`

- [ ] **Step 1: 审计消费驱动链（不改代码）**

Grep `process_event` / `consume_replay` / `subscribe` 的调用方，确认是否有后台循环持续消费 `image_candidates` 主题的新候选。记录结论：18:33/18:34 候选"发布未落盘"是因为 (a) 消费循环不存在/中断，还是 (b) 走了 `offline` 等不落盘分支。把结论写入本 Task 说明。

- [ ] **Step 2: 写失败测试（终态必落盘）**

```python
def test_process_event_writes_terminal_state_to_store():
    """消费者处理一条候选后，store 必须存在该 idempotency_key 的终态记录（除有意保留的 offline pending 外）。"""
    import tempfile
    from pathlib import Path
    from core.world_image_candidates import JsonWorldImageCandidateStore

    with tempfile.TemporaryDirectory() as d:
        store = JsonWorldImageCandidateStore(Path(d) / "c.json")
        # 构造一条 expired 候选事件, 处理后再查 store
        # (按实际候选事件构造方式填写)
        ...
        assert store.get(candidate_key) is not None
```

- [ ] **Step 3: 跑测试确认失败**

Run: `pytest tests/test_phase10_image_workflow.py -v`
Expected: FAIL（当前 `expired` 分支已落盘，但 `suppressed`/`disabled` 等分支未落盘或行为未钉住）。

- [ ] **Step 4: 实现兜底落盘 + INFO 日志**

在 `process_event` 各终态分支（`suppressed`/`expired`/`duplicate` 等）统一确保调用 `self.store.put(record)` 后再 ACK；`offline` 分支**保持不落盘**（有意设计：不 ACK、不丢 pending 数据，等待交付通道恢复），但补一条 `logger.info("[ImageConsumer] offline pending key=%s", key)` 便于观察。对 `disabled` 分支补落盘 `record("disabled", ...)` 与日志。

> 说明：Task 5 的精确代码依赖 Step 1 审计结论与候选事件结构，需在实际文件上按真实字段补齐，禁止照抄占位。

- [ ] **Step 5: 跑测试确认通过 + 无回归**

Run: `pytest tests/test_phase10_image_workflow.py -v`
Expected: 新用例 PASS，其余无回归。

- [ ] **Step 6: 提交**

```bash
git add core/world_image_candidates.py core/companion.py tests/test_phase10_image_workflow.py
git commit -m "fix(image): 生图候选终态兜底落盘并补充消费驱动日志"
```

---

## Task D:（决策项）主动发图额度并入 max_per_day

**前提**：需用户确认产品预期——用户设 `max_per_day=10` 是否希望**同时**限制主动发图数量？

- 选项 1（推荐，最简单）：把主动发图计入全局主动次数。在 `_run_proactive_photo_loop` 发布前，用 `PushPolicy.can_send()`/`max_per_day` 与文字推送**共用同一额度**，发图成功后也扣减该额度（`image_max_per_day` 改为沿用 `max_per_day` 或设更高值）。
- 选项 2：保持两套独立（当前行为），仅把 `image_max_per_day` 从 `0` 改为用户期望的具体数字。
- **本任务暂不写代码**，等用户选定后再展开为独立子计划。

---

## Task E:（可选/低危）陈旧情绪加固 + 时钟源统一

- **E-1 陈旧情绪**：在 `_run_proactive_photo_loop` 决策前，读取情绪时校验 `CompanionState.load()._emotion_change` 的时间戳新鲜度（如超过 N 分钟视为陈旧，决策时降权或忽略）。**仅在有实际误判证据后再实施**（P1-1 未证实）。
- **E-2 时钟源统一**：情绪/欲望/推送统一改为使用与世界一致的时钟入口（`solar_time.py` 或 `LOCAL_TZ` aware 时间），消除 naive 差异。**低危，可在后续批次处理。**

---

## 三、验证方式（整体回归）

1. 单元回归：
```bash
.venv\Scripts\python.exe -m pytest tests/test_p1_c1_world_simulation.py tests/test_phase11_world_port.py tests/test_phase10_image_workflow.py -v
```
2. 日志观察（重启后端后）：
   - 时段应随时间推进：日志出现 `[WorldLoop] phase=afternoon/evening/...` 交替，而非长期停在 `morning`。
   - 主动发图：`skip duplicate` 不再是"唯一话题空转"，话题能在不同 phase 间轮换；发布候选后有 `[ImageConsumer]` 落盘/生成日志。
   - 生图：`world_image_candidates.json` 每条发布候选都有终态落盘记录。
3. 端到端：任意时刻主动发图能基于"当前时段"产出新话题并发图。

---

## 四、自审

- **Spec 覆盖**：P0-1/2/3 → Task 1-4；P0-4 → Task D（待决策）；P1-1/2 → Task E。无遗漏。
- **占位符检查**：Task 5 明确标注"需按真实字段补齐、禁止照抄占位"，属审计驱动而非占位。
- **类型一致性**：`get_snapshot(max_age_sec=...)` 在 Task 3/4 签名一致；`_world_snapshot_for_context(max_age_sec=...)` 调用点与定义一致。
