# Aerie · 云栖 — 完整重建计划

## 需求总结

基于 `OpenCloud_Companion_System_Features.md` v9.0 和 `opencloud-companion-ui/` 设计稿，重建整个系统。

### 核心目标
1. **Electron 桌面壳**：悬浮球 + 聊天窗 + 主窗口（侧边栏），隐藏 Python 后端控制台
2. **Python 后端**：HTTP API (127.0.0.1:7890)，FastAPI，处理消息管线
3. **NapCat QQ 接入**：OneBot11 WebSocket (127.0.0.1:3001)，后台静默启动，日志嵌入 UI
4. **统一消息存储**：SQLite `chat_log` 表，QQ 和聊天窗共享同一记忆
5. **实时同步**：Python stderr → `[CHAT_EVENT]` → Electron main 解析 → IPC → 所有窗口
6. **消息路由**：Master (3998874040) → FULL，Friend (3489352115) → AUTO_REPLY，陌生人 → BASIC
7. **聊天条消息不发 QQ**：`source="local"` 跳过 SendQueue
8. **设计语言**：Pinguo design tokens (Apple-inspired)，colors_and_type.css，iMessage 风格气泡

### 保留文件
- `config/settings.yaml` — 已配置正确
- `requirements.txt` — 依赖完整
- `Aerie · 云栖.svg` / `.png` — Logo
- `opencloud-companion-ui/` — 设计稿（不做修改）
- `NapCat/` — NapCat 框架（不做修改）
- `data/`, `logs/`, `userData/` — 运行时目录
- `.venv/` — Python 虚拟环境

---

## 删除清单（所有现有源文件）

### Python 后端
- `main.py` ✗
- `core/api_server.py` ✗
- `core/brain.py` ✗
- `core/companion.py` ✗
- `core/context_builder.py` ✗
- `core/database.py` ✗
- `core/emotion_engine.py` ✗
- `core/emotion_threshold.py` ✗
- `core/pipeline.py` ✗
- `core/chat_events.py` ✗
- `core/tool_registry.py` ✗
- `core/function_calling.py` ✗
- `core/token_tracker.py` ✗
- `core/system_monitor.py` ✗
- `core/backup.py` ✗
- `core/elevator.py` ✗
- `core/self_healing.py` ✗
- `core/task_scheduler.py` ✗
- `core/napcat_launcher.py` ✗
- `core/providers/` ✗
- `communication/message.py` ✗
- `communication/qq_client.py` ✗
- `communication/router.py` ✗
- `communication/send_queue.py` ✗
- `communication/splitter.py` ✗
- `communication/recall_manager.py` ✗
- `config/persona_loader.py` ✗
- `tools/__init__.py` ✗
- `memory/memory_store.py` ✗
- `memory/short_term.py` ✗
- `knowledge/kb.py` ✗
- `scheduler/` ✗ (如果存在)
- `proactive/` ✗ (如果存在)
- `emotion/` ✗ (如果存在)
- `persona/` ✗ (如果存在)

### Electron 前端
- `electron/src/main.js` ✗
- `electron/src/preload.js` ✗
- `electron/src/renderer/index.html` ✗
- `electron/src/renderer/floating-chat.html` ✗
- `electron/src/renderer/floating-ball.html` ✗
- `electron/src/renderer/js/*.js` ✗
- `electron/src/renderer/styles/main.css` ✗
- `electron/src/renderer/styles/floating-chat.css` ✗
- `electron/src/renderer/styles/floating-ball.css` ✗
- `electron/src/renderer/styles/themes/*.css` ✗

### 启动脚本
- `start-dev.bat` ✗

---

## 重建计划

### 阶段 1：Python 后端核心（数据 + 消息 + 管线）

#### 1.1 `core/database.py` — SQLite 单例

**不作改动**，现有实现已满足：
- 9 张表 + WAL 模式 + 线程安全 + CRUD 工具
- `insert()` 返回 `lastrowid`，emit 时需要

