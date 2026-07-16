---
name: vercel-react
description: Vercel React 最佳实践 / Vercel React
provider_hint: text
read_only: true
---

# vercel-react / Vercel React 最佳实践

React/Next.js 性能优化指南。

## 入参
- `code`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "review": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 无需凭据

## 安全
- read_only = `true`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `text`
