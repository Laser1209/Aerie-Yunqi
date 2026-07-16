# Phase 9 续批 · Block-3（混合输入 + Office→Markdown 转码 + 语音输入）执行计划

> 范围锚定：plan-phase9-e2e-and-block2-execute.md 已交付；本计划接力 Block-3。
> 决策 1：markitdown[all]（本地 Python 库）
> 决策 2：Web Speech API（webkitSpeechRecognition，需联网告知）
> 跑 SCRUM 节奏：先做完一个原子能力再下一个。

---

## 一、目标拆解

### Part A · 后端能力（先于前端）
- A.1 requirements.txt 加 `markitdown[all]>=0.0.1`
- A.2 新建 `core/attachment_handler.py`：office/pdf → markdown 转码，存 `data/attachments_md/`
- A.3 扩 `/api/upload` ALLOWED_TYPES 接收 docx/xlsx/pptx/pdf/html/csv/json/xml/epub
- A.4 扩 `/api/chat/send` 在 attachments 列表里挂 `markdown` 字段（由 handler 实时算）
- A.5 context_builder 优先读 attachment.markdown，缺则降级 metadata

### Part B · 前端混合输入
- B.1 chat-input-area 改 toolbar 模式：附件按钮（已存在）+ 语音按钮（新加）
- B.2 语音输入：webkitSpeechRecognition，中文 zh-CN，识别中显示脉冲
- B.3 附件卡片：上传后 .docx/.pdf 等非图文件，悬停显示"正在转 markdown"→ "已转好"
- B.4 文案：中英双语 + "需联网"提示，禁词禁"主人"

### Part C · 安全自审（TRAE-security-review）
- C.1 SQL/XSS/Path Traversal 复审：handler 路径拼接 + 上传文件名 / LLM prompt 注入 / shell 调用 markitdown
- C.2 三原则铁律：伊塔人格 / 5 主题色 / 代码层英文
- C.3 6 脚本零回归

---

## 二、后端详细计划

### 2.1 A.1 · requirements.txt

在 `e:\Agent_reply\requirements.txt` AI/LLM 区块追加：
```text
# Document → Markdown conversion (office / pdf / html / csv)
markitdown[all]>=0.0.1
```

`[all]` extra 含 docx/xlsx/pptx/pdf/audio，需多装 ~150MB 依赖（pdfminer.six / mammoth / openpyxl / python-pptx / pydub 等）。

### 2.2 A.2 · core/attachment_handler.py

**新文件**：`e:\Agent_reply\core\attachment_handler.py`

**关键设计**：
- 入口函数 `extract_markdown(file_path: str | Path, *, max_bytes: int = 20 * 1024 * 1024) -> str | None`
- 仅白名单类型走 markitdown：`{pdf, doc, docx, xls, xlsx, ppt, pptx, html, htm, csv, json, xml, epub, txt, md}`
- 非白名单或转码失败 → 返回 None（让上层降级到 metadata）
- 转码结果存 `data/attachments_md/{sha1}.md`，二次相同 sha1 走缓存
- 内容超 8000 字（项目级规范）截断，附 `(truncated to 8000 chars)` 标记
- 转码超时 30s 用 `signal.alarm`（POSIX）或 `multiprocessing.Pool` 兜底

**关键代码骨架**：
```python
from __future__ import annotations
import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from markitdown import MarkItDown

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ATTACH_DIR = _PROJECT_ROOT / "data" / "attachments_md"
_ATTACH_DIR.mkdir(parents=True, exist_ok=True)

_EXTS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
         ".html", ".htm", ".csv", ".json", ".xml", ".epub", ".txt", ".md"}
_MAX_MD_CHARS = 8000

_md = MarkItDown()

def _cache_path(file_path: Path) -> Path:
    h = hashlib.sha1(file_path.read_bytes()).hexdigest()[:16]
    return _ATTACH_DIR / f"{h}.md"

def extract_markdown(file_path: str | Path) -> Optional[str]:
    p = Path(file_path)
    if not p.exists() or not p.is_file():
        return None
    ext = p.suffix.lower()
    if ext not in _EXTS:
        return None
    cache = _cache_path(p)
    if cache.exists():
        return cache.read_text(encoding="utf-8", errors="replace")[:_MAX_MD_CHARS]
    try:
        result = _md.convert(str(p))
        text = (result.text_content or "").strip()
    except Exception:
        return None
    if not text:
        return None
    if len(text) > _MAX_MD_CHARS:
        text = text[:_MAX_MD_CHARS] + "\n\n(truncated to 8000 chars)"
    cache.write_text(text, encoding="utf-8")
    return text
```

