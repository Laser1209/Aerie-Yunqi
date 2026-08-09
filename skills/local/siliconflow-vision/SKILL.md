---
name: siliconflow-vision
description: 图片视觉理解 / Vision Q&A (SiliconFlow)
provider_hint: text
read_only: true
---

# siliconflow-vision / 图片视觉理解

调用 SiliconFlow 视觉 API（OpenAI 兼容）理解图片内容：描述画面、
提取文字、分析图表/截图，输出 answer。

## 入参
- `image_path`：核心入参（必填，图片绝对路径）
- `question`：可选，针对图片的问题/指令；缺省时请求详细描述画面

## 出参
- 成功：`{"status": "ok", "answer": ...}`
- 缺 key：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 环境变量：`SILICONFLOW_API_KEY`（必填，复用在 .env）
- `SILICONFLOW_BASE_URL`：可选，默认 `https://api.siliconflow.com/v1`
- `VISION_MODEL`：可选，默认 `Qwen/Qwen3-VL-8B-Instruct`

## 安全
- read_only = `true`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell
- 图片路径需为本机绝对路径，读入后仅 base64 编码后 POST 到 API，不外传

provider_hint: `text`
