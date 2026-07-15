# OpenCloud Companion 完整开发计划

> 基于 NapCatQQ 连接成功案例（账号 3489352115 向 3998874040 发送消息已验证通过）
> 发布日期：2026-07-15

---

## 一、当前状态基线

### 已验证成果
| 项目 | 状态 |
|------|------|
| NapCatQQ 4.18.9 安装运行 | 已完成 |
| QQ 号 B (3998874040 伊塔) 登录 | 已完成 |
| OneBot11 适配器加载 | 已完成 |
| 账号 A → B 发送消息 "1" | 验证通过 |
| AI API 接入（硅基流动/DeepSeek/智谱） | 未开始 |
| Python 项目代码 | 零行 |

### 待确认事项
| 事项 | 重要性 | 负责 |
|------|--------|------|
| NapCat OneBot11 WebSocket 实际端口 | **P0** | 开发 |
| 硅基流动 / DeepSeek / 智谱 API Key 申请 | **P0** | 开发 |
| QQ 号 B 的 OneBot11 配置文件路径 | **P1** | 开发 |

---

## 二、功能扩展路线图

```
Phase 1 (MVP)     Phase 2          Phase 3          Phase 4          Phase 5+
QQ收发+AI回复     性格+上下文记忆    内置工具+桌面UI   技能市场+知识库    语音+主动服务
   2周              2-3周             3-4周             3-4周             持续迭代
```

### Phase 1：最简可运行骨架（2周）

**目标：手机 QQ 发消息 → AI 生成回复 → QQ 返回**

| 编号 | 功能模块 | 具体内容 | 交付物 |
|------|---------|---------|--------|
| F1.1 | 项目骨架搭建 | 创建 Python 项目结构、依赖管理 | `main.py` + `requirements.txt` |
| F1.2 | QQ 消息接收 | WebSocket 连接 NapCat OneBot11，解析消息事件 | `communication/qq_client.py` |
| F1.3 | AI 回复生成 | 接入硅基流动 API，构建 System Prompt | `core/brain.py` |
| F1.4 | QQ 消息发送 | 通过 WebSocket 发送 OneBot11 `send_private_msg` | 集成于 qq_client.py |
| F1.5 | 配置管理 | .env 环境变量 + YAML 配置文件 | `config/settings.yaml` + `.env.example` |
| F1.6 | 日志系统 | 分级日志、文件轮转 | 使用 Python logging |
| F1.7 | 异常容灾 | WebSocket 断线重连、API 调用重试 | 重试装饰器 |

**Phase 1 技术实现细节**：

```
消息处理链路：
┌──────────────────────────────────────────────────────┐
│  手机 QQ(账号A:3489352115)                            │
│       │ 发送 "今天天气怎么样"                          │
│       ▼                                              │
│  QQ 服务器 ──→ NapCatQQ(账号B:3998874040)            │
│       │  OneBot11 Event: {"post_type":"message",      │
│       │   "message_type":"private",                   │
│       │   "user_id":3489352115, "message":"..."}      │
│       ▼                                              │
│  WebSocket ws://localhost:3001                        │
│       │                                              │
│       ▼                                              │
│  communication/qq_client.py                          │
│       │  parse_message() → MessageDTO                 │
│       │                                              │
│       ▼                                              │
│  core/brain.py                                       │
│       │  build_prompt(msg) → call_ai_api() → reply    │
│       │                                              │
│       ▼                                              │
│  communication/qq_client.py                          │
│       │  send_private_msg(user_id, reply)             │
│       │  {"action":"send_private_msg",                │
│       │   "params":{"user_id":3489352115,             │
│       │   "message":"今天北京多云，24°C~32°C..."}}     │
│       ▼                                              │
│  QQ 服务器 ──→ 手机 QQ(账号A)                          │
└──────────────────────────────────────────────────────┘
```

### Phase 2：性格 + 记忆系统（2-3周）

| 编号 | 功能模块 | 具体内容 | 关键依赖 |
|------|---------|---------|---------|
| F2.1 | 性格引擎 | 加载 `persona.yaml`，动态构建 System Prompt | Phase 1 |
| F2.2 | 对话分类器 | AI 判断消息是「闲聊」还是「命令」 | Phase 1 |
| F2.3 | Mem0 记忆集成 | 接入 Mem0 实现长期对话记忆 | Phase 1 |
| F2.4 | 聊天日志存储 | SQLite + SQLCipher 加密存储原始记录 | Phase 1 |
| F2.5 | 上下文构建器 | 记忆检索 → 注入 Prompt 的统一上下文逻辑 | F2.3, F2.4 |

