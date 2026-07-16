# Phase 9 续批 · E2E 收尾 + Block-2（托盘菜单 + 聊天头像/名字 + 角色设置）执行计划

> 范围锚定：plan-phase9-e2e-and-block2.md 的 §3 项决策已锁（E2E 全 3 项 / 托盘=Aerie 自己的 / 头像两边都加），本计划据此落地。

---

## 一、目标拆解

### Part A · E2E 收尾（必做，先于一切）
- A.1 创建 `e2e_checklist.md`（18 项验收清单）
- A.2 跑 6 套脚本全绿：`verify_pacing_persistence.py` / `verify_zero_regression.py` / `verify_emotion_history.py` / `verify_self_evolve.py` / `e2e_pacing.py` / `e2e_self_evolve.py`
- A.3 自我怀疑 review（3 轮），3 原则铁律自检
- A.4 向用户**问 1 个澄清问题**（确认是否启动 Block-2）

### Part B · Block-2 整改（等用户回答"是"才启动）
- B.1 托盘右键菜单（T1）
- B.2 聊天头像 + 名字（A1）
- B.3 角色设置页面（A2：头像上传 + 中英名输入）
- B.4 自我怀疑 review + 三原则自检

---

## 二、E2E 收尾详细计划

### 2.1 E2E.3 · 18 项 checklist 文档

**新文件**：`e:\Agent_reply\.trae\documents\phase9-e2e-checklist.md`

**结构**（参考 plan-phase9-batch4-7 §E2E.4 6 组划分）：
| 组 | 项数 | 验证手段 |
| --- | --- | --- |
| 表与 schema | 4 | `verify_zero_regression.py` + `PRAGMA integrity_check` |
| API 健康 | 3 | `verify_self_evolve.py` + `verify_emotion_history.py` 内置 `/api/health` 调用 |
| UI 渲染 | 4 | 手动浏览器开 index.html 看 chat / 主题 / 大脑中枢 / 自进化卡片 |
| pacing 落库 | 2 | `verify_pacing_persistence.py`（27/27）+ `e2e_pacing.py` |
| 自进化闭环 | 3 | `e2e_self_evolve.py`（10 段全过） |
| 文档与规范 | 2 | grep 禁词 + 检查代码层纯英文 |
| **合计** | **18** | |

每项用 `- [ ]` markdown 复选框，附"如何验证"一行。

### 2.2 E2E.4 · 跑 6 套脚本

执行顺序（任一失败立即停）：
```powershell
# 在 e:\Agent_reply 下，启用 UTF-8
$env:PYTHONIOENCODING="utf-8"
python -X utf8 verify_pacing_persistence.py
python -X utf8 verify_zero_regression.py
python -X utf8 verify_emotion_history.py
python -X utf8 verify_self_evolve.py
python -X utf8 e2e_pacing.py
python -X utf8 e2e_self_evolve.py
```

期望：每套都 `passed=X  failed=0` 或 `X/Y 通过`。

### 2.3 E2E.4 · 自我怀疑 review

- **R1**：6 脚本是否都真的动了真实 DB / 决策树？（不是 mock 假绿）
- **R2**：checklist 18 项是否每项都有可执行的"如何验证"？无空话
- **R3**：5 主题色 / 禁词 / `app_name=Aerie` 三原则是否在新增 checklist 文本中守住

### 2.4 E2E 收尾后向用户问 1 个问题

用 AskUserQuestion 工具询问："E2E 阶段全部通过，是否启动 Block-2（托盘右键菜单 + 聊天头像/名字 + 角色设置）？"
- 选项 A：**是，立即启动**（执行 Part B）
- 选项 B：先调整 E2E
- 选项 C：暂停，今天先到这里

---

## 三、Block-2 详细计划（待 E2E 收尾 + 用户确认后执行）

### 3.1 T1 · 托盘右键菜单

**文件**：`e:\Agent_reply\electron\src\main.js`

**改动**（在 L2 import 块 + L197-211 createTray 内）：
1. 导入 `Menu` 与 `dialog`：
   ```js
   const { app, BrowserWindow, Tray, ipcMain, nativeImage, screen, Menu, dialog } = require("electron");
   ```
2. `createTray()` 末尾追加 `setContextMenu`：
   ```js
   const menu = Menu.buildFromTemplate([
     { label: "显示 / 隐藏窗口", click: () => {
         if (!mainWindow) return;
         mainWindow.isVisible() ? mainWindow.hide() : mainWindow.show();
     }},
     { label: "设置", click: () => {
         if (mainWindow) { mainWindow.show(); mainWindow.focus(); }
         const wins = BrowserWindow.getAllWindows();
         wins.forEach(w => w.webContents.send("ui:open-tab", "settings"));
     }},
     { label: "关于", click: () => {
         dialog.showMessageBox({
           type: "info",
           title: "Aerie · 云栖",
           message: "Aerie · 云栖",
           detail: "伊塔在你身边。/ Ita is with you.\n版本 v9.0 Hybrid\n© 2026",
           buttons: ["好 / OK"],
         });
     }},
     { type: "separator" },
     { label: "退出", click: () => { app.quit(); } },
   ]);
   tray.setContextMenu(menu);
   ```
