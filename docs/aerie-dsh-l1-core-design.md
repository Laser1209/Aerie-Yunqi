# Aerie × DSH 路径一核心代码框架 · 详细设计(L1)

> **版本**:v1.0 · 2026-08
> **定位**:[aerie-dsh-integration-roadmap.md](aerie-dsh-integration-roadmap.md) 的 L1 落地细化,精确到文件/类/方法签名/字段。
> **前提**:桥接层采用**手写轻量 JSON-RPC 桥**(不依赖 `deepseek-harness-sdk`),已由 `tools/dsh_poc.py` 验证完整链路。
> **范围**:本设计只覆盖 L1 的 4 个新增文件 + 1 个配置,不含 L2(MCP/记忆桥/Console)与 L3(生图闭环)。

---

## 0. 一句话架构

```text
Pipeline(brain 阶段前)
  └─ WorkModeRouter.decide()        三层路由判定,决定"委托 DSH"或"走原 LLMCaller"
       └─ DshCli.delegate()         手写 JSON-RPC 桥,异步拉起 node 闭包子进程并收发帧
            └─ (stdio) DSH 子进程   场景 Preset 组合,产出 WorkProtocol JSON
       └─ WorkProtocolExecutor.execute()  校验协议 → 分发到既有安全管线执行
```

**核心不变式**:
1. DSH 不碰关系/人格,只做任务规划;Aerie 不碰执行细节,只做安全执行 + 人格呈现。
2. 单向委托(L1),无递归环;DSH 任何失败 → 降级 LLMCaller,聊天零阻塞。
3. 新增模块只依赖既有 Controller 的**方法**,不 import `tool_registry`(避免污染 function calling 面)。

---

## 1. 文件清单与依赖方向

| 文件 | 类型 | 依赖 | 复用/新增 |
| --- | --- | --- | --- |
| `core/dsh_cli.py` | 新增 | `asyncio`、`yaml`(复用)、`paths` | 新增(DshPoc 进化) |
| `core/work_mode_router.py` | 新增 | `dsh_cli`、`llm_caller`(判定用) | 新增 |
| `core/work_protocol.py` | 新增 | `computer_control`、`file_organizer`、`doc_writer` | 新增 |
| `config/work_presets.yaml` | 新增 | — | 新增(仿 settings.yaml 热加载) |
| `core/pipeline.py` | 修改 | `work_mode_router` | 唯一插入点(≈20 行) |

单向依赖:`pipeline → router → dsh_cli / work_protocol → 既有 Controller`。DSH 侧零反向依赖(协议文本经 stdio)。

---

## 2. JSON-RPC 手写桥协议层(从 PoC 提炼)

> PoC 已实测验证以下方法/通知真实可用;字段名与官方 SDK 源码(`python/sdk/src/deepseek_harness/client.py`)一致。

### 2.1 传输与帧

- **载体**:`node <runtime闭包>/packaged-bin.js`,stdio 三管道。
- **帧**:每行一个 JSON(`json.dumps(..., separators=(",", ":")) + "\n"`),UTF-8,`bufsize=1`。
- **纪律**:stdout 只承载 JSON-RPC 帧;stderr 是诊断;两者严格分离(DSH 官方约定)。
- **启动环境**:`DSH_CORDIS_CONFIG`(cordis.yml 绝对路径)、`DSH_SESSION_ROOT`(会话持久化目录)、`DSH_CWD`(工作目录)、`DEEPSEEK_API_KEY`/`DEEPSEEK_BASE_URL`(从 Aerie `.env` 注入,不落盘不打印)。

### 2.2 方法(client → runtime,带 `id`)

| 方法 | params | result | 说明 |
| --- | --- | --- | --- |
| `initialize` | `{cwd, provider, model, maxTokens?}` | `dict` | 会话级初始化,PoC 实测热启动 ~0.4s |
| `session/prompt` | `{sessionId, contentBlocks}` | `{messageId}` | 提交一轮,`contentBlocks=[{"type":"text","text":...}]` |
| `shutdown` | `null` | `{}` | 协议级优雅关闭 |

### 2.3 通知(runtime → client,无 `id`)

| 通知 | params | 关键字段 | 用途 |
| --- | --- | --- | --- |
| `session.event` | `{sessionId, event}` | `event.type` ∈ `turn/end` / `assistant/message` / `agent/inbox/spliced` / `step/*` / `tool/*` | 进度播报 + 结果提取 |
| `session.status` | `{sessionId, status}` | `status` ∈ `idle` / `running` / `error` | **`idle` 是轮次完成的终止信号** |
| `subagent.started` / `subagent.finished` | `{parentSessionId, childSessionId}` | — | 子代理生命周期(思考可视化锚点) |

### 2.4 结果提取(对齐 SDK `api.py`)

