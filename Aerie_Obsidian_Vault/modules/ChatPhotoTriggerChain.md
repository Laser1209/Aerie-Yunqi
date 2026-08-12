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

## 2026-08-12 升级：POV 自拍约束 + 发图自我认知闭环（M1–M4）

> 本轮升级解决四个体验问题：① 生图第三人称视角失控；② 活动话题模板匮乏；③ 主动发图后伊塔"失忆"不知图里内容；④ `[图片](...)` 伪 markdown 被当正文输出。方案详见 [[plans/生图提示词模块化升级与室内定位计划#九、生图体验修缮（M1–M4）记录]]。

### M1 · POV 手持自拍约束（companion.py）
- **恒定注入** `_SELFIE_POV_PHRASE`："这张照片由她本人手持手机拍摄，画面角落可见她的手指或手机边缘……绝无他人拍摄。"人物类 full 提示词始终追加。
- **机位自拍化** `_PHOTO_ANGLE_PHRASE`：把第三方机位词（"仰视低角度""从后面"等）改写为"她手持手机放低自拍取景""她把手机举到身后用后置摄像头拍背影"。
- **出口兜底** `_ensure_selfie_pov(prompt, prompt_key)`：幂等（已含手持关键词不重复追加），`_image_prompt_for` 三处返回点统一接入。
- **黑名单** `_POV_THIRD_PARTY_BLACKLIST`：轻量 LLM 接力校验门拒绝"摄影师/他人拍摄/旁观/第三人称/路人/拍摄者/别人拍"。

### M2 · 活动话题翻译 + 模板动态映射（companion.py）
- `_VISUAL_TOPIC_ZH`：11 个活动话题（reading_time/deep_focus/morning_plan/coffee_break/lunch_time/tea_break/evening_chill/good_night/starry_window/desk_view/quiet_moment）+ 3 个兼容话题 → 中文画面描述；`_visual_topic_zh(topic)` 翻译优先级 `_VISUAL_TOPIC_ZH` → `_HER_HOME_OBJECTS_ZH` → 原文。
- `_prompt_key_for_visual_topic(topic)`：活动话题 → `role_in_scene`，物件 → `environment_object`（主动发图不再硬编码 environment_object，size 跟随）。
- `role_in_scene` 模板参数化：改为"她举着手机前置摄像头对着自己……"，`_world_context_text` topics/nearby 统一走翻译表。

### M3 · 发图自我认知落账（companion.py + world_image_candidates.py + memory/sync_adapter.py）
- `_deliver_world_image`（async）：QQ 发送成功后补写 chat_log `[图片] {desc}` + `_persist_image_event`。
- `_deliver_local_chat_image`（async）：content 追加 `\n[图片内容] {desc}` + 落 EVENT 记忆。
- `_persist_image_event`：EVENT 记忆落 long_term 层，`importance ≥ 7.0`，metadata 含 `occurred_at/channel/image_path`，**不存完整 URL**（防记忆膨胀）。
- `_image_event_desc(plan)`：从 delivery plan 生成中文描述（含场景/动作）。
- `_deliver(workflow_result, candidate=None)`：把 `reason_code/prompt_key/scene` 注入 delivery plan（setdefault），供 sender 生成图片事件描述。
- 消费端 → sender 双接线：主动发图与用户要图两条路径都落账。
- **RECALL 触发**：pipeline `_RECALL_KEYWORDS` 扩展"你发的/发的什么/那张图/那张照片/照片给我看/刚才发的"，用户追问时召回图片事件记忆 → 伊塔能回答"我发的是什么"。

### M4 · 发图机制定义 + 出口清洗（context_builder.py + qq_client.py）
- L6 `_build_l6_image_capability` 重写：新增【发图机制 · How Sending a Photo Works】段——发图 = 系统后台生图 + 附件送达；**绝对禁止**写 `[图片](...)` / `![图片](...)` / 生图提示词 / 画面描述文字。
- `strip_fake_image_markdown(text)`：剥伪 markdown（`!?[图片](...)` 且 URL 非 http(s)），空输入返回 `""`；接入 `send_message` 与 `send_message_with_segments` 清洗链（在 `strip_thought_action_tags → strip_timestamp_markers` 之后），真实 `image` 附件段不受影响。

### 测试覆盖
- `tests/test_modular_photo_prompt.py`（34 例）：POV 出口兜底 / 机位自拍化 / 翻译表全覆盖 / prompt_key 映射 / `_image_event_desc` / `_persist_image_event`（long_term/occurred_at/无URL）。
- `tests/test_phase14_world_image_candidates.py`（27 例）：`_deliver` 注入 candidate 字段 + 无 candidate 幂等。
- `tests/test_pipeline.py`：RECALL 关键词含发图触发词 + 旧关键词保留。
- `tests/test_communication.py`（22 例）：`strip_fake_image_markdown` 六项（剥伪语法 / 保留真实 URL / 保留裸词 / 空输入）+ 保真 image segment。
