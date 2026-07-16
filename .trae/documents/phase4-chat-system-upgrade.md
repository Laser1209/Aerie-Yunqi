---
title: Phase 4 — 本地对话系统全面优化实施计划
date: 2026-07-16
tags:
  - phase4
  - chat-ui
  - recall
  - quote
  - upload
  - ita-persona
aliases:
  - Phase 4 Plan
cssclasses:
  - wide-page
---

# Phase 4 — 本地对话系统全面优化

> **保留**：QQ 渠道全部功能（NapCat OneBot11 WS、send_private_msg、QQ WS 双向消息）
> **改造**：本地 Electron 聊天面板 + 数据模型 + API + 人格引擎对接
> **新增**：撤回机制 / 消息引用 / 文件上传三大核心功能

---

## 一、用户决策记录

| 决策点 | 决策结果 |
|--------|----------|
| 推进范围 | **三件套全做**（撤回 + 引用 + 上传） |
| 撤回时限 | **2 分钟窗**（QQ 标准），LLM 可在 2 分钟内主动撤回 |
| 引用设计 | **叠加式**（消息气泡内嵌引用上下文，点击跳转原消息） |
| 上传范围 | **全面支持 19 类**（图片 4 + 文档 8 + 压缩包 3 + 语音 + 视频 + 可执行） |
| 伊塔主动撤回 | **人格融合式**（LLM 自由决策，结合情绪与闷骚人设） |
| 上传存储 | **本地存储**（`uploads/` 目录 + chat_log.attachments 字段） |
| QQ 渠道 | **本地+QQ 同步**（本地和 QQ 渠道同时生效，撤回通过 NapCat delete_msg） |
| 人格频次 | **与闷骚人设一致**（温柔/开心情绪主动撤回，崩坒/冷暴模式不撤） |

---

## 二、Phase 1 探索结果摘要

### 2.1 现状盘点

| 维度 | 现状 | 缺口 |
|------|------|------|
| 聊天 UI | 纯文本轮询，3s 拉取 | 无 hover/右键/复制/引用/上传/撤回 UI |
| chat_log 表 | 10 张表，基础字段齐备 | 无 `reply_to_id` / `is_recalled` / `attachments` / `recalled_at` 字段 |
| RecallManager | 类已写好（63 行） | **未被 Companion 实例化、未挂接 Pipeline、未暴露 API** |
| 引用回复 | 完全未实现 | 需新建字段 + API + UI |
| 文件上传 | 完全未实现 | 需前端 input + 后端 multipart + 存储 + NapCat 图片发送 |
| 伊塔主动撤回 | persona.yaml 有预设 | 代码未读取配置，LLM 提示词未含撤回决策 |
| 工具系统 | 3 个工具（get_time/get_system_info/echo） | 无文件上传/撤回/引用相关工具 |

### 2.2 文档指引

| 章节 | 内容 | 状态 |
|------|------|------|
| §4.6 | RecallManager 完整设计稿 | ⏳ 需落地 |
| §6.6 | ChatManager 完整 JS 设计 | ⏳ 需落地 |
| §17 | 多模态扩展（图片/表情包） | ⏳ 需落地 |
| §11.3.1 | 情绪→行为映射表（含撤回频率） | ⏳ 需落地 |

---

## 三、实施批次（共 8 批次）

---

### Batch 1：数据模型扩展（P0 基础设施）

**目标**：扩展 `chat_log` 表支持撤回/引用/上传三件套，不破坏现有数据。

**改写文件**：`e:\Agent_reply\core\database.py`

**SQL 迁移**（用 `ALTER TABLE` 兼容已有数据）：
```sql
ALTER TABLE chat_log ADD COLUMN reply_to_id INTEGER DEFAULT NULL;
ALTER TABLE chat_log ADD COLUMN reply_to_content TEXT DEFAULT NULL;
ALTER TABLE chat_log ADD COLUMN reply_to_role TEXT DEFAULT NULL;
ALTER TABLE chat_log ADD COLUMN is_recalled INTEGER DEFAULT 0;
ALTER TABLE chat_log ADD COLUMN recalled_at TEXT DEFAULT NULL;
ALTER TABLE chat_log ADD COLUMN attachments TEXT DEFAULT NULL;     -- JSON 数组
ALTER TABLE chat_log ADD COLUMN msg_state TEXT DEFAULT 'normal';   -- normal/recalled/edited
```

