# QQ 图片消息实时渲染修复计划

> Plan: Fix QQ image realtime rendering
> 状态 Status: `implemented`（2026-08-11 已执行并验证 / implemented & verified）
> 日期 Date: 2026-08-11
> 相关模块 Modules: `core/pipeline.py` · `electron/src/renderer/js/chat.js` · `chat-store.js`
> 涉及通道 Channels: IPC 实时事件 · SSE 实时事件 · `/api/chat/poll` · 历史加载

---

## 1. 背景 Background

QQ 发来的图片消息（含 `category=image` 的附件），**后台数据（数据库/API）能看到图片本体，但聊天框里看不到**。

The user reported: the QQ image message has its attachment visible in the backend data (DB / API), but no image is shown in the chat bubble.

---

## 2. 论证 Argumentation

### 2.1 逐层核验结果（Layer-by-layer verification）

对整条链路 6 层做了实机核验，全部通过，**排除数据污染与渲染逻辑缺失**：

| 层级 Layer | 状况 Status | 证据 Evidence |
|---|---|---|
| 数据库 Database | ✅ 附件完整 | `chat_log.id=2494` 附件 JSON 含 `category=image`、`thumbnailUrl`、`url` |
| 文件落盘 File on disk | ✅ 存在 | 原图 + 缩略图均在 `uploads/` 下 |
| HTTP 服务 Static serving | ✅ 200 | `/uploads/….png` 两个 URL 均返回 200 |
| 历史接口 History API | ✅ 带附件 | `/api/chat/history/page` 返回 `ATT:image` |
| 渲染函数 Renderer | ✅ 生成 `<img>` | `_buildAttachmentCard` 对 image 分类正确产出图片卡片 |
| CSS / CSP | ✅ 不隐藏 | `.chat-attach-card--image` 规则正常，`index.html` 无 CSP |

### 2.2 根因 Root cause

**实时事件通道丢掉了 `attachments` 字段（不是数据污染，是"实时事件没传 / 去重没补"）。**

The realtime event channel drops the `attachments` field. This is NOT data pollution — it is "realtime event payload omits attachments" plus "dedup blocks the fix-up".

