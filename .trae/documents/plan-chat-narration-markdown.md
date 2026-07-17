# 聊天消息 · 动作/心理/旁白专用排版 + 完整 Markdown 渲染（Plan v1）

> 用户诉求：
> 1. 伊塔消息里那些 `*xxx*` 描写（动作/心理）从对话里**剥出来**，独立成行、居中、灰色边、字号更小
> 2. 明确**区分心理 vs 动作**两类（不同强度）
> 3. 顺手让消息支持完整 Markdown 渲染（代码块带语法高亮、粗体、斜体、4 级标题）
>
> 用户已确认的 3 个核心决策（从 AskUserQuestion 拿到）：
> - **识别方式**：LLM 用 `<action>...</action>` / `<thought>...</thought>` 结构化标签（最精确，但需要改 persona prompt）
> - **视觉区分**：动作 灰边+居中+小字号+无 italic；心理 更深灰底+居中+小字号+italic
> - **库选型**：marked + DOMPurify + highlight.js 全套（社区最成熟组合）

---

## 0. 范围 / 非范围

**做**
- 改 [persona.yaml](file:///e:/Agent_reply/config/persona.yaml) 的 `system_prompt`：在末尾加"动作/心理必须用 `<action>`/`<thought>` 标签"的使用规则和 3 条示范
- 新增 vendor 资产：[marked.min.js](file:///e:/Agent_reply/electron/src/renderer/vendor/marked.min.js) / [purify.min.js](file:///e:/Agent_reply/electron/src/renderer/vendor/purify.min.js) / [highlight.min.js](file:///e:/Agent_reply/electron/src/renderer/vendor/highlight.min.js) + 主题 css `github.min.css` —— 从 npm 复制到 vendor/，不引入新依赖安装步骤
- [index.html](file:///e:/Agent_reply/electron/src/renderer/index.html) 顶部加 vendor 引用（chat.js 之前）
- [chat.js](file:///e:/Agent_reply/electron/src/renderer/js/chat.js) 加 `_parseMessage()`：先用 marked 解析对话部分、用 `&lt;action&gt;` / `&lt;thought&gt;` 标签切出三类（对话 / 动作 / 心理），然后 DOMPurify 净化，highlight.js 跑代码块
- [main.css](file:///e:/Agent_reply/electron/src/renderer/styles/main.css) 加 `.chat-bubble--action` / `.chat-bubble--thought` / `.chat-bubble pre` / `.chat-bubble code` 等样式
- 在 E2E 增加 1 个新检查：消息结构化标签解析的 round-trip

**不做**
- 不动后端 / 不动 SendQueue / 不动 cognition / 不动 emotion
- 不动 launcher-user.bat / 不动 main.py
- 不动 QQ 入站消息（只在主应用 chat 窗口内生效）
- 不引入新的打包依赖（marked / DOMPurify / highlight.js 全部走 vendor/ 单文件）
- 不动其他模块的样式（brief-drawer / emotion-dashboard / cognition-panel 不受影响）

---

## 1. 当前状态

- **chat.js 第 460 行**：`<div class="chat-bubble">${this._escapeHtml(msg.content || "")}</div>` —— 纯文本 escape，**完全没 markdown**
- **index.html 716 行**附近：`<script src="js/chat.js">` 之前没有任何 vendor 引用
- **persona.yaml** 的 system_prompt 没提动作/心理需要标签
- **vendor/ 目录**：不存在（需新建）
- **main.css** 有 `.chat-bubble` 的基础样式（蓝底/灰底/圆角/最大宽度 560px），无 `--action` / `--thought` 变体
- **没有 marked / DOMPurify / highlight.js 任何之一**

---

## 2. 消息结构化协议（LLM 输出约定）

新约定（persona prompt 中要写明的）：

```
# 一条伊塔消息的结构
"对话文本部分"（可直接被 markdown 渲染）
<action>伸手碰了碰你的脸。</action>           ← 动作
<thought>他今晚一定很累了。</thought>         ← 心理
"继续对话文本。"
<action>她侧身让出半边肩膀。</action>

# 规则
- 同一段动作或心理必须各自一个 <action>/<thought> 标签，不能两个混在一个标签里
- 标签内不要带引号、不要带 markdown，纯叙述
- 同一段对话 + 多个动作/心理可以交错
- 不写 action/thought 时就只是普通对话
```

客户端解析流程：
1. 用 regex `/<(action|thought)>([\s\S]*?)<\/\1>/g` 抽出所有标签及其内容
2. 原文移除这些标签后，剩下的就是"对话部分"——用 marked 解析 → DOMPurify 净化
3. 抽出的 `<action>` 内容放进 `.chat-bubble--action` 玻璃行
4. 抽出的 `<thought>` 内容放进 `.chat-bubble--thought` 玻璃行（更深的灰底 + italic）
5. 三类内容按出现顺序**逐行**塞进消息 body（DOM 顺序：对话-动作-心理-对话-动作...）

---

## 3. 改动清单

### 3.1 [persona.yaml](file:///e:/Agent_reply/config/persona.yaml) — system_prompt 末尾追加 1 段

在 system_prompt 末尾的 `现在，让他感受到。` 之前插入：

```yaml
## 消息结构约定（必须遵守）
你输出的每条消息由两类内容组成：**对话** 和 **动作/心理描写**。
- 对话：直接说话的内容，遵循上面的风格指南。
- 动作描写：用 `<action>...</action>` 包裹你的肢体动作（如伸手、低头、靠过来）。
- 心理描写：用 `<thought>...</thought>` 包裹你的内心活动或对用户情绪的判断。

规则：
1. 动作和心理必须各自独立一个标签，不要混在一起。
2. 标签内不要包含 markdown 符号、不要带引号，纯自然语言。
3. 同一段对话可以交错多个 <action> / <thought>，按出现顺序穿插。
4. 标签不要嵌套；不要在对话文本里写 <action> 字面量。

正确示范：
"在干嘛。{{停顿}}<action>伊塔放下手里的杯子，靠过来。</action>{{停顿}}<thought>他今天好像有心事。</thought>想说说吗。"

错误示范（不要这么写）：
- "<action>伸手，<thought>心里一软</thought>。</action>"  ← 嵌套
- "她想：<thought>我应该抱他。</thought>"                ← 心理带"她想："前缀
```

### 3.2 vendor 资产（新增）

`electron/src/renderer/vendor/`
- `marked.min.js` — 从 npm `marked@12.0.2` 取 dist/marked.min.js（~30KB）
- `purify.min.js` — 从 npm `dompurify@3.0.11` 取 dist/purify.min.js（~50KB）
- `highlight.min.js` — 从 npm `highlight.js@11.9.0` 取 build/highlight.min.js（~140KB）
- `github.min.css` — 从 npm `highlight.js@11.9.0` 取 styles/github.min.css（~1KB）

**安装方式**（手工复制，不引入 npm 依赖）：
```powershell
# 在 e:\Agent_reply\electron\src\renderer\ 下创建 vendor
mkdir vendor
# 从已下载的 npm 缓存或 unpkg 拉文件
Invoke-WebRequest -Uri "https://unpkg.com/marked@12.0.2/marked.min.js" -OutFile "vendor/marked.min.js"
Invoke-WebRequest -Uri "https://unpkg.com/dompurify@3.0.11/dist/purify.min.js" -OutFile "vendor/purify.min.js"
Invoke-WebRequest -Uri "https://unpkg.com/@highlightjs/cdn-assets@11.9.0/highlight.min.js" -OutFile "vendor/highlight.min.js"
Invoke-WebRequest -Uri "https://unpkg.com/@highlightjs/cdn-assets@11.9.0/styles/github.min.css" -OutFile "vendor/github.min.css"
```

（如果用户不喜欢从 unpkg 拉，可以从 `e:\Agent_reply\node_modules\` 现有包里 copy，project 之前应该已经装了 `marked` / `dompurify` / `highlight.js` 因为前端有 dependencies。计划默认用 unpkg 兜底。）

### 3.3 [index.html](file:///e:/Agent_reply/electron/src/renderer/index.html) — 加 vendor 引用

在 `<script src="js/chat.js">` 之前插入：

```html
<link rel="stylesheet" href="vendor/github.min.css">
<script src="vendor/marked.min.js"></script>
<script src="vendor/purify.min.js"></script>
<script src="vendor/highlight.min.js"></script>
```

### 3.4 [chat.js](file:///e:/Agent_reply/electron/src/renderer/js/chat.js) — 加 `_parseMessage()` 替换 _escapeHtml

新增方法：

```javascript
_parseMessage(content) {
  // 1) 抽出 <action> / <thought> 标签，按出现顺序记下
  const tagRe = /<(action|thought)>([\s\S]*?)<\/\1>/g;
  const parts = []; // {type: "text" | "action" | "thought", body: string}
  let last = 0;
  let m;
  while ((m = tagRe.exec(content)) !== null) {
    if (m.index > last) {
      parts.push({ type: "text", body: content.slice(last, m.index) });
    }
    parts.push({ type: m[1] === "action" ? "action" : "thought", body: m[2].trim() });
    last = m.index + m[0].length;
  }
  if (last < content.length) {
    parts.push({ type: "text", body: content.slice(last) });
  }
  // 2) 每段分别渲染：text → marked + DOMPurify，action/thought → 纯文本 escape
  return parts.map((p) => {
    if (p.type === "text") {
      const md = window.marked.parse(p.body, { breaks: true, gfm: true });
      const safe = window.DOMPurify.sanitize(md, {
        ADD_ATTR: ["class"], // 让 highlight.js 注入的 hljs 类名能通过
      });
      return `<div class="chat-bubble chat-bubble--text">${safe}</div>`;
    }
    const esc = this._escapeHtml(p.body);
    return `<div class="chat-bubble chat-bubble--${p.type}">${esc}</div>`;
  }).join("");
}
```

把第 460 行：
```javascript
html += `<div class="chat-bubble">${this._escapeHtml(msg.content || "")}</div>`;
```
改成：
```javascript
html += this._parseMessage(msg.content || "");
```

**highlight.js 集成**：在 `DOMContentLoaded` 后调一次 `window.hljs.highlightAll()`，marked 配置 `langPrefix: 'hljs language-'` 让 class 走对。

### 3.5 [main.css](file:///e:/Agent_reply/electron/src/renderer/styles/main.css) — 加 action/thought 样式

```css
/* 已有 .chat-bubble 作为基类，新增 3 个变体 */
.chat-bubble--text { /* 保持原样，蓝色 / 灰色 bubble */ }

/* 动作：灰边、居中、小字、无 italic */
.chat-bubble--action {
  max-width: 80%;
  margin-top: 4px;
  background: var(--glass-bg-2);
  border: 1px solid var(--glass-border);
  border-radius: var(--brief-row-radius);
  padding: 6px 14px;
  text-align: center;
  font-size: 12px;
  color: var(--color-text-muted);
  align-self: center;
  font-style: normal;
  font-weight: 400;
  line-height: 1.55;
}

/* 心理：更深灰底、居中、小字、italic */
.chat-bubble--thought {
  max-width: 80%;
  margin-top: 4px;
  background: color-mix(in srgb, var(--color-text-muted) 8%, var(--glass-bg-1));
  border: 1px dashed color-mix(in srgb, var(--color-text-muted) 40%, transparent);
  border-radius: var(--brief-row-radius);
  padding: 6px 14px;
  text-align: center;
  font-size: 12px;
  font-style: italic;
  color: var(--color-text-muted);
  align-self: center;
  line-height: 1.55;
}

/* 用户消息里的 action/thought 也要走居中（气泡容器 body 已经是 align-items: flex-end） */
.chat-msg--user .chat-bubble--action,
.chat-msg--user .chat-bubble--thought { align-self: center; }
```

外加 Markdown 元素样式：
```css
.chat-bubble pre {
  background: rgba(0,0,0,0.06);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 10px 12px;
  overflow-x: auto;
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.55;
  margin: 6px 0;
}
.chat-bubble code {
  background: rgba(0,0,0,0.06);
  padding: 1px 5px;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 0.9em;
}
.chat-bubble pre code { background: transparent; padding: 0; }
.chat-bubble h1, .chat-bubble h2, .chat-bubble h3, .chat-bubble h4 {
  margin: 8px 0 4px;
  font-weight: 600;
  line-height: 1.3;
  color: var(--color-text);
}
.chat-bubble h1 { font-size: 18px; }
.chat-bubble h2 { font-size: 16px; }
.chat-bubble h3 { font-size: 14.5px; }
.chat-bubble h4 { font-size: 13.5px; }
.chat-bubble ul, .chat-bubble ol { margin: 4px 0 4px 18px; padding: 0; }
.chat-bubble li { margin: 2px 0; }
.chat-bubble strong { font-weight: 600; color: var(--color-text); }
.chat-bubble em { font-style: italic; }
.chat-bubble a { color: var(--color-primary); text-decoration: underline; }
.chat-bubble blockquote {
  border-left: 3px solid var(--color-primary);
  padding-left: 10px;
  margin: 6px 0;
  color: var(--color-text-muted);
  font-style: italic;
}
```

---

## 4. 验证步骤（按顺序）

1. **手动恢复后端**（先）
   - 关掉 Electron 窗口
   - 双击 `launcher-user.bat` 重启套件
   - 确认 Electron 状态栏显示"后端已连接"
2. **三原则自检**（R6 三原则，承诺过每次都跑）
   - `npm run check:emojis` —— vendor 文件夹里的 js 不是项目 emoji 扫描范围
   - `npm run check:forbidden` —— 同上
   - `npm run check:tokens` —— 新增的 `color-mix()` 调用必须能通过现有 token 检查器（先跑看）
3. **新加 E2E**：`e2e_narration.py`（建议新文件，~40 行）
   - POST `/api/chat/send` 发送测试 prompt "请用 `<action>` / `<thought>` 标签写一句"
   - 拉 `/api/chat/history?limit=1`
   - assert `content` 包含至少 1 个 `<action>` 或 `<thought>` 标签
   - assert 后端没有因为 persona 改动崩（status 200）
4. **零回归 + e2e 套件**
   - `python verify_zero_regression.py` —— 14/14
   - `python e2e_pacing.py` —— 96/96
   - `python e2e_self_evolve.py` —— 20/20
5. **手动验收**（用户在自己机器上跑）
   - 启动 launcher-user.bat
   - 给伊塔发 "用 `<action>` 描写你正在做的事 + `<thought>` 你的想法"
   - 截图：消息里出现居中、灰边、小字的 action 玻璃行；italic 的 thought 虚线行
   - 给伊塔发 "写一个 `console.log('hello')` 代码块"
   - 截图：消息里出现带 github 主题高亮的灰底代码块
   - 给伊塔发 "**粗体** *斜体* `行内代码` # 标题"
   - 截图：粗体/斜体/行内代码/4 级标题都正确渲染

---

## 5. 风险与决策

| 风险 | 缓解 |
|---|---|
| LLM 不遵守 `<action>`/`<thought>` 标签 | prompt 写明 3 个正确 + 1 个错误示范；3 天后看 e2e_narration 命中率，< 70% 就改 prompt |
| marked 渲染长消息慢（> 5KB） | 用 worker 异步；先验证 < 1KB 消息 < 5ms 渲染 |
| DOMPurify 拒绝 highlight.js 注入的 class | `ADD_ATTR: ["class"]` 已在 plan 里 |
| vendor 文件没装 / 路径错 | 用 `unpkg` 兜底拉取；如果网络受限改 `npm install marked dompurify highlight.js` 然后 copy |
| `color-mix()` CSS 函数在老 Chromium 不支持 | fallback：直接用 `rgba(0,0,0,0.06)` 等已存在 token |
| 用户消息里也有 `<action>` 字面量（不是 LLM 写的） | regex 只匹配大小写敏感的 `<action>` / `<thought>`，用户消息照常 escape |
| 后端 persona prompt 改动导致伊塔性格漂移 | prompt 改动只追加末尾的"消息结构约定"段，不动前 170 行；跑零回归验证情绪/认知未漂移 |

---

## 6. 决策点（已确认不需要再问）

- 识别方式：`<action>` / `<thought>` 标签（已选）
- 视觉区分：动作灰边+小字号+无italic；心理更深灰底+小字号+italic（已选）
- 库选型：marked + DOMPurify + highlight.js 全套（已选）
- 范围：只动 chat.js / index.html / main.css / persona.yaml / 新增 vendor/，不外溢

---

## 7. 实施后产物

- [persona.yaml](file:///e:/Agent_reply/config/persona.yaml) system_prompt 末尾追加 1 段（~25 行）
- 新建 [electron/src/renderer/vendor/](file:///e:/Agent_reply/electron/src/renderer/vendor/) 4 个文件（marked / purify / highlight / github.min.css）
- [index.html](file:///e:/Agent_reply/electron/src/renderer/index.html) +4 行（3 个 script + 1 个 link）
- [chat.js](file:///e:/Agent_reply/electron/src/renderer/js/chat.js) +~60 行（`_parseMessage` 方法 + 替换第 460 行）
- [main.css](file:///e:/Agent_reply/electron/src/renderer/styles/main.css) +~70 行（action / thought 玻璃行 + Markdown 元素样式）
- 新建 [e2e_narration.py](file:///e:/Agent_reply/e2e_narration.py)（~40 行）
- 计划文件归档：`.trae/documents/plan-chat-narration-markdown.md`
- **额外（Step 0）**：确认后端"离线"是用户操作问题，不是 R7.3 引起的；恢复方式：双击 `launcher-user.bat`
