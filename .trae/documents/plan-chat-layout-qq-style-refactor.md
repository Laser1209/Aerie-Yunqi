# 对话页面重构 / Chat Page Refactor — Block-5E R6.5

## Summary

对话页面目前存在严重排版错乱：avatar 跑到名字和气泡上方堆成单列，
导致气泡宽度等于消息容器全宽却只显示单字。本计划在不重写 chat.js
渲染逻辑的前提下，补齐缺失的 CSS、重做行级排版、增加时间戳、保证
响应式与动画。

## Current State Analysis

### 根因（已通过代码阅读定位）

`chat.js` 渲染的 DOM 结构（[_renderMessage, line 396-435](file:///e:/Agent_reply/electron/src/renderer/js/chat.js#L396-L435)）：

```html
<div class="chat-msg chat-msg--assistant">
  <div class="chat-msg__avatar-wrap">…avatar…</div>     ← class 无 CSS
  <div class="chat-msg__body">                            ← class 无 CSS
    <div class="chat-msg__name">伊塔</div>
    <div class="chat-quote-overlay">…</div>              ← 可选
    <div class="chat-attachments">…</div>                ← 可选
    <div class="chat-bubble">…content…</div>
  </div>
  <div class="chat-msg-actions">…</div>                  ← hover-only
</div>
```

`main.css` 现状（[line 239-264](file:///e:/Agent_reply/electron/src/renderer/styles/main.css#L239-L264)）：

```css
.chat-msg { display: flex; margin-bottom: 12px; }      /* flex 但无 align-items */
.chat-msg--user { justify-content: flex-end; }
.chat-msg--assistant { justify-content: flex-start; }
.chat-bubble { max-width: 75%; padding: 10px 16px; … }
/* ⚠ chat-msg__avatar-wrap / chat-msg__body 完全没有规则 */
```

**失效链路**：
1. `.chat-msg` 是 flex row，三个直接子元素（avatar-wrap / body / actions）应横排
2. 但 `.chat-msg__avatar-wrap` 和 `.chat-msg__body` 是无样式的 `display: block`
3. flex 容器的子元素即使是 block，也仍按 row 排列——但 `align-items` 默认 `stretch`
4. body 拉伸到 `.chat-msg` 全高，bubble 在 body 内 column 排成单字宽
5. 实际表现：avatar 在最上一行、name 下一行、bubble 再下一行，bubble 仅含一个汉字

### 截图症状对应

| 截图位置 | 现象 | 根因 |
|---------|------|------|
| "早。" 气泡极窄 | bubble 宽度 ≈ 单字宽 | body 内 max-width: 75% 链断裂 |
| "过来一点，我听着。" 换行异常 | "我" / "听着" 独占行 | bubble 父容器宽度被压缩到 ~80px |
| "你" 消息只在最右显示 "早" | body 与 avatar 位置混乱 | row 布局下 actions 按钮截断了 body |
| 右侧大片空白 | chat-messages 容器宽但内容只占 5% | bubble 实际只占 1 个字符 |

## Proposed Changes

### 改动范围（最小化）

仅修改 `electron/src/renderer/styles/main.css`，**不动** chat.js / index.html。

理由：chat.js 已渲染正确的 DOM 结构，缺失的只是 CSS 布局规则。补齐
CSS 即可一次性解决所有排版问题，并顺势加上时间戳与动画。

### 1. 重写 `.chat-msg` 为标准 QQ 风格行布局

```css
.chat-msg {
  display: flex;
  align-items: flex-start;     /* 头像顶部对齐气泡列 */
  gap: 10px;
  margin-bottom: 16px;
  padding: 0 8px;
  animation: chat-msg-enter 320ms cubic-bezier(0.2, 0.8, 0.2, 1) both;
  position: relative;
}

/* Assistant（伊塔）: 头像在左，body 列在右 */
.chat-msg--assistant { flex-direction: row; }

/* User（你）: body 列在左，头像在右 */
.chat-msg--user { flex-direction: row-reverse; }

/* 让 user 消息里 body 的列靠右对齐 */
.chat-msg--user .chat-msg__body { align-items: flex-end; }
.chat-msg--assistant .chat-msg__body { align-items: flex-start; }
```

### 2. 补齐缺失的 avatar-wrap / body 样式

```css
.chat-msg__avatar-wrap {
  flex-shrink: 0;
  width: 36px;          /* 略放大到 36px，QQ 风格更清晰 */
  height: 36px;
  align-self: flex-start;
}

.chat-msg__body {
  display: flex;
  flex-direction: column;
  max-width: min(560px, 65%);   /* 上限 560px；窄屏用 65% */
  min-width: 0;                  /* 防止 flex 子元素被内容撑大 */
}

/* 名字小字：assistant 显示在气泡上方，user 也显示（QQ 习惯） */
.chat-msg__name {
  font-size: 11px;
  color: var(--color-text-muted, #888);
  margin: 0 4px 3px 4px;
  letter-spacing: 0.02em;
  line-height: 1.2;
  user-select: none;
}
```

### 3. 重写 `.chat-bubble` 圆角与配色

```css
.chat-bubble {
  max-width: 100%;                /* 由 __body 控制 560px 上限 */
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.55;              /* 阅读舒适度 */
  word-break: break-word;         /* 单词/长串换行 */
  white-space: pre-wrap;          /* 保留换行符 */
  letter-spacing: 0.01em;
  box-sizing: border-box;
}

/* 助手：浅灰 */
.chat-msg--assistant .chat-bubble {
  background: var(--bg-200, #f2f2f7);
  color: var(--color-text, #1a1a1a);
  border-top-left-radius: 4px;    /* 指向头像的小尖角 */
}

/* 用户：品牌主色 */
.chat-msg--user .chat-bubble {
  background: var(--color-primary, #007aff);
  color: var(--color-primary-fg, #ffffff);
  border-top-right-radius: 4px;
}
```

### 4. 增加时间戳 / 状态（chat.js 需小改）

需要 chat.js 协助输出 timestamp。在 `_renderMessage` 内：

```js
// 在 .chat-msg__name 旁边增加时间戳
const ts = msg.ts ? this._formatTime(msg.ts) : "";
html += `<div class="chat-msg__name">${this._escapeHtml(displayName)}</div>`;
if (ts) {
  html += `<div class="chat-msg__meta-time">${ts}</div>`;
}
```

时间格式方法：

```js
_formatTime(ts) {
  const d = new Date(typeof ts === "number" ? ts * 1000 : ts);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  if (sameDay) return `${hh}:${mm}`;
  const mo = String(d.getMonth() + 1).padStart(2, "0");
  const da = String(d.getDate()).padStart(2, "0");
  return `${mo}-${da} ${hh}:${mm}`;
}
```

CSS 配套：

```css
.chat-msg__meta-time {
  display: none;                  /* 后续可加：hover 显示 */
}
.chat-msg:hover .chat-msg__meta-time {
  display: block;
  position: absolute;
  top: -2px; left: 50%;
  transform: translateX(-50%);
  font-size: 10px;
  color: var(--color-text-muted, #888);
  background: var(--color-surface, #fff);
  padding: 1px 6px;
  border-radius: 4px;
  white-space: nowrap;
  z-index: 2;
  pointer-events: none;
}
```

> **决策点**：hover 才显示 vs 常驻显示
> - QQ 移动端常驻（每条消息都有时间）
> - QQ 桌面端 hover 才显示
> - 推荐：沿用桌面端习惯 hover 显示，避免时间戳把气泡撑高
> - 连续消息 ≤ 2 分钟时复用同一时间戳（减少视觉噪音）

### 5. 响应式（媒体查询）

```css
/* 平板 (≤ 768px) */
@media (max-width: 768px) {
  .chat-msg__body { max-width: 78%; }
  .chat-msg__avatar-wrap { width: 32px; height: 32px; }
}

/* 移动 (≤ 480px) */
@media (max-width: 480px) {
  .chat-msg { gap: 6px; padding: 0 6px; }
  .chat-msg__body { max-width: 82%; }
  .chat-msg__avatar-wrap { width: 28px; height: 28px; }
  .chat-bubble { font-size: 13.5px; padding: 8px 12px; }
}
```

### 6. 动画

```css
/* 进入动画：从下方 8px 淡入 */
@keyframes chat-msg-enter {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* 引用高亮 */
.chat-msg--highlight {
  animation: chat-msg-flash 1.2s ease;
}
@keyframes chat-msg-flash {
  0%, 100% { background: transparent; }
  20%      { background: rgba(255, 215, 0, 0.18); }
}

/* 新消息发送时按钮脉冲 */
.btn-send:active { transform: scale(0.92); }
.btn-send { transition: transform 120ms ease; }
```

### 7. 列表自动滚动

在 chat.js 的 `_renderMessage` 末尾已经 `this._el.messages.scrollTop = ...`
保持不变；CSS 加 `scroll-behavior: smooth` 即可让新消息平滑滚入：

```css
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
  scroll-behavior: smooth;       /* ← 新增 */
}
```

### 8. 移除冲突的旧规则

旧 CSS 中：
```css
.chat-msg--user { justify-content: flex-end; }
.chat-msg--assistant { justify-content: flex-start; }
```

改用 `flex-direction: row / row-reverse` 后这两行 `justify-content`
实际上不会生效（row-reverse 改变了主轴方向，但仍能让 body 列在头像
的「外侧」），保留也无所谓。但建议删除以减少混淆。

## Files to Edit

| 文件 | 改动 |
|------|------|
| `electron/src/renderer/styles/main.css` | **主要改动**：补齐 avatar-wrap/body 规则、重写 chat-msg / chat-bubble、增加响应式 / 动画 / 时间戳样式 |
| `electron/src/renderer/js/chat.js` | **小改**：在 `_renderMessage` 内增加 `_formatTime` 与 meta-time span 输出 |
| `electron/src/renderer/index.html` | 不改 |

## Assumptions & Decisions

- **时间戳显示策略**：hover 气泡时显示。理由：QQ 桌面端习惯；避免短消息被时间戳撑高；与现有 `.chat-msg:hover` 规则一致
- **气泡宽度上限**：560px（中等桌面端最佳）。窄屏按 65% → 78% → 82% 渐进
- **头像尺寸**：36px 主尺寸，移动端 28px。理由：36px 是 QQ 桌面端默认
- **chat.js 改动范围**：仅 `_renderMessage` 内插入 ts 字段，不动其他渲染逻辑
- **不改 HTML 结构**：现有 DOM 树足够，加 CSS 即可
- **不动深色模式**：所有颜色用 CSS 变量，五套主题自动适配

## Verification

实施后按顺序验证：

1. **布局回归** — 重启 Electron 客户端，进入聊天页发送消息
   - 期望：头像在左/右、名字小字在气泡上方、气泡宽度自适应
   - 验证：短消息（"早。"）气泡不再只有 1 字宽
2. **时间戳** — 鼠标 hover 消息气泡，期望时间戳在气泡上方淡入
3. **响应式** — 拖动窗口到 < 768px / < 480px，期望气泡与头像同步缩小
4. **动画** — 新消息发出，期望 320ms 淡入位移
5. **E2E 三原则** — `npm run check:emojis` / `check:forbidden` / `check:tokens` 全绿
6. **零回退** — 旧消息（数据库 / 内存）正常显示，时间戳兼容 ISO 字符串与 unix 时间戳

## Out of Scope

- 撤回 / 引用重写（已有 chat-quote-overlay / chat-msg-actions 保持不变）
- 消息发送节奏（Batch 7 pacing 改动不冲突）
- 表情/图片附件渲染（chat-attachments 样式不动）
- 输入区 / 麦克风（chat-input-area 不动）
