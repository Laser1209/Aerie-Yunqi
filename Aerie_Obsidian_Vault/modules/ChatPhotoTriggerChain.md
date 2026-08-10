---
title: ChatPhotoTriggerChain
kind: module_note
status: Implemented
updated_at: 2026-08-10
owners:
  - CORE
related_modules:
  - VisualIntentRouter
  - ImageObservation
  - WorldImageCandidateConsumer
related_risks:
  - R-TC-003
  - R-TC-008
---

# ChatPhotoTriggerChain — 聊天出图触发与发布链路

## 定义

用户**主动要图**（自拍/场景照/合照/环境照）时，从聊天消息触发真实生图、并把图片落进聊天页面的完整链路。与主动推送发图（`world_image_candidates_v1` 的 proactive 路径）不同，本链路由**用户当前这一轮对话**直接驱动，`scene=local_send`，不占用主动发图每日额度。

## 链路总览

```
用户消息 + AI 回复文本
        │
        ▼
┌─ _resolve_chat_photo_intent（pipeline.py）───────────────┐
│ ① VisualIntentRouter 关键词快路径（免费）                  │
│ ② 用户消息语义判断（LLM，宽信号闸门 _FUZZY_IMAGE_HINTS）     │
│ ③ AI 回复语义判断（LLM，窄信号闸门 _REPLY_PHOTO_HINTS）     │
└───────────────────────┬───────────────────────────────┘
                        │ 命中 role_selfie / role_in_scene /
                        │ couple_photo / environment_object
                        ▼
┌─ _deliver_chat_photo（pipeline.py）──────────────────────┐
│ 构造 candidate（scene=local_send, channel=local_chat/qq）  │
│ → Companion.publish_image_candidate                     │
└───────────────────────┬───────────────────────────────┘
                        ▼
┌─ Companion.publish_image_candidate（companion.py）───────┐
│ world_port.publish_image_candidate（发布到世界 outbox）     │
│   ├─ 进程内 InProcess  → {"status":"accepted",sequence}   │
│   └─ sidecar         → {"seq", "event_id", "payload"}    │  ← 两种返回协议！
│ 通过校验（两种协议都认）→ process_world_image_candidates_once
└───────────────────────┬───────────────────────────────┘
                        ▼
┌─ WorldImageCandidateConsumer（world_image_candidates.py）─┐
│ 幂等/过期/离线/manual 豁免 → ImageWorkflow.generate_image    │
│ （to_thread 线程池执行，不阻塞事件循环）                     │
│ → 资产落盘 uploads/ → local_chat 注入 / QQ 发送             │
└──────────────────────────────────────────────────────┘
```

**发送顺序（文本等图）**：命中出图意图时，先发回复**第一段引导句**（如"你稍微等一下"）→ 出图并等待图片落到页面 → 再发剩余文本段落。生图失败/超时（120s 上限）不阻塞文本放行。

## 语义判断逻辑（三层）