#### 1.2 `communication/message.py` — 消息数据模型

```python
@dataclass
class IncomingMessage:
    user_id: int
    content: str
    msg_type: str       # private | group
    source: str         # qq | local
    raw_event: dict

    @staticmethod
    def from_onebot_event(event: dict) -> "IncomingMessage": ...
    @staticmethod
    def from_local(content: str, user_id: int) -> "IncomingMessage": ...

@dataclass
class OutgoingReply:
    user_id: int
    content: str
    render_mode: str    # plain | markdown
    msg_id: int         # 对应 chat_log 的 DB id
```

#### 1.3 `communication/qq_client.py` — NapCat WS 客户端

**保持现有逻辑**（WebSocket 重连、OneBot11 协议解析），**只改 startup 行为**：
- 不在 `companion.start()` 里自动调用 `get_launcher().start()` ——那会拉起 QQ
- 改为：被动等待端口 3001。如果端口开着就连；没开放就定时重试，不主动启动 NapCat
- NapCat 的**启动控制**交给 Electron 侧的 NapCat 面板

```python
class QQClient:
    async def connect(self):
        """连接 NapCat WS，自动重连，不主动启动 NapCat"""
        while self._running:
            if not self._port_open():
                await asyncio.sleep(3)
                continue
            try:
                async with websockets.connect(...) as ws:
                    await self._listen(ws)
            except Exception:
                await asyncio.sleep(5)
```

#### 1.4 `communication/router.py` — 路由

```python
class Router:
    def __init__(self, self_qq: int, friends_qq: list[int]):
        self.master = self_qq
        self.friends = set(friends_qq)

    def route(self, user_id: int) -> str:
        """FULL | AUTO | BASIC"""
        if user_id == self.master: return "FULL"
        if user_id in self.friends: return "AUTO"
        return "BASIC"

    def get_role_label(self, user_id: int) -> str:
        """[MASTER] | [FRIEND] | [STRANGER]"""
```

#### 1.5 `communication/send_queue.py` — 发送队列

```python
class SendQueue:
    """频次控制 + 拟人延迟 + 分段发送"""
    def enqueue(self, reply: OutgoingReply):
        """仅 QQ 消息入队，source=local 不调用此方法"""
    async def _worker(self): ...
```

#### 1.6 `communication/splitter.py` — 消息分段

保持现有逻辑：按语义边界拆分超长消息。

#### 1.7 `core/brain.py` — LLM 调用层

```python
class Brain:
    """多 Provider 容灾：硅基流动 → DeepSeek → 本地"""
    async def chat(self, messages: list, tools: list = None, ...) -> BrainResponse:
        ...
```

#### 1.8 `core/context_builder.py` — 上下文组装

```python
class ContextBuilder:
    def build(self, user_id: int, msg: str, route_mode: str) -> list[dict]:
        """FULL: 人格+记忆+知识+历史+情感
           AUTO: 人格+短期历史
           BASIC: 基础寒暄模板"""
```

#### 1.9 `core/emotion_engine.py` — 情感引擎

```python
class EmotionEngine:
    def analyze(self, text: str) -> dict:  # PAD 三维度
    def update_trajectory(self, user_id: int, event: str): ...
    def get_state(self, user_id: int) -> dict:  # PAD 当前值
```

#### 1.10 `core/tool_registry.py` — 工具注册

```python
class ToolRegistry:
    def register(self, name, func, schema): ...
    def execute(self, name, args) -> dict: ...
    def get_openai_schema(self) -> list[dict]: ...
```

#### 1.11 `tools/__init__.py` — 内置工具

```python
def register_all_tools(registry: ToolRegistry):
    registry.register("get_time", get_time, {...})
    registry.register("get_system_info", get_system_info, {...})
    registry.register("echo", echo, {...})
```

#### 1.12 `core/pipeline.py` — 消息管线

