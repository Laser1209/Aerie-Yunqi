# Aerie 微信 Claw iLink 原生接入实施方案

> **执行约束：** 本方案采用逐关口确认。每个关口完成设计或实现后，先向用户汇报证据、风险和实际结果；只有用户明确确认，才进入下一关口。不得一次性跨越多个未确认关口。

**目标：** 让 Aerie 通过原生 Python iLink 适配器直连微信 ClawBot，实现应用内扫码、仅本人配对、私聊文本/图片/语音/文件双向收发、输入状态、断线恢复，以及可配置的主动消息单主渠道投递。

**架构：** iLink 协议实现放在独立的 `communication/ilink/` 包中，协议层只负责认证、HTTP、消息解析和加密媒体传输；`core/ilink_gateway.py` 管理连接生命周期、凭据、游标、去重与状态；现有 `MessageBatcher → Pipeline → ConversationRepository` 继续作为唯一业务主链。发送侧将目前 QQ 专用出口收敛为按 `channel` 分派的通用出口，但不重写 QQ 协议实现。

**技术栈：** Python 3.14、asyncio、httpx 0.28.1、cryptography、qrcode + Pillow、pywin32 DPAPI、FastAPI、SQLite、Electron 28、Node.js 内置测试、pytest/pytest-asyncio。

---

## 一、已确认决策

| 决策项 | 锁定结果 |
|---|---|
| 连接拓扑 | Aerie 原生 Python 直连 iLink，不部署 OpenClaw 中转 |
| 首期会话 | 私聊，不接群聊 |
| 首期媒体 | 文本、图片、语音、普通文件；不做视频原生收发 |
| 登录入口 | Aerie Electron 设置页内扫码、查看状态、退出登录 |
| 访问控制 | 仅绑定本人，其他联系人消息不进入 Pipeline |
| 绑定方式 | 一次性配对码，由用户从微信发送后完成绑定 |
| 凭据保护 | Windows DPAPI 当前用户范围加密，不允许明文降级 |
| 主动消息 | 首期接入微信；QQ、微信、桌面三者配置一个主渠道 |
| 主动投递语义 | 单主渠道、单次投递；主渠道失败时明确失败，不暗中广播 |
| 微信撤回 | iLink 当前无可靠撤回端点，保留“不支持平台撤回”的明确能力结果 |
| 兼容策略 | 不保留旧 ClawBot 内存桩，不增加兼容层，不支持旧式媒体上传字段 fallback |

## 二、当前状态与影响面

### 2.1 可直接复用

- `communication/message.py` 已有 `IncomingMessage.attachments/channel/channel_account_id`，可承载微信消息。
- `core/identity/`、`core/conversation_repository.py`、`core/message_batcher.py` 已按渠道与账号隔离身份和会话。
- `core/pipeline.py` 已具备完整的上下文、人格、记忆、情绪、工具和落库链路。
- `core/qq_media.py` 已具备图片落盘和语音转写能力，可抽取通道无关服务，不复制实现。
- `core/api_server.py → electron/src/main.js → preload.js → renderer` 已有 QQ 二维码展示模式，可复用安全边界。
- `requirements.txt` 已包含 `httpx`、`Pillow`、Windows 条件依赖 `pywin32`、`pytest` 和 `pytest-asyncio`。

### 2.2 必须修正

- `core/companion_channel.py` 的 ClawBot 仅为不联网内存桩，不能作为生产连接器。
- `communication/message.py::OutgoingReply` 不携带通用渠道地址。
- `core/pipeline.py` 仅在 `msg.source == "qq"` 时回发消息。
- `communication/send_queue.py` 虽可注入 sender，但回执、引用和撤回记录仍带 QQ 语义。
- `core/companion.py::_dispatch_push` 当前可能向 QQ、桌面和系统通知多路投递，不符合单主渠道约束。
- `IncomingMessage.user_id` 是内部整数，而 iLink 用户 ID 是字符串，必须保持“内部用户身份”和“渠道地址”分离。
- 仓库当前没有 DPAPI 凭据存储、iLink 游标持久化、上下文 Token 缓存和 iLink 消息去重。

## 三、依赖库方案

### 3.1 直接依赖

| 依赖 | 当前状态 | 用途 | 决策 |
|---|---|---|---|
| `httpx==0.28.1` | 已存在 | 扫码 API、长轮询、发送、流式 CDN 上传下载 | 直接复用 `AsyncClient` |
| `pywin32==312` | 已存在，Windows 条件依赖 | `win32crypt.CryptProtectData/CryptUnprotectData` | 直接复用，不新增第二套凭据系统 |
| `Pillow==12.2.0` | 已存在 | 二维码 PNG 生成、图片尺寸/缩略图处理 | 直接复用 |
| `cryptography==50.0.0` | 新增并固定版本 | AES-128-ECB + PKCS#7 媒体加解密 | 当前 Python 3.14 环境已验证；禁止自行实现密码算法 |
| `qrcode[pil]==8.2` | 新增并固定版本 | 将服务端二维码 payload 渲染为 PNG | 新增；二维码在内存生成 |

