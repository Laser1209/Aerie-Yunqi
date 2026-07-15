# Aerie · 云栖 v9.0 → 下一步实施计划

> **生成时间**: 2026-07-16
> **安全审查范围**: v9.0 全量 70 文件 (68b295a...HEAD, 3 commits)
> **审查结果**: 1 低风险发现（记录技术债务），无高危漏洞

---

## 1. 安全审查报告

### 1.1 审查结论

审查了 diff 覆盖的全部 70 个文件，涵盖 Python 后端（main.py、core/、communication/、tools/）、Electron 前端（src/）、配置文件等。

**✅ 无高危漏洞。** 发现 1 个低风险防御性改进项（已按用户要求记录为技术债务，延后处理）。

### 1.2 安全基线性状

| 类别 | 现状 | 评估 |
| --- | --- | --- |
| SQL 注入 | 全部使用参数化查询 (`?` 占位符 + `db.query(sql, params)`) | ✅ 安全 |
| YAML 加载 | 全局使用 `yaml.safe_load()` | ✅ 安全 |
| 子进程调用 (task_scheduler) | 使用 `subprocess.run(["powershell", ...])` 列表参数 | ✅ 安全 |
| API 暴露 | `aiohttp` 绑定 `127.0.0.1:7890`，仅本地 | ✅ 安全 |
| API Key 管理 | `.env` + `dotenv`，已 gitignore | ✅ 安全 |
| `.env.example` | 仅占位符，无真实密钥 | ✅ 安全 |
| Electron | `contextIsolation: true`，`nodeIntegration: false` | ✅ 安全 |
| IPC 桥 | `contextBridge.exposeInMainWorld`，窄 API 暴露 | ✅ 安全 |

### 1.3 发现的低风险项 (记录为技术债务)

| # | 类别 | 标题 | 严重度 | 置信度 | 证据 (Source → Sink) | 建议 | 位置 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | command_injection | `_tool_close_application` 使用 `shell=True` 拼接 LLM 生成的应用名 | LOW | 0.82 | QQ 消息 → LLM prompt → tool_call `name` 参数 → `_run_shell(f"taskkill /IM {name}.exe /F")` | 添加应用名白名单过滤（仅允许 `[a-zA-Z0-9._-]+`），或改用 `subprocess.Popen` 列表参数 + 绝对路径 | [`tools/__init__.py:(122, 124)`](file:///e:/Agent_reply/tools/__init__.py#L122-L124) |

> **降级理由**: LLM 作为中间层对用户输入做了语义转换，直接利用链需要 LLM 忠实地复现注入 payload，置信度 0.82。用户选择延后处理。

### 1.4 其他检查项（均通过）

- `core/database.py` — `insert()` 方法使用 `?` 占位符；`query()` 使用参数化查询
- `core/api_server.py` — 全部 28 个端点绑定 `127.0.0.1`
- `core/providers/` — 3 个 Provider 均从 `os.getenv()` 取 key，不硬编码
- `core/backup.py` — zipfile 操作无路径遍历风险（内部 glob 固定目录）
- `electron/src/main.js` — `spawn()` 使用数组参数；`shell.openExternal()` 仅限 IPC 调用
- `electron/src/preload.js` — `contextBridge` 仅暴露 5 个安全方法
- `tools/__init__.py` — `_tool_open_application` 使用 `subprocess.Popen(name)`（非 shell 模式，安全）
- `tools/__init__.py` — `_tool_play_local_music` 使用 `os.startfile(path)`（仅打开文件，不执行命令）

---

## 2. 项目当前状态

### 2.1 已完成 (v9.0.0)

