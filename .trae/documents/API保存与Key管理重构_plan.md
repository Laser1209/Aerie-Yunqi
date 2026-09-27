# API 保存修复与 Key 管理架构重构 · 实施计划

> 范围：设置页「API Key」标签页（AI 服务配置 / 添加模型 / 自定义 API / 功能点映射）的保存、持久化、运行时接入与按功能点独立管理。
> 日期：2026-09-25 ｜ 状态：待评审

***

## 1. 问题复现与根因（已取证）

### 1.1 现象

* 新增「自定义 API」保存后，**关闭并重启应用出现 API 数据错误合并/串配**（截图实证：DeepSeek 厂商卡片的模型字段显示 `grok-4.5`；自定义厂商名为 "Grok"，Base URL 却是 OpenAI 代理地址）。

* 自定义 API 保存后实际**不参与任何模型调用**（见根因 2）。

### 1.2 根因清单

| #  | 根因                                                                                                                                                                                | 证据                                                                                                                          |
| -- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| R1 | **功能点映射与厂商卡片共用同一批 env 变量**。`main_chat → DEEPSEEK_MODEL`，功能点面板和 DeepSeek 卡片都写 `DEEPSEEK_MODEL`，功能点选了 grok-4.5 后 DeepSeek 卡片模型被串改，且运行时拿着 `grok-4.5` 模型名请求 `api.deepseek.com` 必然 400 | `core/api_server.py:5824-5835`、`.env:14 DEEPSEEK_MODEL=grok-4.5`                                                            |
| R2 | **自定义 Provider 只有持久化、没有运行时接入**。全项目仅 `api_server.py` 与 `settings.js` 读写 `AERIE_CUSTOM_PROVIDERS`，`LLMCaller._load_providers()` 完全不消费它，保存后既不生效也不热加载                                 | grep 全仓仅 2 文件 13 处；`core/llm_caller.py:144-315` 无 custom 分支；保存端点 `api_server.py:6126-6170` 无 `os.environ.update`、无 brain 重建 |
| R3 | **结构化 JSON 裸写进** **`.env`** **单行、不加引号**，重启经 python-dotenv 解析时：值内含  ` #`（空白+井号）被当行内注释截断；`${FOO}` 被变量插值清空。实测两种 case 均解析损坏。当前存量数据侥幸不含特殊字符，属潜伏数据损坏点                                   | `api_server.py:5968-5972`；探针实测：`Grok #1` → `'[{"name": "Grok'`，`sk-${FOO}` → `sk-`                                          |
| R4 | **双解析器语义不一致**。设置 API 用自研 `_read_env_file()`（不剥引号、不认注释），运行时用 python-dotenv（认引号/注释/插值）；保存又是「读全量→改一键→整文件重写」，任何一条脏数据会波及全部厂商配置                                                         | `api_server.py:5884-5922` vs `main.py:101-109`                                                                              |
| R5 | **无去重/无服务端校验**。自定义厂商允许与内置厂商同名同 Key（存量 "Grok" 与内置 GROK 重复）；脱敏串 `••••xxxx` 只靠前端比对拦截，后端收到即当真 Key 落盘                                                                                  | `settings.js:820` 仅前端判断；`api_server.py:6134-6159` 无重名校验、无脱敏值拒绝                                                              |
| R6 | **自定义厂商卡片只展示不可编辑**（只能移除），Key 轮换/改错 URL 必须删了重建，迫使前端用「全量数组 + 空 key 占位」的合并式保存，放大错误合并面                                                                                                | `settings.js:497-518`、`726-733`                                                                                             |

### 1.3 结论

不是单点 bug，而是**架构层缺陷**：凭证（.env）、功能点路由（env 变量复用）、自定义厂商（JSON 塞 env）三种关注点被压在同一条 `.env` 链路上，且自定义厂商未接入运行时。修数据/补判断无法根治，必须按「凭证 / 厂商目录 / 功能点绑定 / 连通验证」四件事拆开。

***

## 2. 影响面分析（前端改动前置排查，已完成）

