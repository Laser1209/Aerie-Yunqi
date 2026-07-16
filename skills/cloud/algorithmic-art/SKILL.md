---
name: algorithmic-art
description: 算法艺术 / Algorithmic art
provider_hint: text
read_only: false
---

# algorithmic-art / 算法艺术

p5.js seeded randomness + 交互参数艺术。

## 入参
- `seed`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "p5_url": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 无需凭据

## 安全
- read_only = `false`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `text`