### Phase 3：工具执行 + 桌面 UI（3-4周）

| 编号 | 功能模块 | 具体内容 |
|------|---------|---------|
| F3.1 | 文件操作工具 | 读/写/搜/移动/整理文件 |
| F3.2 | 系统操作工具 | 打开软件、查看系统状态 |
| F3.3 | 网页工具 | 搜索、天气查询、新闻获取 |
| F3.4 | 待办管理 | 记录、提醒、完成待办 |
| F3.5 | Function Calling 集成 | 将工具注册为 OpenAI Tool Schema |
| F3.6 | 命令执行流水线 | AI 决策 → 工具调用 → 结果包装 → QQ 回复 |
| F3.7 | PyQt6 悬浮球 | 桌面悬浮球、开机自启 |
| F3.8 | 对话窗口 | 点击悬浮球打开，支持文字输入 |

### Phase 4：技能市场 + 自主知识库（3-4周）

| 编号 | 功能模块 | 具体内容 |
|------|---------|---------|
| F4.1 | 技能管理器 | 搜索/下载/安装/注册技能包 |
| F4.2 | QQ 审批流程 | 技能安装通过 QQ 申请审批 |
| F4.3 | 知识采集 | 从对话/文件/网页提取知识 |
| F4.4 | 知识分类 | HDBSCAN 聚类 + LLM 命名 |
| F4.5 | 知识重组 | 去重、矛盾解决、碎片整理、冷热分离 |
| F4.6 | Markitdown 文档管道 | 文档格式转换 + 省 token 处理 |

### Phase 5+：语音 + 主动服务 + 打磨

| 编号 | 功能模块 | 具体内容 |
|------|---------|---------|
| F5.1 | 语音输入 | SpeechRecognition 集成 |
| F5.2 | 语音输出 | pyttsx3 本地 TTS |
| F5.3 | 每日简报 | APScheduler 定时推送 |
| F5.4 | 主动关怀 | 天气提醒、晚安问候 |
| F5.5 | 设置面板 | PyQt6 配置 UI |
| F5.6 | 性能优化 | 并发处理、缓存、冷启动加速 |

---

## 三、技术实现方案

### 3.1 项目目录结构

```
OpenCloud_Companion/                    # 项目根目录（e:\Agent_reply\OpenCloud_Companion\）
├── main.py                             # 入口：启动所有模块
├── requirements.txt                    # Python 依赖
├── requirements-dev.txt                # 开发依赖（测试、lint）
├── .env.example                        # 环境变量模板
├── .gitignore
│
├── core/                               # AI 核心层
│   ├── __init__.py
│   ├── brain.py                        # AI API 调用、Prompt 构建、回复生成
│   ├── personality.py                  # 性格引擎（加载 persona.yaml → System Prompt）
│   └── classifier.py                   # 对话/命令分类器
│
├── communication/                      # 通信层
│   ├── __init__.py
│   ├── qq_client.py                    # NapCatQQ WebSocket 客户端（收/发消息）
│   └── message.py                      # 消息数据模型（DTO）
│
├── memory/                             # 记忆层
│   ├── __init__.py
│   ├── mem0_store.py                   # Mem0 长期记忆（向量检索）
│   ├── chat_log.py                     # 原始聊天记录（SQLite + SQLCipher）
│   └── context_builder.py             # 统一上下文构建
│
├── tools/                              # 工具层（Phase 3+）
│   ├── __init__.py
│   ├── base.py                         # 工具基类 + 注册装饰器
│   ├── file_ops.py                     # 文件操作
│   ├── system_ops.py                   # 系统操作
│   ├── web_ops.py                      # 搜索/天气/新闻
│   ├── todo_manager.py                 # 待办管理
│   ├── doc_pipeline.py                 # Markitdown 文档管道
│   └── skill_manager.py                # 技能市场（Phase 4+）
│
├── desktop/                            # 桌面 UI（Phase 3+）
│   ├── __init__.py
│   ├── floating_ball.py                # 悬浮球
│   ├── chat_window.py                  # 对话窗口
│   ├── daily_brief.py                  # 每日简报
│   ├── settings_panel.py               # 设置面板
│   ├── voice_input.py                  # 语音输入（Phase 5+）
│   └── voice_output.py                 # 语音输出（Phase 5+）
│
├── scheduler/                          # 定时任务（Phase 5+）
│   ├── __init__.py
│   └── tasks.py                        # APScheduler 任务定义
│
├── config/                             # 配置
│   ├── settings.yaml                   # 主配置
│   ├── persona.yaml                    # 性格设定
│   └── brief_sources.yaml              # 简报来源
│
├── skills/                             # 下载的技能包（Phase 4+）
│   └── .gitkeep
│
└── tests/                              # 测试
    ├── __init__.py
    ├── conftest.py                     # pytest fixtures
    ├── test_qq_client.py               # QQ 客户端测试
    ├── test_brain.py                   # AI 核心测试
    ├── test_personality.py             # 性格引擎测试
    ├── test_memory.py                  # 记忆系统测试
    ├── test_tools.py                   # 工具层测试
    └── integration/                    # 集成测试
        ├── test_e2e_message_flow.py    # 端到端消息流测试
        └── test_ai_api.py              # AI API 连通性测试
```

