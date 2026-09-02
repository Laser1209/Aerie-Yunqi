# A05 当前流量通路与发布诊断报告

日期：2026-09-03 05:00-06:00（北京时间）  
版本：`0.3.2-beta.0903-A05`  
源码提交：`d80a32d`（A05 二进制 manifest 对应运行时提交 `7b7b7e3`）

## 结论

Aerie 的本地核心链路已在 D 盘隔离环境完成启动、队列聊天、记忆检索、权益接口和打包后端验证。外部服务不可用时，系统进入可识别的 degraded 状态，不阻断本地聊天。Companion Studio 的 HTTP 代理、TTS echo 链路和模型发现均可用；ASR、Chat 和 RVC 因配置为 disabled，属于能力降级，不是进程故障。

## 实测数据流

```text
Electron/HTTP 客户端
  -> POST /api/chat/send
  -> ChatRequestService 入队
  -> ChatRequestWorker
  -> ContextBuilder + persona 隔离
  -> ChromaDB 语义检索（失败时 SQLite fallback）
  -> 本地确定性回复（AERIE_DISABLE_MODEL_CALLS=1）
  -> SQLite messages / 请求状态
  -> GET /api/chat/requests/{request_id}
```

独立语音链路为：

```text
POST /api/integrations/companion-studio/talk
  -> CompanionStudioAdapter
  -> Studio /api/talk
  -> echo reply + Edge TTS 音频
```

## A05 验收证据

| 检查 | 结果 |
| --- | --- |
| 源码 `/api/health` | HTTP 200，版本 A05，QQ 未连接所以 status=degraded |
| 源码 `/api/chat/send` | HTTP 202，队列请求最终 `completed`，2 条 assistant 消息 |
| Chroma 过滤器 | 修复前会抛 `Expected where to have exactly one operator`；修复后同类链路日志计数为 0 |
| Aerie `/api/integrations/companion-studio` | HTTP 200，base URL 已配置，Studio 健康状态被透传 |
| Studio `/api/health` | HTTP 200；Edge TTS 可用，ASR/Chat disabled |
| Studio `/api/models/live2d` | HTTP 200，返回可发现模型 |
| Studio `/api/models/rvc` | HTTP 200，返回 `lenai.pth`、`lenai_v2.pth` |
| `/api/billing/entitlement` | HTTP 200，Free 本地计量状态 |
| `/api/billing/trial` | HTTP 200，本地试用状态幂等；不代表真实支付 |
| A05 包内 manifest | 版本 A05，`git_commit=7b7b7e3`，runtime SHA-256 与构建一致 |
| 打包后端隔离验证 | `/api/health` 200，`/api/skills/list` 返回 18 个技能 |
| Python 定向回归 | 89 passed，1 个 Python 3.16 弃用警告 |
| Spotlight 构建 | `tsc + vite build`，466 modules，成功 |
| 官网强制刷新 | A05 脚本存在、A04 消失；规范化 Setup 下载 URL HTTP 302 |

## 根因修复

`memory/layers/long_permanent.py` 原先把多个字段和 `$or` 放在 Chroma `where` 同一层。Chroma 要求过滤器只有一个顶层操作符，因此每次带 persona 的向量检索都会异常并退回 SQLite。现在把条件组织为单字段或 `$and`，persona 的共享空串仍通过嵌套 `$or` 保留，且新增回归测试覆盖过滤器结构。

## 发布资产

GitHub Release：<https://github.com/Laser1209/Aerie-Yunqi/releases/tag/v0.3.2-beta.0903-A05>

- Portable：`93D6BFC2F2391A92F084825428412713BB8A4E7D410E6BF35F59573991E0DE9F`
- Setup：`023E7DCD32B3AD81E8A98F2BC8B96E77409E6497CEE75682320A707A5BE92570`
- Blockmap：`C379C9ABE73F5D1792803131E46FCF7A1858DABCA4631BD20F0BD40A9D5F4CAE`

构建目录：`D:\aerie-dist-v046`。由于 GitHub 上传后将空格规范化为点号，官网已使用 `Aerie.Companion-...` 的真实资产名；空格版本 URL 已实测为 404，不能再使用。

## 未闭合项

1. QQ/NapCat 未连接时保持 degraded；需要用户提供账号和明确授权后再做真实消息通路验收。
2. Studio 的 ASR、Chat、RVC 仍是 disabled；外部 provider、模型和许可资产不能由仓库代替提供。
3. 真实支付、服务端 entitlement、webhook 验签、退款、发票和商业 EULA 尚未完成，因此 A05 只能做非商业技术评估。
4. 干净 Windows profile 的真实安装、升级、重启和卸载仍需人工验收。
5. Electron `check:tokens` 仍被历史 CSS 中 100 个硬编码颜色阻断；本轮未通过放宽检查器掩盖。
6. OpenAI Ads Pixel 默认关闭；没有真实 Pixel ID、同意机制和支付成功边界时，不发送订阅转化事件。

## 建议

先用 A05 Setup 对 10-20 名 Windows 用户做非商业封闭测试，记录匿名安装、首条消息、工作区任务和崩溃指标；完成许可、支付和隐私边界后，再启用真实 Ads 转化与收费。