3. `app.on("before-quit", …)` 已 kill pythonProc ✓ 不动
4. `setContextMenu` 后，Windows 上 `on("click")` 行为：单击仍切换显示/隐藏（保留原行为，符合用户"不知道叫啥想用快捷操作"中"双击=显示"预期）

**自检**：
- [ ] 4 菜单项点击都有响应
- [ ] 「退出」会 kill pythonProc
- [ ] 右键不打开时 `tray.on("click")` 仍工作

### 3.2 A1 · 聊天头像 + 名字

**文件**：`e:\Agent_reply\electron\src\renderer\js\chat.js`

**改动**（在 `_render` 内，气泡 DOM 之前）：
1. 新增字段：
   ```js
   this._personaCache = null;   // {name, english_name, avatar_url}
   this._masterAvatar = null;   // string|null
   ```
2. 在 `init()` 末尾异步拉 persona + master avatar：
   ```js
   this._loadPersona();
   this._loadMasterAvatar();
   ```
3. `_loadPersona`：`GET /api/persona`（端点见 §3.3）→ 缓存
4. `_loadMasterAvatar`：`GET /api/qq/avatar?user_id={this._masterQQ}` → 缓存
5. `_render` 中气泡前注入：
   ```js
   const isAssistant = msg.role === "assistant";
   const name = isAssistant
     ? (this._personaCache?.name || "伊塔")
     : "你";
   const avatar = isAssistant
     ? (this._personaCache?.avatar_url || "/assets/avatar_ita_default.png")
     : (this._masterAvatar || "/assets/avatar_user_default.png");
   html = `<div class="chat-msg__meta">
     <img class="chat-msg__avatar" src="${this._escapeHtml(avatar)}" alt="" onerror="this.style.visibility='hidden'">
     <span class="chat-msg__name">${this._escapeHtml(name)}</span>
   </div>` + html;
   ```
6. CSS 调整（在 `main.css` 末尾追加，5 主题色自适应）：
   ```css
   .chat-msg__meta { display:flex; align-items:center; gap:6px; margin-bottom:2px; }
   .chat-msg--assistant .chat-msg__meta { justify-content:flex-start; }
   .chat-msg--user .chat-msg__meta { justify-content:flex-end; }
   .chat-msg__avatar { width:28px; height:28px; border-radius:50%; object-fit:cover; border:1px solid var(--border, rgba(255,255,255,0.15)); }
   .chat-msg__name { font-size:12px; color:var(--text-muted, #888); }
   ```

**自检**：
- [ ] assistant / user 两侧均显示头像 + 名字
- [ ] `msg.role` 缺失时降级为 user（向后兼容）
- [ ] 头像 404 时不破图（onerror）
- [ ] 5 主题切换时边框/名字色自适应

### 3.3 A2 · 角色设置页面（persona 头像 + 名字）

**前端**：`e:\Agent_reply\electron\src\renderer\index.html`（settings-form-view 顶部，L387-416）

新增区块（插在 `<div id="settings-form-view">` 内、`<div class="settings-group">主题` **之前**）：
```html
<div class="settings-group settings-group--persona">
  <h3 class="settings-section-title">她的样子 · Her Appearance</h3>
  <p class="settings-hint">这是她在你眼中的样子。改完她就是这个人。/ This is who she is to you.</p>
  <div class="persona-edit">
    <div class="persona-avatar">
      <img id="persona-avatar-preview" src="/assets/avatar_ita_default.png" alt="">
      <input type="file" id="persona-avatar-file" accept="image/png,image/jpeg" hidden>
      <button id="persona-avatar-upload" class="btn btn-secondary">换头像 · Change</button>
    </div>
    <div class="persona-fields">
      <label>名字 · Name <input type="text" id="persona-name" maxlength="20"></label>
      <label>English Name <input type="text" id="persona-english-name" maxlength="20"></label>
    </div>
  </div>
  <div class="settings-actions">
    <button id="persona-save-btn" class="btn btn-primary">保存她 · Save</button>
  </div>
  <div id="persona-status" style="font-size:12px;color:var(--success);margin-top:6px;"></div>
</div>
```