- `final_response`:倒序找最后一个 `assistant/message` 事件,取 `data.message.content`(优先)或 `data.content` 的 text block 拼接。
- `finish_reason`:倒序找最后一个 `turn/end` 事件,取 `data.reason.kind`(`completed` / `max-tokens` / `error` / `aborted` / `refusal`)。

---

## 3. `core/dsh_cli.py` — DSH 运行时桥

### 3.1 类签名

```python
class DshCli:
    """手写 JSON-RPC 桥,异步驱动 DSH node 闭包子进程。生命周期仿 napcat_launcher。"""

    def __init__(self, preset_registry: WorkPresetRegistry, *, paths: Paths) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._pending: dict[str, asyncio.Future] = {}      # id -> future
        self._notify: asyncio.Queue[dict] = asyncio.Queue() # 通知队列
        self._restart_count = 0
        self._circuit_open_until = 0.0                     # 熔断时间戳
        self._stderr_tail: deque[str] = deque(maxlen=400)

    async def ensure_running(self, preset: str | None = None) -> None: ...
    async def status(self) -> dict: ...                    # {running, version, sessions, degraded}
    async def delegate(self, task: str, *, preset: str, persona_brief: str,
                       on_notice: Callable[[dict], Awaitable[None]] | None,
                       timeout_s: float = 600) -> DshRunResult: ...
    async def cancel(self, run_id: str) -> bool: ...
    async def stop(self) -> None: ...                      # shutdown 请求 → stdin close → terminate → kill
```

### 3.2 关键方法语义

**`delegate()` 流程**(async):

```text
ensure_running(preset)
  → initialize(cwd, provider, model, maxTokens)      # 首次或进程重启后
  → session/prompt(sessionId, contentBlocks)
  → 消费通知队列,直到 session.status == "idle"(或 timeout / error)
     ├─ session.event → 提取进度,节流调用 on_notice
     └─ turn/end → 记录 finish_reason
  → 返回 DshRunResult(session_id, final_response, finish_reason, events, usage)
```

**进程生命周期**(复用 `napcat_launcher` + `24h watchdog` 经验):

| 事件 | 动作 |
| --- | --- |
| 懒启动 | 首次 delegate 时 `ensure_running`;node 冷启动 ~6.8s |
| 探活 | `self._proc.returncode is None` 判定存活;异常退出捕获 stderr 尾部 |
| 崩溃重启 | 重启 ≤2 次(每次间隔 1s),超过熔断 5min |
| 熔断 | 熔断期内 `delegate()` 直接抛 `DshCircuitOpen`,由 router 降级 |
| 优雅关闭 | `shutdown` 请求 → 关 stdin → `terminate` → 超时 `kill` |

### 3.3 资源监控(可选,PoC 已验证)

后台 `asyncio.Task` 每 1s 用 `psutil.Process(pid)` 采样 RSS/CPU,记录峰值;阈值告警走 `telemetry`。基线参考:纯 boot 62MB,含 LLM 调用 90MB。

---

## 4. `core/work_mode_router.py` — 工作模式路由

### 4.1 三层判定(从便宜到贵)

```python
class WorkModeRouter:
    def __init__(self, dsh: DshCli, preset_registry, llm: LLMCaller) -> None: ...

    async def decide(self, text: str, *, user_id: str, explicit: bool = False) -> RouteDecision:
        """返回委托决策:RouteDecision(kind, preset, reason)"""
```

| 层 | 机制 | 成本 | 动作 |
| --- | --- | --- | --- |
| L1 | 关键词正则(工作动词表:整理/归类/重命名/写文件/打开/点击/截图/执行命令/压缩/清理…) | 免费 | 命中且无歧义 → 委托 |
| L2 | 轻量模型三分类(日常/工作/其他,`siliconflow-light`,5s 超时) | 低 | 命中 → 委托 |
| L3 | 用户显式(`/work ...` / UI 开关) | 用户可控 | 强制委托 |

### 4.2 路由矩阵

| 任务类型 | 路由 | 执行形态 | 复用 |
| --- | --- | --- | --- |
| 日常聊天/情感/陪伴 | LLMCaller | — | 零改动 |
| 电脑操控 | DSH 规划 | 形态 B | `ComputerController` |
| 文件整理 | DSH 规划 | 形态 B | `FileOrganizer` |
| 文档写作 | DSH 执行/规划 | 形态 A/B | `DocWriterService` |
| 生图 | 原方案 | — | 零改动 |

**降级**:`DshCli` 未启动 / 熔断 / 超时 → `decide()` 恒返回 `kind="llm"`,聊天零阻塞。

---

## 5. `core/work_protocol.py` — WorkProtocol 执行器

### 5.1 协议 Schema(形态 B 契约)

```json
{
  "protocol_version": 1,
  "task_type": "computer_control | file_organize | doc_write",
  "persona_id": "yita",
  "session_id": "dsh-session-id",
  "goal": "任务目标(审计用)",
  "plan": { "..." }
}
```