### 3.2 核心 API 调用规范

#### 3.2.1 NapCatQQ OneBot11 WebSocket API

**连接地址**：`ws://localhost:3001`（需确认实际端口）

**接收消息事件**（OneBot11 → Python）：

```json
{
  "post_type": "message",
  "message_type": "private",
  "sub_type": "friend",
  "message_id": 123456,
  "user_id": 3489352115,
  "message": "今天天气怎么样",
  "raw_message": "今天天气怎么样",
  "font": 14,
  "sender": {
    "user_id": 3489352115,
    "nickname": "伊泽",
    "sex": "male",
    "age": 0
  },
  "time": 1690000000,
  "self_id": 3998874040
}
```

**发送消息请求**（Python → OneBot11）：

```json
{
  "action": "send_private_msg",
  "params": {
    "user_id": 3489352115,
    "message": "今天北京多云，24°C~32°C，适合出门哦～"
  }
}
```

**API Echo 机制**（请求-响应关联）：每个发送请求携带 `echo` 字段，响应中回传：

```json
// 请求
{"action": "send_private_msg", "params": {...}, "echo": "msg_001"}

// 响应
{"status": "ok", "retcode": 0, "data": {"message_id": 123457}, "echo": "msg_001"}
```

#### 3.2.2 AI API 调用规范（三级容灾）

```
主 API:    硅基流动 DeepSeek-V3  →  base_url: https://api.siliconflow.cn/v1
备选 API:  DeepSeek 官方         →  base_url: https://api.deepseek.com/v1
兜底 API:  智谱 GLM-4-Flash      →  base_url: https://open.bigmodel.cn/api/paas/v4
```

**调用参数**：

```python
response = client.chat.completions.create(
    model="deepseek-ai/DeepSeek-V3",  # 或 "deepseek-chat" / "glm-4-flash"
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ],
    temperature=0.8,       # 对话场景需要一定创造性
    max_tokens=1024,       # QQ 消息不宜过长
    top_p=0.9
)
```

**容灾策略**：

```python
class AIFailover:
    """三级 API 容灾：主→备→兜底"""
    
    PROVIDERS = [
        {
            "name": "siliconflow",
            "client": OpenAI(api_key=os.getenv("SILICONFLOW_API_KEY"),
                            base_url="https://api.siliconflow.cn/v1"),
            "model": "deepseek-ai/DeepSeek-V3"
        },
        {
            "name": "deepseek",
            "client": OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"),
                            base_url="https://api.deepseek.com/v1"),
            "model": "deepseek-chat"
        },
        {
            "name": "zhipu",
            "client": OpenAI(api_key=os.getenv("ZHIPUAI_API_KEY"),
                            base_url="https://open.bigmodel.cn/api/paas/v4"),
            "model": "glm-4-flash"
        }
    ]
    
    async def call(self, messages: list, timeout: float = 30.0) -> str:
        """依次尝试，任一成功即返回"""
        last_error = None
        for provider in self.PROVIDERS:
            try:
                resp = await asyncio.wait_for(
                    provider["client"].chat.completions.create(
                        model=provider["model"],
                        messages=messages,
                        temperature=0.8,
                        max_tokens=1024
                    ),
                    timeout=timeout
                )
                return resp.choices[0].message.content
            except Exception as e:
                last_error = e
                logger.warning(f"AI 提供商 {provider['name']} 失败: {e}")
                continue
        raise RuntimeError(f"所有 AI 提供商均失败，最后错误: {last_error}")
```

