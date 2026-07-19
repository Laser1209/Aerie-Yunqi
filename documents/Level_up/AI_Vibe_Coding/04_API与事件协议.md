---
title: API 与事件协议
kind: control
tags: [aerie, api, events]
---
# API 与事件协议
> [!note] 协议分层
> Core UI 使用可恢复 SSE；World 使用独立可确认、可续传的可靠协议。

## Core SSE
统一 `event_id`、`request_id`、`conversation_id`、`turn_id`、`message_id`、`response_group_id`、`sequence`；Renderer 按事件去重、按请求序号排序、按消息幂等更新。

## World 协议
版本与能力协商、单调 seq、ACK cursor、checkpoint、heartbeat、幂等键。Renderer 不获取 Sidecar 地址或凭据。

## 兼容
旧 `/api/chat/send` 进入 Request 适配器；poll 保留一个周期并与 SSE 共用事件 ID。