### 3.2 不新增的依赖

- 不引入非官方 `weixin-channel-sdk`，避免 Alpha SDK 成为生产真源。
- 不引入 `tenacity`，退避策略用少量 asyncio 代码实现，避免为单一循环增加抽象层。
- 不引入 ORM；游标、上下文 Token 和去重记录复用项目 SQLite 基础设施。
- 不引入 `platformdirs`；凭据与状态文件沿用项目现有持久化数据目录解析规则。
- 不显式引入 Pydantic 作为 iLink DTO 层；使用项目现有 dataclass 风格和严格解析函数，减少依赖面。

### 3.3 安装与验证

修改 `requirements.txt` 后执行：

```powershell
e:\Agent_reply\venv\Scripts\python.exe -m pip install -r requirements.txt
e:\Agent_reply\venv\Scripts\python.exe -m pip check
```

验收：`pip check` 无冲突；可导入 `cryptography`、`qrcode`、`win32crypt`；日志和命令输出中不出现任何微信 Token。

## 四、目标模块边界

### 4.1 新增文件

| 文件 | 单一职责 |
|---|---|
| `communication/ilink/__init__.py` | 只导出稳定公共接口 |
| `communication/ilink/models.py` | iLink 请求/响应 DTO、枚举和严格解析 |
| `communication/ilink/errors.py` | HTTP、协议、会话失效、限流、媒体错误类型 |
| `communication/ilink/client.py` | 请求头、超时和 iLink API 调用，不承担业务调度 |
| `communication/ilink/auth.py` | 二维码认证状态机与重定向主机校验 |
| `communication/ilink/media_crypto.py` | AES-128-ECB、PKCS#7、MD5 和密钥解析 |
| `communication/ilink/media.py` | 媒体下载、解密、上传 URL、加密上传和附件映射 |
| `communication/ilink/channel.py` | 长轮询、消息过滤、入站转换、出站发送和 typing |
| `core/windows_dpapi.py` | Windows DPAPI 最小封装，非 Windows 明确失败 |
| `core/ilink_credentials.py` | DPAPI 密文、账号元数据和原子文件写入 |
| `core/ilink_state.py` | SQLite 游标、context token、去重键、配对状态读写 |
| `core/ilink_gateway.py` | iLink 生命周期、健康状态、认证和 Channel 编排 |
| `core/channel_delivery.py` | 通用出站地址、发送回执、渠道注册与单渠道分派 |
| `electron/src/renderer/js/external-connections-panel.js` | 外部连接总栏、QQ/微信子折叠、聚合状态和主动主渠道交互 |
| `electron/src/renderer/js/ilink-gateway-panel.js` | 微信扫码、配对、连接、能力和独立日志状态机 |

### 4.2 修改文件

| 文件 | 改动 |
|---|---|
| `requirements.txt` | 增加固定版本的 `cryptography` 与 `qrcode[pil]` |
| `communication/message.py` | 增加 iLink 入站构造；给出站 DTO 增加 channel/account/context 字段 |
| `communication/send_queue.py` | 去除 QQ-only 语义，发送后按回执记录通用远端 ID |
| `core/companion.py` | 初始化/停止 iLink 网关，注册分派器，收口主动消息单主渠道 |
| `core/pipeline.py` | 删除 `source == qq` 出站硬编码，回复原路返回 |
| `core/api_server.py` | 增加 iLink 状态、扫码、配对、启停、退出和能力 API |
| `core/primary_identity.py` | 保持内部整数 ID，增加 iLink 渠道地址绑定读取 |
| `config/settings.yaml` | 增加非敏感 iLink 设置和 `proactive.primary_channel` |
| `electron/src/main.js` | 增加受控 iLink IPC 调用与二维码 Data URL 转换 |
| `electron/src/preload.js` | 暴露最小 iLink bridge |
| `electron/src/renderer/index.html` | 将“QQ 运维”改造成“外部连接”总折叠栏，内置 QQ/微信双子栏、聚合统计与主动主渠道 |
| `electron/src/renderer/js/qq-gateway-panel.js` | 保留 QQ 业务控制，移除其对外层折叠栏的所有权，改为管理 QQ 子栏 |
| `electron/src/renderer/js/settings.js` | 加载/保存 iLink 非敏感配置与主渠道 |
| `electron/src/renderer/styles/main.css` | 将 `status-qq-*` 外层样式收敛为通用外部连接/渠道子栏样式 |
| `communication/recall/factory.py` | 将微信渠道统一命名为 `ilink`，返回明确 unsupported 适配器 |

