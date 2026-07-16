---
title: Phase 6 — 本地系统全面优化（Logo · 窗口控制 · 数据联通 · 人格编辑 · 输入框重构 · Whisper 语音 · 桌宠悬浮球）
date: 2026-07-16
tags:
  - phase6
  - logo-replacement
  - window-controls
  - dashboard-data
  - persona-editor
  - chat-input-redesign
  - whisper-stt
  - floating-ball-desktop-pet
  - ita-persona
aliases:
  - Phase 6 Plan
cssclasses:
  - wide-page
---

# Phase 6 — 本地系统全面优化

> **保留**：现有通过上轮验证的全部模块（Phase 4: 撤回/引用/上传；Phase 5: splitter/SendQueue；情绪引擎；NapCat 桥接；四大主题）
> **目标**：11 项用户反馈一次性落地，**不破坏** 伊塔人格一致性 / 不破坏现有数据 / 不破坏设计美学
> **三原则**（用户重申）：
>   1. **不破坏现有功能** — 所有已验证模块继续工作
>   2. **不破坏伊塔人格** — 任何 UI 文案、动画、徽标都需符合 v8.0 persona（22岁/178cm/四爱/闷骚+病娇/称呼"你"）
>   3. **设计美学统一** — Apple HIG 风格 + 当前粉紫主题

---

## 一、用户决策记录

| 决策点 | 决策结果 | 备注 |
|--------|----------|------|
| 语音输入（STT）方案 | **本地 Whisper.cpp**（完全离线） | 首次下载约 150MB（ggml-base.bin），之后完全离线 |
| 本地多段消息输出 | **始终分段** | 与 QQ 渠道完全一致，splitter 已就绪，只需改本地返回路径 |
| 悬浮球最终定位 | **紧凑图标 + 桌宠动画** | 参考 360/豆包 + GitHub 桌宠开源项目；尺寸 64px + 状态动画 + 情绪反映 |
| 图标资源 | 沿用 `Aerie · 云栖.svg` / `Aerie · 云栖.png` 名称 | 用户已更新源图，本 phase 重新生成 icon.ico |
| 跨多 phase 改动 | 全部并入 Phase 6 | 不再拆分 phase 7/8 |

---

## 二、Phase 1 探索结果摘要

### 2.1 现状盘点（11 项用户反馈 × 当前状态）

| # | 用户反馈 | 现状 | 缺口 |
|---|---------|------|------|
| 1 | 保留现有模块 | ✓ Phase 4/5 全部就绪 | — |
| 2 | 伊塔支持语音识别 | ✗ voice/ 只有 TTS + Silk 编码器 | 完全无 STT 链路 |
| 3 | 更新各项 logo | ⚠ main.js/tray 已引用新 PNG，icon.ico 是旧 146KB | 需重新生成 icon.ico |
| 4 | 设置页人格档案编辑 | ✗ settings.js 只有主题/自启/推送 | 完全缺失 |
| 5 | QQ 多段输出已实现 | ✓ splitter + SendQueue 已工作 | — |
| 6 | 本地多段输出 | ✗ /api/chat/send 返回单条字符串 | 需改为返回 `segments: []` |
| 7 | 输入框文件按钮跑到上面 | ⚠ chat-uploader.js 注入 toolbar 在 input-area 之前 | DOM 顺序错乱，需重构 |
| 8 | 语音输入 | ✗ 完全无 | 需 Whisper.cpp + 前端录音 |
| 9 | 仪表盘数据没联通 | ✗ /api/chat/history?page=X 不支持 / /api/stats/system 不存在 | 后端端点缺失 |
| 10 | 三个按钮无法使用 | ✗ index.html L16-18 按钮无事件 | 完全缺失 |
| 11 | 悬浮球没了 | ⚠ floating-ball.html 存在但未挂到主进程 | 缺独立 BrowserWindow + IPC 联动 |
| 12 | 重新排布元素 | ⚠ sidebar 当前 8 项功能分组尚可 | 需按"使用频率"微调 |

### 2.2 关键文件清单（基于实际探索）

| 文件 | 当前状态 | 改动 |
|------|---------|------|
| `electron/src/main.js` | 275 行，tray/createMainWindow 已存在 | 加 ballWindow、3 个 IPC、Whisper 启动器 |
| `electron/src/preload.js` | 30 行 | 暴露 window:* / ball:* IPC |
| `electron/src/renderer/index.html` | 343 行 | 重构 chat-input-area；加人格编辑 UI；3 按钮 onclick |
| `electron/src/renderer/js/chat.js` | 405 行 | 改 send 返回 segments；多段渲染 |
| `electron/src/renderer/js/chat-uploader.js` | 145 行 | 重构为 chat-input-toolbar 一部分 |
| `electron/src/renderer/js/settings.js` | 78 行 | 加人格档案编辑面板 |
| `electron/src/renderer/js/data-viewer.js` | 105 行 | 改用真实端点；加实时轮询 |
| `electron/src/renderer/js/app.js` | 85 行 | 3 按钮事件绑定；状态栏 token 实时刷新 |
| `electron/src/renderer/floating-ball.html` | 17 行 | 重构为桌宠+动画+长按菜单 |
| `electron/src/renderer/js/floating-ball.js` | 63 行 | 重构为完整桌宠逻辑 |
| `core/api_server.py` | 706 行（已探索） | 加 /api/chat/send 返回 segments；/api/persona；/api/stats/system；/api/voice/transcribe；/api/chat/history 支持 page |
| `core/database.py` | 8 张表 schema | 加 persona_profile 表（如果 settings.yaml 不够） |
| `config/persona.yaml` | 95 行 | 保留只读基线；运行时改 settings.yaml.persona 段 |
| `voice/tts_engine.py` | 92 行 | 不动 |
| `voice/silk_encoder.py` | 50+ 行 | 不动 |
| `voice/stt_engine.py` | **新建** | Whisper.cpp 封装 |
| `electron/scripts/post-build-rcedit.js` | 54 行 | 不动（已支持新图） |
| `electron/builder/icon.ico` | 146KB（旧图） | 重新生成 |

