# 聊天消息 · 动作/心理/旁白专用排版 + 完整 Markdown 渲染（Plan v2）

> 上一版（v1）的核心 R7.4 实现已经完成并在代码中落地，本版（v2）只补 3 个用户确认的加固点 + 1 个用户指出的代码问题。
>
> **本次不重写 chat.js / vendor / persona.yaml 的核心 R7.4 实现**，只做以下 4 个增量改动 + 验证。

---

## 0. 用户最新决策（v1 → v2 增量）

| # | 决策 | 落实方式 |
|---|---|---|
| D1 | 老消息兼容 | **保持现状**——只对 persona prompt 改动之后的新消息生效。历史 `*xxx*` 仍走 marked 渲染为 `<em>`，不被识别为 action 玻璃行。 |
| D2 | 链接安全 | **加固**——DOMPurify 加 `afterSanitizeAttributes` 钩子，给所有 `<a>` 强制 `target="_blank"` + `rel="noopener noreferrer nofollow"`。 |
| D3 | 后端基线恢复 | **包含**——本轮先 `launcher-user.bat` 重启后端 → `verify_zero_regression.py` 14/14 → 再做前端改动 → 最后 4 个 e2e 套件全绿。 |
| D4 | 代码卫生 | 删除 `main.css` 第 1057 行的空规则集 `.chat-bubble--text {}`（用户指出）。 |

---

## 1. 当前状态（v1 已落地，本次无需重做）

R7.4 的核心实现已在仓库中：