### 4.3 删除内容

- 删除生产代码中的 `ClawBotChannelAdapter` 内存桩及其“stub_ok”健康状态。
- 删除只验证 ClawBot 永不联网的生产桩测试。
- 删除主动消息旧的多出口广播分支，不新增 v3 feature flag。
- 删除 `clawbot/wx/wechat` 多别名兼容；内部渠道唯一标识固定为 `ilink`。

## 五、扫码认证详细实现

### 5.1 后端状态机

固定状态：

```text
disabled
  -> idle
  -> qr_pending
  -> scanned
  -> pairing_required
  -> connected

qr_pending/scanned -> expired
任意运行态 -> error
connected -> session_expired -> qr_pending
connected -> logged_out -> idle
```

对前端只返回：`phase`、`connected`、`account_masked`、`qr_available`、`pairing_required`、`last_error_code`、`last_connected_at`、`capabilities`。绝不返回 `bot_token`、完整 `ilink_user_id`、`baseurl` 内部路由信息、context token 或二维码原始会话值。

### 5.2 获取二维码

1. 设置页点击“连接微信”。
2. Electron 通过 preload bridge 调用后端 `POST /api/ilink/start-login`。
3. `ILinkGateway.start_login()` 取消旧认证任务，清空过期二维码内存，但不删除仍有效的正式凭据。
4. `ILinkAuthSession.request_qrcode()` 调用：

```http
GET {auth_base_url}/ilink/bot/get_bot_qrcode?bot_type=3
iLink-App-Id: bot
iLink-App-ClientVersion: <固定审计版本>
```

5. 严格检查 HTTP 2xx、JSON 类型、`qrcode` 和 `qrcode_img_content` 非空。
6. 将 `qrcode_img_content` 作为不透明 payload，用 `qrcode[pil]` 在内存生成 PNG；不把二维码写入磁盘。
7. `GET /api/ilink/qrcode` 只返回 `image/png`，设置 `Cache-Control: no-store`。
8. Electron 主进程限制响应体不超过 2 MB，并转换成 Data URL 交给 renderer。
9. renderer 每 1 秒拉取状态；只在 `qr_available=true` 时请求二维码图片。

### 5.3 扫码状态轮询

`ILinkAuthSession.poll_status()` 调用：

```http
GET {current_auth_base_url}/ilink/bot/get_qrcode_status?qrcode=<url-encoded opaque value>
```

规则：

- 单次请求超时 40 秒，允许服务端长等待。
- `wait`：保持 `qr_pending`，立即进入下一轮，不额外高频短轮询。
- `scaned`：切换 `scanned`，前端显示“已扫码，请在手机确认”。
- `scaned_but_redirect`：只接受 HTTPS 且主机属于允许的微信 iLink 域；更新当前认证 base URL 后继续同一二维码会话。
- `expired`：销毁二维码值和 PNG，切换 `expired`，由用户点击刷新获取新码。
- `confirmed`：严格提取 `bot_token`、`ilink_bot_id`、`ilink_user_id`、`baseurl`；任一缺失都视为协议错误。
- 未知状态：记录脱敏协议错误并停止认证，不猜测成功。
- 用户点击取消、关闭面板或应用退出时取消认证 Task，并等待任务结束，禁止遗留轮询。

### 5.4 DPAPI 持久化

1. 认证确认后，将凭据序列化为 UTF-8 JSON 字节。
2. 调用 `win32crypt.CryptProtectData(data, ..., flags=0)`，使用当前 Windows 用户范围保护。
3. 文件只保存版本号、DPAPI 密文和非敏感时间戳；文件名位于项目数据目录，不进入 Git。
4. 采用“同目录临时文件 → flush/fsync → `os.replace`”原子写入。
5. 应用启动时解密；解密失败或数据损坏时进入 `credentials_error`，不尝试明文读取。
6. 退出登录时先停止 poller，再从内存清零 token，删除凭据文件和 iLink 会话状态。
7. 日志过滤字段：`Authorization`、`bot_token`、`qrcode`、`context_token`、`aeskey`、完整用户 ID。

### 5.5 仅本人配对

1. 首次认证成功后生成 8 位一次性配对码，使用 `secrets`，有效期 10 分钟，只保存哈希。
2. UI 显示配对码和“请从你的微信向 ClawBot 发送此配对码”。
3. poller 在未绑定阶段只解析私聊纯文本，不把任何消息送入 Pipeline。
4. 文本与配对码恒定时间比对成功后，将该消息的 `from_user_id` 绑定到现有 primary actor。
5. 立即销毁配对码；同一二维码会话只允许成功绑定一个 iLink 用户。
6. 非匹配消息只记脱敏拒绝计数，不保存正文，不回复任何内容。
7. 五次失败后使配对码失效，要求用户在应用内重新生成。

