---
name: douyin-interactive-publish
description: 抖音互动空间发布 / Interact publish
provider_hint: text
read_only: false
---

# douyin-interactive-publish / 抖音互动空间发布

上传 zip+icon 创建/更新互动空间。

## 入参
- `zip_path`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "app_id": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 环境变量：`DOUYIN_OPEN_ID`（缺失时返 stub）

## 安全
- read_only = `false`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `text`
