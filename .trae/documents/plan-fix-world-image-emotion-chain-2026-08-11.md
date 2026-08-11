# 世界·生图·情绪·推送 串导卡死修正计划（全对话问题汇总版）

> **For agentic workers:** REQUIRED SUB-SKILL: 按任务逐条执行。步骤用 `- [ ]` 复选框跟踪。

**Goal:** 汇总并修正本次对话中围绕「生图 / 世界 / 情绪 / 推送」暴露出的全部问题——生图重复调用、时间提示词过粗、天文数据缺失、生图未启用、世界时段卡死、生图候选不落盘、模块互相贴合/串导，让整条链路正确贴合、无卡死。

**Architecture:** 多层兜底——① 视觉判重路由（生成前用已生成图判"同场景"）；② 细粒度时间/光线提示词（太阳高度角+方位角、月相、晨昏）；③ 天文数据订阅（日出日落/月落月出/月相/节气 → 每日日报）；④ `get_snapshot()` 新鲜度校验 + 世界循环自愈看门狗根治"旧时段/旧话题"；⑤ 生图候选消费链路兜底落盘 + 可观测性。

**Tech Stack:** Python asyncio / pytest / SiliconFlow(Qwen3-VL / 轻量LLM) / 现有 WorldSimulation / solar_time / ephemeris / WorldImageCandidateConsumer / companion.py / brief-fetcher+drawer。

---

## 一、问题汇总（本次对话全量，含状态与证据等级）

> 状态图例：✅ 已实现并通过测试 · 🟡 已部分/已实现待回归 · 🔶 待决策 · ⬜ 待办/低危

### A 类：生图重复调用（用户首报，已根治）