### 3.3 消息处理流程设计

#### 3.3.1 消息数据模型

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

class MessageType(Enum):
    PRIVATE = "private"     # 私聊
    GROUP = "group"         # 群聊
    TEMP = "temp"           # 临时会话

class Intent(Enum):
    CHAT = "chat"           # 闲聊
    COMMAND = "command"     # 命令（需要工具执行）
    QUERY = "query"         # 信息查询

@dataclass
class IncomingMessage:
    """收到的消息"""
    msg_id: int
    user_id: int
    user_nickname: str
    msg_type: MessageType
    content: str
    timestamp: datetime
    group_id: Optional[int] = None
    
@dataclass
class OutgoingReply:
    """待发送的回复"""
    user_id: int
    content: str
    msg_type: MessageType = MessageType.PRIVATE
    echo: str = field(default_factory=lambda: str(uuid4()))
```

#### 3.3.2 消息处理流程

```
收到 WebSocket 消息
    │
    ▼
┌─────────────────────┐
│ 1. 解析 + 过滤        │  ← 仅处理私聊，过滤群消息/系统通知
│    parse_message()    │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ 2. 限流检查          │  ← 防止高频消息导致 API 超量
│    rate_limit()      │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ 3. 构建上下文         │  ← 记忆检索 + 性格 Prompt 注入
│    build_context()   │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ 4. AI 生成回复       │  ← 三级容灾调用
│    generate_reply()  │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ 5. 发送回复          │  ← WebSocket → NapCatQQ → QQ 服务器
│    send_message()    │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ 6. 存入记忆          │  ← Mem0 + SQLite 双写
│    save_to_memory()  │
└─────────────────────┘
```

### 3.4 WebSocket 连接管理

```python
class QQClient:
    """NapCatQQ WebSocket 客户端"""
    
    def __init__(self, uri: str = "ws://localhost:3001"):
        self.uri = uri
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._reconnect_delay = 1  # 初始重连延迟（秒）
        self._max_reconnect_delay = 60  # 最大重连延迟
        self._running = False
        
    async def connect(self):
        """建立连接，带指数退避重连"""
        while self._running:
            try:
                self._ws = await websockets.connect(
                    self.uri,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5
                )
                self._reconnect_delay = 1  # 连接成功，重置延迟
                logger.info(f"已连接 NapCatQQ: {self.uri}")
                return
            except Exception as e:
                logger.error(f"连接失败: {e}，{self._reconnect_delay}s 后重试")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2,
                    self._max_reconnect_delay
                )
    
    async def listen(self, handler: Callable[[IncomingMessage], Awaitable[Optional[OutgoingReply]]]):
        """监听消息，回调处理"""
        async for raw in self._ws:
            data = json.loads(raw)
            
            # 只处理私聊消息
            if data.get("post_type") != "message":
                continue
            if data.get("message_type") != "private":
                continue
            
            msg = self._parse_message(data)
            reply = await handler(msg)
            
            if reply:
                await self._send_reply(reply)
    
    async def _send_reply(self, reply: OutgoingReply):
        """发送回复"""
        action = {
            "action": "send_private_msg",
            "params": {
                "user_id": reply.user_id,
                "message": reply.content
            },
            "echo": reply.echo
        }
        await self._ws.send(json.dumps(action))
```

---

## 四、开发环境配置与依赖管理

### 4.1 系统环境

| 组件 | 当前版本 | 要求 | 备注 |
|------|---------|------|------|
| OS | Windows 11 Pro 25H2 | Windows 10+ | 已满足 |
| Python | 3.14.3 | ≥ 3.10 | 已安装 |
| pip | 跟随 Python | ≥ 23.0 | 已安装 |
| Git | 2.54.0 | ≥ 2.30 | 已安装 |
| NapCatQQ | 4.18.9 | ≥ 4.0 | 已安装于 E:\NapCat\NapCat.Shell\ |

### 4.2 项目初始化步骤

```powershell
# 1. 创建项目目录
mkdir e:\Agent_reply\OpenCloud_Companion
cd e:\Agent_reply\OpenCloud_Companion

