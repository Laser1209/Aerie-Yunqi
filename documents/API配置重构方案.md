# API 保存与 Key 管理重构方案

> 适用范围：Aerie Companion 设置页「AI 服务配置」（API Key、自定义 API、功能点路由）及全部 AI 调用链。
> 变更时间：2026-06；对应代码：`core/ai_services.py`（新增）、`core/api_server.py`、`core/llm_caller.py`、`core/companion.py`、`core/self_evolve_proposer.py`、`core/typo_corrector.py`、`core/memory_validation.py`、`electron/src/renderer/js/settings.js`、`electron/src/renderer/index.html`。

## 1. 背景与根因

### 1.1 现象
新增自定义 API 保存后，关闭并重启应用，出现厂商与模型串配（如 DeepSeek 卡片显示 `grok-4.5`），自定义厂商不生效。

### 1.2 根因（六点，均已修复）
| 编号 | 根因 | 后果 |
|---|---|---|
| R1 | 功能点映射与厂商卡片共用同一 env 变量（`main_chat → DEEPSEEK_MODEL`） | 自定义模型名写进内置厂商 env，重启后串配 |
| R2 | 自定义厂商以 `AERIE_CUSTOM_PROVIDERS`（JSON 塞 .env 单行）存储，运行时 `LLMCaller` 完全不消费 | 保存不生效、无热加载 |
| R3 | JSON 裸写 .env 无引号，python-dotenv 遇 ` #` 截断、`${FOO}` 插值清空 | 重启后数据被静默破坏 |
| R4 | 自研 `_read_env_file()` 与 python-dotenv 双解析器语义不一致 + 全量重写 | 任何一次保存都可能污染全文件 |
| R5 | 无重名校验、脱敏值仅靠前端拦截 | 与内置厂商重名、`••••` 占位值被当真 Key |
| R6 | 自定义卡片只读，只能「全量数组 + 空 Key 占位」覆盖式保存 | 编辑即丢 Key，且覆盖其他记录 |

结论：**不是单点 bug，是「把结构化数据塞进 .env + 功能点与厂商耦合」的架构缺陷**。

## 2. 目标架构

```
.env（仅内置厂商凭证，写入走 SET 精确更新）
        │
data/ai_services.json（结构化真源：自定义厂商 / 功能点绑定 / 最近 check）
        │
data/provider_checks.jsonl（连通性审计，只追加）
        │
core/ai_services.py（唯一解析层：注册表 + 存储 + 端点解析 + 小流量探测）
        │
core/llm_caller.py（构建调用链时注入自定义厂商、按绑定置顶/覆盖模型）
```

### 2.1 功能点（Role）与 Key 的对应关系
| 功能点 key | 含义 | 默认绑定 | 运行时消费点 |
|---|---|---|---|
| `main_chat` | 主对话大脑 | deepseek / deepseek-chat | `LLMCaller._load_providers()` 链首置顶 |
| `subagent` | 子 Agent（ReAct 工具调用） | aerie-ws / qwen3.7-flash | `chat(tools=...)` 工具链首位 |
| `subagent_code` | 代码自进化模型 | aerie-ws / kimi-k2.7-code | `SelfEvolveProposer` |
| `light_assist` | 轻量任务（问候、纠错、记忆校验、生图语义接力） | siliconflow-light / 模型取 env | typo_corrector、memory_validation、companion 生图三处、brief greeting |

专用服务（语音识别 ASR / 生图 / TTS）不在绑定范围，只读展示，凭证仍在各自厂商卡片配置。

### 2.2 厂商注册表
`_PROVIDER_REGISTRY` 内置 9 个厂商 + 2 个虚拟厂商（`aerie-ws` 多 Key 轮询池、`siliconflow-light` 轻量通道）。自定义厂商 id 为 `cp_xxx`，在调用链中名为 `custom:{id}`。

## 3. 后端实现

### 3.1 存储（`core/ai_services.py`）
- `AiServicesStore`：原子写（`.tmp` + `os.replace`）、mtime 检测自动 reload、线程锁。
- 自定义厂商：`prepare_custom_provider()`（校验+归一化，**不落盘**）→ 外部连通性测试通过 → `commit_custom_provider()` 落盘。编辑时空 Key 保留原 Key。
- 校验：拒脱敏占位（`•·*●`）、名称与内置/自定义重名（大小写不敏感）、URL 必须 http(s)、`max_tool_calls` 钳制 1–50。
- 绑定：`validate_binding()` 纯校验；`set_binding()` 落盘。
- 审计：`record_check()` 同步更新 JSON 内最近状态并向 `data/provider_checks.jsonl` 追加一行。
- 解析：`resolve_provider(provider, model)` / `resolve_role(role)` 返回 `Endpoint(name, base_url, model, api_key/keys, supports_tools, available)`；`role_preference(role)` 返回 `(preferred_provider, model_override)` 供调用点直接使用。

### 3.2 API 端点（`core/api_server.py`）
| 方法/路径 | 行为 |
|---|---|
| GET `/api/env/providers` | 内置厂商卡片数据（脱敏），每条带最近 `check` |
| POST `/api/env/save` | 内置厂商精确写入 .env（拒脱敏值），保存后跑 `/models` 探测并热加载，返回 check |
| GET `/api/env/custom-providers` | 自定义厂商列表（Key 脱敏 + check） |
| PUT `/api/env/custom-providers` | **先测后存**：prepare → 小流量 chat/models 探测 → 失败返回 422 且不写盘；`force=true` 可强存 |
| DELETE `/api/env/custom-providers/{id}` | 删除；引用它的绑定自动重置为默认绑定 |
| GET `/api/env/bindable-providers` | 当前已配齐凭证、可在功能点路由下拉中选择的厂商 |
| GET `/api/env/model-roles` | 4 个功能点绑定 + check + 专用服务只读信息 |
| POST `/api/env/model-roles` | 先全量纯校验 → 逐功能点 `max_tokens=1` chat 探测 → 全过（或 force）才提交，check 记录到 `binding:{role}`，热加载 |
| POST `/api/env/provider-check` | 只测不存（内置或临时 custom 参数） |