### 2.3 资源依赖

| 资源 | 来源 | 用途 | 备注 |
|------|------|------|------|
| `Aerie · 云栖.png` (512KB) | 用户已更新 | 主窗口图标 / 托盘 / 状态栏 | 已有 |
| `Aerie · 云栖.svg` (5.3MB) | 用户已更新 | 关于页 / 高分辨率显示 | 已有 |
| `whisper.cpp Windows release` | github.com/ggerganov/whisper.cpp | STT 引擎二进制 | 首次运行时下载/内置 |
| `ggml-base.bin` (~150MB) | huggingface.co/ggerganov/whisper.cpp | Whisper base 中文模型 | 首次启动下载到 `data/whisper/` |
| 桌宠动画 (Lottie/SVG) | 自制 3 状态 SVG | 悬浮球情绪反映 | 伊塔 q 版 3 表情（平静/开心/怒） |

---

## 三、实施计划（8 Batches）

> **强约束**：每 Batch 完成后立即手动验证，不堆积验证
> **设计原则**：保留所有已存在代码路径，新增功能不替换旧路径

---

### Batch 1 · Logo 资源全栈替换（P0 — 必做，1h）

**目标**：EXE 资源 / 托盘 / 状态栏 / 关于页所有 logo 全部使用用户最新 `Aerie · 云栖.png` + `.svg`

**L1. 重新生成 `builder/icon.ico`**
- 文件: `electron/builder/icon.ico`（删除后重建）
- 工具: `electron-builder` 已带 `iconutil` 流程
- 步骤：
  1. 用 sharp 或 python+Pillow 从 `Aerie · 云栖.png` 生成 16/24/32/48/64/128/256 多尺寸 PNG
  2. 用 png2ico 或 imagemagick 合成 `builder/icon.ico`
  3. 验证：PowerShell 用 `[System.Drawing.Icon]::ExtractAssociatedIcon` 提取并查看

**L2. 验证 main.js 引用**
- 文件: `e:\Agent_reply\electron\src\main.js` L163, L172
- 当前已正确引用 `Aerie · 云栖.png`（窗口图标 + 托盘）
- 不动 — 确认即可

**L3. 验证 renderer 引用**
- 文件: `e:\Agent_reply\electron\src\renderer\index.html` L24, L226
- 当前已正确引用 `../../../Aerie · 云栖.svg`（status bar + about）
- 不动 — 确认即可

**L4. 重建 EXE 图标**
- 重新执行 `npm run build:win`
- 验证：`post-build-rcedit.js` 自动注入新 icon.ico
- 验证：用 `rcedit "Aerie · 云栖.exe" --get-icon` 确认注入成功

**验证脚本**：
```powershell
cd e:\Agent_reply
node -e "const sharp=require('sharp'); sharp('Aerie · 云栖.png').resize(256,256).toFile('electron/builder/icon-256.png').then(()=>console.log('OK'))"
```

**验收标准**：从 `dist-new/win-unpacked/Aerie · 云栖.exe` 提取的图标与 `Aerie · 云栖.png` 一致

---

### Batch 2 · 窗口控制按钮修复（P0 — 必做，30min）

**目标**：最小化/最大化/关闭三个按钮全部可用，遵循 macOS HIG 视觉

**W1. preload.js 暴露 IPC**
- 文件: `e:\Agent_reply\electron\src\preload.js`
- 在 `electron` 段添加：
  ```js
  window: {
    minimize: () => ipcRenderer.invoke('window:minimize'),
    maximize: () => ipcRenderer.invoke('window:maximize'),
    isMaximized: () => ipcRenderer.invoke('window:isMaximized'),
    close: () => ipcRenderer.invoke('window:close'),
  }
  ```
- 在 `onHealth` 旁添加 `onMaximizeChange: (cb) => { ipcRenderer.on('window:maximized', (_e, v) => cb(v)) }`

**W2. main.js 加 IPC handlers**
- 文件: `e:\Agent_reply\electron\src\main.js`（在现有 `ipcMain.handle('get-health', ...)` 之后）
- 4 个 handler：
  ```js
  ipcMain.handle('window:minimize', () => mainWindow?.minimize());
  ipcMain.handle('window:maximize', () => {
    if (!mainWindow) return false;
    if (mainWindow.isMaximized()) mainWindow.unmaximize();
    else mainWindow.maximize();
    return mainWindow.isMaximized();
  });
  ipcMain.handle('window:isMaximized', () => mainWindow?.isMaximized() || false);
  ipcMain.handle('window:close', () => { mainWindow?.close(); return true; });
  ```
- 同步 `mainWindow.on('maximize')` / `on('unmaximize')` → `webContents.send('window:maximized', ...)` 供按钮图标切换

