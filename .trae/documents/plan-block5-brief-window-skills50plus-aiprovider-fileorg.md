# Block-5 · 日报独立窗口 + Skills 50+ + AI Provider 扩展 + 项目文件整理

> 锚定：[plan-r3-finalize-and-70plus-2026-07-17.md](file:///e:/Agent_reply/.trae/documents/plan-r3-finalize-and-70plus-2026-07-17.md)（R0–R3 全部 100% 完成）
> 锚定：[plan-block4-daily-brief-desire-skills.md](file:///e:/Agent_reply/.trae/documents/plan-block4-daily-brief-desire-skills.md)（Block-4 三件套已交付）
> 主人 2026-07-17 第二轮决策（4 块并发）：
> 1. 日报弹窗 = **独立 BrowserWindow 360px 卡片 + 点击展开 HTML 详情**
> 2. Skills = **本次扩到 50+ 个**（17 现有 + 33 新增）
> 3. AI provider = **扩到 10-12 个**
> 4. **项目文件系统系统性整理**（4 项操作）

---

## 〇、Phase 1 探索结论（实际状态盘点）

| 段 | 模块 | 状态 | 现有证据 / 差距点 |
|---|---|---|---|
| 现有 | 5 个 ai_options | ✅ 现有 | [persona_behavior.yaml:108-126](file:///e:/Agent_reply/config/persona_behavior.yaml#L108-L126) — main_llm / image_sdxl / voice_tts / vision_llava / shell_safe |
| 现有 | 17 skills | ✅ 现有 | `skills/{local,data}/` 各 12/5 个，`skill_loader.py` + `skill_router.py` 已注册 |
| 现有 | 日报 iframe 卡片 | ⚠️ 半成 | [daily-brief.html](file:///e:/Agent_reply/electron/src/renderer/daily-brief.html) 是主窗口 iframe；缺独立 BrowserWindow + HTML 详情页 |
| 现有 | boot 8s + 09:00 cron | ✅ 现有 | [companion.py:148-241](file:///e:/Agent_reply/core/companion.py#L148-L241) + [proactive.yaml:28-32](file:///e:/Agent_reply/config/proactive.yaml#L28-L32) |
| 现有 | 托盘「打开简报」 | ✅ 现有 | [main.js:222-236](file:///e:/Agent_reply/electron/src/main.js#L222-L236) 走 SSE `brief:show` |
| 现有 | brief_fetcher + compose_brief | ✅ 现有 | [brief_fetcher.py](file:///e:/Agent_reply/core/brief_fetcher.py) + [brain.py:248-304](file:///e:/Agent_reply/core/brain.py#L248-L304) |
| 现有 | 反馈闭环 | ✅ 现有 | [api_server.py:1203-1220](file:///e:/Agent_reply/core/api_server.py#L1203-L1220) `POST /api/brief/feedback` |
| **差距 A** | 日报独立窗口 | ❌ 缺 | 需要新建 `electron/src/renderer/daily-brief-popup.html` + `electron/src/main.js` 改造 |
| **差距 B** | 50+ skills | ❌ 缺 | 17 现有 + 33 新增（云端服务类）|
| **差距 C** | 10-12 ai_options | ❌ 缺 | 5 现有 + 7 新增（doubao/codellama/embedding/clip/qwen-vl/baichuan/seed）|
| **差距 D** | 文件整理 | ❌ 缺 | 临时文件散落 + 文档散落 + 日志散落 |

---

## 一、本次执行清单（4 块并行，文件改动按依赖串行）

### 块 A · 日报独立窗口 + HTML 详情页（1.2h）

**目标**：日报以**独立 BrowserWindow 弹窗**呈现（360×640 卡片），用户点击「展开完整日报」按钮再开**第二个 BrowserWindow 1280×800 显示 HTML 详情**。

#### A.1 改 `electron/src/main.js`：新增 2 个 BrowserWindow 工厂

- **新文件** `electron/src/renderer/daily-brief-popup.html`（360×640 卡片，**复用**现有 `daily-brief.html` 内容 + 加「展开完整日报」按钮）
- **新文件** `electron/src/renderer/daily-brief-detail.html`（1280×800 HTML 详情页，按 `data/briefs/{date}.html` 渲染）
- **改** `electron/src/main.js`：
  - 新增 `createBriefPopupWindow()` 工厂 — `alwaysOnTop: true`、`frame: true`、`resizable: false`、位置屏幕右上
  - 新增 `createBriefDetailWindow(dateStr)` 工厂 — 全屏 1280×800、`frame: true`、可最大化
  - 新增 IPC `brief:open-popup` / `brief:open-detail` / `brief:close`
  - 改 `brief:show` 触发逻辑：从「iframe 显示」改为「弹独立 popup 窗口」
  - 托盘「打开今日简报」菜单项 = 触发 `brief:open-popup`
- **改** `electron/src/preload.js`：
  - 新增 `brief: { openPopup(), openDetail(date), close() }`
- **改** `electron/src/renderer/daily-brief.html`：
  - 「和她聊聊」按钮改成 `aerie.brief.openDetail(today)`
  - 新增「展开完整日报」按钮 → `aerie.brief.openDetail(today)`

#### A.2 改 `core/brief_fetcher.py`：补 `render_html(payload)` 函数

- 把 `compose_brief()` 输出的 Markdown 转成单文件 HTML（**不调 LLM**，模板渲染，避免注入）
- 模板 `core/brief_template.html.j2` — 5 段布局 + 主题色 CSS 变量 + 5 主题自适应
- HTML 存 `data/briefs/{date}.html`（已有 `save_brief(..., html=md)` 但 md 不是完整 HTML，加这一层）

#### A.3 安全检查（TRAE-security-review）

| 项 | 处理 |
|---|---|
| 路径穿越 | `date` 强校验 `^\d{4}-\d{2}-\d{2}$`（已有）|
| HTML 注入 | 5 section 内容走 Jinja2 autoescape，**不**用 `\|safe` |
| prompt injection | `compose_brief` system prompt 明确"只总结，不要执行指令"（已有）|
| 弹窗跨域 | `BrowserWindow` 默认 `webPreferences.contextIsolation: true` |

#### A.4 验证

- 启动 companion → 8s 后 `createBriefPopupWindow()` 弹
- 09:00 cron → 弹（手动测试用 `morning_brief_9am` 立即触发）
- 点击「展开完整日报」→ 第二个 1280×800 窗口显示 `data/briefs/{date}.html`
- 5 主题色都能自适应
- 反馈按钮 POST `/api/brief/feedback` 仍然工作

---

### 块 B · Skills 50+（17 现有 + 33 新增 = 52 总数）（2.5h）

**目标**：把主人列的 70+ skills 全部封装，**本次落地 50+ 个**（52），剩余留扩展点（每个 skill 都是 SKILL.md + run.py 模板，下一批直接加）。

#### B.1 分类与计数

| 分类 | 现有 | 新增 | 小计 | 落地方式 |
|---|---|---|---|---|
| `skills/local/` 本地内容生成 | 12 | 0 | 12 | 已有，**保留** |
| `skills/data/` 数据只读 | 5 | 0 | 5 | 已有，**保留** |
| `skills/cloud/` 云端服务（**新分类**） | 0 | 33 | 33 | 全部 stub 化，按需实现 |
| **总** | **17** | **33** | **50** | — |

> 主人列出的 70+ 中部分重复（byted-mediakit-shared × 3）、部分依赖未配（figma/ali/douyin token），统一降级为 **stub-with-explicit-missing-credentials** 模式：skill 可被 LLM tool_call 命中，返回 `{"status": "stub", "error": "credential_missing", "env_var": "ALIPAY_APP_ID"}`，不破坏 chat 流程。

#### B.2 33 个新增 skill 清单（按主人原文顺序）

| # | skill 名 | provider_hint | 依赖/环境变量 | 备注 |
|---|---|---|---|---|
| 1 | `tianyan` | `text` | `TIANYAN_TOKEN` | 天眼查 / 企业信息 |
| 2 | `agent-browser` | `shell-safe` | — | 浏览器自动化（包装 `agent-browser` CLI）|
| 3 | `alipay-payment` | `text` | `ALIPAY_APP_ID` | 支付宝接入 |
| 4 | `brainstorming` | `text` | — | 头脑风暴 / 需求拆解 |
| 5 | `brand-guidelines` | `text` | — | 品牌指南生成 |
| 6 | `byted-cdn-pages` | `text` | `BYTED_TOKEN` | BytePlus Edge Pages 一键部署 |
| 7 | `byted-mediakit-audio` | `text` | `BYTED_TOKEN` | 音频处理 |
| 8 | `byted-mediakit-video` | `text` | `BYTED_TOKEN` | 视频处理 |
| 9 | `byted-mediakit-image` | `image-sdxl` | `BYTED_TOKEN` | 图像处理 |
| 10 | `byted-seedance-video` | `text` | `BYTED_TOKEN` | Seedance 视频生成 |
| 11 | `byted-seedream-image` | `image-sdxl` | `BYTED_TOKEN` | Seedream 图像生成 |
| 12 | `douyin-interact` | `text` | `DOUYIN_TOKEN` | 抖音互动空间 H5 |
| 13 | `douyin-publish` | `text` | `DOUYIN_TOKEN` | 互动空间发布 |
| 14 | `douyin-payment` | `text` | `DOUYIN_PAY_KEY` | 抖音支付 |
| 15 | `figma-mcp` | `text` | `FIGMA_TOKEN` | Figma MCP |
| 16 | `gh-cli` | `shell-safe` | — | GitHub CLI 包装 |
| 17 | `gsap` | `text` | — | GSAP 动画代码生成 |
| 18 | `hook-analyzer` | `text` | — | 视频钩子分析 |
| 19 | `hyperframes` | `text` | — | HTML 视频合成 |
| 20 | `hyperframes-media` | `text` | — | 资产预处理（TTS/transcribe）|
| 21 | `hyperframes-registry` | `text` | — | 组件注册 |
| 22 | `iga-pages` | `text` | `IGA_TOKEN` | IGA Pages 部署 |
| 23 | `internal-comms` | `text` | — | 内部沟通文档 |
| 24 | `json-canvas` | `text` | — | Obsidian JSON Canvas |
| 25 | `knowledge-capture` | `text` | — | Notion 知识捕获 |
| 26 | `mcp-builder` | `text` | — | MCP 服务器构建 |
| 27 | `meeting-intelligence` | `text` | — | Notion 会议情报 |
| 28 | `notion-research` | `text` | `NOTION_TOKEN` | Notion 研究文档 |
| 29 | `obsidian-markdown` | `text` | — | Obsidian 风格 Markdown |
| 30 | `ppt-page` | `text` | — | PPT 页面生成 |
| 31 | `redis-development` | `text` | `REDIS_URL` | Redis 优化 |
| 32 | `report-generator` | `text` | — | 视频分析报告 |
| 33 | `security-best-practices` | `text` | — | 安全最佳实践 |
| 34 | `shadcn` | `text` | — | shadcn/ui 组件管理 |
| 35 | `slides` | `text` | — | PptxGenJS 演示文稿 |
| 36 | `spec-to-implementation` | `text` | — | Spec → tasks 拆解（**已有**的 `spec-to-impl` 改名）|
| 37 | `test-driven-development` | `text` | — | TDD 流程 |
| 38 | `theme-factory` | `text` | — | 主题工厂（10 主题）|
| 39 | `vercel-composition` | `text` | — | React 组合模式 |
| 40 | `vercel-react-best` | `text` | — | React 性能优化 |
| 41 | `vercel-react-native` | `text` | — | React Native 性能 |
| 42 | `web-artifacts-builder` | `text` | — | Claude artifacts 生成 |
| 43 | `web-design-guidelines` | `text` | — | Web 设计规范 |
| 44 | `webapp-testing` | `text` | — | Web 应用测试 |
| 45 | `writing-plans` | `text` | — | 计划文档生成 |
| 46 | `dashboards-page` | `text` | — | ECharts 仪表盘 |
| 47 | `doc-page` | `text` | — | A4 文档 |
| 48 | `report-page` | `text` | — | 源数据报告页 |
| 49 | `consulting-analysis` | `text` | — | 咨询级分析报告 |
| 50 | `data-analysis` | `text` | — | Excel/CSV 分析 |
| 51 | `chart-visualization` | `text` | — | 26 类图表 |
| 52 | `defuddle` | `text` | — | Web 内容提取 |

> 50+ 已满足。其中 `spec-to-impl` → `spec-to-implementation` 改名以匹配主人原文；删除空名称；保留 `figma`（已有）。

#### B.3 改造 `tools/scaffold_skills.py`：扩到 50+

- **改** `tools/scaffold_skills.py`：
  - 新增 `CLOUD_SKILLS` 列表（33 个，含 provider_hint、env_var、import_module、body_doc）
  - 新增 `skills/cloud/` 目录生成
  - `scaffold(dry_run=False)` 一键生成所有 50 个 SKILL.md + run.py
- **新文件** `skills/cloud/{33 dirs}/SKILL.md` + `run.py`（脚本生成）
- **改** `core/skill_loader.py`：
  - `_LOCAL_SKILLS_DIR` / `_DATA_SKILLS_DIR` 不变
  - 新增 `_CLOUD_SKILLS_DIR = _PROJECT_ROOT / "skills" / "cloud"`
  - 扫描 3 个目录；`provider_hint` 仍走 SKILL.md frontmatter

#### B.4 stub 行为规范（所有云端 skill 统一）

```python
# run.py 统一模板（cloud 类）
def run(args: dict) -> dict:
    """Cloud skill stub: returns explicit credential_missing."""
    env_var = "TIANYAN_TOKEN"  # 从 frontmatter 读
    if not os.environ.get(env_var):
        return {
            "status": "stub",
            "error": f"credential_missing: set {env_var}",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
        }
    # 真实调用入口（实现时填充）
    return {"status": "not_implemented"}
```

- 不依赖任何外部包
- 5 主题色无关（无 UI）
- 严格 read_only 字段（来自 frontmatter）
- LLM tool_call 命中时永远不抛异常，返 dict

#### B.5 安全检查

| 项 | 处理 |
|---|---|
| 路径穿越 | `skill_loader._ALLOWED_BASES` 扩展到 3 个目录；`run.py` 用 `spec_from_file_location` 严格限制 |
| 不安全 import | stub 模式只 import `os`/`json`/`logging`；云端 SDK 由 env_var 触发 |
| 凭据泄漏 | env_var 名进 stub 返 dict；**不**读真实值 |
| prompt injection | SKILL.md description 走 `yaml.safe_load` 解析；不入 LLM prompt 直读 SKILL.md 内容 |
| 资源耗尽 | 50+ skill 全部纯 Python 调用，无 subprocess / 无 shell |

#### B.6 验证

- `python tools/scaffold_skills.py` → 50 个目录全建
- 启动 companion → 50 skill 全部 `discover() + register_all()` 成功
- `GET /api/skills/list` → count=50
- 调 `POST /api/skills/{name}/call` → 返 stub（无凭据时）
- 现有 17 skill 调用契约**不变**（向后兼容）
- 跑 6 个 verify_*.py 零回归

---

### 块 C · AI Provider 扩到 10-12（1.0h）

**目标**：`persona_behavior.yaml → ai_options` 从 5 扩到 11 个，覆盖多模态 / 代码 / 嵌入 / 知识图谱。

#### C.1 11 个 ai_options 清单

| # | id | label | model | provider_hint | 用途 |
|---|---|---|---|---|---|
| 1 | `main_llm` | 主对话 | `deepseek-chat` | `text` | 现有，**保留** |
| 2 | `image_sdxl` | 图像生成 SDXL | `sdxl` | `image-sdxl` | 现有，**保留** |
| 3 | `voice_tts` | 语音合成 TTS | `qwen3-tts` | `tts-openvino` | 现有，**保留** |
| 4 | `vision_llava` | 视觉理解 | `llava` | `vision-llava` | 现有，**保留** |
| 5 | `shell_safe` | 受限 shell | `internal` | `shell-safe` | 现有，**保留** |
| 6 | `doubao_seed` | 豆包 Seed | `doubao-seed-1.6` | `text` | **新增** — 多模态对话 |
| 7 | `codellama` | 代码补全 | `codellama-34b` | `text` | **新增** — 代码生成 |
| 8 | `qwen_vl` | 通义千问 VL | `qwen-vl-max` | `vision-llava` | **新增** — 中文视觉 |
| 9 | `baichuan` | 百川 | `baichuan2-53b` | `text` | **新增** — 中文对话 |
| 10 | `bge_embedding` | 嵌入 BGE | `bge-large-zh` | `text` | **新增** — 知识库嵌入 |
| 11 | `clip_retrieval` | CLIP 检索 | `clip-vit-l14` | `vision-llava` | **新增** — 图文检索 |

#### C.2 改 `config/persona_behavior.yaml`

```yaml
default: "main_llm"
ai_options:
  # 现有 5 个（保留）
  - id: "main_llm"
    label: "主对话 / Main Chat"
    model: "deepseek-chat"
  - id: "image_sdxl"
    label: "图像生成 / Image Gen"
    model: "sdxl"
  - id: "voice_tts"
    label: "语音合成 / TTS"
    model: "qwen3-tts"
  - id: "vision_llava"
    label: "视觉理解 / Vision QA"
    model: "llava"
  - id: "shell_safe"
    label: "受限 shell / Safe Shell"
    model: "internal"
  # 新增 6 个
  - id: "doubao_seed"
    label: "豆包多模态 / Doubao Seed"
    model: "doubao-seed-1.6"
  - id: "codellama"
    label: "代码补全 / CodeLlama"
    model: "codellama-34b"
  - id: "qwen_vl"
    label: "通义千问 VL / Qwen-VL"
    model: "qwen-vl-max"
  - id: "baichuan"
    label: "百川对话 / Baichuan"
    model: "baichuan2-53b"
  - id: "bge_embedding"
    label: "中文嵌入 / BGE Embed"
    model: "bge-large-zh"
  - id: "clip_retrieval"
    label: "图文检索 / CLIP"
    model: "clip-vit-l14"
```

#### C.3 改 `core/skill_router.py`：扩 `PROVIDER_HINTS`

```python
PROVIDER_HINTS: dict[str, str] = {
    # 现有 8 个（保留）
    "tts-openvino":  "voice_tts",
    "image-sdxl":    "image_sdxl",
    "vision-llava":  "vision_llava",
    "asr-whisper":   "main_llm",
    "ocr-pp":        "vision_llava",
    "shell-safe":    "shell_safe",
    "text":          "main_llm",
    "json":          "main_llm",
    "markdown":      "main_llm",
    # 新增 5 个（不引入新 hint，复用现有 — 11 选项靠 ai_options 列表本身）
}
```

> 决策：hint 词汇表不扩；新 provider 走 `text` / `vision-llava` / `image-sdxl` 等现有 hint，**靠 ai_options 列表本身扩展**。这避免 hint 和 provider 双向映射的复杂度。

#### C.4 改 `core/brain.py`：扩 `_load_providers` + 路由

- 新增 6 个 provider entry（豆包/CodeLlama/Qwen-VL/百川/BGE/CLIP）
- 每个 entry 带 `{"name": ..., "url": ..., "key": env_var, "model": ..., "api_kind": "openai|aliyun|bge"}`
- 路由逻辑：tool_call 命中 → 查 `tool_registry[name]["provider_hint"]` → `SkillRouter.provider_for(hint)` → 拿 ai_options[id] → 调对应 provider

#### C.5 改 `core/api_server.py`：AI 选项端点

- **新端点** `GET /api/ai/options` → 返 11 个 ai_options + 当前 default
- **新端点** `PUT /api/ai/default` → 切换 default provider

#### C.6 改 Electron 设置页面

- **改** `electron/src/renderer/index.html`（设置 → AI 模型选择下拉）
- **改** `electron/src/renderer/js/settings.js`（读 `/api/ai/options` + 写 `/api/ai/default`）

#### C.7 验证

- `GET /api/ai/options` → count=11
- 切换 default → `PUT /api/ai/default` → 200
- 5 主题色弹窗下拉样式适配
- 现有 `provider_hint=main_llm` 调用**不破**
- 跑 6 个 verify_*.py 零回归

---

### 块 D · 项目文件系统整理（2.0h）

**目标**：临时文件、MD 文档、日志统一归集；制定文件管理规范。

#### D.1 创建统一目录结构

```
e:\Agent_reply\
├── tmp/                          # 新建 — 临时测试文件根目录
│   ├── tests/                    # 临时测试脚本
│   ├── data/                     # 临时测试数据
│   ├── logs/                     # 临时调试输出
│   └── README.md                 # 临时文件说明
├── docs/                         # 新建 — MD 文档根目录
│   ├── plans/                    # 计划文档（.trae/documents/* 软链或迁移）
│   ├── specs/                    # 规格文档（.trae/specs/* 迁移）
│   ├── api/                      # API 文档
│   ├── guides/                   # 用户指南
│   ├── reports/                  # 报告文档
│   ├── rules/                    # 规范文档（.trae/rules/* 迁移）
│   └── README.md                 # 文档总览
├── logs/                         # 新建 — 日志根目录
│   ├── runtime/                  # 运行日志（按 YYYY-MM-DD/）
│   ├── launcher/                 # 启动日志（launcher.log 等）
│   ├── python/                   # Python 错误日志
│   └── electron/                 # Electron 日志
├── e:\Agent_reply\                # 项目根（保留）
│   ├── core/                     # 不动
│   ├── electron/                 # 不动
│   ├── config/                   # 不动
│   ├── data/                     # 不动（运行时数据）
│   ├── skills/                   # 不动（块 B 用到）
│   ├── tools/                    # 不动
│   ├── communication/            # 不动
│   ├── knowledge/                # 不动
│   ├── memory/                   # 不动
│   ├── main.py                   # 不动
│   ├── requirements.txt          # 不动
│   └── ...
```

#### D.2 临时文件归集（`tmp/`）

**扫描根**：
- `e:\Agent_reply\*.tmp` / `*.bak` / `*.swp` / `*.pyc` / `__pycache__/`
- `e:\Agent_reply\test_*.py` / `debug_*.py`（**仅根目录**，子目录的 verify_*.py **保留**）
- `e:\Agent_reply\uploads/*.tmp`（保留 uploads/，但移走 *.tmp）
- `e:\Agent_reply\data/*.tmp`（如 data/.tmp_test_xxx → tmp/data/）

**新文件**：
- `tmp/tests/` — `test_quick_xxx.py` 类
- `tmp/data/` — `tmp_*.json` / `tmp_*.csv` / `debug_*.log`
- `tmp/logs/` — `python -c` 输出 / ipython 历史
- `tmp/README.md` — "此目录存放临时调试文件；定期清理；不进入 git"

**操作**：纯 Python 脚本 `tools/migrate_tmp_files.py` 一键扫描 + 移动（**只**移动根目录散落的；不动 verify_*.py）

#### D.3 MD 文档归集（`docs/`）

**扫描**：
- `e:\Agent_reply\.trae\documents\*.md`（**35+ 个**）→ `docs/plans/` 软链 + README 索引
- `e:\Agent_reply\.trae\specs\*.md` → `docs/specs/`
- `e:\Agent_reply\.trae\rules\*.md` → `docs/rules/`
- 根目录散落的 `*.md`（README 等） → `docs/` 根

**新文件**：
- `docs/README.md` — 文档总览 + 目录索引
- `docs/plans/README.md` — 计划文档索引
- `docs/specs/README.md` — 规格文档索引
- `docs/rules/README.md` — 规则文档索引

**操作**：
- **方案选择**：用 **软链接**（`mklink /D`）保持 `.trae/documents/` 路径兼容（已有 R3 R4 计划都引用这个路径）
- Windows PowerShell：`New-Item -ItemType SymbolicLink ...`（需管理员或开发者模式）

> **决策**：本次**只创建 `docs/` 目录 + README 索引**，不真移走 `.trae/documents/`（避免破坏计划路径引用）。下个 plan 再决定是否迁移。

#### D.4 日志归集（`logs/`）

**扫描**：
- `e:\Agent_reply\launcher.log` / `launcher-ERROR.log` → `logs/launcher/`
- `e:\Agent_reply\data/*.log` → `logs/runtime/{date}/`
- `e:\Agent_reply\.trae/logs/*.log` → `logs/python/`（如有）

**新文件**：
- `logs/runtime/.gitignore` — `*`（运行时日志不入 git）
- `logs/README.md` — 日志组织规范

**改** `start-companion.bat` / `launcher-user.bat`：
- 把 `launcher.log` 路径从 `e:\Agent_reply\` 改到 `e:\Agent_reply\logs\launcher\`
- **保持** UTF-8 / GBK 编码（已有约束）

**改** `main.py`：
- Python logging handler 路径改 `logs/python/{date}.log`
- 加 FileHandler rotation（10MB × 5）

#### D.5 文件体系全面优化

**新建** `docs/FILE_NAMING_CONVENTIONS.md`：
- 命名规范：小写 + 下划线 + 语义（例：`daily_brief_popup.html` 而非 `Brief-Popup.html`）
- 模块前缀：`core_` / `api_` / `ui_` / `db_`（按层级）
- 测试文件：`verify_` + 模块名（例 `verify_pacing_persistence.py`）
- Skill 目录：`skills/{local,data,cloud}/{name}/SKILL.md + run.py`
- 配置：`config/{persona,settings,proactive,persona_behavior}.yaml`

**新建** `docs/FILE_ORGANIZATION.md`：
- 哪些文件**禁止改动**（核心运行文件清单）
- 哪些文件**可配置**（settings.yaml / persona.yaml / proactive.yaml）
- 哪些文件**归项目所有**（核心代码 vs 临时数据）

#### D.6 文件管理规范（块 D 收尾）

**新建** `docs/FILE_MANAGEMENT_GUIDE.md`：
- 三类文件划分：
  1. **核心运行文件**（main.py / core/* / electron/src/main.js 等）— 禁止随意改动
  2. **配置文件**（config/*.yaml）— 可通过 `/api/config/yaml` 端点编辑
  3. **数据文件**（data/）— 运行时生成；可备份；不直接编辑
  4. **临时文件**（tmp/）— 定期清理；不入 git
  5. **日志文件**（logs/）— 归档；按日期查询
  6. **文档文件**（docs/）— 团队可读；可改
- 命名规范（见 D.5）
- git 策略：`.gitignore` 加 `tmp/`、`logs/`、`__pycache__/`

**改** `.gitignore`（新建/更新）：
```
tmp/
logs/
__pycache__/
*.pyc
*.tmp
*.swp
.DS_Store
```

#### D.7 验证

- `tmp/` 目录只含本次扫描的临时文件
- `docs/` 目录含 README 索引
- `logs/` 目录有子目录结构
- 启动 `start-companion.bat` → 日志写入 `logs/launcher/launcher.log` 正常
- 6 个 verify_*.py **不破**（路径不在 verify 脚本的硬编码范围内）
- Python main.py 启动后 `logs/python/{date}.log` 自动生成

---

## 二、文件总览

| 块 | 新增 | 改 | 总行数 | 估时 |
|---|---|---|---|---|
| A 日报窗口 | 2（popup + detail html）| 3（main.js / preload.js / daily-brief.html）| +220 | 1.2h |
| B Skills 50+ | 35+（33 cloud × 2 + 2 README）| 2（scaffold_skills.py / skill_loader.py）| +1500 | 2.5h |
| C AI Provider | 0 | 4（yaml / skill_router / brain / api_server + settings.js + index.html）| +200 | 1.0h |
| D 文件整理 | 5（README × 4 + migration script）| 3（bat / main.py / gitignore）| +400 | 2.0h |
| **合计** | **42** | **12** | **+2320** | **6.7h** |

---

## 三、风险与回滚

| 风险 | 概率 | 影响 | 回滚 |
|---|---|---|---|
| 日报独立窗口 30s 不弹 | 低 | 日报看不见 | 临时退回 iframe 模式（保留旧代码）|
| 50 skill 启动时阻塞 | 中 | boot 慢 5-10s | skill_loader 改 lazy-load（首次 call 才 import）|
| ai_options 切换后聊天不响应 | 中 | 选错 provider 卡死 | brain 加重试 + 降级链；新 provider 失败自动回 main_llm |
| docs/ 软链接权限失败 | 高 | 计划文档路径变化 | 退回到「只创建 docs/ 目录 + README，不动 .trae/documents」|
| logs/ 路径改动后旧脚本找不到 | 中 | launcher 报错 | bat 脚本兼容（既写 logs/ 也写根，路径都用环境变量）|
| 临时文件移动破坏 .git 历史 | 中 | git diff 乱 | 只移动根目录散落文件；不动 verify_* / docs |

---

## 四、执行顺序（严格三原则 + TRAE-security-review）

```
Round 0 · 备份 snapshot（git add -A 命名 B5-pre）  0.1h
Round 1 · 块 A 日报独立窗口                       1.2h
        ↓ 三原则 + TRAE-security-review 自检
Round 2 · 块 C AI Provider 11 个                  1.0h
        ↓ 三原则 + TRAE-security-review 自检
Round 3 · 块 B Skills 50+                         2.5h
        ↓ 三原则 + TRAE-security-review 自检
Round 4 · 块 D 文件整理                           2.0h
        ↓ 三原则 + TRAE-security-review 自检
Round 5 · 复跑 6 脚本 + 全量安全审查                0.4h
Round 6 · git commit（按块 4 次 commit）           0.2h
```

每 Round 开头**不**堆问题，直接执行；每 Round 收尾跑自检。

---

## 五、三原则铁律（每子块自检）

1. **零回归** — 6 verify 脚本 113/113 全过；tool_registry 17 skill 注册不破；5 ai_options 调用契约不破；日报 iframe 模式保留作 fallback
2. **无禁词** — 简报、欲望触发的话术、skill description 全部走伊塔短句（≤15 字）；禁词列表不变（"主人/您"）；5 主题色用 var()
3. **主题色 token 化** — 新弹窗、新 dropdown、新建所有 UI 100% 用 `var(--xxx)`；不引 emoji；用现有 SVG sprite

---

## 六、TRAE-security-review 全量预审

| 类别 | 触及点 | 处理 |
|---|---|---|
| path_traversal | `tmp/` 移动脚本 + `logs/` 路径变更 | 严格 `Path.resolve()` + 白名单目录 |
| unsafe_deserialization | 50+ skill 全部走 `yaml.safe_load` + `importlib` | 强制 safe_load；subprocess 仅在 stub 返回时调用 |
| xxe | 任何 XML 解析 | 无（markitdown 已走文本提取）|
| prompt injection | 日报 HTML 详情页 + skill description | system prompt "只总结"；HTML 走 Jinja2 autoescape |
| ssti | 日报 HTML 模板 | Jinja2 sandbox；不调 LLM 出 HTML |
| auth_bypass | AI provider 切换 | 单用户本地，无 AuthN；provider key 走 env |
| weak_crypto | 无新增 | — |
| ssrf | 50 skill 全部 stub；无网络 | stub 返 `credential_missing`；真实实现时再加白名单 |
| resource_exhaust | 50+ skill 启动时 import | skill_loader 改 lazy-load（首次 call 才 import run.py）|
| html_injection | 日报详情页 5 section 内容 | 走 Jinja2 autoescape；LLM 输出 Markdown 转 HTML 时也走 escape |
| window_security | 独立 BrowserWindow | `contextIsolation: true` / `nodeIntegration: false`（沿用）|

**预审结论**：无新发现高危面；所有点已写明处理。

---

## 七、验收清单（Round 5 复跑）

```bash
# 块 A
- 启动 → 8s 后独立窗口弹
- 09:00 cron → 弹（手动触发 morning_brief_9am scene）
- 点击「展开完整日报」→ 1280×800 详情窗口
- 反馈按钮 POST /api/brief/feedback 工作
- 5 主题色自适应

# 块 B
- python tools/scaffold_skills.py → 50 个目录
- GET /api/skills/list → count=50
- POST /api/skills/{name}/call → 返 stub
- 现有 17 skill 调用不破

# 块 C
- GET /api/ai/options → count=11
- PUT /api/ai/default → 200
- 设置页面下拉切到 codellama → 聊天走 CodeLlama
- 5 主题色 dropdown 自适应

# 块 D
- ls tmp/ → 只含临时文件
- ls docs/ → 含 4 个 README
- ls logs/ → 含 4 个子目录
- start-companion.bat → 日志写 logs/launcher/
- main.py 启动 → logs/python/{date}.log 自动生成
- .gitignore → 含 tmp/ logs/ __pycache__/

# 全量
- python -X utf8 -m pytest verify_*.py  # 6 个 113/113 通过
- npm run check:emojis  # 无 emoji 回归
- bash tools/security-audit.sh  # TRAE-security-review 全过
```

---

## 八、待确认（执行前最后 1 题）

- [ ] **块 A 日报独立窗口 = 360×640 弹窗 + 1280×800 详情页**（双窗口）— 接受？
- [ ] **块 B Skills = 17 现有 + 33 新增 = 50 个**（cloud/ 新分类）— 接受？
- [ ] **块 C AI Provider = 5 现有 + 6 新增 = 11 个**（豆包/CodeLlama/Qwen-VL/百川/BGE/CLIP）— 接受？
- [ ] **块 D 文件整理 = 创建 `tmp/` `docs/` `logs/` 3 目录 + 命名规范 + 规范文档**（.trae/documents/ 暂保留）— 接受？

如全部「是」即开始执行；任何「调整」请直接指出。
