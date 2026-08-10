---
title: 聊天渲染层重构 · 代码修改清单与技术路线图
date: 2026-08-11
tags:
  - refactor
  - frontend
  - chat
  - plan
status: approved
aliases:
  - 聊天渲染重构计划
cssclasses:
  - wide
---

# 聊天渲染层重构 · 代码修改清单与技术路线图

> [!important] 目标
> 把聊天消息列表重写为主流架构：**单一消息 Store + 稳定 key 增量渲染 + 请求状态分离 + 虚拟滚动**，一次性修复三个历史 bug：
>
> 1. **同一条消息重复渲染**（多通道信号 domId 分裂）
> 2. **typing/生成中气泡残留**（typing 绕过 Store 直建 DOM + sequence 卡死）
> 3. **用户消息下出现"生成中/取消"按钮**（请求状态错误挂到 user 气泡）
>
> 约束：**只动 2 个文件**（`chat-store.js` + `chat.js`），所有外部契约与公共方法签名保持不变，后端一行不动，git 可随时回滚。

## 背景 · 根因（为什么会有这三个 bug）

> [!bug] 根因一 · 多通道 domId 分裂
> 消息有四条到达通道：**IPC 事件 / SSE / 3s poll / 历史分页**。去重只靠 `seenRealIds` 一个全局 Set，而 domId 由"通道形态"决定（事件带 `request_id` → `req_xxx`；poll/历史裸行 → 真实 id；乐观气泡 → `client_xxx`）。同一条逻辑消息两种形态并存 → **重复渲染**。

> [!bug] 根因二 · typing 气泡绕过 Store
> [chat.js](electron/src/renderer/js/chat.js) 的 `_syncRequestTypingBubble` 用硬编码 `req_<request_id>` **绕过 Store 直建 DOM**，真实分片替换依赖 Store 的 assistant 分支，两条路径的 domId 体系不一致，被 poll 先到 / sequence 丢失 / 重启 restore 三条路径破坏 → **typing 残留**。

> [!bug] 根因三 · 请求状态错误挂载
> `_renderRequestStatus` 的 `clientId` fallback 把 assistant 请求状态徽标挂到 **user 乐观气泡**元素上并写入 `data-request-id`，之后 `querySelector([data-request-id])` 永远先命中 user 消息 → **user 消息下出现"生成中/取消"**。

> [!note] 现状：三套并行状态
> 目前是 **Store `requests` + chat.js `_requests` + DOM 裁剪**三套独立状态，各自维护、边界不清。本次重写统一为 **单一 Store**。

---

## 技术路线图（三步）

### Step 1 · 契约锁定

> [!todo]- Step 1：补契约测试，锁定现有 API 行为（不写业务代码）
> - [ ] 把 13 个公共符号签名以 JSDoc 形式写入新 `chat.js` 头部
> - [ ] 编写 `electron/tests/chat-render-contract.test.js`：用 vm 加载新 `chat-store.js`，断言 `createChatStore` API 行为
> - [ ] 运行现有 `chat-store.test.js` / `chat-request-queue.test.js`，作为行为基线
> - [ ] 产出"契约基线"git commit（回滚点 R0）

**验证**：`npm test`（electron/tests）全绿。

### Step 2 · 重写 chat-store.js（单一消息 Store）

> [!todo]- Step 2：重写消息状态层
> - [ ] **统一消息模型**：`Message { id, domId, msgId, role, content, status, requestId, replyTo, attachments, recalled, ts, source, scene }`
> - [ ] **稳定 key 归一化**：所有通道信号先经 `normalizeSignal()` 归一到同一 `id`（`msgId || realId || clientId`），消灭 domId 分裂
> - [ ] **单一请求状态**：`requests` Map 内聚请求生命周期（queued/running/completed/failed/cancelled），移除 chat.js 侧重复的 `_requests`
> - [ ] **typing 进 Store**：typing 气泡与真实分片共用同一 domId，真实分片到达时原地替换，终态强制清理
> - [ ] **requestSequences 容错**：sequence 丢失时超时（3s）跳过 gap 继续消费，避免缓冲卡死
> - [ ] **去重策略升级**：`seenEventIds`（事件级）+ `byId`（消息级）双层去重，key 从"通道形态"改为"逻辑消息 id"
> - [ ] **裁剪统一**：`maxMessages` 单轨裁剪（替换 Store trim 与 DOM trim 双轨）
> - [ ] 保持 `createChatStore({ maxMessages })` 入口与 `messages()/getMessage/requestState/markRecalled/ingestSignal` 语义
> - [ ] 跑 `chat-store.test.js` / `chat-request-queue.test.js` 回归，失败则同步更新测试断言

