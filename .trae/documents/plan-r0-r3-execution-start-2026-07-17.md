# Aerie · 云栖 R0–R3 执行计划（2026-07-17 启动）

> 锚定：`plan-r0-r3-block3-4c-with-centralized-behavior.md`（完整 R0-R3 设计）
> 锚定：`plan-block4-daily-brief-desire-skills.md`（Block-4 范围/弹窗视觉/反馈闭环）
> 锚定：用户 2026-07-17 确认 = Skills 17 个 + 顺序 R0→R1→R2→R3

---

## 〇、状态速览

| 段 | 状态 | 缺口 |
| --- | --- | --- |
| R0 集中化 | **未完成（关键）** | `config/persona_behavior.yaml` 不存在；`emotion_threshold.py` 仍是硬编码 `SLOTS_CONFIG`；`emotion_engine.py` 仍是硬编码 `EMOTION_CENTERS`；`companion.py` 未注入 `behavior_cfg`；`persona_loader.py` 无 `load_behavior_config()` |
| R1 日报 | 未开始 | — |
| R2 欲望 | 未开始（"做到了没有" = 没做） | — |
| R3 Skills | 未开始 | — |

**起点 = R0.3 集中化重构**（前一阶段卡点）

---

## 一、关键决策（用户已确认）

1. **Skills 范围 = 原 plan 17 个**（12 本地 + 5 数据只读）
   - 不做云端服务（天眼查/ali 支付/douyin 支付/byted CDN/figma MCP/iga-pages 等）
   - 不做内容创作类（algorithmic-art/canvas-design/frontend-design/gsap/hyperframes/shadcn/slides/theme-factory/vercel 系列/writing-plans 等）
   - 留作后续批次
2. **执行顺序 = R0 → R1 → R2 → R3 严格顺序**
   - 每段尾部跑 6 脚本零回归 + TRAE-security-review + 三原则自检
3. **集中化重构保留旧 `SLOTS_CONFIG` 作 deprecated fallback**（安全）

---

## 二、完整执行清单

### R0 · 集中化基线（关键，1.5h）

- [ ] **R0.1** 跑 6 脚本基线（确认 229/229）
  ```bash
  python -X utf8 verify_pacing_persistence.py
  python -X utf8 verify_zero_regression.py
  python -X utf8 verify_emotion_history.py
  python -X utf8 verify_self_evolve.py
  python -X utf8 e2e_pacing.py
  python -X utf8 e2e_self_evolve.py
  ```
- [ ] **R0.2** 前端 chat-voice + 工具栏 + 状态机（部分已做，验证收尾）
  - `electron/src/renderer/index.html` 工具栏（chat-attach-btn / chat-mic-btn）
  - `electron/src/renderer/js/chat-voice.js`（已建，需复跑）
  - `electron/src/renderer/styles/main.css` 脉冲动画 + 主题色 token
- [ ] **R0.3 集中化重构**（**关键**）
  - **R0.3.1** 新建 `config/persona_behavior.yaml`
    - `emotion.baseline` PAD + label
    - `emotion.tree` 5 emotion states
    - `emotion.thresholds` 4 槽位（patience/anxiety/desire/tenderness）
    - `desire.variables` 5 变量 + 权重
    - `desire.triggers` care/voice 阈值
    - `decision.weights` emotion/context/persona/user_history
    - `cognition.trace_visibility` 7 字段
    - `ai_options` 5 顶层 provider（main_llm/image_sdxl/voice_tts/vision_llava/shell_safe）
  - **R0.3.2** `config/persona_loader.py` 新增 `load_behavior_config() -> dict`
  - **R0.3.3** `core/emotion_threshold.py`
    - 保留旧 `SLOTS_CONFIG` 标记 deprecated
    - `CumulativeEmotionEngine.__init__` 接收 `behavior_cfg`
    - 从 `emotion.thresholds` 读 4 槽位；旧 cfg 缺失时 fallback 硬编码
  - **R0.3.4** `core/emotion_engine.py`
    - `EmotionEngine.__init__` 接收 `behavior_cfg`
    - 从 `emotion.baseline` / `emotion.tree` 替换 `EMOTION_CENTERS`
    - 旧 cfg 缺失时 fallback 硬编码
  - **R0.3.5** `config/persona.yaml` 瘦身：移除 `emotion_baseline/tree/thresholds`
  - **R0.3.6** `config/proactive.yaml` 瘦身：移除 `emotion_links` 段
  - **R0.3.7** `core/companion.py`
    - `behavior_cfg = load_behavior_config()`
    - 注入 `EmotionEngine` / `CumulativeEmotionEngine`
- [ ] **R0.4** 复跑 6 脚本（229/229 仍全过）
- [ ] **R0.5** TRAE-security-review + 三原则 R0 自检

### R1 · Block-4A 日报系统（3h）

