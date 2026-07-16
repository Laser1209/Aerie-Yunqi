---
name: report-generator
description: 视频分析报告 / Report gen
provider_hint: text
read_only: true
---

# report-generator / 视频分析报告

分镜 + 钩子 + BGM + 场景分析报告。

## 入参
- `breakdown_json`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "report_md": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 无需凭据

## 安全
- read_only = `true`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `text`
