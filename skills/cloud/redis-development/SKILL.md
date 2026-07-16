---
name: redis-development
description: Redis 开发 / Redis
provider_hint: text
read_only: true
---

# redis-development / Redis 开发

Redis 数据结构 / RQE / 向量检索 / 性能优化。

## 入参
- `query`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "result": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 环境变量：`REDIS_URL`（缺失时返 stub）

## 安全
- read_only = `true`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `text`
