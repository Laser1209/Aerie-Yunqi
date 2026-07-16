---
name: screenshot
description: 系统截图 / Screenshot
provider_hint: text
read_only: true
---

# screenshot / 系统截图

全屏/指定应用/像素区域 OS 级截图。

## 入参
- `region`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "image_path": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 无需凭据

## 安全
- read_only = `true`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `text`
