---
name: tts
description: 文字转语音 / Text to speech
provider_hint: tts-openvino
read_only: false
---

# tts / 文字转语音

调本地 OpenVINO Qwen3-TTS 把文字转成 wav，输出 wav_path。

## 入参
- `text`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "wav_path": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 无需凭据

## 安全
- read_only = `false`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `tts-openvino`
