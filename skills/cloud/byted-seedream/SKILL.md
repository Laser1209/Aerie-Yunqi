---
name: byted-seedream
description: Seedream 文生图 / Seedream image
provider_hint: image-sdxl
read_only: false
---

# byted-seedream / Seedream 文生图

Seedream 高质量文生图；多风格多尺寸。

## 入参
- `prompt`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "image_url": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 环境变量：`SEEDREAM_KEY`（缺失时返 stub）

## 安全
- read_only = `false`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `image-sdxl`
