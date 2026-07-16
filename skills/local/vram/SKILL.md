---
name: vram
description: 显存调整 / GPU VRAM limit
provider_hint: shell-safe
read_only: false
---

# vram / 显存调整

调本地 VRAM 调整器设置百分比，返 ok。

## 入参
- `percent`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "ok": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 无需凭据

## 安全
- read_only = `false`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `shell-safe`