# 2. 创建虚拟环境
python -m venv .venv
.venv\Scripts\Activate.ps1

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
copy .env.example .env
# 编辑 .env 填入 API Key

# 5. 确认 NapCatQQ 配置
# 检查 E:\NapCat\NapCat.Shell\config\ 下 OneBot11 的 WebSocket 端口
```

### 4.3 Phase 1 依赖清单 (`requirements.txt`)

```
# QQ 通信
websockets>=12.0

# AI API（兼容 OpenAI SDK）
openai>=1.30.0

# 异步支持
anyio>=4.0.0

# 配置管理
pyyaml>=6.0
python-dotenv>=1.0.0

# 数据验证
pydantic>=2.0.0

# 日志
loguru>=0.7.0
```

### 4.4 环境变量 (`.env.example`)

```env
# ===== AI API Keys =====
# 硅基流动 (主 API) - 注册: https://siliconflow.cn
SILICONFLOW_API_KEY=redacted-provider-token

# DeepSeek (备选) - 注册: https://platform.deepseek.com
DEEPSEEK_API_KEY=redacted-provider-token

# 智谱 AI (兜底，免费) - 注册: https://open.bigmodel.cn
ZHIPUAI_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ===== NapCatQQ =====
NAPCAT_WS_URI=ws://localhost:3001

# ===== 日志 =====
LOG_LEVEL=INFO

# ===== 她的 QQ 号 =====
SELF_QQ=3998874040
```

### 4.5 主配置 (`config/settings.yaml`)

```yaml
# OpenCloud Companion 主配置文件

napcat:
  ws_uri: "ws://localhost:3001"   # NapCat OneBot11 WebSocket 地址
  self_qq: 3998874040              # 她登录的 QQ 号

ai:
  primary:
    provider: "siliconflow"
    model: "deepseek-ai/DeepSeek-V3"
  fallback:
    - provider: "deepseek"
      model: "deepseek-chat"
    - provider: "zhipu"
      model: "glm-4-flash"
  temperature: 0.8
  max_tokens: 1024
  timeout: 30  # 秒

personality:
  config_file: "config/persona.yaml"

memory:
  mem0_enabled: false              # Phase 2 启用
  chat_log_enabled: true           # Phase 1 记录日志即可
  chat_log_path: "data/chat_log.db"

logging:
  level: "INFO"
  file: "logs/companion.log"
  rotation: "10 MB"
  retention: "7 days"

rate_limit:
  max_per_minute: 20               # 每分钟最多处理消息数
  cooldown_seconds: 3              # 连续消息冷却时间
