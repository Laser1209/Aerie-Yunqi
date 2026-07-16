---
name: figma
description: Figma MCP 调用 / Figma MCP
provider_hint: text
read_only: true
---

# figma / Figma MCP 调用

Figma MCP 客户端；无 token 返 stub。

## 入参
- `method`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "data": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 无需凭据

## 安全
- read_only = `true`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `text`
