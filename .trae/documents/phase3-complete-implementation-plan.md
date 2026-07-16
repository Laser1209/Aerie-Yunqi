# Aerie · 云栖 v9.0 — 第三阶段完整实现计划

> **制定日期**：2026-07-16
> **前置状态**：Batch 1（Ita 灵魂注入）5 个文件已写入但未验证，现有测试文件与重构后的 API 不兼容。

---

## 一、当前状态诊断

### 1.1 已完成但未验证（Batch 1）

| 文件 | 状态 | 说明 |
|------|------|------|
| `core/context_builder.py` | 已写入 | 四层分层 system prompt（L1 核心身份 / L2 关系深度 / L4 语言铁律），`build()` 支持 `emotion_info` + `eruption_info` |
| `core/emotion_threshold.py` | 已写入 | 累积阈值引擎，全局单例，4 槽位 + 爆发 + 角色磨损 |
| `core/emotion_engine.py` | 已写入 | PAD + 五类情绪 + 阈值集成，API：`analyze()`/`update_trajectory()`/`get_label()`/`get_state()`/`tune()` |
| `core/pipeline.py` | 已写入 | 升级为 10 阶段管线，注入情绪上下文 + 爆发模式 |
| `core/companion.py` | 已写入 | 每日衰减调度，阈值引擎单例接入 |

### 1.2 测试文件全部失效

| 测试文件 | 问题 |
|----------|------|
| `tests/test_emotion.py` | 引用旧 API：`PADState`、`trigger()`、`get_all_slots()`、`get_slot()` — 新代码中均不存在 |
| `tests/test_pipeline.py` | 引用旧 API：`_color_reply()`、`recall_manager` — 新 pipeline 无此依赖 |
| `tests/test_communication.py` | 引用 `RouteMode` 枚举（路由返回字符串 `'FULL'`）— 需确认兼容性 |
| `tests/test_tools.py` | 基本兼容，需验证 |

### 1.3 缺失模块

| 模块 | 批次 | 说明 |
|------|------|------|
| `core/token_tracker.py` | Batch 3 | Token 消耗追踪 |
| emotion-dashboard.js | Batch 2 | 情绪仪表盘前端逻辑 |
| `GET /api/emotion/thresholds` | Batch 2 | 独立的阈值查询端点 |
| Brain 多 provider 容灾 | Batch 3 | SiliconFlow → DeepSeek fallback |
| `index.html` emotion + memorial Tab | Batch 2 | UI 新增 Tab |

---

## 二、总体目标

1. **验证 Batch 1 代码无导入/运行时错误**
2. **重写全部测试文件**，覆盖新 API，覆盖率 ≥80%
3. **补全缺失模块**：Token 追踪器、多 Provider 容灾、情绪仪表盘 UI
4. **API 补全**：新增 `/api/emotion/thresholds`、增强 `/api/stats/tokens`
5. **系统整合验证**：端到端测试确保消息流、情绪累积、爆发模式全部连通

---

## 三、实施步骤（按依赖顺序）

### 步骤 1：验证 Batch 1 代码（P0 — 前置条件）

**目标**：确保 5 个改写的核心文件无导入错误，后端能正常启动。

**操作**：
- 启动 Python 后端 `python main.py`，检查 stderr 输出无 ImportError
- 用 curl 调用 `GET /api/health` 确认 200
- 用 curl 调用 `GET /api/emotion/state` 确认返回新格式（含 `thresholds`、`eruption` 字段）
- 用 curl 调用 `POST /api/chat/send` 发送测试消息，确认 LLM 回复人设一致

**涉及文件**：无需修改，仅验证

---

### 步骤 2：重写测试文件（P1 — 阻塞 CI）

**目标**：所有测试文件匹配新 API，覆盖率 ≥80%。

#### 2.1 新建 `tests/test_emotion_engine.py` — 覆盖新 EmotionEngine API

```python
# 测试用例覆盖：

# === EmotionEngine ===
# test_initial_state() — P/A/D 均为 0.0，label 为 neutral
# test_analyze_love_joy() — "我爱你" → P↑
# test_analyze_anger() — "滚蛋" → P↓ A↑
# test_analyze_breakup_fear() — "分手" → P↓ A↑
# test_analyze_empty_string() — "" → P=0 A=0 D=0
# test_analyze_pad_bounds() — 多次调用后 P/A/D 不超出 [-0.95, 0.95]
# test_update_trajectory_ema() — EMA 平滑 alpha=0.3
# test_get_label_joy() — P>0.2 A>0.1 → "joy"
# test_get_label_anger() — P<-0.2 A>0.2 → "anger"
# test_get_label_sad() — P<-0.2 A<0.0 → "sad"
# test_get_label_fear() — P<-0.3 A>0.3 → "fear"
# test_get_label_neutral() — 默认 "neutral"
# test_get_state_returns_full_dict() — 含 label/pad/thresholds/eruption/panel
# test_tune_cold_violence_short() — 冷暴模式：长回复截断至≤4字
```

