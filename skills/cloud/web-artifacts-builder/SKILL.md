---
name: web-artifacts-builder
description: 复杂 artifact 构建 / Web artifacts
provider_hint: text
read_only: false
---

# web-artifacts-builder / 复杂 artifact 构建

React + Tailwind + shadcn/ui 复杂 artifact。

## 入参
- `spec`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "html_path": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 无需凭据

## 安全
- read_only = `false`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `text`
