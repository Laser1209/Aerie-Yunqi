---
name: byted-mediakit
description: 字节 mediakit 多媒体处理 / ByteDance mediakit
provider_hint: text
read_only: false
---

# byted-mediakit / 字节 mediakit 多媒体处理

音视频剪辑、格式转换、抽帧等。

## 入参
- `input_path`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "output_path": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 环境变量：`MEDIAKIT_AK`（缺失时返 stub）

## 安全
- read_only = `false`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `text`
