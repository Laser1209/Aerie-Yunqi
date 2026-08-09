---
title: 修复 LLM 时间感知偏差（“下午却喊快睡觉”）
date: 2026-08-09
tags:
  - plan
  - bugfix
  - llm-context
status: in-progress
---

# 修复 LLM 时间感知偏差

## 背景

用户下午 16:48 发消息，AI 回复「这么晚了还想这些，赶紧睡你的觉去，明天再说」。经排查，**不是多 AI 混淆**，而是**同一个 LLM 在同一个请求内，因时间信息不对称被历史消息误导**。

### 已确认的 3 个结构性根因

| # | 根因 | 证据 |
|---|------|------|
| 1 | **【时间快照】只有日期没有时分** | `get_agent_snapshot` 返回 `date`（YYYY-MM-DD）无时分；`ContextBuilder` 只渲染 `日期：` |
| 2 | **world phase 粗粒度** | `DEFAULT_WORLD_PHASES` 仅 5 段，16:48 与 18:59 都落在 `afternoon`，无法区分“下午”与“傍晚将睡” |
| 3 | **对话历史不带时间戳** | `recent_turn_history` SELECT 无 `created_at`；`ContextAssembler` 组装时丢弃 `ts`；legacy `_load_history` 仅 `role, content` → **凌晨 4 点的“晚安/这么晚了”被当成当下语境** |

### 用户已确认的技术方案

- **问题 3**：绝对时间戳前缀（每条历史消息前缀 `[MM-DD HH:MM]`）
- **问题 1+2**：时间快照加“日期 + 当前时分 + 中文时段”，并把 world phase 映射为中文

---

## 现网关键代码位置（Phase 1 探索结论）

| 文件 | 行 | 现状 |
|------|----|------|
| `core/calendar_manager.py` | L376-384 | `get_agent_snapshot` 返回 `{"date", "today_events", "today_todos", "upcoming_anniversaries"}`，无时分 |
| `core/context_builder.py` | L84 | 「时间快照」只渲染 `日期：<date>` |
| `core/context_builder.py` | L92 | 「世界状态」渲染 `时段：<phase>`（英文 afternoon） |
| `core/context_builder.py` | L230-236 | history 组装只取 `role` + `content`，丢时间 |
| `core/conversation_continuity.py` | L356-366 | `ContextAssembler` 组装 history 只取 `role` + `content`，丢 `ts` |
| `core/conversation_repository.py` | L651 | `recent_turn_history` SELECT 无 `created_at` |
| `core/conversation_repository.py` | L817 | `history_page` 已带 `ts`（可复用） |
| `core/pipeline.py` | L1787-1798 | legacy `_load_history` SELECT 仅 `role, content` |
| `core/world_simulation.py` | L24-60 | `DEFAULT_WORLD_PHASES` 5 段定义 |

---

## 变更方案

### 变更 1：为时间快照补充时分 + 中文时段

**文件**：`core/calendar_manager.py` `get_agent_snapshot`（L376-384）

**改什么**：返回值新增 `datetime`（`YYYY-MM-DD HH:MM`）和 `time_period_cn`（中文时段）。

**为什么**：给 LLM 明确的“当前具体时间 + 中文时段”强信号，替代它依赖粗粒度英文 phase 猜时间。

**怎么做**：
```python
def get_agent_snapshot(self, user_id: int, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    date = now.strftime("%Y-%m-%d")
    # ... 原有逻辑保留 ...
    return {
        "date": date,
        "datetime": now.strftime("%Y-%m-%d %H:%M"),
        "time_period_cn": _time_period_cn(now),   # 新增辅助函数
        "today_events": [...],
        "today_todos": [...],
        "upcoming_anniversaries": [...],
    }
```