### ① 关键词快路径 — `VisualIntentRouter`
- [image_service.py L102-L218](file:///e:/Agent_reply/core/image_service.py#L102-L218)
- 确定性关键词匹配（`_INTENT_KEYWORDS`，L110），免费无延迟。
- 只保留**无歧义**的拍照词（自拍/发张你的/拍照/拍张照/合照/拍一下等）。
- 高危误判词（"家里""房间""合拍""你现在的"等）已移除——它们会把"我在家里""我们很合拍"误判成出图。

### ② 用户消息语义判断 — `_judge_photo_intent`
- [pipeline.py L1106](file:///e:/Agent_reply/core/pipeline.py#L1106)
- LLM 判断"这句话是否隐含想看到你世界里的某个视觉载体"（分享欲 + 可视化载体，**不依赖拍照词**）。
- 前置信号闸门 `_FUZZY_IMAGE_HINTS`（[pipeline.py L46-L59](file:///e:/Agent_reply/core/pipeline.py#L46-L59)）：看/瞅/瞧/拍/照/图/样子/发你/床/家里/photo 等。
- 信号只是"是否值得花一次 LLM 判断"的成本闸门，**判定本身是语义的**，不是关键词匹配。

### ③ AI 回复语义判断 — `_judge_reply_photo_intent`
- [pipeline.py L1153](file:///e:/Agent_reply/core/pipeline.py#L1153)
- 解决"上下文延续"：用户不重复提拍照词，但 **AI 回复自己在叙述"发图"**（"随手对着镜子拍的""点了发送""发给你"）。
- 例："找到了吗？" 用户消息无信号，但回复含"拍/发送" → 回复语义判断命中 role_selfie。
- 窄信号闸门 `_REPLY_PHOTO_HINTS`（[pipeline.py L61-L64](file:///e:/Agent_reply/core/pipeline.py#L61-L64)），避免对每条回复都发起额外调用。

### 人设引导
- [context_builder.py L650-L679](file:///e:/Agent_reply/core/context_builder.py#L650-L679) L6 图片能力认知段：教 AI 发图前给一句自然的引导托词（"你稍微等一下"/"我摄像头好像坏了"），图片后再接收尾，禁止机器话。

## 发布与消费链路

### Companion.publish_image_candidate（[companion.py L597](file:///e:/Agent_reply/core/companion.py#L597)）

**关键坑（已修）— 两种 world_port 的发布返回协议不一致：**

| world_port 模式 | 返回结构 |
|---|---|
| 进程内 `InProcessWorldAdapter`（[world_port.py L565](file:///e:/Agent_reply/core/world_port.py#L565)） | `{"status": "accepted", "sequence": N, "event_id": ...}` |
| sidecar `RemoteWorldAdapter`（[world_adapters/remote.py L253](file:///e:/Agent_reply/core/world_adapters/remote.py#L253)） | `{"seq": N, "event_id": ..., "payload": {...}}`（**无 status 字段**） |

旧代码只认 `result["status"] == "accepted"` → sidecar 模式下发布**永远被判 rejected**（`publish_rejected`），图永远出不来，且无任何报错。

**修复**（[companion.py L636-L652](file:///e:/Agent_reply/core/companion.py#L636-L652)）：accepted 判定改为兼容三种信号——
`status=="accepted"` OR `accepted is True` OR 含 `seq`/`event_id`；seq 从 `sequence` 或 `seq` 取。

**触发模式的判定**：`build_world_port`（[world_port.py L658](file:///e:/Agent_reply/core/world_port.py#L658)）按 feature flag 走：
- `world_sidecar_v1=true` 且端点/令牌齐全 → RemoteWorldAdapter
- `world_inprocess_v1=true` → InProcessWorldAdapter
- 注意：`data/runtime_config.json` 的持久化运行配置**会覆盖** settings.yaml，历史上把 `world_sidecar_v1` 顶成 true 触发过此 bug。

### 消费端豁免
- [world_image_candidates.py L416-L432](file:///e:/Agent_reply/core/world_image_candidates.py#L416-L432)：`scene=local_send`（用户主动要图）豁免 PushPolicy 频率/静默/每日上限与 delivery_online 暂停检查——否则"拍一张照片"会因最近有推送被静默掐掉。
- 图片资产落盘：`uploads/<content-hash>.png`，访问 URL `http://127.0.0.1:7890/uploads/<name>`。

## 排查指南（看日志）

**`main.log` 关键标记与含义：**

| 日志 | 含义 |
|---|---|
| `[ChatPhoto] semantic judge intent=...` | 用户消息语义判断命中某意图 |
| `[ChatPhoto] reply judge intent=...` | AI 回复语义判断命中 |
| `[ChatPhoto] delivered status=published consumed=True` | **链路成功**，图已落盘 |
| `[ChatPhoto] delivered status=rejected reason=publish_rejected` | world_port 发布被拒（旧版 schema bug 的表现） |
| `[ChatPhoto] delivered status=failed reason=deliver_error` | 发布超时/异常，文本已放行 |
| `[WorldImage] delivered generated image to local chat: <url>` | 图片已注入本地聊天 |
| `image provider call failed` | 第三方图源（image2.inian.one）调用失败 |
| `[ProviderHealth] Provider doubao banned` | doubao 欠费被自动踢出轮询 |

**排查顺序：**
1. 看有没有 `[ChatPhoto] semantic/reply judge intent=` —— 判断层有没有识别出意图；没有则查信号闸门或 `world_image_candidates_v1` 开关。
2. 看 `[ChatPhoto] delivered status=` —— 发布层结果；`rejected/publish_rejected` 查 world_port 协议（见上表）；`failed/deliver_error` 查发布超时。
3. 看 `[WorldImage] delivered` —— 消费+落地；没有则查 consumer 的豁免/预算/图片 provider。
4. 看 `uploads/` 有没有新 `*.png` —— 最终落盘证据。

**常见根因速查：**
- `world_sidecar_v1` 被 runtime_config 覆盖成 true + 无端点 → 走 RemoteWorldAdapter（schema 不匹配）→ 检查 `data/runtime_config.json`。
- 图源欠费/宕机 → `image provider call failed`，图片工作流返回 failed。
- doubao 欠费 → `Provider doubao banned`，deepseek 兜底。
