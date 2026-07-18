---
title: v13.9.9 打包修复 + API Key 配置页 + 首次启动自检
tags:
  - packaging
  - api-key
  - settings
  - tray
  - dynamic-island
aliases:
  - 打包修复计划
cssclasses:
---

# v13.9.9 打包修复 + API Key 配置页 + 首次启动自检

## 一、问题总览

打包后运行 `win-unpacked/Aerie · 云栖.exe` 出现以下问题：

| # | 问题 | 严重度 | 根因 |
|---|---|---|---|
| 1 | 后端异常（ECONNREFUSED 127.0.0.1:7890） | 🔴 致命 | `PROJECT_ROOT` 路径计算错误 + Python/`.venv` 未随包发布 |
| 2 | 托盘图标消失 | 🟠 高 | 图标路径依赖错误的 `PROJECT_ROOT`，`fs.existsSync` 失败后静默返回 |
| 3 | 主窗口 Logo 消失 | 🟡 中 | 同问题 2，`BrowserWindow.icon` 路径错误 |
| 4 | EXE 文件图标不是项目 Logo | 🟡 中 | rcedit 后处理脚本执行问题 |
| 5 | 关闭主窗口后灵动岛无法关闭，只能杀进程 | 🟠 高 | `closable: false` + `window-all-closed` 空处理 + 托盘不可用 → 无退出入口 |
| 6 | 新用户无法配置 API Key | 🔴 致命 | 只有 `.env` 文件方式，无 UI 配置入口 |
| 7 | 首次启动无自检引导 | 🟡 中 | 无 API Key 检测，无自动跳转到设置页 |

## 二、根因详细分析

### 2.1 后端启动失败