## 六、长轮询详细实现

### 6.1 请求客户端

`ILinkClient` 维护一个生命周期与网关一致的 `httpx.AsyncClient`：

```python
httpx.Timeout(connect=10.0, read=45.0, write=20.0, pool=10.0)
```

每个业务请求动态生成：

```http
Content-Type: application/json
iLink-App-Id: bot
iLink-App-ClientVersion: <固定审计版本>
AuthorizationType: ilink_bot_token
Authorization: Bearer <token>
X-WECHAT-UIN: <base64(decimal random uint32)>
```

请求体统一包含：

```json
{
  "base_info": {
    "channel_version": "2.1.1"
  }
}
```

禁止手工设置 `Content-Length`；禁止记录完整请求头或完整请求体。

### 6.2 单实例轮询

1. `ILinkGateway.start()` 验证启用状态、DPAPI 凭据和本人绑定。
2. 为每个 iLink Bot 账号只创建一个 `_poll_task`；重复 start 幂等返回当前状态。
3. 从 SQLite 读取 opaque `get_updates_buf`，首次为空字符串。
4. 调用：

```http
POST {baseurl}/ilink/bot/getupdates
```

```json
{
  "get_updates_buf": "<opaque cursor>",
  "base_info": {"channel_version": "2.1.1"}
}
```

5. 区分四类结果：正常空批次、正常消息批次、业务错误、传输错误。
6. 成功响应严格检查 `ret`、`errcode`、`msgs` 和 `get_updates_buf` 类型。
7. 每条消息先构造幂等键，推荐 `bot_id:message_id:client_id`；命中已处理记录则跳过。
8. 只接受 `message_type=USER`、`message_state=FINISH`、私聊且 `from_user_id` 等于已绑定本人。
9. 保存新游标与本批待处理消息状态到同一 SQLite 事务，再逐条提交业务处理。
10. 同一微信联系人串行处理；当前首期只有本人，不引入跨联系人并发调度。
11. 消息成功持久化并交给 MessageBatcher 后，将幂等记录标为完成。
12. poller 被取消时不吞掉 `CancelledError`；关闭 HTTP client 前等待任务结束。

### 6.3 游标与“至少一次”语义

- 游标是不可解析字符串，不解码、不修改。
- SQLite 保存：`bot_id`、`cursor`、`updated_at`。
- 消息表保存：`dedupe_key`、`status(received/processing/completed/failed)`、`attempt_count`、脱敏错误码。
- 崩溃恢复时，`completed` 跳过；`received/processing` 重新处理，由现有消息落库键和远端 client ID 保证不重复展示。
- 去重记录保留 7 天后按批清理；不保存原始聊天正文副本。

### 6.4 错误与退避

| 错误 | 行为 |
|---|---|
| `ret=0` 且 `errcode=0/空` | 正常处理 |
| `errcode=-14` | 立即停止 poller，清理 token/context/cursor，状态改为 `session_expired`，通知重新扫码 |
| HTTP 429 | 尊重 `Retry-After`；否则指数退避 |
| HTTP 5xx、DNS、TLS、连接/读取超时 | 有界指数退避：2、4、8、16、30 秒，加 0–20% jitter |
| HTTP 4xx（除 429） | 不自动重试，状态转 error |
| 协议字段缺失/类型错误 | 不更新为成功状态，记录 `protocol_error`，停止轮询等待人工确认 |
| 未知 `ret/errcode` | 保留数值和脱敏 errmsg，不猜测语义，不无限重试 |

连续失败不会触发 QQ 或桌面 fallback；设置页显示最后错误类别、失败次数和下一次重试时间。

### 6.5 Context Token

- 每次接收本人私聊消息后，按 `(bot_id, from_user_id)` 保存最新 `context_token`。
- 回复原消息优先使用该入站消息携带的 token；主动消息使用该联系人最近一次有效 token。
- 不跨账号、不跨联系人复用。
- 重新扫码、退出登录或 `-14` 时全部清除。
- context token 使用与 bot token 相同的 DPAPI 加密边界，不能明文放入 YAML 或普通日志。

## 七、文本与媒体链路

### 7.1 入站文本

`WeixinMessage.item_list[type=1]` 合并为正文，构造：

```text
IncomingMessage(
  user_id=<内部 primary user 整数>,
  source="ilink",
  channel="ilink",
  channel_account_id=<微信 ilink user id>,
  content=<文本>,
  platform_message_id=<iLink message id>,
  attachments=[],
  timestamp=<create_time_ms / 1000>
)
```

然后进入现有 `_submit_incoming_message → MessageBatcher → Pipeline`，不建立微信专用 AI Pipeline。

### 7.2 入站图片、语音、文件

