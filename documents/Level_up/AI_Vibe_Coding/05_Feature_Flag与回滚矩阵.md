---
title: Feature Flag 与回滚矩阵
kind: control
tags: [aerie, rollback]
---
# Feature Flag 与回滚矩阵
|范围|Flag|回滚路径|
|---|---|---|
|迁移|migration_framework_v1|恢复备份与旧迁移路径|
|主动消息|proactive_delivery_v2|QQ-only|
|身份|identity_contract_v1|legacy user_id|
|四表|conversation_model_v1|chat_log 读路径|
|队列|chat_request_queue_v1|停止 Worker claim，`/api/chat/send` 恢复旧同步 200；保留新列、pending/queued/failed 记录与预分配 Turn，不破坏性降级|
|流式|chat_stream_v1|完整响应与 poll|
|Context|context_budget_v1|旧 Builder|
|Persona|persona_hub_source_v1|旧只读投影|
|图片|image_assets_v1|旧 uploads 只读|
|世界|world_inprocess_v1 / world_sidecar_v1|Null / InProcess Adapter|
|候选|world_image_candidates_v1|关闭 Consumer|

> [!tip] 原则
> 回滚只关闭 Flag、恢复备份或切旧读路径；保留新表、元数据和旧兼容物。
