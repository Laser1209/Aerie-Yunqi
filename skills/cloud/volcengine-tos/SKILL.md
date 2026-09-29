---
name: volcengine-tos
description: 火山引擎对象存储 / TOS
provider_hint: text
read_only: false
requires_module: tos
requires_env: TOS_ACCESS_KEY
---

# volcengine-tos / 火山引擎对象存储

上传 / 下载 / 生成预签名 URL / 列举对象。走官方 Python SDK（包名 `tos`），
密钥签名由 SDK 负责，不需要自己实现 V4 签名。

官方文档：https://www.volcengine.com/docs/6349/92786

## 前置

1. `pip install tos`
2. 在设置页「平台凭证 → 火山引擎对象存储 TOS」填好：
   - `TOS_ACCESS_KEY` / `TOS_SECRET_KEY`：控制台「访问密钥」里取
   - `TOS_REGION`：如 `cn-beijing`（华北2 北京）
   - `TOS_ENDPOINT`：如 `tos-cn-beijing.volces.com`
   - `TOS_BUCKET`：默认桶名（也可每次调用时用 `bucket` 参数覆盖）

变量名与官方文档一致，照文档配环境时不用做名称翻译。

## 入参

- `action`：`upload` / `download` / `sign_url` / `list`，默认 `upload`
- `key`：对象名（如 `dir/example.txt`）。`upload` / `download` / `sign_url` 必填
- `file_path`：本地文件路径。`upload` / `download` 必填
- `bucket`：可选，覆盖默认桶
- `prefix`：可选，`list` 的前缀筛选
- `max_keys`：可选，`list` 返回条数上限（默认 100，最大 1000）
- `expires`：可选，`sign_url` 有效期秒数（默认 3600）

## 出参

- 成功：`{"status": "ok", ...}`（按 action 返回 `url` / `items` / `request_id` 等）
- 未配凭据：`{"status": "stub", "error": "credential_missing: 缺少 TOS_ACCESS_KEY, ..."}`
- 未装 SDK：`{"status": "error", "error": "tos SDK 未安装（pip install tos）: ..."}`
- 服务端拒绝：`{"status": "error", "error": "server_error: <code> <message>",
  "request_id": "...", "http_status": N}`

## 注意

- 桶名全局唯一；同名对象上传会**覆盖**（开了多版本则保留旧版本）
- `sign_url` 生成的是带签名与有效期的链接，过期即失效
- `upload` 走分片 + 断点续传，大文件也适用
- 对象名避免字典序递增（如时间戳前缀），否则容易压热点分区影响吞吐

provider_hint: `text`