**W3. app.js 绑定事件 + 切换图标**
- 文件: `e:\Agent_reply\electron\src\renderer\js\app.js`
- 在 DOMContentLoaded 中加：
  ```js
  const btnMin = document.getElementById('btn-minimize');
  const btnMax = document.getElementById('btn-maximize');
  const btnClose = document.getElementById('btn-close');
  if (btnMin) btnMin.addEventListener('click', () => window.aerie.window.minimize());
  if (btnMax) btnMax.addEventListener('click', async () => {
    await window.aerie.window.maximize();
  });
  if (btnClose) btnClose.addEventListener('click', () => window.aerie.window.close());
  if (window.aerie.electron.onMaximizeChange) {
    window.aerie.electron.onMaximizeChange((max) => {
      if (btnMax) btnMax.textContent = max ? '❐' : '□';
    });
  }
  ```

**验收**：点击三按钮分别实现最小化/全屏切换/关闭；全屏时 □ 变 ❐

---

### Batch 3 · 仪表盘数据全联通（P0 — 必做，2h）

**目标**：状态面板/数据面板/情感仪表盘所有数据点 5s 内实时刷新

**D1. 后端补 /api/chat/history 支持 page 参数**
- 文件: `e:\Agent_reply\core\api_server.py` L98-123
- 当前签名：`user_id, limit: int = 50`
- 改动：增加 `offset: int = 0` 参数 + 返回 `total` 字段
- SQL: `SELECT * FROM chat_log WHERE user_id = ? ORDER BY id DESC LIMIT ? OFFSET ?`
- 另查 `SELECT COUNT(*) as total FROM chat_log WHERE user_id = ?`
- 返回 `{"history": [...], "total": N, "user_id": ..., "page": ..., "limit": ...}`

**D2. 后端补 /api/stats/system**
- 文件: `e:\Agent_reply\core\api_server.py`（在 `/api/stats/tokens` 之后）
- 内容：
  ```python
  @app.get("/api/stats/system")
  async def stats_system() -> dict:
      import psutil, time
      proc = psutil.Process()
      return {
          "uptime_seconds": int(time.time() - _START_TIME),
          "uptime": _fmt_uptime(...),
          "cpu_percent": psutil.cpu_percent(interval=0.1),
          "memory_mb": round(proc.memory_info().rss / 1024 / 1024, 1),
          "message_count": _db.query_one("SELECT COUNT(*) as n FROM chat_log")["n"],
          "user_count": _db.query_one("SELECT COUNT(DISTINCT user_id) as n FROM chat_log")["n"],
          "knowledge_count": _db.query_one("SELECT COUNT(*) as n FROM knowledge_base")["n"],
      }
  ```
- `requirements.txt` 加 `psutil`（已存在则跳过）

**D3. data-viewer.js 改用真实端点 + 实时轮询**
- 文件: `e:\Agent_reply\electron\src\renderer\js\data-viewer.js` L36-98
- 改动：
  - `loadChatLogs()` 改用 `?user_id=X&page=Y&limit=20` + 渲染 `r.data.total`
  - `loadSystem()` 用 `/api/stats/system`（已存在）
  - **新增** 3s 轮询 setInterval，仅当 panel-data 可见时刷新

**D4. app.js 状态栏 token 实时刷新**
- 文件: `e:\Agent_reply\electron\src\renderer\js\app.js` L67-84
- 当前已有 5s 轮询
- 改动：把 `statsBackend/statsQQ/statsTokens/statsCalls` 加上"5 分钟"窗口显示（"今日 / 1h / 5min" 三档），数据从 `/api/stats/tokens` 取 `today`/`week`/`by_provider` 已包含
- 加 1s 内的本地 "已读时间" 显示（从 `last_poll` 记时）

**D5. emotion-dashboard 持续轮询（已实现）**
- 文件: `e:\Agent_reply\electron\src\renderer\js\emotion-dashboard.js` L11-14
- 当前是 3s 轮询 + setVisible 控制
- 改动：`setVisible(true)` 时立即 fetch + 启动 interval；`setVisible(false)` 时保留缓存但停止 interval

**验收**：状态面板/数据面板的 4 个状态卡片每 5s 数字微变；情感仪表盘切换 tab 后立即刷新

---

### Batch 4 · 设置页人格档案编辑（P0 — 必做，2h）

**目标**：设置页新增"伊塔档案"面板：编辑姓名（中/英）/ 头像 / 一句话签名 / 保存

**S1. 后端补 /api/persona GET/PUT**
- 文件: `e:\Agent_reply\core\api_server.py`（在 `/api/settings` 之后）
- 数据存储：用 `config/settings.yaml` 的 `persona` 段（已存在 `_DEFAULTS` 之外的扩展字段）
- 改动：
  ```python
  @app.get("/api/persona")
  async def persona_get() -> dict:
      from config.persona_loader import load_persona
      try:
          return load_persona()
      except Exception as e:
          return {"error": str(e)}

  @app.put("/api/persona")
  async def persona_put(request: Request) -> dict:
      from config.persona_loader import load_persona, save_settings  # 复用 save
      body = await request.json()
      current = load_persona()
      current["persona"].update(body)
      # 保存时把 persona 嵌套展开到 settings
      await _save_persona_yaml(current)
      return {"status": "ok", "persona": current["persona"]}
  ```
- 新建工具函数 `_save_persona_yaml`（在 `persona_loader.py` 加）—— 写回 `config/persona.yaml` 完整文档