**验证**：Store 单测全绿；后端事件重放不产生重复/残留。

### Step 3 · 重写 chat.js 渲染层

> [!todo]- Step 3：渲染层重写
> - [ ] **单一消息列表渲染**：`_reconcileMessage` 改按稳定 key 增量 upsert，事件只更新对应元素
> - [ ] **请求状态组件化**：`_renderRequestStatus` 从"宿主消息"解耦——状态徽标渲染为独立元素，挂在 assistant 消息上（`data-request-id` 只写 assistant），user 消息永不带请求状态
> - [ ] **虚拟滚动**（TanStack Virtual 思路，无依赖手写）：`anchorTo:'end'` + 只渲染可视区 + `followOnAppend`（仅底部时跟随）+ 上滚加载 older 保位
> - [ ] **typing 渲染**：统一走 Store 的 typing intent，不绕过
> - [ ] **恢复重启态**：`restorePendingRequests` 改为从 Store 恢复，不再把真实消息覆盖回 typing
> - [ ] 保留全部 DOM 语义（`.chat-msg` 结构、`data-id/data-msg-id/data-request-id`、`#chat-input` 等）与 `content-visibility:auto`
> - [ ] 保留 `window._chat` 13 个公共符号（见下）与全部事件/HTTP/localStorage 契约
> - [ ] e2e 桌面冒烟（desktop-audit）+ 真机 QQ 收发验证

**验证**：三个 bug 场景逐一复现验证修复；`renderer-performance.test.js` 的 `content-visibility` 断言保持。

---

## 必须保留的公共方法签名（window._chat）

> [!warning] 契约红线
> 以下 13 个符号被外部模块调用，**重写后签名与语义必须完全不变**。逐一列出调用方。

| # | 符号 | 签名（JSDoc） | 调用方 |
|---|---|---|---|
| 1 | `send` | `async send(): Promise<void>` — 发送输入框内容+附件到 `/api/chat/send` | `cognition-panel.js` L1035 |
| 2 | `setUserAvatar` | `setUserAvatar(dataurl: string): void` — 写入本地缓存+刷新头像 DOM | `settings.js` L722 |
| 3 | `setUserName` | `setUserName(name: string): void` — 写入本地缓存+刷新名字 DOM | `settings.js` L732 |
| 4 | `_writeLocalAvatar` | `_writeLocalAvatar(side: 'user'\|'persona', dataurl: string): void` | `settings.js` L823-828/L862-867 |
| 5 | `_loadPersona` | `async _loadPersona(): Promise<void>` — GET `/api/persona` 刷新人设缓存 | `settings.js` L911-912 |
| 6 | `_openAttachment` | `async _openAttachment(attachmentId: string): Promise<void>` | `data-viewer.js` L38-41 |
| 7 | `_retryAttachment` | `async _retryAttachment(attachmentId: string): Promise<void>` | `data-viewer.js` L41 |
| 8 | `_buildAttachmentCard` | `_buildAttachmentCard(att: object): string` — 返回 HTML | `data-viewer.js` L126 |
| 9 | `_request` | `async _request(opts: {method: string, path: string, body?: object}): Promise<object>` | `chat-uploader.js` L30/193/222/239 |
| 10 | `_pendingAttachments` | `(属性) Array<Attachment>` — 待发送附件数组（可读写） | `chat-uploader.js` L141-252；e2e `desktop-audit.js` L1648 |
| 11 | `_renderAttachmentPreviews` | `_renderAttachmentPreviews(): void` | `chat-uploader.js` L142/177/184/202/... |
| 12 | `_userName` | `(属性) string` — 当前用户名 | `settings.js` L670-671 |
| 13 | `_userDataurl` | `(属性) string` — 当前用户头像 dataURL | `settings.js` L674-675 |