1. 解析媒体项，校验下载 URL 只能是 HTTPS 且主机在 iLink/CDN 白名单。
2. 使用 `httpx.AsyncClient.stream()` 流式下载密文。
3. 密文大小限制：图片 20 MB、语音 30 MB、普通文件 100 MB；超限立即中止。
4. 从协议字段解析 16 字节 AES key。
5. 使用 `cryptography` 执行 AES-128-ECB 解密和 PKCS#7 去填充。
6. 校验声明的明文长度和 MD5；不一致即删除临时文件。
7. 图片复用通用附件落盘/缩略图服务。
8. 语音进入现有通道无关 ASR 服务，转写文本与语音附件一起进入 Pipeline。
9. 普通文件进入桌面附件解析链路；文件名使用 basename 清洗，拒绝路径穿越和危险设备名。
10. 最终附件统一为现有 `attachments` 结构，远端临时 URL 不作为永久附件地址。

### 7.3 出站媒体

1. 校验目标是已绑定本人，读取最新 context token。
2. 读取明文并计算长度和 MD5。
3. `secrets.token_bytes(16)` 生成独立 AES key。
4. AES-128-ECB + PKCS#7 加密；密文写入受控临时文件，发送后无论成功失败均删除。
5. 调用 `/ilink/bot/getuploadurl`，首期只接受当前协议的 `upload_full_url`，没有该字段即返回 `media_protocol_error`。
6. 校验上传 URL HTTPS 与域名白名单后流式上传密文。
7. 读取服务端要求的加密参数，构造 image/voice/file item。
8. 调用 `/ilink/bot/sendmessage`，使用稳定 UUID `client_id`。
9. 发送超时后的未知结果不生成新 client ID 盲重试；以同一 client ID 做一次状态可判定的重试，否则返回 unknown。

### 7.4 输入状态

- 收到已授权消息并进入 Pipeline 后调用 `getconfig` 获取 typing ticket。
- 调用 `sendtyping(status=1)` 显示正在输入。
- 首段回复成功、任务失败或超时后调用 `sendtyping(status=2)`。
- typing 失败只记录健康指标，不阻断正文回复。

## 八、通用出站与主动消息改造

### 8.1 出站 DTO

`OutgoingReply` 增加：

```text
channel: str
channel_account_id: str
context_token: str | None
platform_reply_to_id: str | int | None
```

通用 `SendReceipt` 固定包含：

```text
accepted: bool
channel: str
remote_message_id: str | None
client_id: str | None
error_code: str | None
delivery_state: sent | failed | unknown
```

Pipeline 的回复始终继承入站 `channel/channel_account_id`。QQ 保持走现有发送实现，iLink 走 `ILinkChannel.send()`，桌面仍由本地 API/SSE 返回。

### 8.2 主动消息单主渠道

新增配置：

```yaml
ilink:
  enabled: false
  media:
    image_max_bytes: 20971520
    voice_max_bytes: 31457280
    file_max_bytes: 104857600
proactive:
  primary_channel: desktop
```

- 合法值只有 `desktop`、`qq`、`ilink`。
- `_dispatch_push()` 每次只解析一次主渠道并只调用一个 sender。
- 主动配图继承同一渠道，不再次判断 QQ 在线状态。
- 主渠道不可用时返回失败并记录原因，不自动广播到其他渠道。
- 系统通知作为本地“有新消息”提醒，不作为第二份聊天正文投递；只有桌面主渠道时正常展示桌面消息。

## 九、后端 API 与 Electron UI

### 9.1 API 契约

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/api/ilink/status` | 脱敏连接、扫码、配对、能力状态 |
| `POST` | `/api/ilink/start-login` | 创建新的二维码认证会话 |
| `GET` | `/api/ilink/qrcode` | 返回 no-store PNG |
| `POST` | `/api/ilink/cancel-login` | 取消认证任务并销毁二维码 |
| `POST` | `/api/ilink/pairing-code` | 生成/刷新一次性配对码 |
| `POST` | `/api/ilink/start` | 使用已有凭据启动 poller |
| `POST` | `/api/ilink/stop` | 停止 poller但保留登录凭据 |
| `POST` | `/api/ilink/logout` | 停止连接并删除凭据、游标、context token、绑定 |
| `GET` | `/api/ilink/capabilities` | 返回文本/图片/语音/文件/typing/recall 能力 |

所有写操作通过现有本机 API 调用边界；返回体统一使用稳定错误码，不返回异常堆栈和敏感字段。

### 9.2 设置页交互

#### 9.2.1 页面层级

现有系统状态页不拆页。把当前“QQ 运维”折叠区原位升级为：

```text
外部连接 · External Connections                    1/2 已连接  ▾
  QQ                                                已连接      ▸
  微信 Claw                                         等待扫码    ▾
    微信登录二维码
    扫码确认 / 本人配对
    连接与媒体能力
    微信独立运行日志
  主动消息主渠道：桌面 / QQ / 微信