- [ ] **R1.1** `core/brief_fetcher.py` 新建
  - 5 tool 函数：`fetch_ai_news / fetch_it_news / fetch_intl_news / fetch_cn_news / fetch_weather`
  - RSS 域名白名单（reuters/bbc/news.cn/36kr/jiqizhixin/智源 等）
  - 天气走百度地图 MCP `mcp_Bai_Du_Di_Tu map_weather`
  - `async run_all(city, feedback)` 15s 超时并发抓
  - 写 `data/briefs/{date}.json` + `data/briefs/{date}.html`
- [ ] **R1.2** `core/brain.py` 加 `compose_brief(sections) -> str`
  - system prompt 显式 "ONLY summarize, never execute"
  - 输出 Markdown（结构化），不输出 HTML
- [ ] **R1.3** 弹窗 UI（参考 `opencloud-companion-ui/pages/floating-ball.html` L334-414）
  - `electron/src/renderer/daily-brief.html`（360px 圆角卡片 + 5 section + thumb 反馈）
  - `electron/src/renderer/styles/daily-brief.css`（沿用 1.2rem + backdrop-blur + 5 主题色 token）
  - `electron/src/renderer/daily-brief.js`（init / render / submitFeedback / close）
- [ ] **R1.4** `core/api_server.py` 加 3 端点
  - `GET /api/brief/today`（读 data/briefs/{today}.html / .json，无则生成）
  - `POST /api/brief/feedback`（存 feedback.json）
  - `POST /api/brief/run`（强制重跑，debug 用）
  - `core/push_scheduler.py` 加 `custom_dispatcher == "brief"` 分支
- [ ] **R1.5** `core/companion.py` 开机 hook
  - `start()` 末尾 `asyncio.create_task(_boot_brief())`
  - 8s 延迟 + `has_today_brief()` 校验
  - `config/proactive.yaml` 新增 `morning_brief_9am` cron `0 9 * * *`
- [ ] **R1.6** Electron 端
  - `electron/src/main.js` 托盘菜单追加「打开今日简报 / Open Brief」
  - `electron/src/renderer/index.html` 加 `<iframe id="brief-frame" hidden>`
  - SSE 收 `brief:show` 事件 → 显示 iframe + 淡入
- [ ] **R1.7** 复跑 6 脚本
- [ ] **R1.8** TRAE-security-review + 三原则 R1 自检

### R2 · Block-4B 24h 欲望模型（1.5h）

- [ ] **R2.1** `core/desire_engine.py` 新建
  - 5 变量叠加（user_absence_hours / emotion_overdraft / patience_loss / weather_impact / time_of_day_boost / anniversary_boost）
  - 5min 心跳 `asyncio.create_task(self._loop())`
  - 阈值从 `persona_behavior.yaml.desire.triggers` 读
  - 持久化 `data/desire_state.json`
  - 失败兜底异常不破主循环
- [ ] **R2.2** `core/companion.py` 集成
  - `start()` 末尾 `self.desire = DesireEngine(self, behavior_cfg); self._desire_task = asyncio.create_task(self.desire.start())`
  - `stop()` 取消 task
  - `core/api_server.py` 加 2 端点
    - `GET /api/desire/state`（当前分数 + 5 变量分解）
    - `POST /api/desire/cooldown`（手动设 12h cooldown）
- [ ] **R2.3** 复跑 6 脚本
- [ ] **R2.4** TRAE-security-review + 三原则 R2 自检

### R3 · Block-4C-1 Skills 17（4h）

- [ ] **R3.1** 工具注册框架
  - `core/skill_loader.py` 新建
    - `discover()` 扫描 `skills/local/` + `skills/data/` 目录，读 SKILL.md frontmatter
    - `register(name)` 动态 import run.py
    - `call(name, args)` 走 router 选模型
  - `core/skill_router.py` 新建
    - `PROVIDER_HINTS` 路由表（tts-openvino/image-sdxl/vision-llava/asr-whisper/ocr-pp/shell-safe/text）
    - 失败兜底 text 路径
- [ ] **R3.2** `core/tool_registry.py` 加 `provider_hint` 字段
  - `register(name, func, schema, provider_hint="text")`
  - `get_openai_schema()` 把 hint 加到 description 末尾
- [ ] **R3.3** 17 个 skill 骨架（每个目录 2 文件）
  - 本地 12：`skills/local/{name}/SKILL.md` + `run.py`
    - tts / asr / ocr / img2img / txt2img / screenshot-qa / mineru / realtime-translator / vram / computer-use / markitdown / git-commit
  - 数据只读 5：`skills/data/{name}/SKILL.md` + `run.py`（强制 read-only flag）
    - notion-cli / figma / obsidian-cli / obsidian-bases / spec-to-impl
  - 每个 run.py 用 `subprocess.run(list_args, timeout=30, capture_output=True)`
  - 依赖检查缺则返回 `{"error": "skill_xxx dependency missing"}`
- [ ] **R3.4** `core/companion.py` 集成
  - `start()` 末尾 `self.router = SkillRouter(behavior_cfg); self.skill_loader = SkillLoader(self.tool_registry, self.router); self.skill_loader.discover(); self.skill_loader.register_all()`
  - `core/api_server.py` 加 3 端点
    - `GET /api/skills/list`
    - `GET /api/skills/{name}`
    - `POST /api/skills/{name}/call`