### 2.3 A.3 · api_server.py 扩 ALLOWED_TYPES

**改**：`e:\Agent_reply\core\api_server.py` L228 `ALLOWED_TYPES` 集合：
```python
ALLOWED_TYPES = {
    # 已有
    "image/png", "image/jpeg", "image/gif", "text/plain", "application/json",
    # 新增（markitdown 覆盖）
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # docx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",        # xlsx
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # pptx
    "application/msword",                                                          # doc
    "application/vnd.ms-excel",                                                    # xls
    "application/vnd.ms-powerpoint",                                               # ppt
    "text/html", "text/csv", "text/xml",
    "application/xml",
    "application/epub+zip",
}
```

**关键决策**：mime 白名单写在服务端，**不**信客户端给的 ext。客户端只显示用 `accept`。

### 2.4 A.4 · /api/chat/send 注入 markdown

**改**：`e:\Agent_reply\core\api_server.py` L98-104（`/api/chat/send`）：
```python
attachments = body.get("attachments") or []
# Block-3 A.4: enrich attachments with extracted markdown for LLM
from core.attachment_handler import extract_markdown
for att in attachments:
    if not isinstance(att, dict):
        continue
    url = att.get("url") or ""
    # url 形如 "uuid.xlsx" 或 "/uploads/uuid.xlsx"
    fname = url.lstrip("/").split("/")[-1]
    if not fname:
        continue
    p = Path(UPLOAD_DIR) / fname
    if p.exists() and p.is_file():
        md = extract_markdown(p)
        if md:
            att["markdown"] = md
```

**安全要点**：
- `p.exists() and p.is_file()` 防 path traversal（且 fname 已被 `/uploads/{filename}` 路径的 serve_upload 路径校验 L214 模式）
- `Path(UPLOAD_DIR) / fname` 默认不会跳到 UPLOAD_DIR 外（除非 `..`），而 `serve_upload` 已拒 `..`
- 在 `chat_send` 这里**加二次校验**（白名单前缀）：`if not str(p.resolve()).startswith(str(Path(UPLOAD_DIR).resolve())): continue`

### 2.5 A.5 · context_builder.py 读 markdown

**改**：`e:\Agent_reply\core\context_builder.py` L137-141，把：
```python
att_lines.append(f"- {att.get('name','?')}（{att.get('type','?')}，{att.get('size',0)} bytes，路径 {att.get('url','?')}）")
```
改为优先 markdown 全文：
```python
if att.get("markdown"):
    att_lines.append(f"### {att.get('name','?')}\n\n{att['markdown']}\n")
else:
    att_lines.append(f"- {att.get('name','?')}（{att.get('type','?')}，{att.get('size',0)} bytes，路径 {att.get('url','?')}）")
```

并在 system prompt 文案改成中英双语：
> 你收到了附件。优先基于附件内文回答用户（如果已转成 markdown）。
> She sent an attachment. Read the markdown if available; otherwise note its metadata.

---

## 三、前端详细计划

### 3.1 B.1 · chat-input-area 改 toolbar

**改**：`e:\Agent_reply\electron\src\renderer\index.html` L142-148

把：
```html
<div class="chat-input-area">
  <div class="chat-input-row">
    <input id="chat-input" type="text" placeholder="和伊塔说点什么..." autofocus>
    <button id="chat-send-btn" class="btn-send">...</button>
  </div>
```
扩为：
```html
<div class="chat-input-area">
  <div class="chat-input-toolbar" id="chat-input-toolbar">
    <button id="chat-attach-btn" class="chat-input-toolbar__btn" title="附件">
      <svg class="icon icon--18"><use href="#icon-ui-attach"/></svg>
    </button>
    <button id="chat-mic-btn" class="chat-input-toolbar__btn" title="语音输入" aria-pressed="false">
      <svg class="icon icon--18"><use href="#icon-ui-mic"/></svg>
    </button>
  </div>
  <div class="chat-input-row">
    <input id="chat-input" type="text" placeholder="和伊塔说点什么... (Shift+Enter 换行)" autofocus>
    <button id="chat-send-btn" class="btn-send">...</button>
  </div>
  <div id="chat-mic-status" class="chat-mic-status" hidden>
    <span class="chat-mic-status__pulse"></span>
    <span class="chat-mic-status__text">正在听… / Listening…</span>
    <span class="chat-mic-status__net">需联网 / Online required</span>
  </div>
</div>
```