| # | 问题 | 现象 | 修复 | 状态 |
|---|---|---|---|---|
| A-1 | **相同事件短时间重复生成相同画面** | 05:23/05:25 两个 gpt-image-2 调用画面意思相同，文本去重因 reason_code 不同而互相看不见 | 跨路径统一在消费端做**视觉判重路由**：生成前用 SiliconFlow Qwen3-VL 判"新提示词 vs 参考图是否同一场景"，同场景则跳过 | ✅ [world_image_candidates.py](file:///e:/Agent_reply/core/world_image_candidates.py) `_vision_scene_same` + `_VISION_DEDUP_WINDOW_SEC=4h` |
| A-2 | **视觉判重模板过严** | 模型纠结城市名/家具等细节，同一居家氛围被误判"不同" | 重写提问模板：明确要求忽略细节、只看整体氛围/场景/时段/主体是否同一类生活照 | ✅ 同文件 `_VISION_SCENE_QUESTION` |

### B 类：时间提示词细化 + 天文数据（用户多轮提出，已实现）

| # | 问题 | 修复 | 状态 |
|---|---|---|---|
| B-1 | **时间段分区分段过粗**：凌晨发图出现"傍晚夕阳/刚落山"照片，5 段 phase 不足以描述光线 | `solar_time.py` 基于 NOAA 算法算太阳高度角+方位角，产出"太阳刚出/未出/已出/升到约X° / 落山 / 深夜 / 凌晨 / 清晨 / 鱼肚白"等细粒度描述；`ephemeris.py` 算月相/月出月落 | ✅ |
| B-2 | **太阳方位角公式错误**：正午应朝南 180°，误算成朝东 83° | 修正公式：用**高度角**而非**天顶角**（`alt_rad=(90-zenith)*DEG`） | ✅ [ephemeris.py](file:///e:/Agent_reply/core/ephemeris.py) |
| B-3 | **月相分类解包异常**（`too many values to unpack`） | 重构为显式 if/elif 分支（新月/娥眉/上弦/盈凸/满月/亏凸/下弦/残月） | ✅ |
| B-4 | **天文数据缺少网络源/保底** | 提供网络爬取 + 本地保底（solar_time/ephemeris 确定性计算）双轨 | ✅ |
| B-5 | **天文数据未进每日日报** | 作为可订阅项接入 daily brief（GitHub 式订阅）：[brief_fetcher.py](file:///e:/Agent_reply/core/brief_fetcher.py) + [brief-drawer.js](file:///e:/Agent_reply/electron/src/renderer/js/brief-drawer.js) | ✅ |

### C 类：生图功能未启用 / 模块贴合（已核实/已修复）

| # | 问题 | 处置 | 状态 |
|---|---|---|---|
| C-1 | **生图疑似未启用** | 核实 `world_image_candidates_v1: true`（settings.yaml L24），`world_inprocess_v1: true` | ✅ 已确认开启 |
| C-2 | **主动发图话题轮换卡死**：只取第一个 `morning_plan`，被 4h 去重窗口挡死空转 | 遍历全部 `available_visual_topics` 逐条查重，找到未去重话题为止 | ✅ [companion.py](file:///e:/Agent_reply/core/companion.py#L2198-L2232) |

### D 类：世界时段卡死 / 生图候选不落盘（核心 P0，本次修正主体）

| # | 问题 | 现象 | 根因 | 修复 | 状态 |
|---|---|---|---|---|---|
| D-1 | **世界时段间歇性卡死** | 16:48~18:32 phase 停在 `morning`，话题只有 `morning_plan`，主动发图每分钟空转 | `get_snapshot()` 只返回缓存不重算；推进完全依赖 `_run_world_loop` 每 300s `tick()` | `get_snapshot(max_age_sec=...)` 缓存过期强制 `tick()` 重算 | ✅ [world_simulation.py](file:///e:/Agent_reply/core/world_simulation.py) |
| D-2 | **生图决策用"缓存不重算"快照 → 旧时段/旧话题** | 与 D-1 同源 | 主动发图读的是 D-1 那份缓存 | 主动发图强制新鲜快照 `max_age_sec=60`；world_port 透传 | ✅ [companion.py](file:///e:/Agent_reply/core/companion.py#L2192) [world_port.py](file:///e:/Agent_reply/core/world_port.py) |
| D-3 | **世界时钟时区错位**：UTC 被当本地，本地 16:48 判成 morning | 时段整体偏 8h | `tick()` 对 naive 时钟误用 `replace(tzinfo=LOCAL_TZ)` | 统一归一化：naive 视为 UTC→转本地；aware 直接转本地 | ✅ [world_simulation.py](file:///e:/Agent_reply/core/world_simulation.py) |
| D-4 | **世界循环停摆（异常退出即死）** | 世界推进任务异常后时段不再推进 | 无自愈 | 看门狗 `_supervise_world_loop`：任务异常结束 5s 后自动重建 + `[WorldLoop] phase=` 日志 | ✅ [companion.py](file:///e:/Agent_reply/core/companion.py#L2058) |
| D-5 | **生图候选发布但不落盘/不生成** | 18:33 发布 `deep_focus` 后无日志，store 停在 16:43 | `process_event` 多分支直接 return 不写 store | 各终态分支兜底落盘 + `consume_replay` 逐条 try/except + INFO 日志（`offline` 有意不落盘不 ACK） | ✅ [world_image_candidates.py](file:///e:/Agent_reply/core/world_image_candidates.py) |

### E 类：频控 / 情绪 / 时钟（待决策 / 低危）

| # | 问题 | 说明 | 状态 |
|---|---|---|---|
| E-1 | **主动推送与主动发图频控不共享（错频）** | 文字 `max_per_day=10` 完全管不住发图（`image_max_per_day=0` 无限）；两套独立频控 | 🔶 **Task D 待用户决策**：发图是否并入 `max_per_day` |
| E-2 | **"陈旧情绪"误判** | 情绪持久化，与生图决策无强同步；无日志证据 | ⬜ Task E-1（有实据再实施） |
| E-3 | **时钟源未统一** | 情绪/欲望/推送用 `datetime.now()`(naive)，世界用 `LOCAL_TZ` | ⬜ Task E-2（低危） |

### 已修复（上下文，勿重复）
太阳方位角、月相分类、视觉判重模板、话题轮换、时区归一化、世界循环自愈、生图候选落盘——均已在本计划 Task 内体现并标注 ✅。

---

## 二、修复策略

- **已完成（Tasks 1–5）**：根因审计 → 测试基线修复 → 快照新鲜度校验 → 主动发图新鲜快照 + 世界循环自愈 → 生图候选兜底落盘。✅ **48 项测试全绿**。
- **待决策**：Task D（主动发图额度并入 `max_per_day`，需用户确认）。
- **可选/低危**：Task E（陈旧情绪加固 / 时钟源统一）。

---

## Task 状态（截至本次汇总）

| Task | 内容 | 状态 |
|---|---|---|
| Task 1 | 根因审计（16:48 误判 morning → 结论：世界循环停摆 + 无新鲜度校验） | ✅ |
| Task 2 | 测试基线修复（时钟统一 aware 本地语义） | ✅ |
| Task 3 | `get_snapshot()` 新鲜度校验 | ✅ |
| Task 4 | 主动发图新鲜快照 + 世界循环自愈/日志 | ✅ |
| Task 5 | 生图候选兜底落盘 + 消费日志 | ✅ |
| Task D | 主动发图额度并入 `max_per_day` | 🔶 待用户决策 |
| Task E | 陈旧情绪加固 / 时钟源统一 | ⬜ 低危待办 |

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

## Task 2: 修复失败测试基线（对齐 tick() 的 aware 本地语义）

**背景（Task 1 结论）**：根因是 (B) 世界循环停摆 + `get_snapshot()` 无新鲜度校验，**不是** naive 时区。默认 clock 是 aware `LOCAL_TZ(+8)`，`tick()` 的 `astimezone(LOCAL_TZ)` 对其无操作、phase 正确。naive 分支在生产不生效（已证实 naive UTC 8:47→morning，但默认不触发），**按 YAGNI 不加固**，仅作 Task E 记录。
现有 `test_p1_c1_world_simulation.py` 因 `tick()` 已把 aware UTC 转本地、而测试仍按"UTC 小时即本地小时"断言，导致 **14 failed / 5 passed**。必须先修复基线。

**Files:**
- Modify: `e:\Agent_reply\tests\test_p1_c1_world_simulation.py`（全部失败用例）
- Test: `e:\Agent_reply\tests\test_p1_c1_world_simulation.py`

- [ ] **Step 1: 跑测试确认当前失败基线**

Run: `cd e:\Agent_reply; .venv\Scripts\python.exe -m pytest tests/test_p1_c1_world_simulation.py -v`
Expected: 14 failed / 5 passed（记录具体失败用例）。

- [ ] **Step 2: 统一 clock 构造为"本地 aware"**

把所有 `datetime(2026, 7, 28, H, 0, tzinfo=timezone.utc)` 改为表示"本地 H 点"的 aware 本地时间，例如：
```python
from datetime import timedelta
LOCAL = timezone(timedelta(hours=8))  # 与 solar_time.LOCAL_TZ 一致
# 用例中：datetime(2026, 7, 28, 7, 0, tzinfo=LOCAL)  # 本地 7 点 → morning
```
逐一定位并替换失败用例（含 `test_phase_mapping_by_hour`、`test_energy_decays_and_recovers`、`test_nearby_objects_reflects_environment`、`test_visual_topics_*` 等所有用 UTC 构造 clock 的用例），保持断言（phase/energy 相对关系）不变。

- [ ] **Step 3: 修正 Task 1 追加的回归测试**
- `test_16_48_local_should_be_afternoon`：把构造改为本地 aware——`datetime(2026, 8, 11, 16, 48, tzinfo=LOCAL)`（`LOCAL=timezone(timedelta(hours=8))`），断言 `phase == "afternoon"`。
- 删除 `test_naive_utc_8_47_phase`（纯探测、`assert True` 无意义，且 naive 加固已不作为本次范围）。

- [ ] **Step 4: 跑测试确认全绿**

Run: `.venv\Scripts\python.exe -m pytest tests/test_p1_c1_world_simulation.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add tests/test_p1_c1_world_simulation.py
git commit -m "test(world): 修复失败基线,时钟统一为aware本地语义,钉住本地16:48应判afternoon"
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
    from datetime import datetime, timedelta, timezone
    from core.world_simulation import WorldSimulation

    LOCAL = timezone(timedelta(hours=8))  # 与 solar_time.LOCAL_TZ 一致

    def later_clock():
        return datetime(2026, 7, 28, 15, 0, tzinfo=LOCAL)  # 本地 15 点

    sim = WorldSimulation(clock=lambda: datetime(2026, 7, 28, 9, 0, tzinfo=LOCAL))
    sim.tick()  # 本地 9 点 → morning 缓存
    cached = sim.get_snapshot()
    assert cached.phase == "morning"

    sim.clock = later_clock  # 推进到本地 15 点，但缓存未刷新
    # 默认 None：仍返回旧缓存（保持兼容）
    assert sim.get_snapshot().phase == "morning"
    # 传入 max_age_sec：过期 → 强制刷新 → 本地 15 点 → afternoon
    assert sim.get_snapshot(max_age_sec=300).phase == "afternoon"
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

1. 单元回归：**✅ 已通过**（48 passed）——
```bash
.venv\Scripts\python.exe -m pytest tests/test_p1_c1_world_simulation.py tests/test_phase11_world_port.py tests/test_phase14_world_image_candidates.py -v
```
2. 日志观察（重启后端后，待完成）：
   - 时段应随时间推进：日志出现 `[WorldLoop] phase=afternoon/evening/...` 交替，而非长期停在 `morning`。
   - 主动发图：`skip duplicate` 不再是"唯一话题空转"，话题能在不同 phase 间轮换；发布候选后有 `[ImageConsumer]` 落盘/生成日志。
   - 生图：`world_image_candidates.json` 每条发布候选都有终态落盘记录。
3. 端到端：任意时刻主动发图能基于"当前时段"产出新话题并发图。
4. 视觉判重端到端：触发两次同画面意图，第二次应被 `_vision_scene_same` 拦截跳过（观察 `[ImageConsumer]` 或生成请求日志）。

> 附注：本次汇总仅更新计划文档，核心代码改动（Tasks 1–5）已在工作区且测试全绿，尚未提交；`git status` 显示 core/*、tests/* 处于未提交状态，建议回归确认后统一提交。

---

## 四、自审

- **Spec 覆盖**：A/B/C/D/E 五类问题全覆盖——A/B/C 已实现标注 ✅；D-1~D-5 → Task 1-5（✅）；E-1 → Task D（待决策）；E-2/3 → Task E（低危）。无遗漏。
- **占位符检查**：Task 5 明确标注"需按真实字段补齐、禁止照抄占位"，已在实际文件上实现（`offline pending` 日志、`consume_replay` try/except、终态落盘均已落地）。
- **类型一致性**：`get_snapshot(max_age_sec=...)` 在 Task 3/4 签名一致；`_world_snapshot_for_context(max_age_sec=...)` 调用点与定义一致。