* **后端 API 契约**：`GET/POST /api/env/providers`、`/api/env/save`、`/api/env/custom-providers`、`/api/env/model-roles`、`/api/env/feature-apis` 位于 `core/api_server.py:5788-6260`。本次重构前 4 个端点的请求/响应结构，新增 1 个测试端点；功能 API 端点不动。

* **运行时调用点（功能点→凭证现状）**：

  * 主对话：`llm_caller.py:144-315` 按内置顺序拼 provider 链；`provider_router.py:308-355` 复杂度路由。

  * 通用子 Agent：Aerie WS，`AERIE_WS_MODEL`（llm\_caller:301-310）。

  * 代码子 Agent：`AERIE_WS_CODE_MODEL`（`self_evolve_proposer.py:63`）。

  * 轻量辅助：`SILICONFLOW_LIGHT_MODEL`（llm\_caller:288-297、`typo_corrector.py:32-33`、companion 生图提示词接力走 `siliconflow-light` provider 名）。

  * ASR：`qq_media.py:174-178`（SF 主/Aerie WS）、`multimodal_input.py:324`（DashScope 备）。

  * 生图：`llm_caller.py:2001-2020, 2133-2146`（`IMAGE_GEN_*`，图生图同入口）。

  * TTS：`voice/tts_engine.py:30-68`（MiniMax）。

  * 识图：`image_service.py:445-492` → brain.see\_image（走主 provider 链视觉模型）。

* **Electron preload 桥**：前端全部走通用 `window.aerie.api.request`，**无需改 preload**。

* **事件流/SSE**：不涉及事件结构变更；热加载仍重建 `companion.brain`。

* **数据库 / settings.yaml**：不动表结构、不动 settings.yaml。新配置文件落 `data/`（已 gitignore，密钥不进库）。

* **前端**：仅 `electron/src/renderer/js/settings.js` 与 `index.html` API Key 标签页 DOM；不动 chat.js。

* **启动链路**：`main.py` dotenv 加载保留（内置厂商凭证仍在 .env）；新配置存储自带文件，不经 dotenv。

***

## 3. 目标架构

一句话：**凭证归凭证、厂商归厂商目录、功能点只做「provider + model」绑定、保存即验。**

### 3.1 存储设计

* `data/ai_services.json`（新，单一结构化文件，原子写：tmp + `os.replace`）：

```json
{
  "version": 1,
  "custom_providers": [
    {"id": "cp_xxx", "name": "TokenDance", "base_url": "https://.../v1",
     "api_key": "sk-...", "model": "gpt-4o", "supports_tools": false,
     "max_tool_calls": 8}
  ],
  "bindings": {
    "main_chat":     {"provider": "deepseek", "model": "deepseek-chat"},
    "subagent":      {"provider": "aerie-ws", "model": "qwen3.7-flash"},
    "subagent_code": {"provider": "aerie-ws", "model": "kimi-k2.7-code"},
    "light_assist":  {"provider": "siliconflow", "model": "Qwen/Qwen3-30B-A3B-Instruct-2507"}
  },
  "checks": {
    "deepseek": {"ok": true, "http_status": 200, "latency_ms": 312,
                 "scope": "models", "checked_at": "2026-09-25T18:00:00", "detail": ""}
  }
}
```

* `data/provider_checks.jsonl`（新，只追加审计日志）：每次「保存即测」追加一行，含目标 provider/模型/耗时/结果/错误，即用户要求的「结果保存至指定位置」。

* **内置 8 厂商凭证（key/base\_url/默认 model）继续存** **`.env`**：密钥存储位置不变、不迁移；自定义厂商从 `.env` 彻底移出，删除 `AERIE_CUSTOM_PROVIDERS` 读写链路（不做兼容层、不做 migration）。存量脏键 `.env:116` 在实施时直接删除，存量自定义条目（与内置 Grok 重复）由用户在新 UI 重新添加。

