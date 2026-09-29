---
name: byted-seedance
description: Seedance 文生视频 / Seedance video
provider_hint: text
read_only: false
requires_env: SEEDANCE_KEY
---

# byted-seedance / Seedance 文生视频

调火山方舟 Seedance 系列模型做文生视频 / 图生视频。

视频生成是**异步任务**，耗时以分钟计，所以这个 skill 是**两段式**的：

1. `action: "create"`（默认）提交任务 → 拿到 `task_id`
2. `action: "get"` 带上 `task_id` 查进度 → 未完成只返回状态，完成才返回 `video_url`

**不要**在一次调用里等它跑完 —— 那会把对话卡死几分钟。

接口：`POST/GET https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks[/{id}]`，
Bearer 鉴权。官方文档：https://www.volcengine.com/docs/ark/create-video-generation-task-api

## 入参

- `action`：`create` / `get`，默认 `create`
- `prompt`：`create` 必填，画面描述
- `task_id`：`get` 必填，`create` 返回的那个
- `image_url`：可选，首帧参考图的公网 URL → 即图生视频
- `model`：可选，默认 `doubao-seedance-2-0-260128`
- `ratio`：可选，`adaptive` / `16:9` / `9:16` 等，默认 `adaptive`
- `duration`：可选，秒数，默认 5
- `watermark`：可选，是否加水印

## 出参

- `create` 成功：`{"status": "ok", "task_id": "cgt-…", "task_status": "queued"}`
- `get` 进行中：`{"status": "ok", "task_id": "cgt-…", "task_status": "running"}`
- `get` 完成：`{"status": "ok", "task_status": "succeeded", "video_url": "https://…"}`
- `get` 任务失败：`{"status": "ok", "task_status": "failed", "error": "…"}`
  （任务本身失败不算调用失败，所以外层 `status` 仍是 `ok`）
- 未配密钥：`{"status": "stub", "error": "credential_missing: env 'SEEDANCE_KEY' not set"}`

## 凭据

- 环境变量 `SEEDANCE_KEY`：火山方舟控制台 → API Key
- 还需在控制台「开通模型」里开通所用的 Seedance 模型
- 可在设置页「平台凭证 → 火山 Seedance 文生视频」填写，保存即生效、无需重启

## 注意

- 返回的是**临时 URL**，需要长期保存请及时转存
- 时长与分辨率越高，耗时和费用越高
- 参考视频、多模态参考等高级能力未接入

provider_hint: `text`