**新增索引**：
```sql
CREATE INDEX IF NOT EXISTS idx_chat_reply_to ON chat_log(reply_to_id);
CREATE INDEX IF NOT EXISTS idx_chat_recalled ON chat_log(is_recalled);
```

**兼容性策略**：在 `_create_tables()` 中用 `PRAGMA table_info(chat_log)` 检测列是否存在，已存在则跳过 ALTER。

**验证**：
```python
python -c "from core.database import Database; db=Database(); rows=db.query('PRAGMA table_info(chat_log)'); print([r['name'] for r in rows])"
# 输出应包含 reply_to_id, is_recalled, attachments, msg_state
```

---

### Batch 2：RecallManager 接入（后端 P0）

**目标**：将现有的 `communication/recall_manager.py` 实例化到 Companion 中，挂入 Pipeline 和 SendQueue。

**改写文件**：

| 文件 | 改动 |
|------|------|
| `core/companion.py` | `start()` 中 `self.recall_manager = RecallManager(self.qq)`；注入 Pipeline 和 SendQueue |
| `core/pipeline.py` | `_emit_assistant()` 完成后调用 `recall_manager.on_message_sent()`；`_handle_user_message()` 前调用 `handle_user_negative()` |
| `communication/send_queue.py` | `_worker()` 中每条发送成功后回调 `recall_manager.on_message_sent()` |
| `communication/recall_manager.py` | 增加 `parse_recall_window()` 读取 persona.yaml 配置 |

**新增 persona.yaml 字段读取**：
```python
recall_cfg = load_persona().get("recall", {})
window = recall_cfg.get("window_seconds", 120)
min_gap = recall_cfg.get("min_recall_gap_seconds", 60)
max_recalls = recall_cfg.get("max_recalls_per_session", 5)
```

**LLM 主动撤回决策**（人格融合核心）：
- 在 ContextBuilder L1 prompt 中增加「撤回铁律」：「你发送的消息，如果你判断属于'说漏嘴'、'心直口快'、'表达害羞真心'，可在 2 分钟内主动撤回。每次撤回后说一句'撤回''当我没说'。」
- Pipeline 第 6.5 步：LLM 返回时可附带 `action: recall` 字段（通过 tool_call 或 special format）
- 触发条件：温柔情绪 + 阈值「渴望值」≥ 60 时主动撤回概率提升

**验证**：
- Pipeline 单元测试：mock LLM 返回带 `action: recall` → Pipeline 调用 recall_manager → DB chat_log.is_recalled=1
- 手测：发「我爱你」3 次 → 验证伊塔回复 2 次主动撤回 + 1 次保留

---

### Batch 3：撤回 HTTP API + 前端 UI

**目标**：本地聊天面板可手动撤回自己或伊塔的消息，撤回气泡带"伊塔 撤回了一条消息"提示。

**API 端点新增**（`core/api_server.py`）：
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/chat/recall/{msg_id}` | POST | 撤回消息（用户/AI 都可调用） |
| `/api/chat/recall_status` | GET | 查询消息撤回状态（轮询用） |

**后端逻辑**：
```python
@app.post("/api/chat/recall/{msg_id}")
async def recall_message(msg_id: int):
    msg = _db.query_one("SELECT * FROM chat_log WHERE id = ?", (msg_id,))
    if not msg: return {"error": "not found"}
    if msg["is_recalled"]: return {"error": "already recalled"}
    # 检查时间窗
    if (datetime.now() - parse_dt(msg["created_at"])).total_seconds() > 120:
        return {"error": "recall window expired"}
    _db.update("chat_log", {"is_recalled": 1, "recalled_at": now_iso(), "msg_state": "recalled"}, "id = ?", (msg_id,))
    # 如果是 AI 消息且来源是 QQ，调用 NapCat 撤回
    if msg["role"] == "assistant" and msg["msg_type"] == "private":
        await companion.recall_qq_message(msg_id)
    emit("recall", id=msg_id, user_id=msg["user_id"])
    return {"status": "ok"}
