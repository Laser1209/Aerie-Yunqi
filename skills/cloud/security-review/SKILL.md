---
name: security-review
description: 安全审查 / Security review
provider_hint: text
read_only: true
---

# security-review / 安全审查

对代码 diff 做 path_traversal / unsafe_deserialization / xss / ssrf 风险扫描。

## 入参
- `diff_text`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "findings": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 无需凭据

## 安全
- read_only = `true`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `text`