* ASR / 生图 / TTS 的专用 env（`AERIE_WS_ASR_MODEL`、`IMAGE_GEN_*`、MiniMax TTS）本期保留为各专用服务配置，不强行通用化；其模型名在 UI 上以只读「专用服务」卡片展示。

### 3.2 功能点绑定（与凭证解耦）

* 新增 `core/ai_services.py`（单一职责模块）：

  * `AiServicesStore`：加载/原子写/热 reload（mtime 检测 + 保存后显式 `reload()`）/校验。

  * `resolve(role) -> Endpoint(provider, base_url, api_key, model, supports_tools, max_tool_calls)`：内置厂商凭证从 env meta 解析，自定义厂商从 JSON 解析。

  * `list_bindable_providers()`：供 UI 下拉（已配置内置厂商 + 自定义厂商，aerie-ws 标注多 Key 池）。

* 可绑定功能点（本期开放）：`main_chat` / `subagent` / `subagent_code` / `light_assist`，provider 可任选已配置的 OpenAI 兼容厂商（内置或自定义），model 自由填写或从厂商 models 列表选。

* **功能点保存不再写** **`DEEPSEEK_MODEL`** **等 env 变量**，R1 串配根除。内置卡片上的「模型」字段回归为「该厂商默认模型」，仅供未被绑定时的链路默认值使用。

* 主对话链路：`LLMCaller` 启动时读 binding，把绑定的 provider 用绑定模型置于链首（需要 provider dict 支持 per-call model 覆盖，`chat()` 增加 `model_override`，由调用处按 binding 传入），其余厂商维持现有健康主备链。

* 子 Agent / 代码 / 轻量调用点改从 `resolve(role)` 取 endpoint（替换 `os.getenv("AERIE_WS_MODEL" / "AERIE_WS_CODE_MODEL" / "SILICONFLOW_LIGHT_MODEL")` 直读），涉及 `llm_caller.py`、`self_evolve_proposer.py:63`、`typo_corrector.py:32-33`、companion 生图提示词接力取 provider 处（实施时先 grep 定位全部调用点再改）。

### 3.3 保存即测（小流量机动性验证）

* 新增 `POST /api/env/provider-check`，入参 `{scope: "builtin"|"custom", provider_key?, custom?{name,base_url,api_key,model}, mode: "models"|"chat"}`：

  * `models`：`GET {base_url}/models`，5s 超时（复用 `api_server.py:6007-6058` 探测逻辑下沉为公共函数）。

  * `chat`（默认，自定义厂商 & 绑定保存时）：OpenAI 兼容 `POST /chat/completions`，`max_tokens=1`、固定 10s 超时、消息体固定一句 ping，验证「鉴权 + URL + 模型名」三者同时成立。

  * 返回 `{ok, http_status, latency_ms, scope, detail}`，失败给出可操作文案（401→密钥无效；404→模型名/Base URL 错误；超时→网络不可达）。

* 保存按钮交互改为两步：**先即时测试（不入库）→ 通过后落盘**；测试失败仍允许「强制保存」（内网代理等场景），但 UI 红色警示。结果写 `checks` + 追加 jsonl。

* 内置卡片保存（`/api/env/save`）与自定义厂商保存后同样自动触发一次 check 并落库；功能点绑定保存时对目标 (provider, model) 跑 chat check。

* 热加载：保存成功后 `store.reload()` + 重建 `companion.brain`；绑定变更即时生效，重启后从 JSON 读取，持久一致。

### 3.4 服务端校验（R5/R6）

* 拒绝落盘含脱敏占位符（`•`/`··`）的 api\_key；拒绝空 name/base\_url；`max_tool_calls` 钳制 1–50。

* 自定义厂商 `name` 去重（大小写不敏感，禁止与内置厂商 display name / key 冲突）；`id` 服务端生成、只认已有 id。

* 自定义厂商改为**整条可编辑**（含换 Key），前端不再发「空 key 占位全量数组」，保存端点改为 `PUT 新增/更新` + `DELETE /api/env/custom-providers/{id}` 两个语义化接口，替代全量覆盖式 POST（旧 POST 删除，不留兼容）。