| 模块 | 状态 |
| --- | --- |
| Python 后端核心（main.py / companion / brain / pipeline） | ✅ 完成 |
| LLM Provider ×3（Qwen / DeepSeek / Gemini） | ✅ 完成 |
| 情感引擎（PAD + 累积阈值 + 状态机） | ✅ 完成 |
| 消息通信层（QQ WS / 路由 / 发送队列 / 分段 / 撤回） | ✅ 完成 |
| 主动推送系统（9 场景 + Cron + 频控） | ✅ 完成 |
| 工具系统（14 工具注册 + Function Calling） | ✅ 完成 |
| 数据层（SQLite 9 表 + CRUD + Token 统计） | ✅ 完成 |
| 基础设施（备份 / 自愈 / UAC / Task Scheduler / HTTP API 28 端点） | ✅ 完成 |
| Electron 前端（主窗口 / 悬浮球 / 托盘 / IPC / 5 主题） | ✅ 完成 |
| Electron 打包（便携版 .zip / 安装版 NSIS） | ✅ 完成 |
| 配置体系（settings.yaml / persona.yaml / proactive.yaml） | ✅ 完成 |
| LLM API Key 验证（deepseek / minimax / bigmodel / siliconflow / openai-proxy） | ✅ 完成 |

### 2.2 LLM Provider 覆盖

| Provider | API Key | Model | 端到端验证 | Provider 类 |
| --- | --- | --- | --- | --- |
| DeepSeek | ✅ | `deepseek-chat` | ✅ PASS 2.9s | ✅ `core/providers/deepseek.py` |
| MiniMax | ✅ | `MiniMax-M3` | ✅ PASS 3.8s | ❌ 未创建 |
| BigModel (GLM) | ✅ | `glm-4-plus` | ✅ PASS 2.4s | ❌ 未创建 |
| SiliconFlow (Gemma) | ✅ | `google/gemma-4-26B-A4B-it` | ✅ PASS 2.75s | ❌ 未创建 |
| OpenAI 代理 (GPT) | ✅ | `gpt-5.5` | ✅ PASS 2.33s | ❌ 未创建 |
| Qwen (DashScope) | placeholder | `qwen-plus` | ⏭️ SKIP | ✅ `core/providers/qwen.py` |
| Gemini | placeholder | `gemini-2.0-flash-exp` | ⏭️ SKIP (网络不通) | ✅ `core/providers/gemini.py` |

### 2.3 能力缺口

| 模块 | 现状 |
| --- | --- |
| **NapCat DLC ×11** | 全部未实现（当前仅纯文本收发） |
| **LLM Provider ×4** | API key 已验证，Provider 类未创建（`core/providers/` 缺少 minimax / bigmodel / siliconflow / openai_proxy） |
| **前端体验** | 基础框架完成，数据对接和可视化待做 |
| **知识库全文搜索** | 当前仅关键词匹配（规划 v9.5） |
| **Live2D** | 规划 v10.0 |

---

## 3. 实施计划

### 3.1 优先级排序

```
Priority 1 (本周)  │  NapCat DLC Phase A  │  基础通信能力拓展（MarkDown / Poke / 声聊）
Priority 2 (本周)  │  LLM Provider 补全    │  4 个新 Provider 类 (≈2h)
Priority 3 (下周)  │  前端体验完善        │  悬浮球优化 / 数据面板
Priority 4 (v9.5)  │  知识库增强           │  全文搜索
```

### 3.2 任务分解

---

## Task 1: NapCat DLC Phase A — P1 基础接入 (优先级最高)

**目标**: 当前 QQ 通信仅支持纯文本。完成 3 项 P1 能力接入，使伊塔可以使用富文本、互动和语音。

### 1.1 MarkDown 消息 (1-2h)

**改动文件**:
- `communication/message.py` — 新增 `OutgoingReply.render_mode: str = "text"` 字段（text/markdown）
- `communication/qq_client.py` — `send_message()` 支持 MarkDown 分支：当 `reply.render_mode == "markdown"` 时，修改 message segment 构造为 `{"type": "markdown", "data": {"content": content}}`
- `core/pipeline.py` — `_handle_full()` 在 `_color_reply` 后，对特定场景（如系统状态查询）设置 `render_mode="markdown"`
- `communication/send_queue.py` — `QueuedMessage` 新增 `render_mode` 透传字段