```python
class Pipeline:
    async def handle(self, msg: IncomingMessage, force_full: bool = False):
        """1. 路由 2. 上下文 3. LLM 4. 情感 5. 持久化+emit 6. 回复"""
        mode = self.router.route(msg.user_id)
        if mode == "BASIC" and not force_full:
            return  # 陌生人不回复

        ctx = self.ctx_builder.build(msg.user_id, msg.content, mode)
        response = await self.brain.chat(ctx, tools=...)
        reply_text = self.emotion.tune(response.text)

        # 持久化用户消息 + emit("user", id=..., ...)
        user_id = self.db.insert("chat_log", {...})
        emit("user", id=user_id, ...)

        # 持久化 AI 回复 + emit("assistant", id=..., ...)
        ai_id = self.db.insert("chat_log", {...})
        emit("assistant", id=ai_id, ...)

        # QQ 消息 → SendQueue；本地消息 → 跳过
        if msg.source == "qq":
            reply = OutgoingReply(user_id=msg.user_id, content=reply_text, msg_id=ai_id)
            await self.send_queue.enqueue(reply)

        return {"reply": reply_text, "user_msg_id": user_id, "ai_msg_id": ai_id}
```

#### 1.13 `core/chat_events.py` — stderr 事件桥

```python
import sys, json, time

def emit(event_type: str, **payload):
    payload["type"] = event_type
    payload["ts"] = time.time()
    line = f"[CHAT_EVENT]{json.dumps(payload, ensure_ascii=False)}"
    print(line, file=sys.stderr, flush=True)
```

#### 1.14 `core/napcat_launcher.py` — NapCat 启动器

```python
class NapcatLauncher:
    """提供状态查询 + 手动启动，Electron 侧 NapCat 面板调用"""
    def get_status(self) -> dict:
        """返回 {running, ws_port_open, pid, phase}"""
    async def start(self) -> dict:
        """Electron 面板手动启动时调用"""
    async def stop(self) -> dict:
        """停止 NapCat 和 QQ"""
```

关键改变：**不在 Companion.start() 里自动启动 NapCat**，改为 Electron NapierCat 面板手动控制。

#### 1.15 `core/companion.py` — 调度器

```python
class Companion:
    def __init__(self, settings):
        self.db = Database()
        self.emotion = EmotionEngine(self.db)
        self.brain = Brain()
        self.memory = LongTermMemory(self.db)
        self.knowledge = KnowledgeBase(self.db)
        self.tool_registry = ToolRegistry(self.db)
        register_all_tools(self.tool_registry)

        qq_cfg = settings.get("qq", {})
        self.qq = QQClient(qq_cfg)
        self.router = Router(int(qq_cfg["self_qq"]), qq_cfg.get("friends_qq", []))
        self.splitter = SemanticMessageSplitter()
        self.queue = SendQueue(sender=self._send_to_qq, splitter=self.splitter)
        self.pipeline = Pipeline(
            router=self.router,
            emotion_engine=self.emotion,
            context_builder=ContextBuilder(self.memory, self.knowledge),
            brain=self.brain,
            send_queue=self.queue,
            tool_registry=self.tool_registry,
            db=self.db,
        )

    async def start(self):
        self.queue.start()
        self.qq.set_message_handler(self._on_qq_message)
        # 不自动启动 NapCat —— Electron 面板控制
        asyncio.create_task(self.qq.connect())

    async def _send_to_qq(self, reply: OutgoingReply) -> bool:
        return await self.qq.send_message(reply.user_id, reply.content)

    async def _on_qq_message(self, msg: IncomingMessage):
        await self.pipeline.handle(msg)
```

#### 1.16 `core/api_server.py` — HTTP API