### 3.2 B.2 · 语音识别类

**新文件**：`e:\Agent_reply\electron\src\renderer\js\chat-voice.js`

**关键设计**：
- 用 `window.SpeechRecognition || window.webkitSpeechRecognition`（Electron Chromium 自带）
- `lang = 'zh-CN'`（与 `en-US` 二选一，按 navigator.language 推断）
- `interimResults = true` → input 实时更新
- `continuous = false` → 一句一停
- 录音中按钮加 `is-recording` 状态，bar 出现脉冲
- 失败/拒绝 → 静默隐藏，不弹错

**骨架**：
```js
class ChatVoice {
  constructor(chat) {
    this._chat = chat;
    this._rec = null;
    this._init();
  }
  _init() {
    const btn = document.getElementById("chat-mic-btn");
    if (!btn) return;
    if (!("webkitSpeechRecognition" in window) && !("SpeechRecognition" in window)) {
      btn.addEventListener("click", () => this._showHint("浏览器不支持 / Not supported"));
      return;
    }
    btn.addEventListener("click", () => this._toggle());
  }
  _toggle() {
    if (this._rec) { this._stop(); return; }
    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
    const r = new Ctor();
    r.lang = (navigator.language || "zh-CN").startsWith("zh") ? "zh-CN" : "en-US";
    r.interimResults = true;
    r.continuous = false;
    r.onresult = (e) => {
      let txt = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        txt += e.results[i][0].transcript;
      }
      const input = document.getElementById("chat-input");
      if (input) {
        input.value = txt;
        input.focus();
      }
    };
    r.onerror = () => { this._stop(); };
    r.onend = () => { this._stop(); };
    r.start();
    this._rec = r;
    document.getElementById("chat-mic-btn")?.classList.add("is-recording");
    const status = document.getElementById("chat-mic-status");
    if (status) status.hidden = false;
  }
  _stop() {
    if (this._rec) {
      try { this._rec.stop(); } catch (_) {}
      this._rec = null;
    }
    document.getElementById("chat-mic-btn")?.classList.remove("is-recording");
    const status = document.getElementById("chat-mic-status");
    if (status) status.hidden = true;
  }
  _showHint(msg) {
    if (this._chat && this._chat._setStatus) this._chat._setStatus(msg, false);
  }
}
window.ChatVoice = ChatVoice;
```

### 3.3 B.3 · 附件卡片状态

**改**：`e:\Agent_reply\electron\src\renderer\js\chat.js` 现有 `_renderAttachmentPreviews` 方法，状态机：
1. `uploading` → 灰底 + 进度文字 "上传中…"
2. `converting`（附件非图且 is_doc=true）→ 黄底 + "转 markdown 中…"
3. `ready` → 正常 + 名字
4. `failed`（转换失败）→ 红底 + "她读不了这个 / She can't read this"

文案严格使用「她」和「伊塔」，禁词禁「主人」。

### 3.4 B.4 · SVG icon & CSS

**改**：
- `electron/src/renderer/index.html` 的 SVG sprite 末尾追加 `<symbol id="icon-ui-mic" viewBox="0 0 24 24">...</symbol>`
- `electron/src/renderer/styles/main.css` 末尾追加：
  - `.chat-input-toolbar` 横向 flex
  - `.chat-mic-status` 脉冲动画
  - `.is-recording` 高亮色用 `--color-primary`

---

## 四、安全自审清单（C.1 — TRAE-security-review）

按 `TRAE-security-review` skill 的 §5 类别过一遍，仅复审 Block-3 引入的代码：