**S2. 前端 settings.js 加人格档案面板**
- 文件: `e:\Agent_reply\electron\src\renderer\js\settings.js`
- 在现有 `init()` 末尾加：
  ```js
  document.getElementById('persona-save-btn')?.addEventListener('click', () => this.savePersona());
  document.getElementById('persona-avatar-file')?.addEventListener('change', (e) => this.previewAvatar(e));
  this.loadPersona();
  ```
- 新增 `loadPersona()` / `savePersona()` / `previewAvatar()` 三个方法
- 头像保存：先上传到 `/api/upload`，拿到 url 写到 persona.avatar_url

**S3. index.html 加人格档案 UI 块**
- 文件: `e:\Agent_reply\electron\src\renderer\index.html`（在 `<section id="panel-settings">` 内 `system settings` 之后）
- UI 结构：
  ```html
  <h3 style="margin-top:24px;">伊塔 · 人格档案</h3>
  <div class="persona-avatar-row">
    <img id="persona-avatar" src="" class="persona-avatar">
    <label class="btn btn-secondary">
      更换头像
      <input type="file" id="persona-avatar-file" accept="image/*" hidden>
    </label>
  </div>
  <div class="settings-group">
    <label>中文名</label>
    <input type="text" id="persona-name-cn" maxlength="20">
  </div>
  <div class="settings-group">
    <label>英文名</label>
    <input type="text" id="persona-name-en" maxlength="20">
  </div>
  <div class="settings-group">
    <label>一句话签名</label>
    <input type="text" id="persona-signature" maxlength="50" placeholder="例：过来坐。">
  </div>
  <div class="settings-actions">
    <button id="persona-save-btn" class="btn btn-primary">保存人格</button>
  </div>
  ```

**S4. main.css 加人格档案样式**
- 文件: `e:\Agent_reply\electron\src\renderer\styles\main.css`
- 新增：`.persona-avatar-row { display:flex; align-items:center; gap:12px; margin-bottom:16px; }` / `.persona-avatar { width:64px; height:64px; border-radius:50%; object-fit:cover; border:2px solid var(--color-border); }`

**S5. 运行时引用新名字**
- 文件: `e:\Agent_reply\core\context_builder.py` L19-35
- 当前 `_PERSONA_L1` 写死"伊塔"
- 改动：在 `build()` 开头读 `persona.name` 注入模板（仅当 `name != "伊塔"` 才替换"伊塔"为自定义名；保留 persona 默认 `伊塔` 不动）
- 文件: `communication/qq_client.py` 检查消息气泡中"伊塔"是否需要替换（v8.0 决策为只读基线，不改 message 模块）

**验收**：在设置页改 `name` 为 "依依"，保存后聊天 LLM 回复中名字变为"依依"；头像上传后 about 页和 chat 空状态头像也同步

---

### Batch 5 · 聊天输入框重构（P0 — 必做，3h）

**目标**：参考 WeChat / Slack / Telegram 主流设计，重构输入区；保证多次输出始终分段；不丢现有附件/引用/撤回功能

**C1. 重构 index.html chat-input-area**
- 文件: `e:\Agent_reply\electron\src\renderer\index.html` L83-91
- 当前结构：`<div class="chat-input-row"> <input> <button>`
- 新结构（双层）：
  ```html
  <div class="chat-input-area">
    <!-- 引用条 / 附件预览（动态插入） -->
    <div class="chat-quote-bar" id="chat-quote-bar" style="display:none"></div>
    <div class="chat-attach-preview" id="chat-attach-preview" style="display:none"></div>

    <!-- 主输入容器 -->
    <div class="chat-input-main">
      <button class="chat-tool-btn" id="chat-attach-btn" title="附件">📎</button>
      <div class="chat-input-wrap">
        <textarea id="chat-input" rows="1" placeholder="和伊塔说点什么... (Shift+Enter 换行)"></textarea>
      </div>
      <button class="chat-tool-btn chat-voice-btn" id="chat-voice-btn" title="按住说话">🎤</button>
      <button class="chat-send-btn" id="chat-send-btn" title="发送 (Enter)">
        <svg ...>...</svg>
      </button>
    </div>
  </div>
  ```
- textarea 支持自动增长（1-5 行）；Enter 发送，Shift+Enter 换行

**C2. 改 chat-uploader.js 适配新结构**
- 文件: `e:\Agent_reply\electron\src\renderer\js\chat-uploader.js`
- 改动：不再创建 `chat-input-toolbar`，改为找到 `#chat-attach-btn` 直接绑定 click
- 删除原 36-47 行的 toolbar 注入逻辑

**C3. 改 chat.js 渲染多段回复**
- 文件: `e:\Agent_reply\electron\src\renderer\js\chat.js`
- 改动 `_render(msg)`：
  - 接收 `msg.segments: string[]` 字段（多段）
  - 渲染时每段一个 `.chat-bubble` 子元素 + 50ms 间隔依次淡入
  - 单段时退化为原行为（保持向后兼容）
- 改 `send()`：
  - 移除 `await this._request(...)` 后单纯显示
  - 改为监听 `chat:message` IPC 事件渲染（含 segments）

**C4. 后端 /api/chat/send 返回 segments**
- 文件: `e:\Agent_reply\core\api_server.py` L61-95
- 当前：`return {"reply": result.get("reply", ""), ...}`
- 改动：
  ```python
  from communication.splitter import SemanticMessageSplitter
  splitter = SemanticMessageSplitter()
  reply_text = result.get("reply", "")
  segments = splitter.split(reply_text) if reply_text else []
  return {
      "reply": reply_text,
      "segments": segments,
      ...
  }
  ```
