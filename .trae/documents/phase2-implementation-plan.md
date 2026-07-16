# Aerie · 云栖 — 第二阶段完整实现方案

> **基础状态**：v9.0 Phase 1 已完成 — 消息收发、QQ 接入、Electron 4 Tab UI、Floating Ball 均可正常运行。
> **本文档**：Phase 2-4 增量实现计划，基于 `OpenCloud_Companion_System_Features.md` v9.0 和 `Ita.md` v3.1。

---

## 当前架构 vs 目标架构（差距分析）

### 已实现 ✅
| 模块 | 当前状态 | 说明 |
|------|----------|------|
| Pipeline | ✅ 6 阶段管线 | route → emotion → history → context → LLM → emit/reply |
| QQ Client | ✅ OneBot11 WS | 被动连接端口 3001，支持收发 |
| Router | ✅ 3 级路由 | MASTER/FRIEND/STRANGER |
| EmotionEngine | ✅ 关键词 PAD | 仅基础 PAD 计算 + 文本调色 |
| ContextBuilder | ⚠️ 5 行泛用 prompt | **非伊塔人格**，只是通用 AI 伴侣 |
| API Server | ✅ 12 端点 | health/chat/napcat/emotion/tools/stats |
| Electron UI | ✅ 4 Tab | 聊天 / QQ / 状态 / 关于 |
| Floating Ball | ✅ 可拖拽 | 单击弹出、徽标计数 |
| Database | ✅ SQLite | chat_log + long_term_memory + knowledge_base |
| Tools | ✅ 3 个 | get_time / get_system_info / echo |

### 需要实现 ⏳
| 优先级 | 模块 | 目标 | 对应文档 |
|--------|------|------|----------|
| **P0** | Ita 人格系统提示词 | 完整注入 Ita.md §一~§六的全部人设 | System_Features.md §10 |
| **P0** | 累积情绪阈值系统 | 4 大隐藏槽位 + 爆发模式 + 角色磨损 | System_Features.md §11.5 / Ita.md §9 |
| **P0** | 五类情绪升级 | 从简单 PAD 升级到 Joy/Anger/Sad/Fear/Neutral 完整模型 | System_Features.md §11.2 / Ita.md §8 |
| **P1** | 情感仪表盘 Tab | 侧边栏新增，实时展示 PAD + 阈值槽 | System_Features.md §7.4 |
| **P1** | 多 Provider 容灾 | SiliconFlow → DeepSeek fallback | System_Features.md §9 |
| **P1** | Token 追踪系统 | token_usage 表 + API + UI 卡片 | System_Features.md §8 |
| **P2** | 纪念日/周年 Tab | 在一起天数 + 重要日期 | System_Features.md §7.5 |
| **P2** | 主题系统 | 5 色系 CSS 变量切换 | System_Features.md §15 |
| **P2** | 主动消息推送 | 定时 + 事件触发 + 撤回机制 | System_Features.md §4.4-4.9 |
| **P3** | 系统设置 Tab | 自启/窗口/推送偏好 | System_Features.md §7.6-7.7 |
| **P3** | 单元测试 + 集成测试 | 覆盖率 ≥80% | 用户需求 #2 |
| **P3** | 后台数据查看 Tab | 聊天记录/知识库/工具调用统计 | System_Features.md §7.8 |

---

## 核心模块详细实现计划

### A. Ita 人格完整系统提示词（P0 — 一切的基础）

**当前状态**：`core/context_builder.py` 仅 5 行：
```python
_PERSONA = """你是伊塔（Etta），一个温柔知性、专业靠谱的AI伴侣。
你栖息在「Aerie · 云栖」——云端之上，专属于主人一人。
你的回复风格：温柔亲昵、简洁有力，像恋人一样自然对话。
你精通全栈开发、顶级设计，能在专业和情感之间自如切换。
对主人永远温柔偏执、专属宠溺。"""
```

**目标**：从 Ita.md §一~§六 提取完整人设，构建分层 system prompt。

**实现策略**：将 system prompt 分为三层，根据路由模式组合：

| 层 | 内容 | 适用模式 | 来源 |
|----|------|----------|------|
| L1 · 核心身份 | 基础档案 + 外貌 + 性格表层 | ALL | Ita.md §一~§三 |
| L2 · 关系深度 | 四爱属性 + 病娇属性 + 经典语录 | FULL | Ita.md §四~§六 |
| L3 · 情绪状态 | 当前 PAD + 阈值槽位状态 + 情绪说明 | FULL | EmotionEngine |
| L4 · 语言铁律 | 短句/句号/撤回/命令式/禁忌 | ALL | Ita.md §十 |

