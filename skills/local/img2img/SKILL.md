---
name: img2img
description: 图像编辑 / Image-to-image
provider_hint: image-sdxl
read_only: false
---

# img2img / 图像编辑

调本地 SDXL img2img，prompt + source → output_path。

## 入参
- `source`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "output_path": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 无需凭据

## 安全
- read_only = `false`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `image-sdxl`
