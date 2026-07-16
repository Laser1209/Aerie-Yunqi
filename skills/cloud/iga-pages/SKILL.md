---
name: iga-pages
description: IGA Pages 部署 / IGA Pages
provider_hint: text
read_only: false
---

# iga-pages / IGA Pages 部署

IGA Pages 部署前端与全栈项目；带预览部署。

## 入参
- `project_dir`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "url": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 环境变量：`IGAPAGES_TOKEN`（缺失时返 stub）

## 安全
- read_only = `false`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `text`
