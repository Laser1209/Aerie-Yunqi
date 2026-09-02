# Aerie -> Companion Studio 代理链路验收（2026-09-03）

## 测试环境

- Companion Studio：`127.0.0.1:8899`
- Aerie：`127.0.0.1:7901`
- `AERIE_COMPANION_STUDIO_URL=http://127.0.0.1:8899`
- Aerie 数据目录：`D:\aerie-aerie-studio-smoke`
- 源码版本：`0.3.2-beta.0903-A03`

## 结果

| 请求 | 结果 | 说明 |
|---|---|---|
| Studio `/api/health` | HTTP 200 | TTS Edge healthy；Chat/ASR/RVC 明确 disabled |
| Aerie `/api/health` | HTTP 200 | Aerie backend healthy；QQ 未连接导致整体 degraded，属于预期降级 |
| Aerie `/api/integrations/companion-studio` | HTTP 200 | 返回 Studio 健康状态和服务明细 |
| Aerie `/api/integrations/companion-studio/talk` | HTTP 200 | 返回 `reply`、音频 URL、文件名和 `durationMs` |

## 结论

Aerie 与 Companion Studio 已通过同场真实 HTTP 验收。Studio 作为可选呈现连接器运行，不会取代 Aerie 的对话、身份或持久化真源；QQ/外部 Chat 不可用时，Aerie 仍能启动，Studio 仍可用回声 + TTS 完成第一条体验。

本次测试创建的数据库、日志和临时文件均放在 D 盘；测试进程已在验收后停止。QQ degraded 不应被误报为 Aerie 主后端故障，发布页应分别展示核心后端状态与外部渠道状态。