**验证**: 发送 `/api/chat/send` 测试消息 "查询系统状态"，验证 QQ 侧显示格式化 MarkDown 消息

### 1.2 发送 Poke (0.5h)

**改动文件**:
- `communication/qq_client.py` — 新增 `async def send_poke(self, user_id: int) -> bool` 方法，调用 OneBot11 的 `friend_poke` action
- `tools/__init__.py` — 新增 `_tool_poke_user` 工具函数，注册为 `poke_user`
- `communication/recall_manager.py` — 当用户超过 5 分钟未回应时，触发 poke 联动

**验证**: 通过测试消息 "伊塔戳我一下" 触发 poke，验证 QQ 端收到戳一戳

### 1.3 AI 声聊 (3-5h)

**改动文件**:
- **新建** `voice/tts_engine.py` — TTS 引擎类，调用 MiniMax TTS API 生成音频
- **新建** `voice/silk_encoder.py` — PCM/WAV → Silk v3 编码器（NapCat 语音消息要求 Silk 格式）
- `communication/qq_client.py` — `send_message()` 新增语音分支：检测 `reply.content_type == "voice"` 时，使用 NapCat 的 `send_record` action 发送本地语音文件
- `communication/message.py` — `OutgoingReply` 新增 `content_type: str = "text"` 字段
- `tools/__init__.py` — 新增 `_tool_send_voice` 工具函数，注册为 `send_voice`

**验证**: 发送消息 "伊塔发条语音"，验证 QQ 端收到语音消息

> **依赖**: 需要 NapCat 已启动 (`ws://127.0.0.1:3001`)，需要 FFmpeg 在 PATH 中（Silk 编码）

---

## Task 2: LLM Provider 补全 (约 2h)

**目标**: `.env` 中已有 4 个新 Provider 的 API Key 且全部通过端到端验证，补全 `core/providers/` 下的实现类。

### 2.1 新建 4 个 Provider 文件

每个文件遵循 `core/providers/qwen.py` 的模板模式（OpenAI 兼容 SDK + 环境变量回退）：

| 文件 | Provider 类 | `.env` 前缀 | base_url | model |
| --- | --- | --- | --- | --- |
| **`core/providers/minimax.py`** | `MinimaxProvider` | `MINIMAX_*` | `api.minimaxi.com/v1` | `MiniMax-M3` |
| **`core/providers/bigmodel.py`** | `BigModelProvider` (Zhipu GLM) | `BIGMODEL_*` | `open.bigmodel.cn/api/paas/v4/` | `glm-4-plus` |
| **`core/providers/siliconflow.py`** | `SiliconFlowProvider` | `SILICONFLOW_*` | `api.siliconflow.com/v1` | `google/gemma-4-26B-A4B-it` |
| **`core/providers/openai_proxy.py`** | `OpenAIProxyProvider` | `OPENAI_*` | `api.codexgood.com/v1` | `gpt-5.5` |

**每个 Provider 类的模板**:
```python
class XxxProvider(Provider):
    name = "xxx"
    def __init__(self, api_key=None, base_url=None, model=None, timeout=30.0):
        api_key = api_key or os.getenv("XXX_API_KEY", "")
        base_url = base_url or os.getenv("XXX_BASE_URL", "https://...")
        model = model or os.getenv("XXX_MODEL", "...")
        super().__init__(api_key=api_key, base_url=base_url, model=model, timeout=timeout)
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)

    async def complete(self, messages, tools=None, temperature=0.7, max_tokens=None, **kwargs):
        # ... 同 qwen.py 模式
```

### 2.2 注册到 Brain

**改动文件**: `core/brain.py`
- `_default_providers()` 方法新增 4 个 Provider 的构造尝试（try/except + append）
- 建议注册顺序: Qwen → DeepSeek → MiniMax → BigModel → SiliconFlow → Gemini → OpenAI-Proxy