```

**前端 UI**（`electron/src/renderer/js/chat.js`）：
- 鼠标悬停消息气泡 → 右上角浮现 `⋮` 按钮
- 点击 `⋮` → 弹出操作菜单（撤回 / 引用 / 复制）
- 选择「撤回」→ `POST /api/chat/recall/{msg_id}` → 前端更新气泡显示「你撤回了一条消息」
- IPC 监听 `recall` 事件 → 远端撤回的消息实时同步显示

**CSS**（`electron/src/renderer/styles/main.css`）：
```css
.chat-msg { position: relative; }
.chat-msg-actions {
  position: absolute; top: 4px; right: 8px;
  opacity: 0; transition: opacity .2s;
  display: flex; gap: 4px;
}
.chat-msg:hover .chat-msg-actions { opacity: 1; }
.chat-msg-recalled {
  font-style: italic; color: var(--color-text-muted);
  background: var(--bg-100) !important;
  font-size: 12px;
}
```

**验证**：
- `pytest tests/test_recall.py` 通过
- 手测：发消息 → 1 分钟内点击撤回 → 气泡变"你撤回了一条消息"

---

### Batch 4：消息引用（叠加式设计）

**目标**：用户/伊塔的回复可引用之前的某条消息，引用内容叠加在新消息气泡内。

**数据模型**：依赖 Batch 1 新增的 `reply_to_id` / `reply_to_content` / `reply_to_role` 字段。

**前端交互**（`electron/src/renderer/js/chat.js`）：
- 鼠标悬停消息 → `⋮` 菜单点击「引用」
- 输入框上方出现叠加引用条：显示「引用 XXX」+ 引用内容前 60 字预览 + `✕` 取消按钮
- 输入区高度自动 +40px
- 发送时附带 `reply_to_id`，写入 chat_log

**叠加式气泡渲染**：
```
┌─────────────────────────┐
│ ▎ 引用 伊塔 5 分钟前    │  ← 浅灰色引用条，点击跳转
│ ▎ 我在。过来坐。        │
├─────────────────────────┤
│ 谢谢你记得这些。         │  ← 当前回复正文
└─────────────────────────┘
```

**LLM 上下文注入**（`core/context_builder.py`）：
当用户消息带 `reply_to_id`，在 system prompt 追加：
```
[引用上下文]
上一条被引用的消息（来自 {role}，{time_ago} 前）：
「{reply_to_content}」

回复时可在合适处呼应这条消息，例如：
- 如果是引用伊塔之前的某句话 → 可以延续/补充/纠正
- 如果是引用用户的话 → 表示被听到、被理解
```

**API 端点增强**：
- `/api/chat/send` 接受 `reply_to_id` 字段
- `/api/chat/history` 返回时附带 `reply_to_id` 等字段供前端渲染

**点击跳转**：
```js
function jumpToOriginal(replyToId) {
  const el = document.querySelector(`[data-msg-id="${replyToId}"]`);
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.add('chat-msg--highlight');
    setTimeout(() => el.classList.remove('chat-msg--highlight'), 1500);
  }
}
```

**伊塔主动引用决策**（人格融合）：
- ContextBuilder prompt 注入：「你回复时可以在 20% 概率引用主人 5-10 句内说过的某句话，让主人知道你认真听。」
- 这让伊塔显得「记住」「在意」。

**验证**：
- 手测：用户发「今天好累」 → 伊塔可能回复「(想起你之前说过的'加班好累')」
- 点击引用条 → 跳转并高亮原消息

---

### Batch 5：文件上传（19 类格式）

**目标**：本地聊天面板支持图片、文档、压缩包、语音、视频、可执行文件上传，伊塔可看到附件并结合上下文回复。

**支持的 19 类**（与 QQ/微信/钉钉对齐）：

| 类型 | 格式 | 大小限制 |
|------|------|----------|
| 图片 | jpg/jpeg/png/gif/webp | 20MB |
| 文档 | pdf/doc/docx/xls/xlsx/ppt/pptx/txt | 50MB |
| 压缩包 | zip/rar/7z | 100MB |
| 语音 | mp3/wav/m4a/opus | 20MB |
| 视频 | mp4/mov/avi | 100MB |
| 可执行 | exe/apk（仅记录） | 50MB |

**后端**：
- `core/api_server.py` 新增 `/api/chat/upload` 端点（multipart/form-data）
- FastAPI `UploadFile` 接收 → 保存到 `uploads/{yyyy-MM}/{uuid}.{ext}`
- 返回 `{url: "uploads/xxx.png", size, type, name}`
- 客户端拿到 URL 后用 `/api/chat/send?attachment=...` 发送

**前端**（`electron/src/renderer/index.html` + `chat.js`）：
- 输入框左侧 `📎` 按钮 → `<input type="file" hidden>`
- 输入框支持拖放（`dragover`/`drop` 事件）
- 输入框支持图片粘贴（`paste` 事件 + Clipboard API）
- 发送前显示附件缩略图预览（图片）或文件图标

**附件气泡渲染**：
```html
<div class="chat-msg chat-msg--user">
  <div class="chat-bubble">
    <div class="attachment-card" data-type="image">
      <img src="/api/uploads/2026-07/uuid.png" alt="">
    </div>
    <div class="chat-text">看下这张图</div>
  </div>