| 类别 | 关注点 | 是否触及 | 处理 |
|---|---|---|---|
| sql_injection | attachment URL 拼到 SQL | 否 | 已有 DB ORM，handler 不碰 SQL |
| command_injection | markitdown 子进程调用 | 否 | markitdown 是纯 Python 库，无 shell 调用 |
| path_traversal | `Path(UPLOAD_DIR) / fname` | **是** | 加 `resolve().startswith()` 二次校验 |
| unsafe_deserialization | markitdown 内部 | 否 | markitdown 用 mammoth/pdfminer，不 pickle |
| xxe | XML/HTML 解析 | 否 | markitdown 不启用外部实体 |
| ssti | 无模板 | 否 | 不用 server-side template |
| xss | LLM 输出经 LLM prompt 注入风险 | 否 | system prompt 不接受用户文档内容直接拼接到 prompt，仅在 attachments 段 |
| idor | 无 | 否 | 单一用户本地应用 |
| weak_crypto | 无 | 否 | 不用 crypto |
| auth_bypass | 无 | 否 | 本地单用户 |

**唯一**触发点：path_traversal → 加二次 resolve 校验。

**No patches** 原则下，plan 不写代码替换，仅指明加固点 + 验收点。

---

## 五、文件改动总览

| 文件 | 类型 | 估行数 | 风险 |
| --- | --- | --- | --- |
| `requirements.txt` | 改 | +3 | pip install 多 ~150MB 依赖 |
| `core/attachment_handler.py` | 新 | +90 | 中（markitdown 行为） |
| `core/api_server.py` | 改 | +25 | 扩 ALLOWED_TYPES + 注入 markdown |
| `core/context_builder.py` | 改 | +12 | 优先读 markdown |
| `electron/src/renderer/index.html` | 改 | +30 | toolbar + 状态条 |
| `electron/src/renderer/js/chat-voice.js` | 新 | +75 | 低（浏览器 API） |
| `electron/src/renderer/js/chat.js` | 改 | +50 | 附件状态机 |
| `electron/src/renderer/styles/main.css` | 改 | +40 | toolbar + 脉冲动画 |
| **合计** | | **+325** | 中 |

---

## 六、风险与回滚

| 风险 | 概率 | 影响 | 回滚 |
| --- | --- | --- | --- |
| markitdown pip 装失败 | 中 | 后端起不来 | requirements 注释行 `pip install markitdown[all]>=0.0.1` 仍写但代码不引用 → 旧行为 |
| Web Speech API 离线失效 | 高 | 语音按钮无反应 | 提示"需联网"，不让崩溃 |
| 转码超时 30s+ | 中 | 单条消息卡住 | handler 不做同步 → main thread 仍能返回（markitdown 同步，但加 try/except fallback None） |
| 5 主题色不匹配 | 中 | 美学破坏 | CSS 全走 `var(--color-primary)` |
| markitdown 触发 OOM（巨型 PDF） | 低 | 后端进程崩 | 30s 超时 + max_bytes 20MB 兜底 |
| path traversal 被故意构造 | 低 | 数据越权读 | resolve().startswith() 兜底 |

---

## 七、执行顺序（严格）

```
1.  requirements.txt + markitdown[all]              (0.1h, pip install)
2.  core/attachment_handler.py                      (0.4h)
3.  core/api_server.py 扩 ALLOWED_TYPES + 注入 md    (0.3h)
4.  core/context_builder.py 优先 markdown           (0.15h)
5.  复跑 6 脚本（后端不破）                          (0.2h)
6.  electron/src/renderer/index.html toolbar         (0.25h)
7.  electron/src/renderer/js/chat-voice.js          (0.3h)
8.  electron/src/renderer/js/chat.js 附件状态机     (0.3h)
9.  electron/src/renderer/styles/main.css           (0.2h)
10. Block-3 自我怀疑 review + 三原则 + TRAE-security-review (0.4h)
11. 复跑 6 脚本（前端不破）                          (0.2h)
```

总工时估约 2.8h。

---

## 八、三原则铁律（每步都自检）

1. **不破坏现有功能** — 6 脚本 229/229 仍全过；旧 ALLOWED_TYPES 不删只加；旧 metadata 路径保留（markitdown 失败时降级）
2. **不破坏伊塔人格** — 状态条文案「她读不了这个」；禁词列表不变（"主人/您"）
3. **设计美学统一** — toolbar / 脉冲动画用现有 CSS token（--color-primary / --bg-200）；不引 emoji；用 SVG mic

---

## 九、待用户确认

- 后端优先（A.1-A.5）vs 前端优先（B.1-B.4）？我建议 A 先（前端调后端）。
- 是否同意把 markitdown 依赖装进 venv（增量 ~150MB）？
- 是否同意"语音失败时静默 + 提示需联网"？