#### 2.2 新建 `tests/test_emotion_threshold.py` — 覆盖累积阈值引擎

```python
# === CumulativeEmotionEngine ===
# test_slots_initialized() — 4 槽位名称正确
# test_add_increases_value() — add('patience', 30) → value=30
# test_add_below_threshold_no_eruption() — 未达阈值不触发
# test_scan_text_patience_trigger() — "不用你管" → patience +25
# test_scan_text_anxiety_trigger() — "分手" → anxiety +60
# test_scan_text_desire_trigger() — "想你" → desire +15
# test_scan_text_tenderness_trigger() — "辛苦了" → tenderness +18
# test_scan_text_multiple_triggers() — 同一消息匹配多个关键词组
# test_daily_decay_reduces_values() — 每日衰减减少值
# test_daily_decay_skips_same_date() — 同一天不重复衰减
# test_threshold_eruption_occurs() — 超过阈值触发爆发
# test_eruption_resets_value() — 爆发后 value 归零
# test_eruption_changes_threshold() — patience 爆发后阈值 -15
# test_threshold_floor_20() — 阈值不低于 20
# test_get_active_eruption_within_30min() — 30分钟内返回爆发事件
# test_get_active_eruption_after_30min() — 超过30分钟返回 None
# test_get_slots_summary_format() — 返回 dict 含 value/threshold/label/pct
# test_get_panel_text_format() — 返回带进度条的字符串
# test_singleton_consistency() — 两次 get_threshold_engine() 返回同一实例
```

#### 2.3 重写 `tests/test_pipeline.py` — 匹配新 Pipeline

```python
# 使用 mock 依赖，mock 所有注入对象
# test_handle_local_message_returns_reply()
# test_handle_qq_message_enqueues()
# test_handle_basic_skip_stranger()
# test_handle_saves_to_db()
# test_handle_emits_chat_events()
# test_handle_includes_emotion_in_result()
```

#### 2.4 新建 `tests/test_context_builder.py`

```python
# test_build_full_mode_includes_all_layers()
# test_build_auto_mode_excludes_l2()
# test_build_basic_mode_l1_only()
# test_build_injects_emotion_info()
# test_build_injects_eruption_info()
# test_build_patience_eruption_prompt()
# test_build_anxiety_eruption_prompt()
# test_build_history_limit_per_mode()
```

#### 2.5 保留 `tests/test_communication.py` — 确认兼容

```python
# RouteMode 枚举值为 'FULL'/'AUTO'/'BASIC' — 与 router.route() 返回值匹配
# 确认所有现有测试通过
```

#### 2.6 新建 `tests/test_api.py` — HTTP 端点测试

```python
# 使用 httpx.AsyncClient + FastAPI TestClient
# test_health_returns_200()
# test_chat_send_empty_returns_400()
# test_emotion_state_returns_valid_format()
# test_tools_list_returns_array()
```

---

### 步骤 3：补全缺失模块（P1）

#### 3.1 新建 `core/token_tracker.py`

**功能**：记录每次 LLM 调用的 token 消耗，提供按日/周/月聚合查询。

```python
# 核心类：TokenTracker
# 方法：
#   record(provider, model, prompt_tokens, completion_tokens, user_id)
#   get_today(user_id) → {"prompt": N, "completion": N, "total": N, "calls": N}
#   get_week(user_id) → 同上
#   get_month(user_id) → 同上
#   get_by_provider(user_id) → {"siliconflow": {...}, "deepseek": {...}}
```

**表结构**：
```sql
CREATE TABLE IF NOT EXISTS token_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 0,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_token_usage_user ON token_usage(user_id, created_at);
```

**集成点**：
- `core/brain.py` 的 `chat()` 方法每次调用后调用 `token_tracker.record()`
- `core/pipeline.py` 的 `handle()` 方法在 LLM 调用返回后记录

#### 3.2 升级 `core/brain.py` — 多 Provider 容灾

**当前**：仅有 SiliconFlow 单一 provider，无 fallback。

**目标**：支持 provider 列表，顺序尝试，前一个失败自动切换。

```python
PROVIDERS = [
    {"name": "siliconflow", "url": env("SILICONFLOW_URL"), "key": env("SILICONFLOW_KEY"), "model": "Qwen/Qwen2.5-7B-Instruct"},
    {"name": "deepseek", "url": env("DEEPSEEK_URL"), "key": env("DEEPSEEK_KEY"), "model": "deepseek-chat"},
]
# chat() 方法遍历 providers，成功即返回
# 最后一个 provider 失败时返回降级消息
```

#### 3.3 `api_server.py` — 新增 endpoints

- `GET /api/emotion/thresholds` — 返回 4 槽位当前值 + 百分比
- 增强 `GET /api/stats/tokens` — 接入 TokenTracker 的真实数据

