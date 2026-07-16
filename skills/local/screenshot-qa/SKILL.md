---
name: screenshot-qa
description: 截图问答 / Screenshot Q&A
provider_hint: vision-llava
read_only: true
---

# screenshot-qa / 截图问答

调本地 vision LLaVA 答屏上问题，输出 answer。

## 入参
- `image_path`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "answer": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 无需凭据

## 安全
- read_only = `true`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `vision-llava`