> [!note] Store 层必须保留的 API
> `createChatStore({ maxMessages })`（`window.createChatStore` + node `module.exports` 双暴露）、`ingestSignal(signal, transport)`、`messages()`、`getMessage(domId)`、`requestState(requestId)`、`markRecalled(id)`，以及暴露的 `clientIdToDomId / requestIdToDomId / seenEventIds / requestSequences / requests`（chat.js L980-985 直接读 `clientIdToDomId`）。

---

## 保留边界清单（不可破坏）

> [!abstract] 契约清单
> 1. **全局符号**：`window.createChatStore`、`window._chat`、`window.ChatUploader` / `window.ChatVoice`（可选构造）
> 2. **事件协议**：`user` / `assistant` / `recall` / `chat_request_running/completed/failed/cancelled` 的 payload 字段；`_ingestChatSignal` 过滤条件（`request_id || event_id || type==='recall' || role∈{user,assistant}`）
> 3. **HTTP API**：`/api/chat/send`（202+request_id）、`/history/page`（items/olderCursor/newerCursor/hasOlder/hasNewer）、`/poll`、`/recall/{id}`、`/requests/{id}` 及 cancel/retry（RequestStatusView 字段）
> 4. **DOM 语义**：`.chat-msg` 系列结构、`data-id/data-msg-id/data-request-id/data-request-status/data-chat-typing`、`.chat-empty`、`content-visibility:auto`（测试断言）、输入区 ID（`#chat-input/#chat-send-btn/#chat-attach-btn/#chat-mic-btn/#chat-office-btn/#chat-brief-btn/#chat-file-input/#chat-mic-status`）
> 5. **localStorage 键**：`aerie.chat.pending_requests`、`aerie.user.avatar`、`aerie.user.name`、`aerie.persona.avatar`
> 6. **自定义事件**：监听 `aerie:persona-updated`；派发 `window.bus.emit('brief:open')`
> 7. **图片渲染协议**：`content="![图片](url)"` 的相对路径改写 `http://127.0.0.1:7890`（file:// 无法解析）
> 8. **脚本加载顺序**：vendor(marked/purify/highlight) → chat-store → chat → chat-voice → chat-uploader

---

## 验证与回滚

> [!success] 验证门禁
> - 单元：`chat-store.test.js`、`chat-request-queue.test.js`、`chat-render-contract.test.js`、`renderer-performance.test.js`
> - e2e：`desktop-audit.js` + 真机 QQ 收发/撤回/发图验证
> - 手动复现三个 bug 场景：发送多条消息、快速连续发送、滚动后新消息、重启后恢复

> [!warning] 回滚方案
> 每个 Step 完成后单独 commit（R0 基线 → R1 Store → R2 渲染），任何一步验证失败即 `git checkout -- <file>` 或 `git revert` 回退，后端与数据零影响。

---

## 产出物

| 文件 | 改动 |
|---|---|
| `electron/src/renderer/js/chat-store.js` | 重写（单一 Store + 稳定 key + 状态内聚 + sequence 容错） |
| `electron/src/renderer/js/chat.js` | 重写（增量渲染 + 状态组件化 + 虚拟滚动），保留公共签名 |
| `electron/tests/chat-render-contract.test.js` | 新增（契约基线测试） |
| `electron/tests/chat-store.test.js` / `chat-request-queue.test.js` | 视情况同步断言 |

> [!info] 范围确认
> 后端 `core/*`、`electron/src/main.js`、`preload.js`、`main.css`、其他 renderer 模块 **全部不动**。