- ✅ [chat.js](file:///e:/Agent_reply/electron/src/renderer/js/chat.js) — `_parseMessage()` 拆 `<action>`/`<thought>`，`_renderMarkdown()` 跑 marked + DOMPurify + highlight.js
- ✅ [index.html](file:///e:/Agent_reply/electron/src/renderer/index.html) — vendor 引用齐备（`marked.min.js` / `purify.min.js` / `highlight.min.js` / `github.min.css`）
- ✅ [main.css](file:///e:/Agent_reply/electron/src/renderer/styles/main.css) — `.chat-bubble--action` 玻璃行、`.chat-bubble--thought` 虚线 italic 行、Markdown 元素全套样式
- ✅ [persona.yaml](file:///e:/Agent_reply/config/persona.yaml) — system_prompt 末尾「消息结构约定（必须遵守 · v1）」段已追加
- ✅ [e2e_narration.py](file:///e:/Agent_reply/e2e_narration.py) — 端到端验证脚本（TAG_RE bytes bug 已修复）
- ✅ [vendor/](file:///e:/Agent_reply/electron/src/renderer/vendor/) — 4 个文件齐备

开源社区调研结论（v1 已对齐）：
- **SillyTavern / Character.AI / JanitorAI** 主流方案：`*xxx*` Markdown 斜体表示动作描述
- **JanitorAI 社区脚本** 后处理统一为 italic 行 —— 与 R7.4 的 `<action>` 结构化思路殊途同归
- **marked + DOMPurify + highlight.js** 是社区最成熟组合（已采用）
- **工程铁律**（掘金/CSDN 共识）：先 marked → 再 DOMPurify（已对）、链接必须 `rel="noopener noreferrer nofollow"` + `target="_blank"`（**v2 补**）

---

## 2. v2 改动清单

### 2.1 删除空规则集（用户指出）— [main.css](file:///e:/Agent_reply/electron/src/renderer/styles/main.css) L1057

```diff
- /* R7.4: text bubble keeps the original look (assistant green / user
-    blue from the existing .chat-msg--assistant / .chat-msg--user rules).
-    This selector only makes the variant explicit so a future
-    dark/light theme override has a stable hook. */
- .chat-bubble--text {}
```

整段 6 行（含注释）删除。`getDiagnostics` 不再因空规则发警告。

### 2.2 链接安全加固（决策 D2）— [chat.js](file:///e:/Agent_reply/electron/src/renderer/js/chat.js) `_renderMarkdown()`

在 `try` 块的 `window.DOMPurify.sanitize(...)` **之前**注册钩子（一次性）：

```javascript
_renderMarkdown(text) {
  const body = text || "";
  if (!window.marked || !window.DOMPurify || !window.hljs) {
    return this._escapeHtml(body);
  }
  try {
    // R7.4 v2: 给所有 <a> 强制加 target=_blank + rel=noopener noreferrer nofollow
    // 这是社区共识（掘金/CSDN）：防止 reverse tabnabbing，且外链不传 SEO 权重。
    // 钩子只注册一次；多次调用 _renderMarkdown 也不会重复注册（DOMPurify 内部去重）。
    if (!window.DOMPurify._aerieLinkHooked) {
      window.DOMPurify.addHook("afterSanitizeAttributes", (node) => {
        if (node.tagName === "A") {
          node.setAttribute("target", "_blank");
          node.setAttribute("rel", "noopener noreferrer nofollow");
        }
      });
      window.DOMPurify._aerieLinkHooked = true;
    }
    const html = window.marked.parse(body, {
      gfm: true,
      breaks: true,
      langPrefix: "hljs language-",
    });
    const safe = window.DOMPurify.sanitize(html, {
      ADD_ATTR: ["class", "target", "rel"],
    });
    return safe;
  } catch (e) {
    console.warn("chat._renderMarkdown failed", e);
    return this._escapeHtml(body);
  }
}
```

**为什么不直接用 marked 的 renderer？** 因为 marked renderer 改 `<a>` 输出在 sanitize 之后还要被 DOMPurify 重新解析，反而引入新的不一致。afterSanitizeAttributes 钩子是 DOMPurify 官方推荐的外链加固点。

### 2.3 不改 chat.js 其它方法（边界保护）

- `_parseMessage()` — 不变（D1 决策：老消息不迁移）
- `_render()` — 不变（不区分 role，user 消息含 `<action>` 字面量被 escape 不渲染成玻璃行——已通过 regex 行为保证）
- `_escapeHtml()` — 不变
- vendor 文件 — 不动

### 2.4 不改其它文件

- [persona.yaml](file:///e:/Agent_reply/config/persona.yaml) — 不动
- [index.html](file:///e:/Agent_reply/electron/src/renderer/index.html) — 不动
- 其它 css — 不动

---

## 3. 验证步骤（按顺序，先恢复基线 → 再改前端 → 再 e2e）

### Step 0：后端基线恢复（决策 D3）

```powershell
# 1) 关闭 Electron 窗口（如果有残留）
# 2) 启动 launcher-user.bat
cd e:\Agent_reply
.\launcher-user.bat
# 3) 等后端 7890 端口就绪（statusbar 显示"后端已连接"）
```

```bash
# 4) 跑零回归，确认上一版没把后端搞坏
python verify_zero_regression.py
# 期望：14/14 通过
```

**基线不通过怎么办？** 不进入 Step 1，先排查后端问题（拉 `e2e_self_evolve.log` / `verify_zero_regression.log` / Electron console）。

### Step 1：应用 v2 改动

按 §2.1、§2.2 改 [main.css](file:///e:/Agent_reply/electron/src/renderer/styles/main.css) 和 [chat.js](file:///e:/Agent_reply/electron/src/renderer/js/chat.js)。

### Step 2：三原则自检

```bash
npm run check:emojis
npm run check:forbidden
npm run check:tokens
# 期望：3 项全过；check:tokens 的 33 个 R6.4 已知项不动
```

### Step 3：E2E 套件

```bash
python verify_zero_regression.py     # 14/14
python e2e_pacing.py                 # 96/96
python e2e_self_evolve.py            # 20/20
python e2e_narration.py              # 新 · 期望 LLM 真的输出 <action>/<thought>
```

**e2e_narration 软失败处理**：如果 LLM 第一次没输出 tag，prompt 已写明 3 正确 + 1 错误示范，TAG_RE 用 `re.compile` 字符串（非 bytes）。如果持续 < 70% 命中率（连续 3 次），回到 prompt 调整。

### Step 4：手动验收

启动 launcher-user.bat，给伊塔发：

1. **玻璃行验证**：发 "用 `<action>` 描述你正在做的事 + `<thought>` 你的想法"
   - 期望：消息体出现居中、灰边、小字（12px）的 action 玻璃行；italic 虚线边的 thought 玻璃行；对话在普通 bubble 里

2. **代码块验证**：发 "写一个 `console.log('hello')` 代码块"
   - 期望：github 主题灰底代码块，字体 `JetBrains Mono`

3. **粗斜体标题**：发 "**粗体** *斜体* # 一级标题"
   - 期望：3 种格式全部正确渲染

4. **链接安全**：发 "[测试外链](https://example.com)"
   - 期望：DevTools 检查 `<a target="_blank" rel="noopener noreferrer nofollow">`

---

## 4. 范围 / 非范围

**做**
- [main.css](file:///e:/Agent_reply/electron/src/renderer/styles/main.css) L1057 删空规则集
- [chat.js](file:///e:/Agent_reply/electron/src/renderer/js/chat.js) `_renderMarkdown` 加 DOMPurify 链接钩子
- launcher-user.bat 重启后端 + 4 个 e2e 套件

**不做**
- 不动 chat.js 的 `_parseMessage`（D1 决策：老消息不迁移）
- 不动 persona.yaml（v1 已定稿，命中率达预期不需要再改）
- 不动 vendor 文件
- 不动其它 css / html / 后端 Python 代码
- 不动 launcher-user.bat / start-companion.bat（已在 project_memory 硬约束）
- 不引入新依赖

---

## 5. 风险与决策记录

| 风险 | 缓解 |
|---|---|
| DOMPurify 钩子重复注册导致内存泄漏 | 用 `window.DOMPurify._aerieLinkHooked` 布尔位幂等保护 |
| LLM 不输出 `<action>` 标签 | persona prompt 已给 3 正确 + 1 错误示范；e2e_narration 跑 3 次都 < 70% 才视为失败 |
| 改完前端导致 Electron 缓存旧 vendor | 启动 launcher-user.bat 自动重建窗口，vendor 是 `<script src>` 直接读盘，无缓存问题 |
| 用户消息含 `<action>` 字面量被误识别为 action 行 | D1 决策保留：用户侧走 `_parseMessage` 也解析标签但 user 一般不写；如果误判，从视觉上也是居中玻璃行，不破坏布局 |
| check:tokens 33 个 R6.4 已知项 | 不动 v2 范围，R6.4 是独立批次 |

---

## 6. 实施后产物

- [main.css](file:///e:/Agent_reply/electron/src/renderer/styles/main.css) -6 行（L1057 空规则集删除）
- [chat.js](file:///e:/Agent_reply/electron/src/renderer/js/chat.js) +8 行（_renderMarkdown 加钩子 + 幂等保护）
- `.trae/documents/plan-chat-narration-markdown-v2.md` ← 本文件
- 4 个 e2e 套件全绿日志

---

## 7. 决策点闭环（v1 + v2 全部决策汇总）

| 决策点 | 选型 | 来源 |
|---|---|---|
| 识别方式 | `<action>`/`<thought>` 结构化标签 | v1 AskUserQuestion |
| 视觉区分 | 动作 灰边+居中+小字+无 italic；心理 更深灰底+虚线边+居中+小字+italic | v1 AskUserQuestion |
| Markdown 库 | marked + DOMPurify + highlight.js | v1 AskUserQuestion |
| 库安装方式 | vendor 单文件 + unpkg 兜底 | v1 实施 |
| 老消息兼容 | 仅新消息生效 | v2 AskUserQuestion D1 |
| 链接安全 | 加 afterSanitizeAttributes 钩子 | v2 AskUserQuestion D2 |
| 后端基线 | 包含后端恢复 | v2 AskUserQuestion D3 |
| 代码卫生 | 删空规则集 | v2 用户主动指出 D4 |
