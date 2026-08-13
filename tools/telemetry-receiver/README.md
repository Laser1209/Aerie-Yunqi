# Aerie 诊断数据接收端 · Deployment Guide / 部署指引

接收桌面端 `core/telemetry.py` 上传的诊断包（zip），存入 Cloudflare R2。
本目录是独立的小服务，不影响主程序。免费额度足够测试版使用（R2 存储按量计费，测试期通常极低甚至 0 成本）。

> 收费说明：Cloudflare Workers 免费计划（每日 10 万请求）与 R2 免费额度（每月 10GB 存储 / 1000 万次 A 类操作）对本场景绰绰有余。除非诊断包体量极大，否则不会产生费用。**诊断数据上传与下载本身不向受测者收费。**

---

## 1. 需要准备什么 / Prerequisites

- 一个 Cloudflare 账号（免费）
- 已安装 Node.js 与 npm
- `npx wrangler`（会按需自动拉取，或先 `npm i -g wrangler`）
- **R2 存储需先在 Cloudflare 控制台手动启用**（需绑定信用卡 / PayPal，免费额度内不扣费）——见 2.2

## 2. 首次部署 / First deploy

在 Cloudflare 控制台或命令行完成，任选其一。

### 2.1 登录 / Login

```bash
npx wrangler login
```

### 2.2 启用 R2 / Enable R2（前置必做）

R2 是 Cloudflare 的付费对象存储，**必须先手动启用一次**（即使有免费额度）：

1. 打开 https://dash.cloudflare.com 并登录
2. 左侧菜单点 **R2 Object Storage**
3. 按引导完成启用：同意条款 + 绑定一张信用卡 / PayPal（免费额度内不扣费）

> 若跳过此步直接建桶，会报 `code: 10042 · Please enable R2 through the Cloudflare Dashboard`。

### 2.3 创建 R2 存储桶 / Create R2 bucket

```bash
npx wrangler r2 bucket create aerie-diagnostics
```

### 2.4 （推荐）设置上传鉴权 Token / Set auth token

```bash
npx wrangler secret put DIAG_UPLOAD_TOKEN
```

输入一个你自己生成的长随机串（例如 `openssl rand -hex 32` 的输出）。
桌面端会把同样的串填进 `.env` 的 `AERIE_TELEMETRY_UPLOAD_TOKEN`。
**不设置则接收端不校验鉴权**，公网域名下不建议。

### 2.5 部署 / Deploy

在 `tools/telemetry-receiver` 目录下执行：

```bash
npx wrangler deploy
```

部署成功后，终端会输出类似：

```text
Uploaded aerie-diagnostics-receiver (2 sec)
Deployed aerie-diagnostics-receiver
  https://aerie-diagnostics-receiver.<你的子域>.workers.dev
```

记下这个域名，上传端点就是：

```text
https://aerie-diagnostics-receiver.<你的子域>.workers.dev/upload
```

## 3. 把端点接回桌面端 / Wire it back

编辑项目根目录 `.env`（没有就新建），新增：

```dotenv
AERIE_TELEMETRY_UPLOAD_URL=https://aerie-diagnostics-receiver.<你的子域>.workers.dev/upload
AERIE_TELEMETRY_UPLOAD_TOKEN=<你在 2.3 设置的 Token>
```

重启后端即可生效。设置页“诊断数据”面板会显示“上传端点已配置”。

## 4. 验证 / Verify

```bash
curl -X POST "https://aerie-diagnostics-receiver.<你的子域>.workers.dev/upload" \
  -H "Authorization: Bearer <Token>" \
  -H "X-Diagnostic-Filename: test.zip" \
  -H "Content-Type: application/zip" \
  --data-binary "@测试文件.zip"
```

成功返回：

```json
{ "ok": true, "key": "diagnostics/20260814/...", "bytes": 1234, "receivedAt": "..." }
```

## 5. 下载诊断包 / Retrieve packages

在 Cloudflare 控制台 → R2 → `aerie-diagnostics` 桶里浏览 `diagnostics/` 前缀，或：

```bash
npx wrangler r2 object get aerie-diagnostics/<key> --file ./downloaded.zip
```

---

## 接口约定 / API contract

| 项 | 值 |
|---|---|
| Method | `POST` |
| Path | `/upload` |
| Body | 原始 zip 字节（`application/zip`） |
| Header `X-Diagnostic-Filename` | 包文件名 |
| Header `X-Device-Id` | 设备标识（12 位） |
| Header `Authorization` | `Bearer <DIAG_UPLOAD_TOKEN>`（可选，配置了才校验） |

存储键格式：`diagnostics/<yyyyMMdd>/<ISO时间戳>-<deviceId>-<filename>`