使用 FastAPI + uvicorn：

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/health` | GET | 心跳 + QQ 连接状态 |
| `/api/chat/send` | POST | 发送消息（`text` + `user_id`） |
| `/api/chat/history` | GET | 获取聊天历史（`user_id` + `limit`） |
| `/api/chat/poll` | GET | 增量轮询（`user_id` + `since_id`） |
| `/api/napcat/status` | GET | NapCat 状态 |
| `/api/napcat/start` | POST | 手动启动 NapCat |
| `/api/napcat/stop` | POST | 停止 NapCat |
| `/api/napcat/logs` | GET | NapCat 最新日志 |
| `/api/napcat/qrcode` | GET | 二维码图片 |
| `/api/emotion/state` | GET | 情感状态 |
| `/api/tools/list` | GET | 工具列表 |
| `/api/stats/tokens` | GET | Token 统计 |

#### 1.17 `main.py` — 入口

```python
async def _main():
    # setup logging
    # load .env, settings
    # Companion.start()
    # start API server
    # wait for stop signal
```

#### 1.18 `config/persona_loader.py` — 配置加载

```python
def load_settings() -> dict:
    with open("config/settings.yaml") as f:
        return yaml.safe_load(f)

def load_persona() -> dict:
    ...
```

#### 1.19 `memory/memory_store.py` — 长期记忆

```python
class LongTermMemory:
    def store(self, user_id, memory_type, content, importance): ...
    def retrieve(self, user_id, query, limit=5): ...
    def decay(self): ...
```

#### 1.20 `knowledge/kb.py` — 知识库

```python
class KnowledgeBase:
    def search(self, query, limit=5): ...
    def add(self, category, title, content, tags): ...
```

---

### 阶段 2：Electron 前端

#### 2.1 `electron/src/main.js` — 主进程

```javascript
// 职责：
// 1. 创建主窗口 (BrowserWindow, frameless, transparent)
// 2. 创建系统托盘 (Tray)
// 3. spawn Python 子进程 (pythonw.exe, windowsHide: true)
// 4. 解析 stderr → [CHAT_EVENT] → IPC 广播
// 5. 管理悬浮球窗口
// 6. 心跳检测 (poll /api/health)
// 7. 监听 IPC: api:request, napcat:start, napcat:stop
```

#### 2.2 `electron/src/preload.js` — 安全桥接

```javascript
contextBridge.exposeInMainWorld("aerie", {
    api: {
        request: (opts) => ipcRenderer.invoke("api:request", opts),
        onMessage: (cb) => ipcRenderer.on("chat:message", (_, data) => cb(data)),
    },
    napcat: {
        getStatus: () => ipcRenderer.invoke("napcat:getStatus"),
        start: () => ipcRenderer.invoke("napcat:start"),
        stop: () => ipcRenderer.invoke("napcat:stop"),
        onLog: (cb) => ipcRenderer.on("napcat:log", (_, data) => cb(data)),
        onEvent: (cb) => ipcRenderer.on("napcat:event", (_, data) => cb(data)),
    },
    electron: {
        toggleChat: () => ipcRenderer.send("toggle-chat"),
        getHealth: () => ipcRenderer.invoke("get-health"),
    },
});
```

#### 2.3 `electron/src/renderer/index.html` — 主窗口

三层布局：
```
┌────────────────────────────────────────┐
│  顶部状态栏: Logo + 连接状态           │
├──────┬─────────────────────────────────┤
│      │                                 │
│ 侧边栏│        聊天区域                 │
│ 5 Tab│    (iMessage 风格气泡)          │
│      │                                 │
│      │   ┌─────────────────────────┐   │
│      │   │  输入框                      │
│      │   └─────────────────────────┘   │
└──────┴─────────────────────────────────┘
```

侧边栏 5 Tab：
1. **聊天** — 实时对话
2. **QQ 连接** — NapCat 状态 + QR 码 + 日志
3. **状态** — Token/内核/AI 展示
4. **设置** — 主题/窗口/其他
5. **关于**

#### 2.4 `electron/src/renderer/js/chat.js` — 聊天逻辑

```javascript
class ChatManager {
    constructor() {
        this.messages = [];
        this._seenIds = new Set();
        this._listenIPC();   // 监听 [CHAT_EVENT] → 渲染
        this._startPoll();   // 增量轮询补充
    }