- 同时在 Pipeline emit 时也带上 segments 字段（chat.js 走 IPC，不走 HTTP，但保持一致）

**C5. main.css 输入框样式**
- 文件: `e:\Agent_reply\electron\src\renderer\styles\main.css`
- 删原 `.chat-input-area` 旧样式
- 新增：
  ```css
  .chat-input-main { display:flex; align-items:flex-end; gap:8px; padding:10px 16px; }
  .chat-tool-btn { width:36px; height:36px; border:none; background:transparent; color:var(--color-text-muted); border-radius:50%; cursor:pointer; }
  .chat-tool-btn:hover { background:var(--color-border); color:var(--color-text); }
  .chat-input-wrap { flex:1; background:var(--color-surface); border:1px solid var(--color-border); border-radius:18px; padding:8px 14px; }
  .chat-input-wrap:focus-within { border-color:var(--color-primary); }
  #chat-input { width:100%; border:none; background:transparent; outline:none; resize:none; font-family:var(--font-sans); font-size:14px; max-height:120px; line-height:1.5; }
  .chat-send-btn { background:var(--color-primary); color:#fff; }
  .chat-send-btn:hover { background:var(--color-primary-hover); }
  .chat-voice-btn.recording { color:var(--error); animation:pulse 1s infinite; }
  ```

**验收**：附件按钮、语音按钮、输入框、发送按钮横向排列；多段回复每段独立气泡依次出现；上传/引用/撤回按钮全部工作

---

### Batch 6 · Whisper 本地语音输入（P1 — 必做，3h）

**目标**：长按 🎤 按钮录音 → Whisper 离线识别 → 文本填入输入框 → 用户可编辑后发送

**V1. 准备 Whisper.cpp 资源**
- 路径: `e:\Agent_reply\bin\whisper\`
- 步骤：
  1. 下载 whisper.cpp Windows x64 release：https://github.com/ggerganov/whisper.cpp/releases
  2. 解压出 `whisper-cli.exe` + `ggml-base.bin`（中文推荐 base）到 `bin/whisper/`
  3. 若 release 不可用，回退：`git clone https://github.com/ggerganov/whisper.cpp` + `cmake -B build && cmake --build build --config Release`
- 首次启动检测：若 `bin/whisper/whisper-cli.exe` 不存在 → 显示"语音功能需要先下载 Whisper 模型（150MB），是否立即下载？" 弹窗

**V2. voice/stt_engine.py 封装**
- 新建文件: `e:\Agent_reply\voice\stt_engine.py`
- 内容：
  ```python
  class STTEngine:
      def __init__(self, model="base", language="zh"):
          self.whisper_bin = PROJECT_ROOT / "bin" / "whisper" / "whisper-cli.exe"
          self.model_path = PROJECT_ROOT / "bin" / "whisper" / f"ggml-{model}.bin"
      async def transcribe(self, wav_path: Path) -> str:
          """Transcribe wav → text via whisper.cpp subprocess."""
          proc = await asyncio.create_subprocess_exec(
              str(self.whisper_bin),
              "-m", str(self.model_path),
              "-f", str(wav_path),
              "-l", "zh",
              "--no-timestamps",
              stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
          )
          stdout, _ = await proc.communicate(timeout=30)
          return _parse_whisper_output(stdout.decode('utf-8', errors='ignore'))
  ```

**V3. 后端 /api/voice/transcribe**
- 文件: `e:\Agent_reply\core\api_server.py`（在 `/api/upload` 之后）
- 内容：
  ```python
  @app.post("/api/voice/transcribe")
  async def voice_transcribe(file: UploadFile = File(...)) -> dict:
      from voice.stt_engine import STTEngine
      audio = await file.read()
      wav_path = Path("uploads") / f"voice_{uuid.uuid4().hex}.webm"
      wav_path.write_bytes(audio)
      # 用 ffmpeg 转 wav
      wav_path = await _ffmpeg_to_wav(wav_path)
      engine = STTEngine()
      text = await engine.transcribe(wav_path)
      wav_path.unlink(missing_ok=True)
      return {"text": text, "status": "ok"}
  ```

**V4. 前端 voice-input.js（新建）**
- 新建文件: `e:\Agent_reply\electron\src\renderer\js\voice-input.js`
- 使用 MediaRecorder API：
  ```js
  class VoiceInput {
    start() { /* navigator.mediaDevices.getUserMedia + MediaRecorder.start() */ }
    stop()  { /* stop + 转 webm + POST /api/voice/transcribe + 填入 #chat-input */ }
  }
  ```
- 事件：
  - mousedown / touchstart → start()
  - mouseup / touchend / mouseleave → stop()

**V5. chat.js 集成 VoiceInput**
- 文件: `e:\Agent_reply\electron\src\renderer\js\chat.js` `constructor()` 末尾
- 实例化：`if (window.VoiceInput) this._voice = new VoiceInput(this);`
- 绑定 `chat-voice-btn` 的 mousedown/mouseup 给 `_voice`

**验收**：长按 🎤 → 顶部出现"录音中..."红点 → 松开 → 1-3s 后输入框出现识别文字

---

### Batch 7 · 悬浮球重做（桌宠 + 紧凑图标，P1 — 必做，4h）