---

### 步骤 4：UI 前端升级（P1）

#### 4.1 `index.html` — 新增 Emotion Tab

在 sidebar 新增第 5 个 Tab（聊天 / QQ / 情绪 / 状态 / 关于），panel-emotion 区域包含：
- PAD 三维度实时卡片（数值 + 环形条）
- 四大隐藏槽位进度条（忍耐/不安/渴望/温柔透支）
- 当前情绪标签 + 爆发模式警告横幅
- 最近情绪事件日志（最后 5 条）

#### 4.2 新建 `electron/src/renderer/js/emotion-dashboard.js`

- 每 3 秒轮询 `GET /api/emotion/state`
- 更新 PAD 卡片数值
- 更新进度条（CSS custom properties 驱动宽度）
- 检测爆发模式：显示红色警告横幅
- 渲染情绪事件日志列表

#### 4.3 `main.css` — 新增情绪仪表盘样式

新样式块包括：
- `.emotion-dashboard` 容器
- `.emotion-pad-cards` 三列卡片布局
- `.emotion-threshold-bar` 渐变进度条（冷蓝色调）
- `.emotion-eruption-banner` 爆发警告横幅（红/橙背景）
- `.emotion-event-log` 日志列表

#### 4.4 `electron/src/renderer/js/app.js` — 更新初始化

- 注册 emotion tab 的切换逻辑
- 初始化 EmotionDashboard

---

### 步骤 5：系统整合与端到端验证（P2）

#### 5.1 集成测试：消息 → 情绪 → 回复 完整链路

```python
# test_e2e_full_flow.py — 真实组件集成测试
# 1. 发送 "我爱你" → 确认 desire+20，PAD P↑
# 2. 连续发送 6 次 "不用你管" → patience 达阈值 → 触发冷暴
# 3. 冷暴模式下发送消息 → 回复 ≤3字 + 句号
# 4. 发送 "分手" → anxiety +60，检测 fear 情绪
# 5. 午夜衰减 → 确认所有槽位值下降
```

#### 5.2 API 响应时间验证

```python
# 使用 time.monotonic() 测量每个端点响应时间
# 目标：所有端点 <200ms（不含 LLM 调用时间）
```

#### 5.3 Electron UI 可用性检查

- 情绪 Tab 在 3 秒内展示实时数据
- 进度条动画流畅（CSS transition）
- 爆发警告横幅正确显示/消失
- 深色模式下颜色对比度合规

---

## 四、文件变更清单

### 新建文件（7 个）
| 文件 | 步骤 |
|------|------|
| `tests/test_emotion_engine.py` | 步骤 2.1 |
| `tests/test_emotion_threshold.py` | 步骤 2.2 |
| `tests/test_context_builder.py` | 步骤 2.4 |
| `tests/test_api.py` | 步骤 2.6 |
| `core/token_tracker.py` | 步骤 3.1 |
| `electron/src/renderer/js/emotion-dashboard.js` | 步骤 4.2 |

### 修改文件（6 个）
| 文件 | 步骤 | 改动 |
|------|------|------|
| `tests/test_pipeline.py` | 步骤 2.3 | 完全重写，匹配新 Pipeline API |
| `core/brain.py` | 步骤 3.2 | 多 provider 遍历 + fallback + token_tracker 集成 |
| `core/api_server.py` | 步骤 3.3 | 新增 `/api/emotion/thresholds`，增强 token stats |
| `electron/src/renderer/index.html` | 步骤 4.1 | 新增 Emotion Tab + panel |
| `electron/src/renderer/styles/main.css` | 步骤 4.3 | 新增情绪仪表盘样式块 |
| `electron/src/renderer/js/app.js` | 步骤 4.4 | 注册 emotion tab 切换 + 初始化 dashboard |

---

## 五、执行顺序

```
步骤 1（验证 Batch 1）
    ↓
步骤 2（重写测试）—— 可与步骤 3 并行
    ↓                        ↓
步骤 3（补全缺失模块）    步骤 4（UI 升级）
    ↓                        ↓
步骤 5（系统整合 & 端到端验证）
```

---

## 六、验收标准

1. `pytest tests/ -v` 全部通过，无 skip/xfail，覆盖率 ≥80%
2. `curl http://127.0.0.1:7890/api/emotion/state` 返回完整情绪状态（含 thresholds + eruption）
3. `curl http://127.0.0.1:7890/api/emotion/thresholds` 返回 4 槽位
4. 发送 "不用你管" 6 次 → patience 达 100 → 触发冷暴 → 回复截断为 ≤3字
5. 发送 "分手" → anxiety +60 → 情绪标签变为 fear
6. Electron UI Emotion Tab 实时展示所有数据，3 秒刷新
7. Brain 多 provider：SiliconFlow 超时/失败 → 自动 fallback 到 DeepSeek
8. Token 消耗被正确记录到 token_usage 表