</div>
```

**LLM 上下文注入**：
当消息带 attachments，prompt 追加：
```
[附件]
用户发送了一张图片 / 一个文件：
- 文件名：xxx.png
- 类型：image
- 路径：uploads/2026-07/uuid.png

请基于这个附件内容回应。如果附件是图片（多模态 API 可用），请描述/分析它。
```

**伊塔多模态能力**：当前 DeepSeek/SiliconFlow/Qwen 中，Qwen-VL 和 Gemini 支持图像理解。Pipeline 检测到图片附件时自动切换到 vision-capable provider。

**验证**：
- `pytest tests/test_upload.py` 通过
- 手测：拖入一张猫图 → 伊塔描述图片内容

---

### Batch 6：QQ 渠道同步撤回与引用

**目标**：本地撤回/引用通过 NapCat OneBot11 API 同步到 QQ 渠道。

**改写文件**：
- `communication/qq_client.py` 新增 `recall_message(msg_id)` 方法（OneBot11 `delete_msg`）
- `communication/qq_client.py` 新增 `send_reply_message(user_id, content, reply_to_msg_id)` 方法（OneBot11 `reply` 消息段）
- `core/companion.py` 新增 `recall_qq_message(msg_id)` 协调方法

**OneBot11 delete_msg 协议**：
```json
{
  "action": "delete_msg",
  "params": { "message_id": 123456 }
}
```

**OneBot11 reply 消息段**：
```json
{
  "action": "send_private_msg",
  "params": {
    "user_id": 3998874040,
    "message": [
      { "type": "reply", "data": { "id": 123456 } },
      { "type": "text", "data": { "text": "我也在想你" } }
    ]
  }
}
```

**同步逻辑**（Pipeline 第 10 步）：
```python
if msg.source == "qq":
    # 写入 chat_log 后
    # 如果是用户消息附带 reply_to，发送到 QQ 时附带 reply 段
    reply_segments = []
    if msg.reply_to_id:
        reply_segments.append({"type": "reply", "data": {"id": msg.reply_to_id}})
    reply_segments.append({"type": "text", "data": {"text": reply_text}})
    self.qq.send_message_with_segments(user_id, reply_segments)
```

**撤回同步**（Pipeline `_emit_recall`）：
```python
async def recall_qq_message(self, msg_id):
    """撤回 QQ 端消息，同步本地 chat_log"""
    # 查 chat_log 找到对应 QQ message_id（需在 OneBot11 元数据中保存）
    msg = self.db.query_one("SELECT * FROM chat_log WHERE id = ?", (msg_id,))
    if not msg or not msg.get("qq_message_id"):
        return False
    # 调 NapCat delete_msg
    return await self.qq.recall_message(msg["qq_message_id"])