```

- 外层是一个“外部连接”总折叠栏，默认展开。
- 外层内部是 QQ 与微信 Claw 两个独立子折叠栏，允许同时展开。
- 现有大标题“QQ 运维”改为“外部连接 · External Connections”。
- 系统状态顶部的“QQ 连接”统计卡改为“外部连接”，显示 `0/2 未连接`、`1/2 已连接`、`2/2 已连接`；任一渠道异常时优先显示异常数量。
- 外层聚合状态不替代子栏状态；QQ 与微信各自保留状态徽标。
- 主动消息主渠道放在两个子栏之后、外部总栏内部，因为它同时依赖两个外部渠道。

#### 9.2.2 折叠状态规则

- 总栏默认展开；用户手动折叠后，本次应用会话内保持该选择。
- QQ/微信子栏采用按状态展开：`qr_pending`、`scanned`、`pairing_required`、`session_expired`、`error` 自动展开一次。
- `idle/disabled` 与稳定 `connected` 默认折叠。
- 普通三秒状态轮询不得覆盖用户手动展开/折叠；只有从稳定状态首次进入需要用户操作的状态时才触发一次自动展开。
- 总栏折叠时继续刷新轻量状态，但暂停二维码和日志请求；重新展开时立即补拉可见子栏数据。
- 每个折叠按钮使用原生 `button`，同步维护 `aria-expanded` 与 `aria-controls`，支持 Enter/Space 和可见焦点。

#### 9.2.3 QQ 子栏

- 现有启动、停止、二维码和日志功能原样迁入 QQ 子栏，后端 QQ API 不改名。
- 保留“只有 Aerie 自己启动的 QQ 引擎才允许停止”的保护。
- QQ 子栏使用独立日志，不与微信日志混合。
- `qq-gateway-panel.js` 只管理 QQ 子栏内容，不再绑定整个外部连接总栏。

#### 9.2.4 微信 Claw 子栏

- 未连接：显示“连接微信”按钮与能力说明。
- 等待扫码：显示二维码、刷新和取消；二维码只在子栏可见时加载。
- 已扫码：弱化二维码并显示“已扫码，请在手机确认”。
- 待配对：显示一次性配对码、有效期和失败次数。
- 已连接：显示脱敏账号、连接时间、最近收发时间、停止与退出登录。
- 异常：显示可操作的稳定错误文案；会话失效只提供重新扫码，不继续重试失效 Token。
- 退出登录前二次确认，确认内容明确说明会删除凭据、游标、Context Token 和本人绑定。
- 微信使用独立脱敏日志，不显示 Token、二维码原始值、Context Token、AES key 和完整用户 ID。

#### 9.2.5 主动消息主渠道

- 使用单选控件选择桌面、QQ 或微信，同一时刻只能选择一个。
- 用户点击后先立即更新选中视觉，再异步保存；保存失败恢复原值并显示原因。
- 选择未连接的 QQ/微信时拒绝保存，并自动展开对应子栏帮助完成连接。
- 主动文本与主动配图共用同一次渠道选择，不允许二次分流。

#### 9.2.6 视觉与响应式

- 将现有 `status-qq-*` 外层类改为 `external-connections-*`，两个子栏共用 `external-channel-*`，不复制微信专属折叠样式。
- 保持现有主题的圆角、柔和边框、状态色和小字号；标题不过度加粗。
- 使用现有 SVG 图标库，不使用 emoji。
- 二维码居中；状态、操作和说明保留足够间距。
- 窄窗口中操作按钮自动换行，日志与二维码不能产生横向溢出。
- Renderer 不直接 fetch 固定 7890 端口，所有敏感和二维码操作必须经现有受限 bridge。

## 十、实施关口与确认机制

### 关口 0：工作区保护与协议基线

**实施内容**
- 记录当前未提交改动，禁止覆盖用户正在修改的 `core/companion.py` 等文件。
- 固定本轮审计的 iLink 协议版本、请求字段和媒体字段。
- 添加依赖并完成导入验证。

**确认材料**
- 依赖变更 diff、`pip check`、协议契约测试列表、与现有改动无冲突证明。

**用户确认点**
- 确认依赖版本与协议基线后才进入认证实现。

### 关口 1：扫码、DPAPI 与本人配对

**测试先行**
- `tests/test_ilink_auth.py`
- `tests/test_ilink_credentials.py`
- `tests/test_ilink_pairing.py`

**实施内容**
- 完成 client/auth/DPAPI/credentials/state。
- 完成 API 与 mock 扫码，不启动真实长轮询。
- 验证 token、二维码值和用户 ID 不泄漏。

**用户确认点**
- 用户在应用内确认二维码 UI、扫码状态文案、配对流程与退出登录语义。

### 关口 2：长轮询与文本端到端

**测试先行**
- `tests/test_ilink_models.py`
- `tests/test_ilink_client.py`
- `tests/test_ilink_channel.py`
- `tests/test_ilink_gateway.py`
- `tests/test_ilink_pipeline_integration.py`

**实施内容**
- 游标、去重、context token、退避、会话失效处理。
- 仅本人私聊文本进入 Pipeline，AI 回复原路返回。
- 应用关闭时 poller 可验证地退出。

**用户确认点**
- 展示一次真实或受控 mock 的“微信发文本 → Aerie 处理 → 微信收到回复”证据，确认后才进入媒体。

### 关口 3：图片、语音、文件

**测试先行**
- `tests/test_ilink_media_crypto.py`
- `tests/test_ilink_media.py`
- 扩展 `tests/test_ilink_pipeline_integration.py`
- 回归 `tests/test_qq_media.py`

**实施内容**
- 流式下载、AES 解密、完整性校验、附件落盘。
- 图片理解、语音 ASR、文件解析进入现有 Pipeline。
- 图片/语音/文件加密上传与发送。

**用户确认点**
- 分别确认三种媒体的收、识别/解析、回复和回发结果；任何一种账号能力受限都必须明确报告，不伪装成功。

### 关口 4：通用出站与主动单主渠道

**测试先行**
- `tests/test_channel_delivery.py`
- `tests/test_proactive_primary_channel.py`
- 回归 `tests/test_send_queue_batch.py`
- 回归 `tests/test_recall_adapters.py`

**实施内容**
- 去除 Pipeline/SendQueue 的 QQ-only 硬编码。
- 删除主动消息旧多路广播逻辑。
- 主动文本和配图均只走设置的唯一主渠道。

**用户确认点**
- 用户分别切换桌面、QQ、微信并确认每次只有一个渠道收到主动内容。

### 关口 5：Electron 完整体验与全量验收

**测试先行**
- `electron/tests/external-connections-panel.test.js`
- `electron/tests/ilink-gateway-panel.test.js`
- `electron/tests/ilink-preload.test.js`
- 扩展现有设置页和系统状态测试。

**实施内容**
- 将现有“QQ 运维”原位升级为“外部连接”总折叠栏，完成 QQ/微信双子栏、聚合统计和按状态展开。
- 完成微信状态、扫码、配对、退出、独立日志和主渠道设置。
- 保留 QQ 启停、二维码、日志与外部进程停止保护，并迁入 QQ 子栏。
- 删除 ClawBot 生产桩和失效测试。
- 更新 README、CHANGELOG、Obsidian 模块文档和故障排查文档。

**用户确认点**
- 完成应用内人工验收清单后，用户确认最终交付。

## 十一、测试矩阵

### 11.1 协议与安全

- 请求头每次生成不同 `X-WECHAT-UIN`。
- Authorization 不进入日志、异常、API 和 UI。
- 扫码 wait/scaned/confirmed/expired/redirect/unknown 全覆盖。
- DPAPI 往返、损坏密文、不同用户、非 Windows、原子写入失败全覆盖。
- 重定向、下载、上传 URL 的 HTTPS 和域名白名单校验。
- AES 已知向量、PKCS#7、错误 key、错误 MD5、超限流式中止全覆盖。

### 11.2 长轮询可靠性

- 首次空游标、连续游标、空批次、多消息批次。
- 相同消息重复返回只进入 Pipeline 一次。
- 崩溃后 processing 消息可恢复，completed 不重复。
- 45 秒 read timeout 与正常 35 秒空返回严格区分。
- 429/5xx/网络超时退避，4xx 不重试，`-14` 停机并清凭据。
- start/stop/logout 幂等，关闭后无悬挂 Task 和未关闭 HTTP client。

### 11.3 业务与回归

- 非本人、群聊、Bot 自己消息、GENERATING 状态不进入 Pipeline。
- 文本、图片、语音、文件进入同一 actor，但会话按 ilink 渠道隔离。
- 回复始终返回原 iLink 联系人，不误发 QQ。
- QQ 文本/图片/语音、桌面聊天、移动端和现有主动调度回归通过。
- 微信撤回返回 unsupported，不影响 QQ 真实撤回。
- 主动消息只投递一个主渠道，配图不二次分流。

### 11.4 外部连接前端

- 页面只存在一个“外部连接 · External Connections”总区域，不再出现“QQ 运维”大标题。
- 总栏内同时存在 QQ 与微信 Claw 两个可独立展开的子栏。
- 顶部统计卡正确显示 `0/2`、`1/2`、`2/2` 和异常聚合状态。
- QQ 与微信状态徽标、二维码和运行日志互不串用。
- 等待扫码、已扫码、待配对、会话失效或错误时，对应子栏自动展开一次。
- 用户手动折叠后，普通轮询不强制改回；状态进入新的需操作阶段时才自动展开一次。
- 总栏折叠后不请求二维码或日志，展开后立即补拉当前可见数据。
- 微信扫码完成、过期、取消或退出后，二维码 `src` 立即从 DOM 清除。
- 所有折叠按钮具有正确的 `aria-expanded/aria-controls`，可用键盘操作并有可见焦点。
- 主动主渠道先更新视觉选中状态；保存失败恢复旧值；未连接渠道无法保存并展开对应子栏。
- 窄窗口按钮换行，二维码、日志和子栏均无横向溢出。

### 11.5 验证命令

```powershell
e:\Agent_reply\venv\Scripts\python.exe -m pytest tests/test_ilink_models.py tests/test_ilink_client.py tests/test_ilink_auth.py tests/test_ilink_credentials.py tests/test_ilink_pairing.py -q
e:\Agent_reply\venv\Scripts\python.exe -m pytest tests/test_ilink_media_crypto.py tests/test_ilink_media.py tests/test_ilink_channel.py tests/test_ilink_gateway.py tests/test_ilink_pipeline_integration.py -q
e:\Agent_reply\venv\Scripts\python.exe -m pytest tests/test_channel_delivery.py tests/test_proactive_primary_channel.py tests/test_qq_media.py tests/test_pipeline.py tests/test_recall_adapters.py -q
node --test electron/tests/external-connections-panel.test.js electron/tests/ilink-gateway-panel.test.js electron/tests/ilink-preload.test.js electron/tests/qq-gateway-panel.test.js
e:\Agent_reply\venv\Scripts\python.exe -m pytest tests -q
```

最终还要启动本地后端和 Electron，通过应用内设置页完成一次人工 E2E。人工验证不使用生产聊天内容截图；证据只记录脱敏状态、时间、消息类型和成功/失败回执。

## 十二、验收标准

- 用户无需安装 OpenClaw 或 Node 微信插件，即可在 Aerie 内扫码连接。
- Bot Token 只以 DPAPI 密文落盘，API/UI/日志/诊断包扫描不到明文。
- 只有完成一次性配对的本人微信消息会进入 Aerie。
- 长轮询可持续运行、可取消、可恢复、可去重；断网不会忙循环，会话失效不会无限重试。
- 微信文本、图片、语音、文件均能进入既有 Aerie 对话、记忆和附件链路。
- Aerie 能向本人微信发送文本、图片、语音和文件，并返回明确发送状态。
- 微信、QQ、桌面回复不会串渠道、串账号、串 context token。
- 主动消息及其配图每次只投递到设置的唯一主渠道。
- 系统状态页以一个“外部连接”总折叠栏统一管理 QQ 和微信，顶部聚合卡与两个子栏状态一致。
- QQ/微信子栏各自拥有独立状态、二维码和日志，按状态自动展开且尊重用户手动折叠。
- iLink 不支持撤回时明确显示 unsupported，不伪造平台撤回。
- QQ、桌面、移动端、主动消息、附件、会话和 Electron 全量回归无新增失败。

## 十三、主要风险与处置

| 风险 | 处置 |
|---|---|
| iLink 裸协议并非完整公开稳定规范 | 固定审计版本；协议字段集中在 `communication/ilink`；未知字段严格报错，不扩散到业务层 |
| 媒体上传可能受账号权限限制 | 连接后能力探测；UI 显示实际能力；失败明确返回，不回退灰色协议 |
| 真实 Token 与个人消息敏感 | DPAPI、最小日志、脱敏 API、诊断扫描、域名白名单 |
| 长轮询重复或丢消息 | 单 poller、持久化 opaque 游标、幂等键、状态恢复 |
| `core/companion.py` 当前有用户未提交改动 | 实施前逐段重新读取，最小补丁，不覆盖无关变更 |
| 通用发送改造破坏 QQ | 先补通用契约测试，再迁移 QQ，最后接 iLink；每关跑 QQ 回归 |
| 主动消息改造改变现有体验 | 设置默认保持 `desktop`，切换必须用户显式操作；不隐式 fallback |

## 十四、实施期间的对话规则

- 每个关口开始前，先说明将修改哪些文件、不会触碰哪些区域、验收证据是什么。
- 每个关键协议选择、依赖变更、数据删除语义、UI 行为变化都要求用户明确确认。
- 遇到真实 iLink 响应与本方案契约不一致时立即停在当前关口，展示脱敏响应结构，不自行猜测或加入兼容 fallback。
- 遇到账号媒体能力受限时先报告实际错误与影响，由用户决定缩减范围或暂停，不改变既定目标掩盖失败。
- 未经用户明确要求不提交 Git；每个关口可准备符合项目规范的提交信息，但不执行提交。
