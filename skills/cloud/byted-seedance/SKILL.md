---
name: byted-seedance
description: Seedance 文生视频 / Seedance video
provider_hint: text
read_only: false
---

# byted-seedance / Seedance 文生视频

Seedance 模型文生视频；支持图生视频与参考视频。

## 入参
- `prompt`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "video_url": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 环境变量：`SEEDANCE_KEY`（缺失时返 stub）

## 安全
- read_only = `false`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `text`