### 2.3 更新 `.env.example`

在 `.env.example` 中已有的占位符基础上，补充每个 Provider 的已知可用模型清单注释。

### 2.4 验证

```powershell
python scripts/probe_llm_providers.py  # 验证全部 7 个 Provider
```

---

## Task 3: 前端体验完善 (v9.1-v9.3, 下周)

### 3.1 悬浮球交互细节优化
- 拖拽记忆位置（写入 `userData/config.json`）
- 状态动画（伊塔情绪对应的颜色/动效变化）
- 边缘吸附 + 呼吸动效

### 3.2 侧边栏数据对接
- Token 统计面板（消费 `GET /api/token/usage` + `GET /api/model/calls`）
- 情绪仪表盘（消费 `GET /api/emotion/current` + `GET /api/emotion/panel`）
- 系统状态面板（消费 `GET /api/status/all`）
- 聊天记录预览（消费 `GET /api/chat/history`）

### 3.3 纪念功能
- 对接 `GET /api/memorial/list` + `GET /api/memorial/anniversary`

---

## 4. 依赖与前置条件

| 依赖 | 状态 |
| --- | --- |
| Python 3.14.3 + 依赖 (`pip install -r requirements.txt`) | ✅ |
| NapCat QQ 启动 (`ws://127.0.0.1:3001`) | 需要启动 |
| `.env` 中 5 个 Provider Key 全部可用 | ✅ |
| FFmpeg (声聊 Silk 编码, Task 1.3) | 需要 `winget install FFmpeg` |
| MiniMax API Key (TTS, Task 1.3) | ✅ |

---

## 5. 验证清单

### 5.1 NapCat DLC Phase A
- [ ] `POST /api/chat/send` 触发 MarkDown 响应 → QQ 端显示格式化消息
- [ ] 工具调用 `poke_user` → QQ 端收到 "伊塔 戳了戳你"
- [ ] 工具调用 `send_voice` → QQ 端收到语音消息（含伊塔声线）

### 5.2 LLM Provider
- [ ] `GET /api/llm/providers` 返回 7 个 Provider（Qwen/DeepSeek/MiniMax/BigModel/SiliconFlow/Gemini/OpenAI-Proxy）
- [ ] `python scripts/probe_llm_providers.py` 全部 PASS

### 5.3 端到端
- [ ] Electron 启动 → 悬浮球可见 → 托盘图标可见
- [ ] 主窗口 5 主题切换正常
- [ ] NapCat 消息收发正常（含 MarkDown + Poke + 语音）

---

## 6. 风险与注意事项

| 风险 | 缓解 |
| --- | --- |
| NapCat PacketBackend 兼容性（不同版本 OneBot 协议差异） | 使用 `packetBackend: "auto"` 默认配置，MarkDown/poke 字段名参考 NapCat 最新文档 |
| FFmpeg 未安装导致 Silk 编码失败 | 声聊模块启动时检测 FFmpeg 可用性，缺失时降级为纯文本提示 |
| MiniMax TTS 配额耗尽 | 实现 TTS 失败时的优雅降级（纯文本回复 + 日志告警） |
| 4 个新 Provider 与 Qwen 模式不兼容 | 所有新 Provider 均为 OpenAI 兼容 API（已通过 `probe_llm_providers.py` 验证），无兼容风险 |

---

## 7. 技术债务 (延后处理)

| 项 | 说明 | 预估 |
| --- | --- | --- |
| `_tool_close_application` shell 注入 | `tools/__init__.py:122-124`，添加应用名白名单 `[a-zA-Z0-9._-]+` | 10min |
| 知识库全文搜索 | 当前仅 `LIKE '%keyword%'` 关键词匹配，需引入嵌入向量或 FTS5 | 1d |
| API 认证 | 当前 28 个 HTTP 端点无鉴权（仅 localhost），未来若有远程需求需加 Token/JWT | 待定 |