```

**验证**：
- `pytest tests/test_qc_recall.py` 通过
- 手测：本地撤回伊塔的 QQ 消息 → QQ 端也撤回

---

### Batch 7：UI 设计统一与可用性测试

**目标**：所有新功能 UI 与现有 5 套主题保持视觉一致；可用性测试通过。

**视觉规范检查清单**：
- [ ] 引用条颜色用 `--color-bg-secondary`
- [ ] 撤回气泡斜体用 `--color-text-muted`
- [ ] 操作按钮 hover 用 `--color-primary`
- [ ] 附件卡片用 `--bg-200` 背景
- [ ] 高亮跳转用 `box-shadow: 0 0 0 2px var(--color-primary)` 闪烁

**交互一致性**：
- [ ] 所有可操作元素 hover 有视觉反馈
- [ ] 按钮 active 状态有按下效果
- [ ] 操作菜单出现/消失用 0.2s 缓动
- [ ] 输入框聚焦有 primary 色 outline

**键盘快捷键**：
- `↑` 编辑上一条消息
- `Esc` 取消当前引用
- `Ctrl+Z` 撤回刚发送的消息

**可用性测试**：
- 任务 1：发送图片 → 检查伊塔回复含图片描述（通过率 ≥ 90%）
- 任务 2：引用某条消息 → 检查新消息气泡显示引用条（通过率 ≥ 95%）
- 任务 3：2 分钟内撤回自己消息 → 检查气泡变"你撤回了一条消息"（通过率 ≥ 95%）

---

### Batch 8：测试套件 + 文档

**目标**：完整测试覆盖 + 文档归档。

**测试文件**：
| 文件 | 测试数 | 覆盖 |
|------|--------|------|
| `tests/test_recall.py` | 12 | RecallManager + API + 时间窗 |
| `tests/test_quote.py` | 10 | 引用数据库字段 + API + LLM 注入 |
| `tests/test_upload.py` | 8 | 上传 endpoint + 附件存储 + 类型验证 |
| `tests/test_chat_ui.py` | 6 | DOM 渲染 + 事件 + 操作菜单 |

**总测试数**：129 + 36 = **165 测试**

**文档归档**：
- `.trae/documents/chat-system-design.md` — 聊天系统设计稿
- `.trae/documents/recall-mechanism-spec.md` — 撤回机制规范
- `.trae/documents/upload-types-spec.md` — 上传类型规范
- 更新 `logic-link-analysis-report.md`

---

## 四、文件清单

### 新建文件

| 文件 | 说明 |
|------|------|
| `electron/src/renderer/js/chat-actions.js` | 消息操作菜单（撤回/引用/复制） |
| `electron/src/renderer/js/chat-uploader.js` | 文件上传组件（拖放/粘贴/选择） |
| `electron/src/renderer/js/quote-bar.js` | 引用输入条组件 |
| `tests/test_recall.py` | 撤回机制测试 |
| `tests/test_quote.py` | 引用功能测试 |
| `tests/test_upload.py` | 上传功能测试 |
| `tests/test_chat_ui.py` | 聊天 UI 测试 |
| `uploads/.gitkeep` | 上传目录占位 |
| `e:\Agent_reply\.trae\documents\chat-system-design.md` | 聊天系统设计文档 |
| `e:\Agent_reply\.trae\documents\recall-mechanism-spec.md` | 撤回机制规范 |
| `e:\Agent_reply\.trae\documents\upload-types-spec.md` | 上传类型规范 |

### 改写文件

| 文件 | 改动 |
|------|------|
| `core/database.py` | +7 列 chat_log + 2 索引 + 兼容性检测 |
| `core/companion.py` | 实例化 RecallManager + 注入 Pipeline/SendQueue |
| `core/pipeline.py` | 接入 recall + quote + 主动撤回决策 |
| `core/api_server.py` | +4 端点（recall/recall_status/upload/chat send 支持附件） |
| `core/context_builder.py` | 引用上下文注入 + 撤回铁律 prompt |
| `core/brain.py` | vision-capable provider 选择 |
| `communication/recall_manager.py` | 读取 persona.yaml 配置 + parse_recall_window |
| `communication/qq_client.py` | + recall_message + send_message_with_segments |
| `communication/send_queue.py` | 回调 recall_manager.on_message_sent |
| `communication/message.py` | + reply_to_id / attachments 字段 |
| `electron/src/renderer/index.html` | + 附件预览 + 引用条 + 操作菜单 DOM |
| `electron/src/renderer/js/chat.js` | hover/右键/操作菜单/撤回/引用/上传 |
| `electron/src/renderer/styles/main.css` | + 操作按钮/引用条/撤回气泡/附件卡片样式 |
| `electron/src/main.js` | + 上传文件下载静态路由 |
| `electron/src/preload.js` | + recall API + upload API |
| `config/persona.yaml` | 完善 recall 配置 |

---

## 五、依赖关系图

```
Batch 1 (DB Schema)
    ↓
Batch 2 (Recall 后端) ←─── Batch 3 (Recall API+UI)
    ↓                        ↓
Batch 4 (Quote) ←─────── Batch 5 (Upload)
    ↓                        ↓
Batch 6 (QQ 同步) ←─────── Batch 7 (UI 统一)
                              ↓
                          Batch 8 (测试+文档)