热加载：写盘后 `os.environ.update()` 并 `get_companion().brain = LLMCaller()`，无需重启。

### 3.3 运行时接线（`core/llm_caller.py`）
- 建脑时快照功能点绑定；`_load_providers()` 末尾注入全部自定义厂商（含 `supports_tools`、`max_tool_calls`）。
- `main_chat` 绑定目标以**绑定模型**复制后置顶；未配置/失效的绑定不改变容灾顺序。
- `aerie-ws`、`siliconflow-light` 条目的模型名由对应绑定决定，绑向别处时回退 env。
- `chat()` 新增 `model_override`：仅作用于本次被提升的 `preferred_provider` 副本，不污染共享链。
- 工具调用（子 Agent）重排时，把 `subagent` 绑定目标（须 supports_tools）置于工具链首位。
- 其余功能点统一经 `role_preference()` 解析：typo_corrector、memory_validation、companion 生图三处、SelfEvolveProposer（支持绑定到自定义/多 Key）。

## 4. 前端实现（设置页）

- **内置厂商卡片**：状态位展示最近连通性（`连通正常 123ms` / `测试失败(401)`，hover 看详情）；按钮统一为「测试并保存」，保存后状态栏区分成功/失败原因。
- **自定义 API 卡片**：可编辑（回填名称/URL/模型/tools/上限，Key 留空表示不变）、可删除（删除前确认，提示绑定会重置）；表单新增「支持函数调用」勾选，删除无效的 KV 文本域。
- **自定义 API 保存**：PUT 单条，先测后存；422 时弹窗可「强制保存」（force 重发）。
- **功能点路由面板**（原「功能点映射」）：每个功能点一行 = 厂商下拉（仅列已配置厂商）+ 模型输入 + 实时测试状态点；底部只读展示 ASR/生图/TTS 专用服务当前模型。保存时整批小流量测试，任一失败可选择强制保存。
- 前端只用既有通用桥 `window.aerie.api.request`，无需改 preload。

## 5. 数据迁移与兼容

- 按项目约定**不做向后兼容**：旧 `AERIE_CUSTOM_PROVIDERS` 键已从 `.env` 删除；被串改的 `DEEPSEEK_MODEL` 已修正为 `deepseek-chat`。
- 旧自定义厂商需要在 UI 重新添加一次（新存储要求显式重名校验与 tools 能力声明）。
- 首次访问任意新端点时自动创建 `data/ai_services.json`（含默认绑定）；文件损坏时静默回退默认值，下次成功写盘即修复。

## 6. 用户操作指南

1. **添加厂商**：「＋ 添加模型」→ 选厂商或「自定义 API」→ 填 Key/URL/模型 →「测试并保存」。失败会明确提示 HTTP 状态与原因，不会写入坏配置。
2. **分配用途**：点「功能点路由」→ 为对话/子Agent/代码/轻量任务各选一个厂商与模型 →「测试并保存」。四个探测全部通过才生效。
3. **修改/删除**：自定义卡片点「编辑」或「移除」；删除后引用它的功能点自动回到默认厂商。
4. **验证结果**：所有探测结果落 `data/provider_checks.jsonl`，卡片与路由面板的状态点展示最近一次结果。

## 7. 测试

| 文件 | 覆盖 |
|---|---|
| `tests/test_ai_services_store.py` | 存储 CRUD、先 prepare 后 commit、脱敏/重名/URL/钳制校验、绑定、check 审计、端点解析 |
| `tests/test_api_provider_config.py` | PUT 先测后存/422 不写盘/force、编辑保 Key、DELETE 重置绑定、model-roles 全批校验与 force、脱敏拒绝、bindable 列表、只测端点 |
| `tests/test_llm_caller_bindings.py` | 自定义注入链、main_chat 置顶与模型覆盖、light 绑定模型、per-call model_override、subagent 工具链置顶 |
| `electron/tests/ai-services-settings.test.js` | 前后端契约（PUT/DELETE/bindable/model-roles/force、UI 按钮与面板） |

回归结果：新增后端 26 例、前端 6 例全部通过；全量后端 2167 passed（2 个与本次无关的存量问题：`test_inbound_message_records_event_engine_activity` 缺 `source` 属存量测试桩问题；`test_file_management_tools` 单独运行通过，为顺序相关 flake）；electron 全套 172 passed。

## 8. 设计决策备注（ADR 摘要）
- 结构化数据绝不进 `.env`：自定义厂商/绑定/check 全部 JSON 文件化，从根上消除双解析器与全量重写风险。
- 功能点与厂商解耦：一个厂商一张卡（配 Key），功能点只做「指向厂商+模型」的绑定，消除串配。
- 先测后存 + 可强制：默认安全（坏配置不落盘），但保留用户在特殊网关（403/非标准 /models 实现）下的强制保存出口。
- 绑定仅在调用点生效，未配置时保持原有容灾链行为，核心对话稳定性不受影响。