**新增模块级辅助函数 `_time_period_cn`**（放在 `calendar_manager.py` 顶部）：
```python
def _time_period_cn(now: datetime) -> str:
    h = now.hour
    if 5 <= h < 8:
        return "清晨"
    if 8 <= h < 12:
        return "上午"
    if 12 <= h < 14:
        return "中午"
    if 14 <= h < 18:
        return "下午"
    if 18 <= h < 22:
        return "晚上"
    return "深夜"
```
> 说明：此映射与 world phase 的 5 段（night/morning/noon/afternoon/evening）边界对齐，但更细，能区分 16:48（下午）与 19:30（晚上）。

### 变更 2：world phase 映射中文

**文件**：`core/context_builder.py` L89-98

**改什么**：渲染「世界状态时段」时，把英文 phase 映射为中文。

**为什么**：`afternoon` 是英文弱信号，映射为「下午」后 LLM 中文语境理解更直接。

**怎么做**：新增模块级映射字典，并在渲染处使用：
```python
_WORLD_PHASE_CN = {
    "night": "深夜",
    "morning": "上午",
    "noon": "中午",
    "afternoon": "下午",
    "evening": "晚上",
    "unknown": "未知",
}

# 渲染处：
phase_cn = _WORLD_PHASE_CN.get(world_snapshot.get("phase", "unknown"), "未知")
f"时段：{phase_cn}\n"
```

### 变更 3：时间快照渲染输出时分 + 中文时段

**文件**：`core/context_builder.py` L84-87

**改什么**：「时间快照」区块增加当前时分与中文时段。

**为什么**：LLM 直接看到「16:48 / 下午」，比从 world 侧间接拼更可靠。

**怎么做**：
```python
system += "\n\n【时间快照】"
system += "\n当前时间：" + str(time_context.get("datetime", ""))          # YYYY-MM-DD HH:MM
system += "\n当前时段：" + str(time_context.get("time_period_cn", ""))     # 下午
system += "\n日期：" + str(time_context.get("date", ""))
system += "\n今日事件：\n" + (...)
system += "\n今日未完成任务：\n" + (...)
system += "\n未来 7 天纪念日：\n" + (...)
```

### 变更 4：对话历史带绝对时间戳前缀

**4a. `recent_turn_history` SELECT 补 created_at**

**文件**：`core/conversation_repository.py` L651

**改什么**：SELECT 增加来自 turns 的时间字段。
```python
SELECT m.role, m.content, m.sequence, m.channel, rt.created_at
FROM recent_turns rt
JOIN messages m ON m.turn_id = rt.turn_id
ORDER BY rt.created_at ASC, rt.turn_order ASC, m.sequence ASC
```

**4b. legacy `_load_history` 补 created_at**

**文件**：`core/pipeline.py` L1787-1798

**改什么**：SELECT 增加 `created_at`（两条分支都改）：
```python
"SELECT role, content, created_at FROM chat_log "
"WHERE user_id = ? ORDER BY id DESC LIMIT ?"
```

**4c. `ContextBuilder` history 组装带时间前缀**

**文件**：`core/context_builder.py` L230-236

**改什么**：组装每条历史时，若消息带 `created_at`/`ts`，前缀 `[MM-DD HH:MM]`。
```python
def _hist_label(row: dict) -> str:
    ts = row.get("created_at") or row.get("ts")
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(str(ts))
    except (ValueError, TypeError):
        return ""
    return f"[{dt.strftime('%m-%d %H:%M')}] "

for h in history_for_context[-limit:]:
    label = _hist_label(h)
    messages.append({
        "role": h.get("role", "user"),
        "content": label + str(h.get("content", "")),
    })
```

**4d. `ContextAssembler` history 组装带时间前缀**

**文件**：`core/conversation_continuity.py` L356-366

**改什么**：`history_page` 的 items 已带 `ts`，组装时复用同样的前缀逻辑。
```python
for item in reversed(page["items"]):
    role = item.get("role")
    if role not in {"user", "assistant"}:
        continue
    content = str(item.get("content") or "")
    if not content:
        continue
    if used + len(content) > budget:
        continue
    label = _hist_label(item)   # 复用同一套前缀逻辑
    content = label + content
    history.append({"role": role, "content": content})
    used += len(content)
```