**前端 JS**：`e:\Agent_reply\electron\src\renderer\js\settings.js`
- `init()` 末尾加载 persona：`this.loadPersona()`
- 新增方法：
  - `loadPersona()`：GET `/api/persona` → 填 3 个控件
  - `savePersona()`：PUT `/api/persona` body={name,english_name}，上传头像用 `POST /api/persona/avatar` multipart
  - 文件上传前客户端校验 ≤2MB + type 白名单
- 文案严格使用「她」「伊塔」，禁词禁「主人」

**后端**：新增 3 端点到 `e:\Agent_reply\core\api_server.py`
- `GET /api/persona` → 返回 `{name, english_name, avatar_url}`
- `PUT /api/persona` body={name?, english_name?} → 写 `config/persona.yaml`（走 B3 强校验 + 备份）
- `POST /api/persona/avatar` multipart → 写 `data/persona/avatar.png`（≤2MB，PNG/JPG），并保留 4 周内备份

**persona_loader 扩展**：`e:\Agent_reply\config\persona_loader.py`
- 新增 `save_persona(patch: dict) -> bool`：深合并后原子写回，yaml 强校验失败回滚
- 新增 `load_avatar_bytes() -> bytes | None`：读 `data/persona/avatar.png`

**自检**：
- [ ] 上传后真写到 `data/persona/avatar.png`（ls 验证）
- [ ] yaml 写回走 `_deep_merge` 不破坏其他字段
- [ ] 聊天刷新后真读新头像（不缓存）
- [ ] 客户端 + 服务端双层拦截 >2MB 文件

---

## 四、文件改动总览

| 文件 | 类型 | 估行数 | 风险 |
| --- | --- | --- | --- |
| `.trae/documents/phase9-e2e-checklist.md` | 新 | +120 | 纯文档，零风险 |
| `electron/src/main.js` | 改 | +35 | 加 Menu/dialog import + setContextMenu + ui:open-tab IPC |
| `electron/src/renderer/index.html` | 改 | +30 | 新增 persona 区块 HTML |
| `electron/src/renderer/js/chat.js` | 改 | +45 | 加载 persona + avatar + 渲染 meta |
| `electron/src/renderer/js/settings.js` | 改 | +60 | loadPersona/savePersona + 上传 |
| `electron/src/renderer/styles/main.css` | 改 | +12 | 头像 / meta 样式 |
| `core/api_server.py` | 改 | +70 | 3 端点 + 头像保存 + 备份 |
| `config/persona_loader.py` | 改 | +50 | save_persona + load_avatar_bytes |
| **合计** | | **+422** | 中等 |

---

## 五、风险与回滚

| 风险 | 概率 | 影响 | 回滚 |
| --- | --- | --- | --- |
| E2E 某脚本失败 | 中 | 阻断 Block-2 | 该脚本 git 复位（仅是 verify 脚本） |
| persona.yaml 写坏 | 低 | 伊塔文案乱 | save_persona 强校验 + 写前自动备份到 `data/backups/config/` |
| 头像上传炸磁盘 | 低 | 占空间 | 客户端 2MB + 服务端 2MB 双层拦截 + 保留 4 周 |
| 5 主题色不匹配 | 中 | 美学破坏 | CSS 用 `var(--border)` 等现有 token |

---

## 六、执行顺序（严格）

```
1. 创建 phase9-e2e-checklist.md         (0.25h)
2. 跑 6 脚本，全绿                       (0.5h)
3. 自我怀疑 review × 3 轮                (0.25h)
4. AskUserQuestion 问"启动 Block-2?"     (0)
        ↓ 主人答"是"
5. T1 main.js tray menu                  (0.25h)
6. A1 chat.js avatar + name              (0.4h)
7. A2 后端 3 端点 + persona_loader       (0.5h)
8. A2 前端 index.html + settings.js      (0.4h)
9. A2 CSS main.css                       (0.1h)
10. Block-2 自我怀疑 review + 三原则     (0.3h)
```

总工时估约 3.0h（不含用户决策等待）。

---

## 七、三原则铁律（每步都自检）

1. **不破坏现有功能** — verify 4 套脚本必须仍 113/113 全过；新增端点不破坏现有 42 端点
2. **不破坏伊塔人格** — 区块文案用「她/伊塔」；禁词列表不变（"主人/您"）；UI 中英双语
3. **设计美学统一** — 头像/名字用现有 CSS token；5 主题色自适应；不上 emoji（用 SVG）

---

## 八、待用户确认

- E2E 收尾（A.1-A.4）是否同意立即执行？
- E2E 全绿后，问我 1 个问题（启动 Block-2 否？），用户答"是"才进 Part B，是否同意？
- 任何子项失败立即中断，不堆到下一子项，是否同意？