### 5.2 执行器

```python
class WorkProtocolExecutor:
    async def execute(self, protocol: dict, *, source: str = "dsh") -> list[dict]:
        """解析协议并分发到既有安全管线。
        返回 [{op, status, detail, audit_id}],status ∈ ok|denied|approved|rejected|failed
        异常:ProtocolError(未知 task_type / Schema 非法)
        """
```

### 5.3 执行安全红线(每条 op 前,顺序)

1. `RestrictedShell.is_dangerous()` 危险命令硬闸(任何来源不可绕过);
2. `AccessPolicy.decide()` 四模式裁决;
3. 需审批 op → 复用 `request_approval/approve_action/reject_action`(审批卡片标注来源 DSH);
4. 审计落盘 `data/audit/`,标记 `source=dsh` + `session_id`。

### 5.4 既有 Controller 改造点(≤40 行/个)

| Controller | 改造 |
| --- | --- |
| `ComputerController` | `_audit()` 加 `source=dsh`/`session_id`;新增 `from_protocol(op)` 适配 |
| `FileOrganizer` | `execute_organize` 加协议来源入参;事务链零改动 |
| `DocWriterService` | `doc_write` plan → `create_document` 适配 |

---

## 6. `config/work_presets.yaml` — 场景预设

```yaml
presets:
  file-organizer:
    label: "文件整理"
    enabled: true
    dsh_cordis: "presets/file-organizer.cordis.yml"
    model: "deepseek-chat"
    max_tokens: 16000
    session_pool: 1
    safety: {fs_roots: ["E:\\Downloads"], shell: disabled, network: disabled}
    protocol: "file_organize"
    persona_inject: true
  computer-control:
    label: "电脑操控"
    enabled: true
    dsh_cordis: "presets/computer-control.cordis.yml"
    model: "deepseek-chat"
    max_tokens: 24000
    session_pool: 1
    safety: {fs_roots: [], shell: disabled, network: disabled}
    protocol: "computer_control"
    persona_inject: true
  # doc-writer / research / coder 同构,首批 5 预设
```

**设计原则**:Preset 管「工作专业度」,Persona 管「表达人格」,正交组合。热加载仿 `settings.yaml`,新增场景 = 加一段 YAML。

---

## 7. 错误码与降级(桥层契约)

| 域 | 错误码 | 降级动作 |
| --- | --- | --- |
| 桥 | `DSH_BRIDGE_NOT_RUNNING` / `DSH_RUNTIME_CRASHED` | 重启 ≤2 次 → 降级 |
| 会话 | `DSH_SESSION_NOT_FOUND` / `DSH_SESSION_CORRUPT` | 新建会话 + 提示 |
| 任务 | `DSH_TIMEOUT` / `DSH_MAX_TOKENS` / `DSH_TOOL_FAILED` | 幂等重试 → 降级 |
| 熔断 | `DSH_CIRCUIT_OPEN` | 恒走 LLMCaller |
| 协议 | `PROTOCOL_UNKNOWN_TASK` / `PROTOCOL_SCHEMA_INVALID` | 拒绝 + 审计告警 |

---

## 8. 集成点与 pipeline 插入(唯一改动)

`core/pipeline.py` brain 阶段前插入(≈20 行,关闭开关时直通):

```python
if feature_flags.enabled("dsh_cli_v1"):
    decision = await router.decide(user_text, user_id=..., explicit=...)
    if decision.kind == "delegate":
        result = await dsh.delegate(user_text, preset=decision.preset, ...)
        # 翻译层重写 + Gate 校验 → 先落库再 emit
```

进度推送复用 `chat_events.emit`(新消息类型 `dsh_task_card`),三端零改动。

---

## 9. 里程碑与验收(M1)

| 项 | 验收标准 |
| --- | --- |
| dsh_cli 手写桥 | PoC 协议跑通;崩溃重启 ≤2 次自动降级 |
| 路由三层 | 误伤 <2%(黄金样本) |
| 协议执行器 | 电脑操控/文件整理闭环三端回显 |
| 降级演练 | DSH 崩溃 → 聊天零中断 |
| 单元测试 | 新模块覆盖率 ≥90%,纳入既有 pytest 体系 |

---

## 10. 待定与风险

| 项 | 状态 | 说明 |
| --- | --- | --- |
| node 闭包物化脚本 | 待固化 | V19-V22 的 deploy+restore+materialize 需固化成可重复脚本 |
| 会话池预热 | M2 | 抵消懒启动 +6.8s 冷启动(V1) |
| 翻译层模型 | 复用 siliconflow-light | 人格化进度播报,原始输出折叠保留 |
| DSH provider/model 名 | 待最终确认 | PoC 用 `deepseek-official`/`deepseek-chat` 跑通 |
