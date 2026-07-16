# 统一消息层重构方案

## 业界调研结论

### 主流做法

| 方案 | 适用场景 | 我们的对齐度 |
|------|---------|-------------|
| **主进程广播 IPC** (AionUi, electron-better-ipc) | 后端 → main → `webContents.send()` 给所有窗口 | **已实现** — `_emitChatEvent` 已向 mainWindow/floatingChat/floatingBall 发送 |
| **Broadcast Channel API** | 纯浏览器多 Tab / 同源窗口同步 | **不需要** — 我们已有 IPC 广播 |
| **electron-state-sync / pinia-plugin-electron-share** | Vue/React 状态管理 | **不需要** — 我们不是 SPA 框架 |

**结论**：我们的架构（Python stderr → Electron main → IPC 广播 → 多窗口消费）本身就是业界标准做法。问题不在架构，在消费端。

### 现有基础设施（不需要改）

```
Python 后端
  ├─ pipeline.py → emit("user"/"assistant") → stderr [CHAT_EVENT]
  └─ api_server.py → HTTP API（历史/轮询/发送）

Electron main.js
  ├─ handleLogStream() → 解析 [CHAT_EVENT] → _emitChatEvent(payload)
  └─ _emitChatEvent() → webContents.send('chat:message') 给所有窗口 ✅

Electron preload.js
  └─ 'chat:message' 已在 validChannels ✅
```

### 根因：消费端三个致命断点

| # | 文件 | 断点 | 影响 |
|---|------|------|------|
| 1 | chat.js:94,110 | history/poll 缺 user_id → 默认 0 → DB 存 master_qq → 永远查不到 | **主窗口零消息** |
| 2 | chat.js:151 | HTTP 返回了 reply 但代码直接丢弃，不渲染 | **主窗口零回复** |
| 3 | chat.js 全文 | 不监听 `chat:message` IPC | **跨窗口完全隔离** |
| 4 | pipeline.py:160 | 本地消息（聊天条）也 enqueue 到 SendQueue → 发给自己 QQ | **消息泄漏到QQ** |
| 5 | floating-chat.js:72-88 | HTTP + IPC 双通道同一消息，无去重 | **每条回复显示两次** |

---

## 修复方案

### 改动 1：pipeline.py — 本地消息不发给 QQ

**文件**：`core/pipeline.py`  
**位置**：`_handle_full()` 方法，第 160 行  
**现状**：无论消息来源，reply 都无条件 `self.queue.enqueue(reply, splitter=True)`  
**改为**：检查 `msg.source`，`source="local"` 的消息不 enqueue（本地聊天条回复不需要发到 QQ）

```python
# 第 158-160 行改为：
source = getattr(msg, "source", "qq") or "qq"
if source != "local":
    self.queue.enqueue(reply, splitter=True)
```

### 改动 2：api_server.py — chat_history/chat_poll 默认 user_id

**文件**：`core/api_server.py`  
**位置**：`chat_history()` 第 271-280 行，`chat_poll()` 第 283-291 行  
**现状**：`user_id = int(request.query.get("user_id", 0))` → 默认 0  
**改为**：默认值从 settings 读取 self_qq（3998874040）

```python
def _default_user_id() -> int:
    try:
        return int(load_settings().get("qq", {}).get("self_qq", 0))
    except Exception:
        return 0

async def chat_history(request):
    user_id = int(request.query.get("user_id", _default_user_id()))
    ...
```

### 改动 3：chat.js — 监听到 IPC push 直接渲染

**文件**：`electron/src/renderer/js/chat.js`  
**改动点**：

1. **新增 `chat:message` IPC 监听**（第 222-243 行 DOMContentLoaded 区域）
   - 接收 `chat:message` 事件
   - 解析 `payload.type`，user/assistant/notification
   - 调用已有的 `renderMessage()` 渲染（已有 ID 去重）

2. **修复 history/poll 请求**（第 94、110 行）
   - 添加上下文获取 master_qq，传入 `?user_id=<master_qq>`

3. **渲染 HTTP 回复**（第 150-158 行 `sendCurrent`）
   - HTTP 返回的 `data.reply` 也渲染（用 data 的 id 或时间戳做去重）
   - 不再只做乐观本地 echo

### 改动 4：floating-chat.js — 消息去重 + user_id 修正

**文件**：`electron/src/renderer/js/floating-chat.js`  
**改动点**：

1. **消息去重**：`renderMessage()` 引入 `Set` 跟踪已渲染的 DB id
2. **history 查询加上 user_id**：`loadHistory()` 的请求 URL 追加 `?user_id=<master_qq>`

---

## 改动汇总

| 文件 | 改动行数 | 性质 |
|------|---------|------|
| `core/pipeline.py` | ~3 行 | source 判断跳过 SendQueue |
| `core/api_server.py` | ~6 行 | history/poll 默认 user_id |
| `chat.js` | ~30 行 | IPC 监听 + user_id 参数 + HTTP reply 渲染 |
| `floating-chat.js` | ~15 行 | ID 去重 + user_id 参数 |

不改的东西：
- main.js 的 `_emitChatEvent` / `handleLogStream` — 已经是正确模式
- preload.js — 已有 `chat:message` 通道
- pipeline.py 的 emit 逻辑 — 正确
- napcat_launcher.py — 本次不涉及

---

## 验证步骤

1. 启动 `start-dev.bat`
2. 在聊天条发消息 → 应该看到 AI 回复（且回复不再发给 QQ）
3. 在主窗口发消息 → 应该看到 AI 回复
4. 在聊天条发消息 → 切到主窗口 → 应该看到相同的历史
5. 如果 QQ 已连接，在 QQ 发消息 → 聊天条和主窗口都应该看到
6. 刷新页面 → 历史消息正常加载

## 假设 & 决策

- **user_id 统一为 config 中的 self_qq**：所有本地消息（聊天条、主窗口）都用同一个 user_id 写入 DB 和查询
- **IPC push 为主，HTTP 回执 + polling 为辅**：IPC 是实时通道，HTTP 是确认和兜底
- **不引入新依赖**：现有 Node.js + Electron + vanilla JS 已足够
