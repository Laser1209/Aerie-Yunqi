---
name: ocr
description: 图像文字识别 / OCR
provider_hint: ocr-pp
read_only: true
---

# ocr / 图像文字识别

调本地 NPU PP-OCRv5 提取图像文字，输出 text。

## 入参
- `image_path`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "text": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 无需凭据

## 安全
- read_only = `true`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `ocr-pp`
