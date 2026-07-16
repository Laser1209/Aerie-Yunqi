---
name: computer-use
description: 系统状态查询 / System query
provider_hint: shell-safe
read_only: true
---

# computer-use / 系统状态查询

调本地系统状态查询器，输出 value。

## 入参
- `category`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "value": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 无需凭据

## 安全
- read_only = `true`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `shell-safe`