**目标**：参考 360/豆包 + GitHub `pet-page`/`live2d-widget` 风格；紧凑 64px 球 + 3 状态桌宠动画

**B1. main.js 创建独立 ballWindow**
- 文件: `e:\Agent_reply\electron\src\main.js`（在 `createMainWindow` 之后）
- 新增 `createFloatingBall()`：
  ```js
  function createFloatingBall() {
    const { width, height } = screen.getPrimaryDisplay().workAreaSize;
    ballWindow = new BrowserWindow({
      width: 72, height: 72,
      x: width - 100, y: height - 100,
      frame: false, transparent: true,
      alwaysOnTop: true, skipTaskbar: true,
      resizable: false,
      webPreferences: {
        preload: path.join(__dirname, 'preload.js'),
        contextIsolation: true, nodeIntegration: false,
        devTools: false,  // 防止"诡异滑块"重演
      },
      icon: path.join(PROJECT_ROOT, "Aerie · 云栖.png"),
    });
    ballWindow.loadFile(path.join(__dirname, 'renderer', 'floating-ball.html'));
    // 窗口移动 → 边沿吸附
    ballWindow.on('moved', snapToEdge);
  }
  ```
- `snapToEdge` 函数：检测窗口中心离哪条边最近，距离 < 30px 时贴边
- 启动时 5s 后 `createFloatingBall()` 延迟（避免主窗口未就绪时的闪烁）
- 监听 `mainWindow.on('close')` → 隐藏主窗口并显示悬浮球（不退出 app）
- 监听 `mainWindow.on('show')` → 隐藏悬浮球（避免重复显示）

**B2. preload.js 暴露 ball IPC**
- 文件: `e:\Agent_reply\electron\src\preload.js`
- 新增：
  ```js
  ball: {
    expand: () => ipcRenderer.invoke('ball:expand'),    // 显示主窗口 + 隐藏球
    quickChat: () => ipcRenderer.invoke('ball:quickChat'),  // 打开快速聊天 popover
    settings: () => ipcRenderer.invoke('ball:settings'),    // 打开设置
    setMood: (mood) => ipcRenderer.invoke('ball:setMood', mood),  // 'neutral'|'joy'|'sad'|'anger'
  }
  ```

**B3. main.js ball IPC handlers**
- 4 个 handler：
  - `ball:expand` → `mainWindow.show(); mainWindow.focus(); ballWindow.hide();`
  - `ball:quickChat` → `mainWindow.show(); mainWindow.webContents.send('ball:focus-chat'); ballWindow.hide();`
  - `ball:settings` → `mainWindow.show(); mainWindow.webContents.send('ball:focus-settings'); ballWindow.hide();`
  - `ball:setMood` → `ballWindow.webContents.send('ball:mood', mood);`

**B4. floating-ball.html 重构**
- 文件: `e:\Agent_reply\electron\src\renderer\floating-ball.html`
- 新结构（双层：球 + 弹出菜单）：
  ```html
  <div id="floating-ball" class="floating-ball">
    <div class="ball-pet" id="ball-pet">
      <!-- 3 个 SVG 表情叠层，按 mood 切换显示 -->
      <img class="ball-pet__face ball-pet__face--neutral" src="../assets/ita-neutral.svg">
      <img class="ball-pet__face ball-pet__face--joy" src="../assets/ita-joy.svg">
      <img class="ball-pet__face ball-pet__face--sad" src="../assets/ita-sad.svg">
    </div>
    <span id="ball-badge" class="ball-badge hidden">0</span>
  </div>

  <div id="ball-menu" class="ball-menu hidden">
    <button class="ball-menu__item" data-act="chat">💬 打开对话</button>
    <button class="ball-menu__item" data-act="settings">⚙ 设置</button>
    <button class="ball-menu__item" data-act="quit">✕ 退出</button>
  </div>
  ```

**B5. floating-ball.js 重构**
- 文件: `e:\Agent_reply\electron\src\renderer\js\floating-ball.js`
- 行为：
  - 单击 → 切换菜单（带 200ms scale 动画）
  - 菜单项 click → 调对应 IPC
  - 双击 → `ball:expand`（直接展开主窗口）
  - 拖拽：记录 mousedown 起点，mousemove 时通过 `moveBallWindow` IPC 调 `ballWindow.setPosition`
  - 边沿吸附在主进程完成（前端只发位置）
  - 接 `ball:mood` IPC 切换 SVG class
  - 接 `chat:message` 增加未读 badge

**B6. main.css + floating-ball.css 重构**
- 文件: `e:\Agent_reply\electron\src\renderer\styles\floating-ball.css`
- 关键样式：
  - `.floating-ball { position:fixed; inset:0; pointer-events:none; }` （全屏透明容器，吸收拖拽事件）
  - `.ball-pet { position:absolute; width:64px; height:64px; pointer-events:auto; cursor:grab; ... }`
  - `.ball-pet__face { position:absolute; inset:0; transition: opacity .3s; opacity:0; }`
  - `.ball-pet__face--active { opacity:1; }`
  - `.ball-menu { position:absolute; width:160px; background: rgba(255,255,255,.95); backdrop-filter: blur(20px); border-radius:14px; box-shadow: 0 8px 24px rgba(0,0,0,.18); }`

