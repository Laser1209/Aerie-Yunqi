---
name: hyperframes-registry
description: HyperFrames 块注册 / HF registry
provider_hint: text
read_only: false
---

# hyperframes-registry / HyperFrames 块注册

安装 / 接入 hyperframes 块与组件。

## 入参
- `block`：核心入参（见具体 run.py）
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

provider_hint: `text`
