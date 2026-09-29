---
name: byted-mediakit
description: 字节 AI MediaKit 音视频处理 / ByteDance mediakit（官方 CLI）
provider_hint: shell-safe
read_only: false
requires_cli: mediakit-cli
setup_hint: '本机执行：npm install -g @volcengine/mediakit-cli，然后 mediakit-cli init --api-key <MediaKit API Key>；本地裁剪模式还需 FFmpeg 在 PATH 上'
---

# byted-mediakit / 字节 AI MediaKit

通过本机官方 CLI `mediakit-cli` 处理音视频：

- **本地模式**（`--local`）走本机 FFmpeg：裁剪等轻编辑，**同步**返回；
- **云端模式**走 AI MediaKit：画质增强等 AI 能力，**异步**返回 `task_id`，
  再用 `query_task` 取结果。

## 前置

```bash
npm install -g @volcengine/mediakit-cli        # 要求 Node.js >= 18
mediakit-cli init --api-key <MediaKit API Key> --yes   # 云端能力需要，写进 CLI 自己的配置
```

本地模式还需要 FFmpeg 在本机 PATH 上。API Key 由 CLI 自持，**本 skill 不代持任何密钥**。

## 入参

- `action`：必填，取值见下表
- `video_url`：视频地址（本地文件路径或公网 URL），`enhance_video` / `trim_video` 必填
- `resolution`：可选，`enhance_video` 输出分辨率（默认 `1080p`，形如 `720p` / `1080p` / `2k` / `4k`）
- `start_time` / `end_time`：`trim_video` 必填，秒，需 `start < end`
- `output_path`：`trim_video` 必填，输出**目录**（必须在项目根之内）
- `task_id`：`query_task` 必填
- `poll_complete`：可选，`query_task` 是否轮询到任务完成（`true` / `false`）

## action 取值（已查证白名单，其余能力面暂未接入）

| action | 命令 | 说明 |
|---|---|---|
| `enhance_video` | `video enhance-video` | 云端画质增强（异步，返 `task_id`） |
| `trim_video` | `--local editing trim-video` | 本地裁剪（同步，写 `output_path`） |
| `query_task` | `shared query-task` | 查询异步任务结果 |
| `help` | `--help` | 打印 CLI 帮助（发现其余 100+ 原子能力） |

> 只实现上面四条。其它子命令等官方文档逐条核准后再加，**不凭记忆编造**。

## 出参

- 成功：`{"status": "ok", "action": "...", "stdout": "..."}`
- CLI 未安装：`{"status": "error", "error": "mediakit-cli CLI 不可用（未安装或不在 PATH）..."}`
- 参数非法（含输出目录越界）：`{"error": "invalid arguments"}`
- 未初始化/鉴权失败：`{"status": "error", "error": "... —— 需要先在本机执行 mediakit-cli init --api-key <KEY>"}`

## 安全

- `read_only = false`（本地裁剪会写文件），由 SkillLoader 强制
- 子进程调用，`shell=False`，argv 由「固定前缀 + 白名单参数」拼出，调用方拼不出任意子命令
- 本地输出目录必须落在项目根之内，越界直接拒绝

provider_hint: `shell-safe`