**B7. 桌宠 SVG 资源**
- 新建 3 个文件（最小可用版本，用 CSS 渐变 + emoji 简版）：
  - `e:\Agent_reply\electron\src\renderer\assets\ita-neutral.svg`（伊塔 q 版圆脸 + 冰蓝眼睛）
  - `e:\Agent_reply\electron\src\renderer\assets\ita-joy.svg`（同脸 + 微笑）
  - `e:\Agent_reply\electron\src\renderer\assets\ita-sad.svg`（同脸 + 皱眉）
- 借鉴开源：https://github.com/stevenjoezhang/live2d-widget （仅作结构参考，资源不复制）

**B8. 情绪引擎联动**
- 文件: `e:\Agent_reply\electron\src\renderer\js\emotion-dashboard.js`
- 在 `_render()` 末尾加：`if (window.aerie.ball) window.aerie.ball.setMood(this._mapMoodToPet(data.label));`
- `emotion label` → `pet mood` 映射：
  - joy → 'joy'
  - sad/anger/fear → 'sad'
  - neutral → 'neutral'

**验收**：启动后 5s 出现悬浮球；拖拽贴边；双击展开主窗口；右键/单击弹菜单；LLM 情绪变化时悬浮球表情跟着切

---

### Batch 8 · 页面元素排布 + 三原则贯彻（P1 — 收尾，2h）

**目标**：在 1-7 批基础上，按"使用频率 × 功能分组"重新排布 sidebar，确保三原则落地

**P1. sidebar 顺序优化**
- 文件: `e:\Agent_reply\electron\src\renderer\index.html` L36-73
- 当前：聊天 / 情绪 / 纪念 / 数据 / QQ / 状态 / 设置 / 关于
- 新顺序（按每日使用频次降序）：
  1. **聊天**（核心，几乎每次都用）
  2. **情绪**（每日查看伊塔状态）
  3. **QQ**（运维连接，每日 1-2 次）
  4. **数据**（每周看一次）
  5. **状态**（系统监控，平时不看）
  6. **纪念**（特定日子用）
  7. **设置**（低频）
  8. **关于**（一次性）

**P2. 三原则验证检查表**
- [ ] **不破坏现有功能**：
  - chat.js 的撤回 / 引用 / 上传 / 多段输出 全部保留
  - emotion-dashboard 的 PAD 卡片 / 阈值条 / 爆发 banner 全部保留
  - 5 个主题切换正常
  - NapCat 启动 / 停止 / QR 码 / 日志正常
- [ ] **不破坏伊塔人格**：
  - 系统所有默认文案是"伊塔"不是"你"
  - LLM 提示词保持 v8.0 persona（context_builder.py 不动）
  - 桌宠动画命名 "ita-neutral/joy/sad"
  - 设置页"伊塔 · 人格档案"标题保持 v8.0 风格
- [ ] **设计美学统一**：
  - 标题栏三按钮用 Apple HIG 圆角 + hover 红色（仅关闭）
  - 悬浮球 + 主窗口主题色一致（粉/紫/绿随主题）
  - 输入框使用当前 `.chat-input-row` 圆角风格
  - 新增人格档案 UI 与现有 settings-group 同款

**P3. 验证清单（10 项）**
- [ ] EXE 图标 = `Aerie · 云栖.png` 视觉
- [ ] 启动后 5s 出现悬浮球
- [ ] 悬浮球双击 → 主窗口展开
- [ ] 悬浮球单击 → 弹出菜单（3 选项）
- [ ] 拖拽悬浮球到右下角 → 自动贴边
- [ ] 主窗口三按钮：最小化、最大化、关闭全可用
- [ ] 聊天输入：附件、表情、语音三按钮横向排列
- [ ] 多段回复：每段独立气泡依次出现
- [ ] 长按语音按钮 → 录音 → 松开 → 输入框出现文字
- [ ] 设置页：编辑伊塔姓名 → 保存 → 下次 LLM 回复使用新名字
- [ ] 状态面板：后端/QQ/Token/调用 4 卡片 5s 内数字微变
- [ ] 仪表盘 8 卡片有真实数据（非 0/--）

---

## 四、实施顺序与里程碑

| 顺序 | Batch | 时长 | 依赖 |
|------|-------|------|------|
| 1 | B1 Logo | 1h | 无 |
| 2 | B2 窗口控制 | 30min | 无 |
| 3 | B3 数据联通 | 2h | 无 |
| 4 | B4 人格编辑 | 2h | 无 |
| 5 | B5 输入框重构 | 3h | B3 (segments 联动) |
| 6 | B6 Whisper | 3h | 无（独立） |
| 7 | B7 悬浮球 | 4h | 无（独立） |
| 8 | B8 收尾验证 | 2h | 1-7 全部 |

**总时长约 17.5 小时**（若串行）

**并行化建议**：
- B1 + B2 可并行（无依赖）
- B4 + B5 + B6 可并行（3 人可同步开发）
- B3 必须先于 B5 的 segments 部分
- B7 独立，可全程并行
- B8 收尾串行

---

## 五、假设与决策