***

## 4. 前端改造（settings.js / index.html）

1. 厂商卡片：保持 凭证（Key/Base URL/默认模型）三字段；保存按钮文案「测试并保存」；行内展示最近一次 check 结果点（绿/红 + 延迟 + 时间，hover 看 detail）。
2. 自定义 API：卡片支持展开编辑（名称/URL/Key/模型/工具上限），Key 留空表示不修改；新增时名称冲突即时红字提示。
3. 「功能点映射」面板重构为「功能路由」：每个功能点一行 = 功能点名 + provider 下拉（只列已配置内置 + 自定义）+ 模型输入（下拉可选/可手填）+ 测试按钮 + 状态点；保存即测、通过才落盘（可强制）。
4. 顶部徽标数量改为「已配置厂商数」（内置 configured 去重 + 自定义数），同名重复不再双计。
5. 错误提示统一：保存失败/测试失败均在卡片行内反馈，不弹阻塞弹窗；遵循现有圆角柔色、小号非粗体样式规范，不引 emoji。

***

## 5. 任务拆解（执行顺序）

* **P0 调用点终勘**：grep 确认 `siliconflow-light` / `aerie-ws` provider 名的全部引用与 chat() model 覆盖影响面，列改动清单。

* **P1 存储与解析层**：新建 `core/ai_services.py`（store + resolve + check 下沉）；`api_server.py` 删除 `AERIE_CUSTOM_PROVIDERS` env 链路与 `/model-roles` env 写法，改为 JSON 文件端点（custom GET/PUT/DELETE、bindings GET/PUT、provider-check POST）；`.env` 删除脏键；修正 `DEEPSEEK_MODEL=grok-4.5` 为 `deepseek-chat`（执行前与用户二次确认）。

* **P2 运行时接线**：`LLMCaller` 注入 custom providers、binding 置链首 + model override；替换 4 个功能点调用点为 `resolve()`；保存热加载补 custom/binding 生效。

* **P3 前端**：按 §4 改造面板与交互。

* **P4 测试与文档**：见 §6/§7。

每阶段独立可回归，P1 完成后旧 UI 会暂时读不到自定义厂商（该数据本就未生效），P3 同日完成，不产生长期中间态。

## 6. 测试计划

* 新增 `tests/test_ai_services_store.py`：原子写、并发写不损坏、mtime reload、默认 bindings、resolve 内置/自定义、脏数据（缺字段/坏 JSON）拒绝。

* 新增 `tests/test_api_provider_config.py`：custom 增改删、重名 400、脱敏值 400、check 端点 mock httpx（200/401/404/超时）、jsonl 追加、bindings 保存后 brain 重建。

* 新增 `tests/test_llm_caller_bindings.py`：binding 链首排序、model override 生效、custom provider 进入链、未配置 binding 时行为。

* 扩展现有调用点测试（test\_llm\_caller\_provider\_routing.py 等），全量 `pytest` 回归（基线 2102 例）。

* 新增前端测试 `electron/tests/ai-services-settings.test.js`：渲染、测试并保存流程、重名拦截、强制保存路径。

* 手工验收：新增自定义 API（含名称含 `#`/Key 含 `${X}` 的抗污染用例）→ 重启应用 → 数据无损、绑定生效、主对话实际走自定义厂商（日志 provider 字段确认）。

## 7. 交付文档

* 实现完成后输出 `documents/API配置重构方案.md`：架构设计、存储契约、端点说明、关键代码索引、回归与排障手册、用户操作指南（如何添加厂商、如何给对话/子 Agent 单独指定 API、如何看连通结果）。

## 8. 明确不做（Out of scope）

* 不迁移内置厂商 Key 出 .env、不动 settings.yaml、不动数据库。

* 不通用化 ASR/生图/TTS 的专用凭证体系（UI 只读展示）。

* 不做云端同步/加密托管（密钥仍仅本地；DPAPI 加密为后续独立议题）。

* 不留旧 POST 全量覆盖接口与旧 env JSON 键的兼容层。

