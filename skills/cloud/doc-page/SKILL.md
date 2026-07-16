---
name: doc-page
description: 可打印文档页 / Doc page
provider_hint: text
read_only: false
---

# doc-page / 可打印文档页

报告/表单/排班/简历/备忘录 A4 排版 + PDF/DOCX 导出。

## 入参
- `topic`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "pdf_path": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 无需凭据

## 安全
- read_only = `false`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `text`