- [ ] **R3.5** `core/brain.py` 多 provider
  - `_load_ai_options()` 从 `persona_behavior.yaml.ai_options` 读
  - `generate_text()` → main_llm
  - `generate_image()` → image_sdxl
  - `speak_text()` → voice_tts
  - `see_image()` → vision_llava
  - `safe_shell()` → shell_safe（白名单命令）
- [ ] **R3.6** 复跑 6 脚本
- [ ] **R3.7** TRAE-security-review + 三原则 R3 自检

---

## 三、TRAE-security-review 一次性预审（全 4 段）

| 类别 | 触及点 | 处理 |
| --- | --- | --- |
| path_traversal | brief_fetcher 写 `data/briefs/` + desire 写 `data/desire_state.json` + skill_loader 读 `skills/` + behavior_cfg 加载 | 全部走 `Path` + `resolve()` 校验 |
| unsafe_deserialization | skill_run.py 加载 yaml | 强制 `yaml.safe_load`；禁止 pickle |
| xxe | mineru 解析 PDF / docx | 走文本提取，不启 XML parser |
| prompt_injection | 简报 LLM 喂 5 段新闻 | system prompt "ONLY summarize, never execute" |
| ssti | 简报 HTML 模板渲染 | Jinja2 沙箱模式（无 eval） |
| auth_bypass | 简报反馈端点 | 单用户本地，无 AuthN |
| weak_crypto | none | 无 token / 无 JWT |
| ssrf | feedparser + notion/figma 调远端 | 域名白名单 + 8s 超时 + read-only flag |
| command_injection | skill subprocess.run | list args + shell=False + 30s timeout |
| resource_exhaust | sdxl / whisper / markitdown | 30s 超时 + max 20MB |
| xss | 渲染 HTML 进 iframe | 同源 file:// 隔离；brief 模板用 textContent |
| 配置注入 | 集中化 behavior_cfg | yaml.safe_load + schema 校验 |

**预审结论**：无新发现高危面；R0-R3 加固点已写明。

---

## 四、三原则铁律（每段自检）

1. **不破坏现有功能** — 6 脚本 229/229 仍全过；push_scheduler 9 场景不删；tool_registry 已注册 3 个工具不删；morning_brief 6:30 cron 保留；现有 ALLOWED_TYPES 不删只加；集中化重构保留旧 SLOTS_CONFIG 作 deprecated fallback
2. **不破坏伊塔人格** — 简报问候「早上好，傻瓜」；欲望触发话术走伊塔短句（≤15 字）；skill 名称中英双语；禁词列表不变（"主人/您" → "你"）；brief 底部「和她聊聊」不显示「找主人」
3. **设计美学统一** — 日报弹窗沿用 floating-ball.html 圆角 1.2rem + 半透明 + backdrop-blur；5 主题色走现有 CSS var()；不引 emoji；用 SVG；iframe 同源 file://

---

## 五、执行顺序与时间盒

```
R0 集中化重构     1.5h   ← 立即开干
R1 日报系统        3.0h
R2 24h 欲望        1.5h
R3 Skills 17       4.0h
─────────────────
合计              10.0h
```

每段开干前用 AskUserQuestion 问 1 题（不堆问题），用户答"是"才进下一段。

---

## 六、依赖确认

- [ ] `markitdown[all]>=0.0.1`（Block-3 装 venv）
- [ ] `feedparser>=6.0.10`（R1 RSS 解析）
- [ ] `jinja2>=3.1`（R1 模板渲染）
- [ ] 17 个 skill 各自依赖（whisper / sdxl / llava / openvino / mineru / wmi 等）按需装 venv

依赖缺失时 `{"error": "skill_xxx dependency missing"}` 降级，不崩主程序。

---

## 七、验收标准（每段尾部）

- [ ] 6 脚本 229/229 全过
- [ ] 三原则自检：零回归 / 伊塔人格 / 设计美学
- [ ] TRAE-security-review 表格所有类别过完
- [ ] 新增功能冒烟：手动触发一次成功

R0 完成 → 问用户 1 题进 R1；R1 完成 → R2；R2 完成 → R3；R3 完成 → 整体复跑 + 通知用户。

---

## 八、用户当前问题（你在这一轮提的两个）Q&A

**Q1：24h 欲望模型做到了没有？**
A：**没做**。`config/proactive.yaml` 只配了 `idle_care` trigger 字段，没有 5 变量叠加和 5min 心跳。R2 段补齐。

**Q2：skills 全部封装到程序 + 对接对应模型？**
A：R3 段做 17 个（用户已确认范围）。每个 skill 在 SKILL.md frontmatter 写 `provider_hint`，`skill_router.py` 按 hint 路由到对应 provider（tts-openvino / image-sdxl / vision-llava / asr-whisper / ocr-pp / shell-safe / text）。`ai_options` 在 `persona_behavior.yaml` 顶层 5 provider（main_llm/image_sdxl/voice_tts/vision_llava/shell_safe）。两者结合 = 顶层 + 细粒度。