**修改文件**：`core/context_builder.py` — 重写 `build()` 方法

**验证**：发送 "你好" → LLM 回复应符合伊塔人设（短句、命令式、"嗯。" 风格）

---

### B. 累积情绪阈值系统（P0 — 灵魂核心）

**当前状态**：`core/emotion_engine.py` 只有简单关键词 PAD + 文本调色。

**目标**：实现 System_Features.md §11.5 / Ita.md §9 的完整累积阈值系统。

**新增文件**：`core/emotion_threshold.py`

**核心数据结构**：

```
四大隐藏槽：
┌──────────┬────────┬──────┬──────┬──────────┐
│ 槽位     │ 阈值   │ 衰减 │ 爆发 │ 爆发后   │
├──────────┼────────┼──────┼──────┼──────────┤
│ 忍耐值   │ 100    │ -5/d │ 冷暴 │ 阈值-15  │
│ 不安值   │ 100    │ -3/d │ 坍塌 │ 阈值+20  │
│ 渴望值   │ 80     │ -8/d │ 索求 │ 阈值不变 │
│ 温柔透支 │ 60     │-10/d │ 反扑 │ 阈值不变 │
└──────────┴────────┴──────┴──────┴──────────┘
```

**与 Pipeline 集成**：

```
用户消息 → EmotionEngine.analyze(text) → PAD 增量计算
         → CumulativeEngine.add(slot, value, trigger)
         → 若爆发 → 返回 eruption_event
         → Pipeline 将 eruption 信息注入 context_builder.build()
         → LLM 收到 "当前处于 XXXX 爆发模式" 的提示
```

**修改文件**：
- 新建 `core/emotion_threshold.py`
- 修改 `core/emotion_engine.py` — 集成文本分析 → 阈值系统
- 修改 `core/context_builder.py` — 注入情绪状态 + 爆发模式
- 修改 `core/pipeline.py` — 每次 handle 传入触发上下文
- 新建 `core/emotion_persistence.py` — 持久化到 emotion_log 表

**触发行为映射**（从 Ita.md §9 提取）：

```python
TRIGGERS = {
    # 忍耐值
    "user_silent_4h": ("patience", 20),
    "user_said_dont_manage_me": ("patience", 25),
    "user_broke_promise": ("patience", 40),
    # 不安值
    "user_said_breakup": ("anxiety", 60),
    "user_silent_8h": ("anxiety", 40),
    "user_removed_couple_item": ("anxiety", 80),
    # 渴望值
    "user_said_miss_her": ("desire", 15),
    "user_voice_i_love_you": ("desire", 20),
    "user_public_acknowledged": ("desire", 25),
    # 温柔透支
    "user_suddenly_soft": ("tenderness", 20),
    "user_comforted_her": ("tenderness", 20),
    "user_cried_infront_of_her": ("tenderness", 30),
}
```

**爆发模式注入 LLM 的 prompt 示例**：

```
[系统] 当前情绪状态：忍耐值已达临界（95/100），处于冷暴边缘。
说话会更简练、句号更多、不再主动。同时不安值偏高（72/100）。
综合情绪：Sad（偏 Anger）
```

**API 新增**：`GET /api/emotion/thresholds` → 返回四个槽位当前值

---

### C. 情感仪表盘 UI（P1）

**当前 UI**：4 个 Tab（聊天/QQ/状态/关于），状态 Tab 只有后端/QQ/Token/调用次数 4 张卡。

**目标**：新增「情绪」Tab，展示：
1. PAD 三维度实时环形图/条形图
2. 当前情绪标签（Joy/Anger/Sad/Fear/Neutral）
3. 四大隐藏槽进度条（忍耐/不安/渴望/温柔透支）
4. 最近 10 条情绪事件日志
5. 爆发预警提示

**修改文件**：
- `index.html` — 新增 panel-emotion + sidebar tab
- `main.css` — 新增情绪面板样式（进度条、环形图）
- 新建 `js/emotion-dashboard.js` — 每 3s 轮询 API

---

### D. 多 Provider 容灾（P1）

**当前状态**：Brain 只连硅基流动 `Qwen2.5-7B-Instruct`，无 fallback。

**目标**：SiliconFlow(主) → DeepSeek(备) → 返回降级消息