```

可并行：Batch 3 + Batch 4（依赖 Batch 1/2）+ Batch 5（依赖 Batch 1）

---

## 六、累积式验证策略

### 第 1 轮：Batch 1 独立
- `pytest tests/test_database.py` 通过
- DB migration 不破坏已有数据

### 第 2 轮：Batch 1+2 集成
- `pytest tests/test_recall_manager.py` 通过
- 手测 Pipeline 记录 on_message_sent

### 第 3 轮：Batch 1+2+3 集成
- 完整发消息 → 手动撤回 → DB 标记 + UI 更新

### 第 4 轮：Batch 1+2+3+4 集成
- 发消息 → 引用 → LLM 上下文正确注入
- 点击引用条 → 跳转 + 高亮

### 第 5 轮：Batch 1+2+3+4+5 集成
- 上传图片 → 伊塔描述图片
- 上传文档 → 伊塔确认收到

### 第 6 轮：Batch 6（QQ 同步）
- 本地撤回 → QQ 同步撤回
- 本地引用 → QQ 消息带 reply 段

### 第 7 轮：Batch 7（UI 一致性）
- 5 套主题下视觉一致
- 可用性测试通过

### 第 8 轮：全量回归
- 全部 165 测试通过
- 0 回归

---

## 七、关键风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| DB ALTER 失败 | 破坏已有数据 | 用 PRAGMA 检测列是否存在，幂等迁移 |
| LLM 主动撤回频率过高 | 用户体验差 | persona.yaml 限频 + min_recall_gap_seconds |
| 上传大文件阻塞 | UI 卡顿 | 流式上传 + 进度条 |
| OneBot11 reply 段失败 | QQ 端引用不显示 | 退化为纯文本 + 引用描述前缀 |
| 多模态 API 不一致 | 伊塔看不到部分图片 | 根据 provider 自动降级到文本描述 |

---

## 八、验收标准

| # | 验收项 | 通过标准 |
|---|--------|----------|
| 1 | DB Schema 扩展 | 7 列 + 2 索引，无破坏 |
| 2 | RecallManager 接入 | Companion 实例化 + Pipeline/SendQueue hook |
| 3 | 手动撤回 UI | 2 分钟内可撤回，气泡显示"撤回了一条消息" |
| 4 | 伊塔主动撤回 | 温柔情绪 + 阈值触发时自动撤回 |
| 5 | 引用叠加气泡 | 引用内容在新气泡内，点击跳转 |
| 6 | LLM 引用感知 | ContextBuilder 注入引用上下文 |
| 7 | 19 类上传 | 全部支持，类型校验正确 |
| 8 | 多模态 | 图片类附件触发 vision-capable provider |
| 9 | QQ 同步 | 本地撤回 → NapCat delete_msg |
| 10 | 165 测试全过 | 含原 129 + 新增 36 |

---

## 九、输出物清单

| 类型 | 文件 |
|------|------|
| **新建 Python** | （仅 Batch 8 测试 + 已有 recall_manager 重写） |
| **改写 Python** | `database.py`, `companion.py`, `pipeline.py`, `api_server.py`, `context_builder.py`, `brain.py`, `recall_manager.py`, `qq_client.py`, `send_queue.py`, `message.py` |
| **新建 JS** | `chat-actions.js`, `chat-uploader.js`, `quote-bar.js` |
| **改写 JS** | `chat.js`, `main.js`, `preload.js` |
| **改写 CSS** | `main.css` |
| **改写 HTML** | `index.html` |
| **新建测试** | `test_recall.py`, `test_quote.py`, `test_upload.py`, `test_chat_ui.py` |
| **新建文档** | `chat-system-design.md`, `recall-mechanism-spec.md`, `upload-types-spec.md` |
| **新增目录** | `uploads/` |

---

## 十、时序安排

```
Day 1：Batch 1 + Batch 2 并行
  ├── Batch 1: DB Schema 扩展（~30 min）
  └── Batch 2: RecallManager 接入（~90 min）

Day 2：Batch 3 + Batch 4 并行
  ├── Batch 3: 撤回 UI + API（~120 min）
  └── Batch 4: 引用数据模型 + UI（~120 min）

Day 3：Batch 5 + Batch 6 并行
  ├── Batch 5: 文件上传（~150 min）
  └── Batch 6: QQ 渠道同步（~90 min）

Day 4：Batch 7 + Batch 8 并行
  ├── Batch 7: UI 一致性（~60 min）
  └── Batch 8: 测试 + 文档（~120 min）

Day 5：全量回归 + 修复
  └── 165 测试 + 0 回归 + 可用性测试通过
```

---

## 十一、设计原则坚持

1. **数据模型一致**：DB schema ↔ API response ↔ 前端 DOM 一一对应
2. **功能保护**：新增功能不破坏已有 5 主题系统 / 7 Tab / 129 测试
3. **QQ 兼容**：保留 NapCat OneBot11 全部功能，仅在已有 API 上扩展
4. **人格融合**：撤回/引用/上传三件套全部与伊塔的闷骚人设深度绑定
5. **累积验证**：每批次完成后立即验证，不堆到最后
6. **代码质量**：语法检查 + 注释规范 + 文件命名一致