```

---

## 五、测试策略

### 5.1 测试框架与工具

| 工具 | 用途 |
|------|------|
| `pytest` + `pytest-asyncio` | 核心测试框架 |
| `pytest-mock` | Mock 外部依赖 |
| `pytest-cov` | 覆盖率报告 |
| `unittest.mock` | WebSocket、API 模拟 |
| `websockets` 测试服务器 | 模拟 NapCatQQ 行为 |

### 5.2 测试分层

#### 单元测试

| 模块 | 测试文件 | 重点覆盖 |
|------|---------|---------|
| 消息解析 | `test_qq_client.py` | 正常消息解析、异常消息过滤、群消息过滤、边界值 |
| AI 调用 | `test_brain.py` | Prompt 正确构建、API 容灾切换、超时处理、空/长文本 |
| 性格引擎 | `test_personality.py` | YAML 加载、Prompt 模板变量替换、缺失配置降级 |
| 消息模型 | `test_messages.py` | DTO 序列化/反序列化、类型验证 |

#### 集成测试

| 场景 | 测试方法 |
|------|---------|
| WebSocket 连接 → 消息收发 | 本地 mock 服务器模拟 OneBot11 协议 |
| AI API 连通性 | 用最小 Prompt 测试三家 API 是否能正常返回 |
| 端到端消息流 | 模拟消息 → AI 回复 → 发送的完整链路 |
| WebSocket 断线重连 | 模拟断线，验证指数退避重连 |

#### 验收标准

| 编号 | 验收项 | 通过条件 | 阶段 |
|------|--------|---------|------|
| AC-1 | QQ 消息接收 | 收到私聊消息后 500ms 内解析为 MessageDTO | Phase 1 |
| AC-2 | AI 回复生成 | 消息送达 AI API 后 5s 内生成回复 | Phase 1 |
| AC-3 | 消息发送 | 回复送达 QQ 服务器（retcode=0） | Phase 1 |
| AC-4 | 断线重连 | WebSocket 断开后 30s 内自动重连成功 | Phase 1 |
| AC-5 | API 容灾 | 主 API 不可用时自动切换至备选，整体 < 15s | Phase 1 |
| AC-6 | 端到端延迟 | 消息到达 → QQ 回复发出 < 10s (P95) | Phase 1 |
| AC-7 | 记忆连续性 | Mem0 正确检索最近相关记忆，注入 Prompt | Phase 2 |
| AC-8 | 性格一致性 | 100 轮对话中回复风格保持一致（人工评定） | Phase 2 |
| AC-9 | 工具调用 | AI 正确识别命令意图，调用工具并包装结果 | Phase 3 |
| AC-10 | 技能安装 | 技能包下载、安装、注册、调用全流程通过 | Phase 4 |

### 5.3 测试数据与环境

- **AI API 测试**：使用固定 Prompt + 固定响应 mock，不消耗真实 tokens
- **QQ 客户端测试**：本地 WebSocket 服务器模拟 NapCatQQ 行为
- **记忆测试**：预置对话数据集（20-50 轮），验证检索准确率
- **集成测试**：需要真实 NapCatQQ 环境，建议用 CI nightly 跑

---

## 六、项目进度安排与里程碑

### 6.1 总览时间线

```
2026 Q3                           2026 Q4                    2027 Q1
Jul        Aug        Sep         Oct   Nov   Dec         Jan   Feb   Mar
│          │          │            │     │     │           │     │     │
├─Phase 1──┤          │            │     │     │           │     │     │
│  MVP     │          │            │     │     │           │     │     │
│          ├─Phase 2──┤            │     │     │           │     │     │
│          │  性格+记忆│            │     │     │           │     │     │
│          │          ├─Phase 3────┤     │     │           │     │     │
│          │          │  工具+UI   │     │     │           │     │     │
│          │          │            ├─Phase 4──┤            │     │     │
│          │          │            │ 技能+知识库│           │     │     │
│          │          │            │           ├─Phase 5+──┤     │     │
│          │          │            │           │ 语音+打磨 │     │     │
```

### 6.2 详细里程碑

#### M1：Phase 1 启动（2026-07-15 ~ 2026-07-16）

| 任务 | 负责人 | 工时 |
|------|--------|------|
| 确认 NapCat OneBot11 WebSocket 端口 | 开发 | 0.5h |
| 申请三大 AI 平台 API Key | 开发 | 1h |
| 创建项目目录 + 虚拟环境 | 开发 | 0.5h |
| 安装 Phase 1 依赖 | 开发 | 0.5h |
| 配置 .env + settings.yaml | 开发 | 0.5h |
| **交付物**：环境就绪，依赖安装通过 `pip check` | | |

#### M2：Phase 1 核心开发（2026-07-17 ~ 2026-07-23）

| 任务 | 产出文件 | 优先级 |
|------|---------|--------|
| 实现消息数据模型 (DTO) | `communication/message.py` | P0 |
| 实现 QQ WebSocket 客户端 | `communication/qq_client.py` | P0 |
| 实现 AI 调用 + 容灾 | `core/brain.py` | P0 |
| 实现配置加载 | `config/` 相关 | P0 |
| 实现日志系统 | 集成于各模块 | P1 |
| 实现 main.py 入口 | `main.py` | P0 |
| 编写单元测试 | `tests/test_*.py` | P1 |
| **交付物**：手机 QQ 发消息，AI 回复，返回 QQ | | |

#### M3：Phase 1 联调 + 测试（2026-07-24 ~ 2026-07-28）

| 任务 | 描述 |
|------|------|
| 真实环境联调 | 手机 QQ → NapCatQQ → Python → AI → QQ 全链路跑通 |
| 异常场景测试 | 断网、API 超时、QQ 离线等 |
| 性能基准采集 | 端到端延迟、内存占用、API 调用次数 |
| Bug 修复 | 修完后重新跑验收标准 AC-1 ~ AC-6 |
| **交付物**：Phase 1 版本 `v0.1.0`，全部验收通过 | |

#### M4：Phase 2 性格 + 记忆（2026-07-29 ~ 2026-08-18）

| 周次 | 任务 |
|------|------|
| W5 | 性格引擎 (`personality.py`) + persona.yaml 设计 |
| W6 | Mem0 集成 + 记忆存储测试 |
| W7 | 对话分类器 + 上下文构建器 |
| W8 | Phase 2 联调 + 验收 (AC-7, AC-8) |
| **交付物**：版本 `v0.2.0`，她有性格、有记忆 | |

#### M5：Phase 3 工具 + UI（2026-08-19 ~ 2026-09-15）

| 周次 | 任务 |
|------|------|
| W9-10 | 内置工具开发（file_ops, system_ops, web_ops, todo_manager） |
| W11 | Function Calling 集成 + 命令执行流水线 |
| W12 | PyQt6 悬浮球 + 对话窗口 |
| W13 | Phase 3 联调 + 验收 (AC-9) |
| **交付物**：版本 `v0.3.0`，她能操作电脑，桌面有悬浮球 | |

#### M6：Phase 4 技能 + 知识库（2026-09-16 ~ 2026-10-13）

| 周次 | 任务 |
|------|------|
| W14-15 | 技能管理器 + QQ 审批流程 |
| W16 | Markitdown 文档管道 |
| W17 | 自主知识库（采集 + 分类 + 重组） |
| **交付物**：版本 `v0.4.0`，她能自己学新技能，知识库自管理 | |

#### M7：Phase 5+ 持续迭代（2026-10-14+）

| 任务 | 描述 |
|------|------|
| 语音输入/输出 | SpeechRecognition + pyttsx3 |
| 每日简报 | APScheduler + 新闻聚合 |
| 主动关怀 | 天气提醒、晚安问候、待办催办 |
| 设置面板 | PyQt6 可视化配置 |
| 性能优化 | 冷启动加速、并发消息处理、缓存策略 |
| 打磨 | 交互细节、错误提示、体验优化 |

---

## 七、风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| NapCatQQ 版本升级导致 WebSocket 协议变化 | 中 | 高 | 锁定已知稳定版本，升级前测试 |
| 腾讯封禁机器人账号 | 低 | 高 | 使用独立小号，控制消息频率 |
| AI API 全部不可用 | 低 | 高 | 三级容灾 + 本地模型备选（Ollama） |
| API 费用超出预算 | 低 | 中 | 设置用量告警，优先使用免费 API |
| E 盘剩余空间不足 (24GB) | 中 | 中 | 定期清理日志和缓存，知识库使用轻量存储 |
| Mem0 依赖冲突 | 中 | 低 | 使用虚拟环境隔离，锁定版本号 |

---

## 八、开发规范

### 8.1 代码规范

- 使用 `black` 格式化，`ruff` 做 linting
- 类型注解覆盖率 ≥ 80%
- 所有公共函数有 docstring（Google 风格）
- 异步 IO 统一使用 `asyncio`

### 8.2 Git 工作流

```
main ←── develop ←── feature/phase1-qq-client
                    ←── feature/phase1-ai-brain
                    ←── feature/phase2-personality
                    ...