> **注意 token 预算**：`ContextAssembler` 按字符预算 `budget` 截断历史（L352/L363）。加时间前缀会增加每条消息字符数，需在 `used + len(content)` 判断前把 `len(label)` 计入，否则可能超预算。建议：
> ```python
> entry_len = len(label) + len(content)
> if used + entry_len > budget:
>     continue
> ```

**4e. 公共辅助函数 `_hist_label` 复用**

为避免 `context_builder.py` 与 `conversation_continuity.py` 重复实现，建议：
- 在 `core/context_builder.py` 定义一个模块级 `_hist_label(row)`，`ContextBuilder` 使用；
- `conversation_continuity.py` 内部定义同名私有函数（或从共享 util 导入）。
  因两文件无强依赖，**优先各自实现同一个小函数**（逻辑仅 6 行，避免引入新模块耦合），符合“最小必要变更”。

---

## 假设与决策

1. **时间来源**：`get_agent_snapshot` 用 `datetime.now()`（本地时间，服务器为 UTC+08），与聊天 `created_at` 一致，无需额外时区处理。
2. **时间前缀格式**：`[MM-DD HH:MM]`（不包含秒，节省 token 且足够区分跨天）。
3. **phase 中文映射**：仅映射 `ContextBuilder` 渲染处，不改 `world_simulation.py` 的 phase 计算逻辑（避免影响 world tick 等其它消费方）。
4. **中文时段 `_time_period_cn`**：新增在 `calendar_manager.py`，与 world phase 边界尽量对齐但更细。
5. **不引入新模块/依赖**：时间前缀函数在消费方各自实现，保持低耦合。
6. **token 开销**：每条历史 +~10 字符，24 条历史约 +240 字符，在 `max_total_chars=24000` 预算内可接受；`ContextAssembler` 需把前缀长度计入预算。

---

## 验证步骤

1. **单元测试（新增/更新）**：
   - `tests/test_calendar_manager.py`：断言 `get_agent_snapshot` 返回含 `datetime` 与 `time_period_cn`，且 `_time_period_cn` 对 16:48 返回「下午」、对 19:30 返回「晚上」。
   - `tests/test_context_builder.py`：断言「时间快照」含 `当前时间`、`当前时段`；「世界状态时段」为中文；history 消息前缀 `[MM-DD HH:MM]`。
   - `tests/test_conversation_continuity.py`：断言 `ContextAssembler` 组装历史带时间前缀，且加前缀后不超字符预算、不丢消息（预算边界测试）。

2. **数据源回归**：
   - `recent_turn_history` 返回 dict 含 `created_at` 字段。
   - legacy `_load_history` 返回 dict 含 `created_at` 字段。

3. **全量回归**：
   ```powershell
   python -m pytest tests -q
   ```
   预期 1000+ 条全绿，无新增失败。

4. **人工复现验证**（可选）：
   用 `cognition_log id=352` 的场景（16:48 + 凌晨历史）重新组装 system prompt，确认：
   - 时间快照出现「当前时间：2026-08-09 16:48」「当前时段：下午」；
   - 历史中凌晨 4 点消息显示 `[08-09 04:07] 讨厌你！…`，LLM 能区分时间跨度。

---

## 涉及文件清单

| 文件 | 变更 |
|------|------|
| `core/calendar_manager.py` | `get_agent_snapshot` 加 `datetime`/`time_period_cn`；新增 `_time_period_cn` |
| `core/context_builder.py` | 渲染时间快照（时分+中文时段）；world phase 中文映射；history 加时间前缀 |
| `core/conversation_continuity.py` | `ContextAssembler` history 加时间前缀并计入预算 |
| `core/conversation_repository.py` | `recent_turn_history` SELECT 补 `created_at` |
| `core/pipeline.py` | legacy `_load_history` SELECT 补 `created_at` |
| `tests/test_calendar_manager.py` | 新增时间快照断言 |
| `tests/test_context_builder.py` | 新增时间渲染 + history 前缀断言 |
| `tests/test_conversation_continuity.py` | 新增前缀 + 预算边界断言 |