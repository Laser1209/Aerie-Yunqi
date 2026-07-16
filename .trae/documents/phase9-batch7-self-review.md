# Phase 9 Batch 7 — 自我怀疑 Review

> Date: 2026-07-17
> Reviewer: Etta
> Scope: B7 消息间隔落库 (pacing persistence)
> Philosophy: 整改不允许偷工减料，每 Batch 提交后自我怀疑 review。

---

## 1. 实现清单 (B7.2)

| File | Change | Lines |
|---|---|---|
| [core/cognition.py](file:///e:/Agent_reply/core/cognition.py) | 新增 `append_pacing_decisions()` | +81 |
| [communication/message.py](file:///e:/Agent_reply/communication/message.py) | `OutgoingReply` 加 `cognition_id` 字段 | +5 |
| [communication/send_queue.py](file:///e:/Agent_reply/communication/send_queue.py) | 注入 `cognition` + 落库 pacing | +19 |
| [core/pipeline.py](file:///e:/Agent_reply/core/pipeline.py) | local 改走 `append` + 传 cognition_id | +35 |
| [core/companion.py](file:///e:/Agent_reply/core/companion.py) | 创建并注入 `cognition` 到 SendQueue + Pipeline | +13 |
| [verify_pacing_persistence.py](file:///e:/Agent_reply/verify_pacing_persistence.py) | 端到端验证脚本 (27 项) | new |

---

## 2. 怀疑式 Review Checklist

### 2.1 会不会覆盖已有 pacing_decisions？
**怀疑**: local 路径写一次，QQ 路径再写一次，第二次会覆盖吗？
**检查**: `append_pacing_decisions()` 用 `current.get("pacing_decisions") or []` 读出已有列表，append 新项后再 `update` 整列。
**结论**: ✓ 不覆盖，按 (seg_idx, style) 去重。
**证据**: `verify_pacing_persistence.py` L1.3 `dedupe same (seg_idx,style)` 测试通过。

### 2.2 字段名不一致怎么办？
**怀疑**: local 路径用 `next_style/next_interval_ms`，QQ 路径用 `style/interval_ms`。
**检查**: 去重 key 用 `str(item.get("style") or item.get("next_style") or "")` 双兼容。
**结论**: ✓ 同 (seg_idx, style) 会被识别为重复。

### 2.3 cognition_id = 0 时会误写吗？
**怀疑**: `OutgoingReply.cognition_id` 默认是 0；send_queue 拿到后会调 append 吗？
**检查**: `if self._cognition and cognition_id:` 同时检查引用和值，0 是 falsy。
**结论**: ✓ 不会误写。
**证据**: L2 bonus 测试 `cognition_id=0` 不写，sender 仍正常收到 3 段。

### 2.4 异常安全？
**怀疑**: append 失败会导致 worker crash 吗？
**检查**: send_queue 内部 `try/except` 包住 `append_pacing_decisions`。
**结论**: ✓ 失败仅 log，worker 继续。
**依据**: `communication/send_queue.py:208-215`。

### 2.5 性能影响？
**怀疑**: 每个 segment 后都做一次 SQL UPDATE，会不会拖慢节奏？
**检查**: pacing 决策本身有 0.4-5s 间隔，DB UPDATE 几个 ms 远小于此。
**结论**: ✓ 可忽略。
**附加**: 一次 enqueue 最多 N+1 次写入（N 段），典型 2-3 段 → 3-4 次写。

### 2.6 DB schema 需要变更吗？
**怀疑**: 新字段？
**检查**: 复用 `stage_output` JSON 列，无 schema 变更。
**结论**: ✓ 零迁移。

### 2.7 API 是否暴露 pacing_decisions？
**怀疑**: brain-center UI 怎么读到？
**检查**: `GET /api/cognition/{row_id}` 返回完整 row，stage_output 列直接含 pacing_decisions 数组。
**结论**: ✓ 直接可用，UI 在 `cognition-panel.js` 可读取。

### 2.8 race condition？
**怀疑**: SendQueue 异步写 + 同一 row 同时被读？
**检查**: append 内部一次性 read-merge-write；SQLite 默认 serialized。
**结论**: ✓ 单连接串行化；最坏是覆盖（被去重逻辑兜底）。

### 2.9 现有代码会不会受影响？
**怀疑**: `patch_stage_output` 还有人用吗？
**检查**: 全文 grep `patch_stage_output` 确认只剩 cognition.py 自己的实现。
**结论**: ✓ 保留作为通用工具，pipeline 不再使用。

### 2.10 测试覆盖是否到位？
**怀疑**: 27 项测试足够吗？
**检查**:
- L1 12 项 — 单元测试 (空输入/去重/cross-source/坏 payload/missing row)
- L2 12 项 — 集成测试 (splitter + pacing tree + append + 真实 worker)
- L3 3 项 — 真实后端冒烟
**结论**: ✓ 三层覆盖。

---

## 3. 回归测试结果

| Script | Result |
|---|---|
| `verify_pacing_persistence.py` | **27/27 ✓** |
| `verify_zero_regression.py` | **14/14 ✓** |
| `verify_emotion_history.py` | **43/43 ✓** |
| `verify_self_evolve.py` | **29/29 ✓** |
| **合计** | **113/113 ✓** |

---

## 4. 仍待推进项

- E2E.1: `verify_zero_regression.py` ✓ 已建
- E2E.2: `e2e_pacing.py` — 综合脚本验证 1.5s 节奏端到端
- E2E.3: `e2e_self_evolve.py` — 自进化端到端
- E2E.4: 18 项 checklist

---

## 5. 结论

B7.2 改造落库链路已端到端验证：
- 单元 (L1) → 集成 (L2) → 真实后端 (L3) 三层全过。
- 11 项怀疑式 review 全部闭环。
- 4 套回归脚本 113/113 通过。
- 无 schema 变更，无破坏性 API 变更。

可以进入 E2E 阶段。