[main.js](file:///e:/Agent_reply/electron/src/main.js#L12-L14) 第 12 行：

```javascript
const PROJECT_ROOT = path.resolve(__dirname, "..", "..");
const PYTHON_EXE = path.join(PROJECT_ROOT, ".venv", "Scripts", "python.exe");
const PY_MAIN = path.join(PROJECT_ROOT, "main.py");
```

**开发模式下：**
- `__dirname` = `e:\Agent_reply\electron\src`
- `../..` = `e:\Agent_reply\` → 正确 ✅

**打包后（asar 内）：**
- `__dirname` = `...\resources\app.asar\src`
- `../..` = `...\resources\` → 错误 ❌
- Python 和 `.venv` 根本不在这个路径下

而且 electron-builder 的 `files` 配置只包含 `electron/src/**/*`，完全没有 Python 代码和虚拟环境。

### 2.2 托盘消失

[main.js](file:///e:/Agent_reply/electron/src/main.js#L362-L367) 第 362-367 行：

```javascript
function createTray() {
  const iconPath = path.join(PROJECT_ROOT, "Aerie · 云栖.png");
  if (!fs.existsSync(iconPath)) {
    console.warn("[main] tray icon not found:", iconPath);
    return;
  }
  // ...
}
```

`PROJECT_ROOT` 错误 → 图标找不到 → 静默 return → 托盘不创建。

### 2.3 灵动岛无法退出

[main.js](file:///e:/Agent_reply/electron/src/main.js#L251) 第 251 行设置了 `closable: false`，而 `window-all-closed` 事件处理器是空的（第 1358-1360 行）。当主窗口关闭、托盘又不存在时，用户完全没有退出途径。

### 2.4 API Key 配置缺失

API Key 目前只通过 `.env` 文件配置，由 [main.py](file:///e:/Agent_reply/main.py#L75-L80) 第 75-80 行用 `dotenv.load_dotenv()` 加载，[brain.py](file:///e:/Agent_reply/core/brain.py#L112-L175) 的 `_load_providers()` 从环境变量读取。设置面板里完全没有 API Key 相关的表单。

## 三、方案选型：便携版分发（Portable Bundle）

> 用户选择：便携版 + 自带 .venv，原项目 .venv 不动，分发版只带 DeepSeek。

**分发目录结构：**

```
Aerie · 云栖 v0.1.0-beta.1/
├── Aerie · 云栖.exe          ← Electron 启动器（带图标）
├── locales/                    ← Electron 语言包
├── resources/
│   ├── app.asar                ← Electron 壳子代码
│   └── icon.png                ← 图标资源
├── python/
│   ├── main.py                 ← Python 入口
│   ├── core/                   ← 核心模块
│   ├── config/                 ← 配置文件（带默认值，不含 API Key）
│   ├── .venv/                  ← Python 虚拟环境（精简版，DeepSeek 依赖）
│   └── data/                   ← 运行时生成的数据库
└── 启动说明.txt                ← 首次使用指南
```

## 四、实施步骤

### 模块 A：Electron 路径自适应（修复后端/托盘/图标）

**修改文件：** [electron/src/main.js](file:///e:/Agent_reply/electron/src/main.js)

| 改动 | 说明 |
|---|---|
| A1. 检测 `app.isPackaged` | 开发模式用旧路径；打包后基于 `process.execPath` 向上找项目根 |
| A2. 定位 Python 和 `.venv` | 打包后在 `<exe目录>/python/.venv/Scripts/python.exe` 和 `<exe目录>/python/main.py` |
| A3. 托盘图标路径 | 打包后用 `<exe目录>/resources/icon.png`，开发模式用旧路径 |
| A4. 主窗口图标 | 同 A3 |
| A5. `cwd` 设置 | Python 的工作目录设为 `<exe目录>/python/`，确保 `data/`、`config/` 相对路径正确 |

**路径检测逻辑：**
```
if app.isPackaged:
    APP_ROOT = path.dirname(process.execPath)  // exe 所在目录
    PYTHON_ROOT = path.join(APP_ROOT, "python")
    PYTHON_EXE = path.join(PYTHON_ROOT, ".venv", "Scripts", "python.exe")
    PY_MAIN = path.join(PYTHON_ROOT, "main.py")
    ICON_PATH = path.join(APP_ROOT, "resources", "icon.png")
else:
    // 开发模式保持原样
```

### 模块 B：灵动岛关闭逻辑修复

**修改文件：** [electron/src/main.js](file:///e:/Agent_reply/electron/src/main.js)

| 改动 | 说明 |
|---|---|
| B1. `window-all-closed` 事件 | 当所有窗口（主窗 + 灵动岛）都关闭时，调用 `app.quit()` |
| B2. 主窗关闭时灵动岛行为 | 主窗关闭后灵动岛可以保留（设计如此），但托盘必须可用，否则联动关闭灵动岛 |
| B3. 托盘不可用时的 fallback | 如果托盘创建失败，主窗关闭时同时关闭灵动岛并退出应用 |

### 模块 C：API Key 设置页

**新增 + 修改文件：**

| 文件 | 改动 |
|---|---|
| [electron/src/renderer/index.html](file:///e:/Agent_reply/electron/src/renderer/index.html) | 在设置面板"常用"模式下新增"AI 服务配置"分组 |
| [electron/src/renderer/js/settings.js](file:///e:/Agent_reply/electron/src/renderer/js/settings.js) | 新增 API Key 表单逻辑：加载、保存、验证 |
| [electron/src/renderer/styles/main.css](file:///e:/Agent_reply/electron/src/renderer/styles/main.css) | 新增 API Key 相关样式（密码框、provider 选择器） |
| [electron/src/main.js](file:///e:/Agent_reply/electron/src/main.js) | 新增 IPC：读写 `.env` 文件 |
| [electron/src/preload.js](file:///e:/Agent_reply/electron/src/preload.js) | 暴露 `env:read` / `env:write` 接口 |
| [core/api_server.py](file:///e:/Agent_reply/core/api_server.py) | 新增后端 API：`GET /api/env/providers`（返回已配置的 provider 列表，不含密钥值） |

**API Key 设置页功能：**
- Provider 选择器（DeepSeek / 通义千问 / 豆包 / SiliconFlow / OpenAI / Gemini / GLM / MiniMax）
- API Key 输入框（密码模式，带显示/隐藏切换）
- Base URL 输入框（可选，有默认值）
- Model 输入框（可选，有默认值）
- "测试连接"按钮（调用 `/api/health` 的 provider ping 接口）
- 保存时写入 `.env` 文件

### 模块 D：首次启动自检 & 引导

**修改文件：**

| 文件 | 改动 |
|---|---|
| [core/api_server.py](file:///e:/Agent_reply/core/api_server.py) | 新增 `GET /api/self-check` 返回自检结果（API Key 是否配置、数据库是否正常等） |
| [electron/src/renderer/js/app.js](file:///e:/Agent_reply/electron/src/renderer/js/app.js) | 启动后调用自检接口，检测到无 API Key 时自动跳转到设置页的 API Key 配置 |
| [electron/src/renderer/index.html](file:///e:/Agent_reply/electron/src/renderer/index.html) | 设置页的 API Key 区块加高亮引导 |

**自检逻辑：**
1. 应用启动，后端就绪后，前端调用 `GET /api/self-check`
2. 后端返回 `{ has_api_key: bool, providers_configured: [...], first_run: bool }`
3. 如果 `has_api_key === false`，自动切换到设置面板 → API Key 分组，并高亮提示

### 模块 E：分发打包脚本

**新增文件：** `scripts/build-portable.ps1`

| 步骤 | 说明 |
|---|---|
| E1. 构建 Electron | `npm run build:win` |
| E2. 创建分发目录 | `dist-portable/Aerie · 云栖 v0.1.0-beta.1/` |
| E3. 复制 Electron 产物 | `dist/win-unpacked/*` → 分发根目录 |
| E4. 复制 Python 代码 | `main.py`、`core/`、`config/`、`knowledge/`、`memory/`、`voice/`、`communication/` 等 → `python/` |
| E5. 创建精简版 .venv | 从原项目复制，但只保留 DeepSeek 相关依赖（httpx + python-dotenv + fastapi + uvicorn + pyyaml + sqlite3 等核心） |
| E6. 复制图标 | `electron/builder/icon-1024.png` → `resources/icon.png` |
| E7. 创建空 data 目录占位 | 确保首次启动有地方写数据库 |
| E8. 生成启动说明 | 简洁的首次使用指南 |

> 原项目 `.venv` 完全不动，通过脚本复制出一个精简版。

### 模块 F：EXE 图标修复

**修改文件：** [electron/scripts/post-build-rcedit.js](file:///e:/Agent_reply/electron/scripts/post-build-rcedit.js)

确认 rcedit 正常执行，图标文件路径正确。如果 rcedit 安装失败，提供降级方案。

## 五、涉及文件清单

| 路径 | 操作 |
|---|---|
| `electron/src/main.js` | 修改（路径自适应、托盘修复、灵动岛退出逻辑、env IPC） |
| `electron/src/preload.js` | 修改（暴露 env 接口） |
| `electron/src/renderer/index.html` | 修改（API Key 设置区块） |
| `electron/src/renderer/js/settings.js` | 修改（API Key 表单逻辑） |
| `electron/src/renderer/styles/main.css` | 修改（API Key 样式） |
| `electron/src/renderer/js/app.js` | 修改（首次自检跳转） |
| `core/api_server.py` | 修改（自检接口 + provider 列表接口） |
| `scripts/build-portable.ps1` | 新增（便携版打包脚本） |

## 六、验证方式

1. **开发模式回归**：`npm start` 启动，确认所有功能正常
2. **打包测试**：运行 `scripts/build-portable.ps1`
3. **分发目录自检**：检查打包产物中是否包含 Python 代码、`.venv`、图标
4. **干净环境测试**：把分发目录复制到另一路径（模拟新电脑），双击 exe 验证：
   - [ ] 后端正常启动（状态页显示正常）
   - [ ] 托盘图标正常显示
   - [ ] 主窗口图标正常显示
   - [ ] EXE 文件图标正常显示
   - [ ] 无 API Key 时自动跳转到设置页
   - [ ] API Key 可以填写并保存
   - [ ] 保存后后端能正常调用 AI
   - [ ] 关闭主窗口后灵动岛仍在（托盘可用时）
   - [ ] 托盘右键可以完全退出应用
   - [ ] `data/` 目录在 `python/` 下正确生成

## 七、风险与注意事项

> [!warning] .venv 体积
> 完整 .venv 约 500MB-1GB，精简后预计 200-300MB。需要实测精简效果。

> [!warning] 路径中文字符
> "Aerie · 云栖" 包含中文和特殊字符，在部分 Windows 系统上可能导致路径问题。分发版目录名建议同时提供英文名备选。

> [!info] API Key 安全性
> API Key 明文保存在 `.env` 中。这是本地桌面应用的常见做法，但应在 UI 中提醒用户密钥仅保存在本地。
