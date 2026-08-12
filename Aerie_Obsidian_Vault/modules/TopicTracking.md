---
title: TopicTracking
kind: module_note
status: Implemented
updated_at: 2026-08-13
owners:
  - CORE
related_modules:
  - ContextBuilder
  - Companion
  - LayeredMemory
tags:
  - module
  - context/topic
---

# TopicTracking — 对话话题生命周期追踪

> [!info] 定位
> 消除"主动消息与上文对话割裂"：话题 = 围绕主体（核心主旨）的语义单元。系统追踪话题 active/closed 生命周期，主动消息触发前判定"续接 / 再造 / 新话题"。

## 核心机制

### 话题模型
```python
Topic { id, subject(围绕主体), state(active|closed),
        started_at, last_active_at, turn_count, summary, stub }
```
- **paused 为派生状态**：`last_active_at` 距今 ≥ 4h 即视为暂停（续接判定用），无显式转移路径。
- **closed 保留存根**（stub），可被"话题再造"唤醒。

### 生命周期状态机
```
active ──收尾词命中 / 沉默 ≥24h──▶ closed ──(再造窗口 72h 内)──▶ 续接/再造
```
- 状态只单向流转，错判可自愈（重启时按当前 idle 重新评估，久未登录的 active 直接 closed）。

### 判定策略（触发式，确定性为主）
- **收尾信号**：确定性收尾词表（"好了/那先这样/明天再说/不聊了"等）。
- **沉默超时**：active 沉默 ≥ 24h 自动 closed。
- **subject 命名**：默认回退 `detect_topics` 类目名（工作/学习/娱乐…）；LLM 命名可注入 override，失败兜底类目名。

### 存根入记忆库
`persist_stub`：显式 `LONG_TERM` + `EXPERIENCE` + `metadata{kind:"topic_stub"}`，**不伪造 importance=7.0**；检索端按 `kind` 过滤，数量上限 50 条。

## 主动消息动机重定义

[companion.py `_dispatch_push`](file:///e:/Agent_reply/core/companion.py) 触发顺序：

1. `PushPolicy` 放行 → `TopicTracker.continuation_plan()`
2. 有 `active/paused` 话题 → **continue**（续接）
3. 无但有 `closed` 存根（72h 内）→ **revive**（再造）
4. 再无 → **new**（新话题）

`generate_push` 新增 `topic_mode` / `dialogue_context` 参数（[llm_caller.py](file:///e:/Agent_reply/core/llm_caller.py)）：continue/revive 时注入最近对话（≤600 字），指令为"延续/重新提起话题"而非硬编码"开新话题"。**决策日志埋点 1** 选择后单点写 `decision_log`（kind=topic_motive）。

## 沉寂检测统一

[companion_state.py](file:///e:/Agent_reply/core/companion_state.py) 增加 `last_user_active_at` + `mark_user_active()` + `idle_hours()`（统一 `time.time()`）。mark 点 4 处：companion 消息入口 ×3（经 `push_event_engine.record_user_activity`）+ `push_event_engine._on_user_message`（`on_user_active` hook）。

## L0.5 话题认知层

[context_builder.py](file:///e:/Agent_reply/core/context_builder.py) `_build_topic_cognition`：FULL/AUTO + provider 有活跃话题时注入"【当前话题】围绕「subject」（已聊 N 轮）"，**只注入事实不注入指令**；`set_topic_provider` 由 companion 注入（`_topic_for_context`）。**发布闸门 flag `topic_tracking_v1` 已于 P0 验收后删除（2026-08-13）**，不再受开关门控。

## 文件

- `core/topic_tracker.py` — 话题追踪引擎
- `core/decision_log.py` — 候选决策证据日志（append-only，按日切片）
- `core/companion_state.py` — 统一沉寂时钟字段
- `tests/test_topic_system.py` — 31 例

## 互链

- 模块入口：[[01_模块总览]]
- 行为调度：[[DailyBehaviorScheduler]]
- 寻路感知：[[IndoorNavigation]]
- 计划：[[对话话题·行为调度·寻路感知系统修缮计划]]