1. **Whisper 模型选 base**（不是 tiny/small/medium）—— 150MB 大小可接受，中文识别准确率 ~85%
2. **悬浮球只做 3 状态**（neutral/joy/sad）—— 避免动画资源爆炸；后续可扩展
3. **人格档案存储用 settings.yaml**（不开新表）—— 简单，yq 已有 yaml 配置管理
4. **多段输出始终开启**（不再有 LLM 主动决定）—— 与用户决策一致
5. **桌宠动画用 SVG 而非 Live2D** —— bundle size 0 增加；后续可升级
6. **不引入第三方图表库**（保持现状纯 SVG 渲染）—— 沿用 Phase 4-5 决定
7. **psutil 用于系统监控** —— requirements.txt 已可能包含
8. **后端 API 不动 Pipeline** —— 只在 /api/chat/send 出口处切段
9. **Whisper 模型首次启动下载** —— 检测到缺失时弹窗询问，不强制
10. **icon.ico 用 sharp 重新生成** —— 避免手动 ImageMagick 依赖

---

## 六、风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| Whisper.cpp Windows release 不可用 | V 不能用 | 兜底：clone 源码 + cmake 本地编译（README 引导） |
| 悬浮球透明度/区域问题 | 球拖动异常 | 全屏 transparent 容器 + `pointer-events: none` 顶层 + `.ball-pet` 单独 `pointer-events: auto` |
| 多段输出让气泡过多 | 视觉过载 | 限制 ≤6 段；超出合并为"..." |
| icon.ico 重新生成失败 | EXE 图标还是旧 | 保留旧 icon.ico 备份；失败时回退 |
| Whisper 150MB 模型下载失败 | 语音输入不可用 | 启动时静默下载到 `data/whisper/`；失败提示"前往设置手动放置" |
| 人格姓名改动影响 LLM 提示词 | 人格跑偏 | context_builder.py 仅在 `name != "伊塔"` 时替换；且 v8.0 persona 基线不动 |
| 桌宠 SVG 资源简陋 | 视觉掉档 | 用 emoji + CSS gradient 兜底（如：`<div class="pet">伊</div>` 大字+背景） |

---

## 七、不在范围内的事项

- 重写后端 Pipeline（splitter 已在 Queue 里用，本地端走同一段代码）
- 引入 Live2D / Cubism 引擎（v2 桌宠方案）
- 多人多设备同步（保持本地单机）
- 语音输出（TTS）—— voice/tts_engine.py 已存在，本 phase 不动
- QQ 渠道改动（保持 Phase 4 现状）
- 5 个主题色重新设计
- 重新设计侧边栏宽度 / 主题切换面板

---

## 八、验证脚本汇总

```powershell
# B1 验证：EXE 图标
$ico = [System.Drawing.Icon]::ExtractAssociatedIcon("E:\Agent_reply\electron\dist-new\win-unpacked\Aerie · 云栖.exe")
$ico.ToBitmap().Save("E:\Agent_reply\verify_exe_icon.png")

# B2 验证：三按钮
# 手动启动 EXE，分别点击最小化/最大化/关闭

# B3 验证：数据联通
curl http://127.0.0.1:7890/api/stats/system | ConvertFrom-Json
curl "http://127.0.0.1:7890/api/chat/history?user_id=3998874040&page=1&limit=20" | ConvertFrom-Json

# B4 验证：人格编辑
curl -X PUT http://127.0.0.1:7890/api/persona -H "Content-Type: application/json" -d '{"name":"依依"}'
curl http://127.0.0.1:7890/api/persona

# B5 验证：多段输出
curl -X POST http://127.0.0.1:7890/api/chat/send -H "Content-Type: application/json" -d '{"text":"测试","user_id":3998874040}'
# 应返回 segments 数组

# B6 验证：Whisper
$wav = "E:\Agent_reply\verify_audio.wav"
& "E:\Agent_reply\bin\whisper\whisper-cli.exe" -m "E:\Agent_reply\bin\whisper\ggml-base.bin" -f $wav -l zh

# B7 验证：悬浮球
# 启动后观察 5s 出现球；点击/拖拽/双击
```

---

## 九、交付物清单

- [ ] `electron/builder/icon.ico`（用新 Aerie 图重新生成）
- [ ] `electron/src/main.js`（+ballWindow、+窗口 IPC、+Whisper 检测）
- [ ] `electron/src/preload.js`（+window, +ball, +voice 桥接）
- [ ] `electron/src/renderer/index.html`（重构 chat-input-area、加 persona 面板）
- [ ] `electron/src/renderer/floating-ball.html`（重构为桌宠 + 菜单）
- [ ] `electron/src/renderer/js/{app,chat,chat-uploader,settings,data-viewer,floating-ball,voice-input,emotion-dashboard}.js`（多文件改）
- [ ] `electron/src/renderer/styles/{main,floating-ball}.css`（重构样式）
- [ ] `electron/src/renderer/assets/ita-{neutral,joy,sad}.svg`（3 桌宠 SVG）
- [ ] `core/api_server.py`（+segments, +persona, +stats/system, +voice/transcribe, +page）
- [ ] `voice/stt_engine.py`（新建，Whisper 封装）
- [ ] `config/persona_loader.py`（+_save_persona_yaml）
- [ ] `bin/whisper/{whisper-cli.exe,ggml-base.bin}`（首次下载）
- [ ] `requirements.txt`（+psutil 如缺失）
- [ ] 重建 `electron/dist-new/win-unpacked/Aerie · 云栖.exe`（自动注入新 icon）

---

> **签批等待**：本 plan 涉及 11 项用户反馈 + 8 个 batch + 17.5h 工作量。
> 用户审批后立即开始执行，按 B1→B2→B3→B4→B5→B6→B7→B8 顺序施工，每批完成后人工验证。
> 执行期间可暂停/恢复；不破坏现有 Phase 4/5 模块为红线。
