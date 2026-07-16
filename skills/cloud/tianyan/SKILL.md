---
name: tianyan
description: 天眼查企业信息 / Tianyancha
provider_hint: text
read_only: true
---

# tianyan / 天眼查企业信息

调用天眼查 API 获取企业主体信息、股东、司法风险等结构化数据。

## 入参
- `company_name`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "info": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 环境变量：`TIANYAN_TOKEN`（缺失时返 stub）

## 安全
- read_only = `true`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `text`