```

- `main` 分支：稳定版本，每个 Phase 结束时合并
- `develop` 分支：日常开发
- `feature/*` 分支：各模块独立开发
- Commit 格式：`[Phase1] feat(qq_client): 实现 WebSocket 断线重连`

### 8.3 版本号规则

- `v0.1.0` → Phase 1 完成
- `v0.2.0` → Phase 2 完成
- `v0.2.1` → Phase 2 的 Bug 修复
- 以此类推

---

## 九、Phase 1 首日检查清单

在开始写代码之前，必须先确认以下项全部通过：

- [ ] NapCatQQ 已在 `E:\NapCat\NapCat.Shell\` 正常运行
- [ ] OneBot11 WebSocket 端口已确认（默认 3001，实际值需验证）
- [ ] 硅基流动 API Key 已申请（https://siliconflow.cn → 右上角「API 密钥」）
- [ ] DeepSeek API Key 已申请（https://platform.deepseek.com/api_keys）
- [ ] 智谱 AI API Key 已申请（https://open.bigmodel.cn → 「API Keys」）
- [ ] Python 3.10+ 虚拟环境已创建
- [ ] `.env` 文件已配置，三组 API Key 已填入
- [ ] 能通过 `python -c "import websockets; import openai; print('OK')"` 验证依赖
