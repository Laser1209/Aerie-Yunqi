---
name: notion-spec-to-impl
description: Notion Spec→任务 / Spec to impl
provider_hint: text
read_only: false
---

# notion-spec-to-impl / Notion Spec→任务

把 spec 页面拆为可执行任务。

## 入参
- `spec_url`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "task_urls": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 环境变量：`NOTION_TOKEN`（缺失时返 stub）

## 安全
- read_only = `false`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `text`