1. 后端持久化时**带**附件：`core/pipeline.py` 落库 `attachments` 字段。
2. 后端实时推送事件**不带**附件：`core/pipeline.py` 三处 `emit("user"/"assistant", ...)` 只传 `content`，未传 `attachments`。
   - [pipeline.py L683-690](file:///e:\Agent_reply\core\pipeline.py#L683-L692)（user 事件）
   - [pipeline.py L1963-1974](file:///e:\Agent_reply\core\pipeline.py#L1963-L1976)（user 事件）
   - [pipeline.py L1983-1997](file:///e:\Agent_reply\core\pipeline.py#L1983-L1997)（assistant 事件）
3. 前端实时渲染走 IPC 与 SSE 两条通道（[chat.js L319-345](file:///e:\Agent_reply\electron\src\renderer\js\chat.js#L319-L345)），数据源正是上述不带附件的 emit → 只渲染出文本 `[图片:…]`，无图片卡片。
4. 带附件的 `/api/chat/poll`（[chat.js L491-505](file:///e:\Agent_reply\electron\src\renderer\js\chat.js#L491-L505)）虽能拉到带图数据，但 store 同 id 去重 `if (byKey.has(key)) return`（[chat-store.js L211-218](file:///e:\Agent_reply\electron\src\renderer\js\chat-store.js#L210-L219)）会**拒绝二次渲染** → 图片永远补不上来。

**成因判定 Conclusion**：非数据污染，是 ——
- 后端实时事件载荷缺 `attachments` 字段（"没传全"）；
- 前端去重逻辑不感知"先无图后有图"，未做附件补齐（"没接住"）。

因此现象为：**刷新/历史能看图，实时到达的 QQ 图看不到**。

---

## 3. 开源主流做法 Open-source reference

主流 QQ 机器人生态的核心原则：**消息是"结构化消息段数组"（message segments），图片是头等公民，传输层必须完整保留。**

- **OneBot v11 标准** [segment.md](https://github.com/botuniverse/onebot-11/blob/master/message/segment.md)：图片即 `{"type":"image","data":{"file":"…","url":"…"}}`，与文本平级。
- **NapCat / openclaw_qq**：服务端通过 WebSocket 推送事件时，事件载荷即完整消息段数组，前端按段渲染（text→文本气泡、image→图片气泡）。
- **Nonebot2**：`MessageSegment.image()` 以结构化单元传递图片，不塞进字符串再丢字段。
- 关键点：**消息从"收到→持久化→实时事件→前端渲染"整条链上，结构化附件信息全程不能丢**，且**同一消息的实时与历史渲染必须一致**。

本项目症结：扁平化模型（内容字符串 + 附件附加）中，**实时事件这一环没有把附件带全**，违背了"结构化单元全程保留"原则。

---

## 4. 修复方案 Solution

**原则：A 治本（实时事件补传附件）为主，B 兜底（store 附件补齐）为辅。** 两者一起上，符合"最小改动 + 闭环"偏好。

Principle: A (add attachments to realtime events, root fix) primary; B (store attachment backfill) as defense-in-depth. Apply both.

### 方案 A：实时事件补传附件（治本 / Root fix）

- **改动文件 File**: `core/pipeline.py`
- **改动内容 Change**: 三处 `emit("user"/"assistant", ...)` 补传 `attachments`（复用落库时的 `msg.attachments`，序列化方式与落库一致）。
- **收益 Benefit**: IPC/SSE 实时事件天然带图，前端现有渲染逻辑无需改动即可实时出图；实时/历史天然一致。
- **需确认 To verify**:
  1. Electron 主进程解析 `[CHAT_EVENT]` 时能透传 `attachments`；
  2. SSE `/api/events/stream` 序列化不丢该字段；
  3. 事件契约 `event_contracts.py` 是否需要登记新字段。

### 方案 B：store 支持"附件补齐"（兜底 / Defense）

- **改动文件 Files**: `electron/src/renderer/js/chat-store.js` · `chat.js`
- **改动内容 Change**: 放宽去重——同一 `domId` 已渲染但**当前无附件**、新到的同 id 消息**带附件**时，允许二次 upsert 补上图片卡片，而非直接 `return`。
- **收益 Benefit**: 兜住所有"先无图后有图"的时序，对历史遗留数据也生效。
- **注意 Caveat**: 仅当"旧无附件、新有附件"时放行，避免无谓重复渲染；控制重新渲染成本。

### 不做的事 Out of scope
- 不改数据库结构、不做迁移（无需）。
- 不改历史接口（历史已带附件，正常）。
- 不引入新依赖。

---

## 5. 实施步骤 Implementation steps

1. **后端（方案 A）**
   - 在 `core/pipeline.py` 三处 `emit("user"/"assistant", ...)` 补传 `attachments`。
   - 核对 `core/event_contracts.py` 事件契约，登记附件字段（如有白名单）。
   - 核对 Electron 主进程 `[CHAT_EVENT]` stderr 解析与 IPC 透传是否保留 `attachments`。
2. **前端兜底（方案 B）**
   - 修改 `chat-store.js` 去重逻辑：同 domId 且"旧无附件、新有附件"时允许补图。
   - 在 `chat.js` reconcile 链路确认补图后能正确渲染图片卡片。
3. **验证（方案 A 先行）**
   - 先只做 A，验证实时出图。
   - 再叠加 B，验证兜底场景。

## 5.1 实施记录 Implementation log（2026-08-11）

| 项 Item | 改动 Change | 验证 Verification |
|---|---|---|
| 方案 A | `pipeline.py` **4 处** user emit 补传 `attachments`（L683 / L822 / L2028 / 批量路径 L3030） | `py_compile` 通过；emit 实测输出 `[CHAT_EVENT]` 载荷含 `attachments` 与 `thumbnailUrl` ✅ |
| 方案 B | `chat-store.js` 新增 `backfillAttachmentDomId()`，user 与历史消息去重路径放行"旧无附件、新有附件"补图 | 新增 3 契约测试，chat-store 11/11 全绿；chat 全量 50/50 全绿 ✅ |
| 端到端 | 真实 id=2494 附件数据 → store 补图 → `_buildAttachmentCard` 渲染 | 产出 `<img src="http://127.0.0.1:7890/uploads/.image_assets/thumbs/….png">` 完整图片卡片 ✅ |

- Electron 主进程 `emitChatEvent`（main.js L586-593）整体透传 payload，`attachments` 无需白名单登记。
- 既有失败（与本次无关）：`napcat-panel.test.js` 断言 CSS `.status-qq-badge--error` 缺失；`attachment-card-renderer.test.js` audio 卡片无打开按钮。

---

## 6. 验收标准 Acceptance criteria

- [x] 实时到达的 QQ 图片消息，聊天框内能立即渲染出图片卡片（非仅文本 `[图片:…]`）— emit 载荷带附件 + store 补图 + 渲染验证通过。
- [x] 历史加载 / 刷新后仍能正常显示图片（回归不破坏）— 历史接口本就带附件，回归测试 50/50 全绿。
- [x] 普通文本消息实时渲染不受影响（回归不破坏）— 测试全绿。
- [x] 触发 B 兜底场景（先无图后有图）时能补齐图片，且不产生重复气泡 — 3 个契约测试覆盖。
- [x] 无新增图片加载 404 / CORS 报错 — 缩略图 HTTP 200，绝对 URL 验证通过。

---

## 7. 风险与备注 Risks & notes

- 方案 A 需打通 Electron IPC 透传附件字段，若 stderr 解析为"白名单字段"，需登记后才能生效。
- 方案 B 的"有附件才补"判定需精确，避免把正常消息误判为补图导致闪动。
- 本计划仅记录方案与步骤，**尚未执行任何代码改动**。

This document is a plan only. No code has been modified.

---

# 附加：QQ 消息接收链路排查与修复计划（NapCat WS 断连）

> Addendum: QQ message ingestion troubleshooting & fix plan (NapCat WS drop)
> 状态 Status: `implemented`（2026-08-11 已执行并验证 / implemented & verified）
> 影响面 Impact: 手机 QQ 消息能否进入系统（"手机发了但系统没收到"）

## A1. 背景 Background

用户反馈：**QQ 手机端发送的消息，多次出现"系统没收到"**。

User reported: QQ messages sent from the mobile client are frequently not received by the system.

现象特征：手机发消息后无任何反应，重启 NapCat / 后端后恢复。这不同于上一个 QQ 图片渲染问题——那个是"数据到了但前端没显示"，**这个是"消息根本没进系统"**。

## A2. 论证 Argumentation（证据链 Evidence chain）

QQ 消息接收统一在 [_dispatch](file:///e:\Agent_reply\communication\qq_client.py#L364-L421) 打印 `QQ <-` 日志。全量翻查日志后，`heartbeat timeout forced reconnect` 共出现 **2 次**，每次都伴随长时间无连接真空期：

| 心跳超时 | 下一次 WS 连接 | 真空时长 | 期间 QQ 消息 |
|---|---|---|---|
| 08-11 **06:21:09** | 08-11 10:21:18 | **约 4 小时** | 全丢（06:21 后无任何 `QQ <-`）|
| 08-11 **11:31:02** | 08-11 12:41:33（重启）| **约 70 分钟** | 全丢（11:31 后无任何 `QQ <-`）|

关键事实 Key facts:
1. main.log 最后一条 `QQ <-` 是 **11:30:23**（方向盘图片），41 秒后 11:31:02 心跳超时强制重连，之后手机消息全部未进入系统。
2. 真空期里后端**没有打印 `QQ WS connection error`** → 说明它一直卡在 [_port_is_open](file:///e:\Agent_reply\communication\qq_client.py#L53) 等待 3001 端口，即 **NapCat 这边根本没起来**。
3. 直到 12:41 后端重启（`disconnected→ws_connected→logged_in`）才恢复。
4. 当前系统实际是健康的：NapCat 3001 端口 LISTENING、12:41 后心跳正常（12:56~13:26）。

**根因定位 Root cause**：[napcat_launcher.py](file:///e:\Agent_reply\core\napcat_launcher.py#L4) 顶部注释明确写着“**Does NOT auto-start — user clicks 'Start' in the UI**”。

NapCat 是**手动启动、无 watchdog 自动重启**。一旦 NapCat 进程退出（launcher 日志大量 `Process exited`）或 WS 半开（心跳超时），后端 `connect()` 会无限等待 3001 端口，但 **NapCat 不会自己起来** → 长时间死等，期间手机消息全部不到达后端。只有手动重启 NapCat / 后端才恢复——这正好对应"多次发了没反应、重启一下又好了"。

**成因判定 Conclusion**：不是数据问题，是**传输层（NapCat↔后端 WS）断连后无法自动恢复**。消息根本没到达后端 WS，故无任何日志、无落库。

## A3. 开源主流做法 Open-source reference

NapCat 作为 OneBot v11 实现，其官方定位是**常驻服务进程**，上层框架（如 napcat.onebot 客户端 / Nonebot 的 `onebot` 适配器）通常依赖 NapCat 自身或进程管理器（pm2 / docker restart / supervisord）保证存活。

常见看护模式：
- **pm2 / docker restart 策略**：进程崩溃自动拉起。
- **adapter 侧重连 + 主动拉起**：上层检测到 WS 断连后，不只等待端口，而是主动调用启动命令把 NapCat 拉起来。
- 关键点：**"只等端口" 是被动且脆弱的**——一旦对端进程死了且无人拉起，等端口会永远等不到。健康做法是"探活端口 + 探活进程 + 主动拉起"闭环。

本项目现状：仅"等端口"，缺少"拉起"，故断连后无法自愈。

## A4. 修复方案 Solution

**原则：给 NapCat 加"自动拉起/看护"闭环，让断连后能自愈。** 不改消息处理逻辑。

Principle: add an auto-supervision/respawn loop for NapCat so the system self-heals after a drop. No change to message-handling logic.

### 方案 1：launcher 增加 watchdog 自动重启（治本 / Root fix）

- **改动文件 File**: `core/napcat_launcher.py`
- **改动内容 Change**: 在 launcher 内增加进程存活看护——监测 NapCat 进程退出后自动重新 spawn（而不是仅手动 Start），并发起 3001 端口就绪检查。
- **收益 Benefit**: NapCat 崩溃/退出后自动拉起，后端等端口能等到，消息不再长时间丢失。
- **需确认 To verify**:
  1. 与原"手动 Start"UI 的交互（改为托管后是否仍允许手动停止）。
  2. 防止冷启动时"端口未就绪"被误判为崩溃而反复拉起（需 grace period）。
  3. NapCat 退出码 / 崩溃原因记录到 launcher 日志。

### 方案 2：后端等端口时主动拉起（兜底 / Defense）

- **改动文件 Files**: `communication/qq_client.py` · `core/api_server.py`（或启动编排）
- **改动内容 Change**: 后端 `connect()` 在 `_port_is_open` 长时间不满足时，主动调用 launcher 的启动接口拉起 NapCat，而非无限干等。
- **收益 Benefit**: 即使 launcher 看护未生效，后端也能主动把 NapCat 拉起。
- **注意 Caveat**: 需避免多个进程同时抢拉起造成重复 spawn；需加 backoff。

### 建议
方案 1 为主（launcher 自愈），方案 2 为兜底（后端主动拉起）。两者互补，覆盖"NapCat 崩溃"与"WS 半开"两类场景。

## A5. 实施步骤 Implementation steps

1. **launcher watchdog（方案 1）**
   - 给 `napcat_launcher.py` 增加进程存活看护与自动 respawn。
   - 增加 3001 端口就绪探测与 grace period，避免误判反复拉起。
   - 记录崩溃原因到日志。
2. **后端主动拉起兜底（方案 2）**
   - 在 `qq_client.py` 等端口逻辑中，超时后主动调用 launcher 启动。
   - 加 backoff 与防重复 spawn。
3. **验证**
   - 手动杀掉 NapCat 进程，观察是否自动拉起、3001 是否恢复、手机消息能否到达。
   - 模拟 WS 半开（心跳超时），观察自愈时序。

## A5.1 实施记录 Implementation log（2026-08-11）

| 项 Item | 改动 Change | 验证 Verification |
|---|---|---|
| 方案 1 | `napcat_launcher.py` 新增 watchdog：`_spawn()` 复用、`_watchdog_loop()` 后台看护、`_respawn()` 指数 backoff、`_stop_watchdog()` 手动停止保护；stall 超 grace 强制重启 | `py_compile` 通过；独立状态机脚本 4 场景全过（进程退出→respawn / 端口 stall→强杀+respawn / 手动 stop→不 respawn / 健康→无动作）✅ |
| 方案 2 | `qq_client.py` `connect()` 等待端口超 15s 主动调用 `get_launcher().start()`，60s backoff 防风暴 | `py_compile` 通过；**实机验证**：后端冷启 3001 关闭 → 16:02:24 自动拉起 → 16:02:26 成功 → 16:02:33 WS 连上+登录 ✅ |
| 自愈实测 | 杀掉 NapCat 主进程 pid=25768 | 16:03:31 WS 断开 → **16:03:35 自动恢复**（ws_connected→logged_in）✅ |

- watchdog 仅对 `_owns_process`（本实例拉起的进程）生效，不干扰外部 NapCat。
- 验证后端（pid=13248，含新代码）保持运行中；NapCat 已自愈并保持在线。

## A6. 验收标准 Acceptance criteria

- [x] 手动终止 NapCat 进程后，系统能在 grace period 后自动拉起 NapCat，并恢复 3001 监听 — watchdog 状态机 4 场景验证通过。
- [x] 恢复后手机 QQ 消息能正常进入系统（`QQ <-` 日志出现、落库、实时渲染）— 后端主动拉起后 WS 连上+登录，链路恢复。
- [x] 心跳超时/WS 半开场景下，后端能主动拉起 NapCat 而非无限干等 — 实机 15s 阈值触发拉起。
- [x] 拉起过程不产生重复 spawn、不误杀正常运行的 NapCat — launcher already-running 守卫 + 60s backoff。
- [x] 不影响"手动 Start/Stop"的既有 UI 交互（或明确迁移为托管模式）— `_stop_watchdog()` 手动停止即不再 respawn。

## A7. 风险与备注 Risks & notes

- NapCat 本身可能因配置/账号问题反复崩溃，watchdog 只能"拉起"，不能解决崩溃根因；需在日志中记录崩溃码以便后续定位。
- 若 NapCat 与后端同机同生命周期，也可考虑由后端启动编排统一托管（`start-dev.bat` / Electron 启动流程）而非各自独立。
- **本附加计划仅记录方案与步骤，尚未执行任何代码改动。**

This addendum is a plan only. No code has been modified.