    async send(text) {
        // HTTP POST /api/chat/send
        // source=local 不走 SendQueue
        // 回复通过 IPC chat:message 到达
    }

    _listenIPC() {
        window.aerie.api.onMessage((msg) => {
            if (this._seenIds.has(msg.id)) return;
            this._seenIds.add(msg.id);
            this._renderMessage(msg);
        });
    }

    _renderMessage(msg) {
        // iMessage 风格：user 蓝色右对齐，assistant 灰色左对齐
    }
}
```

#### 2.5 `electron/src/renderer/js/napcat-panel.js` — NapCat 控制面板

```javascript
class NapcatPanel {
    constructor() {
        this._listenLogs();
        this._pollStatus();
    }

    async start() {
        // 调用 IPC → main → HTTP POST /api/napcat/start
        // 不弹出 QQ 窗口（NapCat 可能仍需 QQ 进程，后续优化）
    }

    _listenLogs() {
        // 实时日志滚动
    }

    _pollStatus() {
        // 每 3s 轮询 /api/napcat/status
        // 显示 phase: 未连接 | 启动中 | 等待扫码 | 已连接
    }
}
```

#### 2.6 `electron/src/renderer/styles/main.css` — Pinguo Design Tokens

基于 `opencloud-companion-ui/colors_and_type.css`：
- CSS 变量：brand / background / text / icon / state
- 字体：DM Sans + JetBrains Mono
- 气泡：iMessage 风格（品牌色右对齐，灰色左对齐）
- 主题：light/dark 两种模式

#### 2.7 `electron/src/renderer/floating-chat.html` — 悬浮聊天条

独立窗口，frameless，始终置顶，与主窗口共享同一 `ChatManager` 逻辑。

#### 2.8 `electron/src/renderer/floating-ball.html` — 悬浮球

可拖拽，点击展开悬浮聊天条，显示未读数徽标。

---

### 阶段 3：启动脚本

#### 3.1 `start-dev.bat`

```batch
@echo off
REM 检查 Python 依赖
pip install -r requirements.txt --quiet
REM 启动 Electron
cd electron
npm start
```

---

### 阶段 4：测试验证

1. `start-dev.bat` → Python 后端启动 → Electron 窗口出现
2. `/api/health` 返回 200
3. NapCat 面板 → 手动点「启动」→ 日志滚动 → QR 码显示（如需要）
4. 手机 QQ 扫码 → 状态变为「已连接」
5. 手机 QQ 发消息 → 聊天窗实时显示 AI 回复
6. 聊天窗发消息 → 实时显示 AI 回复（不发给 QQ）
7. 悬浮球拖拽 → 点击 → 聊天条弹出 → 消息同步
8. 切换到主窗口 → 消息列表一致

---

## 架构决策

1. **NapCat 不自动启动**：由用户通过 UI 面板手动控制，避免每次启动都弹出 QQ 窗口
2. **`[CHAT_EVENT]` 单通道**：Python stderr → Electron main 解析 → IPC 广播，所有窗口平等消费
3. **去重依赖 DB id**：每个消息有唯一 `chat_log.id`，前端 `_seenIds` Set 去重
4. **source 字段决定是否发 QQ**：`source="local"` 跳过 SendQueue
5. **Design Tokens**：严格遵循 Pinguo 色彩体系，Apple HIG 对齐

## 说明

- 本计划为完整重建方案
- 首次重建聚焦核心功能：消息收发 + QQ 接入 + UI 展示
- 高级功能（主动推送、多模态、任务调度等）后续迭代
- 所有删除和创建操作在用户确认后一次性执行
