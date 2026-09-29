---
name: byted-seedream
description: Seedream 文生图 / Seedream image
provider_hint: image-sdxl
read_only: false
requires_env: SEEDREAM_KEY
---

# byted-seedream / Seedream 文生图

调火山方舟 Seedream 系列模型文生图，返回图片 URL。

接口：`POST https://ark.cn-beijing.volces.com/api/v3/images/generations`，
Bearer 鉴权，**一次请求同步返回**（没有轮询）。
官方文档：https://www.volcengine.com/docs/82379/1541523

## 入参

- `prompt`：必填，提示词（中英文均可）。建议不超过 300 汉字 —— 过长模型会抓不住重点
- `model`：可选，Model ID，默认 `doubao-seedream-5-0-260128`
- `size`：可选，`1K` / `2K` / `4K` 或具体像素（如 `2048x2048`），默认 `2K`

## 出参

- 成功：`{"status": "ok", "image_url": "https://...", "size": "2048x2048", "model": "..."}`
- 未配密钥：`{"status": "stub", "error": "credential_missing: env 'SEEDREAM_KEY' not set"}`
- 鉴权 / 未开通 / 限流：`{"status": "error", "error": "http_401: ..."}`，原始报文截断后附在 `error` 里

## 凭据

- 环境变量 `SEEDREAM_KEY`：火山方舟控制台 → API Key（长效）
- 还要在控制台「开通模型」里开通所用的 Seedream 模型，否则会返回 `Model.NotOpen`
- 可在设置页「平台凭证 → 火山 Seedream 文生图」直接填写，保存即生效、无需重启

## 注意

- 返回的是**临时 URL**，需要长期保存请及时转存
- 当前只覆盖文生图；图生图 / 组图 / 图层拆分未接入

provider_hint: `image-sdxl`