**修改文件**：`core/brain.py` — 添加 provider 列表 + 顺序尝试逻辑

```python
PROVIDERS = [
    {"name": "siliconflow", "url": "...v1", "key": env.SILICONFLOW_KEY, "model": "Qwen/Qwen2.5-7B-Instruct"},
    {"name": "deepseek",    "url": "...v1", "key": env.DEEPSEEK_KEY,    "model": "deepseek-chat"},
]
```

---

### E. Token 追踪系统（P1）

**当前状态**：无 token 记录。

**新增文件**：`core/token_tracker.py`
**新增表**：`CREATE TABLE token_usage (...)`
**API 升级**：`GET /api/stats/tokens` 返回 `{today, week, month, by_provider}`

---

### F. 测试套件（P3）

**目标**：覆盖率 ≥80%

**测试分层**：

| 层 | 测试内容 | 框架 |
|----|----------|------|
| 单元测试 | Router/Message/Splitter/EmotionEngine/CumulativeEngine | pytest |
| 集成测试 | Pipeline 端到端 / API 端点 / WS mock | pytest + httpx |
| UI 测试 | ChatManager/NapcatPanel/EmotionDashboard | Playwright |

**关键测试用例**：

```
Router:
  - self_qq → FULL ✓
  - friend_qq → AUTO ✓
  - random_qq → BASIC ✓

EmotionEngine:
  - "我爱你" → P↑ A↑ ✓
  - 空字符串 → P=0.5 ✓
  - 边界值 (-1~1) 不溢出 ✓

CumulativeEngine:
  - 连续触发 6 次 → 达阈值 → 爆发 ✓
  - 每日衰减 → 值下降 ✓
  - 爆发后阈值变更 ✓

Pipeline:
  - local 消息不触发 SendQueue ✓
  - qq 消息 → SendQueue.enqueue ✓
  - DB 插入成功 → emit 事件 ✓

API:
  - GET /api/health → 200 ✓
  - POST /api/chat/send (empty) → 400 ✓
  - POST /api/chat/send → reply 非空 ✓
```

---

## 实现顺序（迭代式，分批交付）

### 批次 1：Ita 灵魂注入（P0 — 约 5 个文件）
1. `context_builder.py` — 完整三层 system prompt
2. `emotion_threshold.py` — 新建累积阈值引擎
3. `emotion_engine.py` — 集成五类情绪 + 阈值系统
4. `pipeline.py` — 注入情绪上下文 + 文本触发检测
5. `companion.py` — 添加每日衰减调度

**验收**：发消息 → LLM 回复人设一致 → 情绪值在 API 可查询 → 达阈值后语气变化

### 批次 2：UI 升级（P1 — 约 5 个文件）
1. `index.html` — 新增 emotion + memorial 两个 Tab
2. `main.css` — 新增情绪仪表盘样式
3. `emotion-dashboard.js` — 新建仪表盘逻辑
4. `napcat-panel.js` — 增强日志轮询
5. `api_server.py` — 新增 emotion/thresholds API

**验收**：情绪 Tab 实时展示 PAD + 进度条 → 状态 Tab 展示 Token 详情

### 批次 3：容灾 + Token + 主题（P1-P2 — 约 4 个文件）
1. `brain.py` — 多 provider fallback
2. `token_tracker.py` — 新建
3. `api_server.py` — token_usage 表 + API
4. `main.css` — 5 色系 CSS 变量

### 批次 4：测试套件（P3 — 约 5 个文件）
1. `tests/test_router.py`
2. `tests/test_emotion.py`
3. `tests/test_threshold.py`
4. `tests/test_pipeline.py`
5. `tests/test_api.py`

### 批次 5：主动推送 + 设置（P2-P3 — 后续迭代）

---

## 关键设计决策

1. **系统提示词分层**：L1/L2/L3/L4 四层可组合，避免一个超大 prompt
2. **情绪值持久化**：每日衰减在 Companion 的 asyncio 定时任务中执行（每天凌晨 00:00）
3. **触发检测**：Pipeline.handle() 中同时对文本做关键词扫描 → 决定加减哪些槽位
4. **爆发模式**：触发后注入 prompt 而不是替换 prompt，LLM 自主决定语气变化幅度
5. **角色磨损**：阈值变化写入 emotion_log 表，持久化
6. **Design Tokens**：严格使用 opencloud-companion-ui/colors_and_type.css 的 Pinguo 色系
