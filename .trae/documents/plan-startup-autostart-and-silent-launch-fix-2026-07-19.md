---
title: 开机自启与静默启动修复计划
date: 2026-07-19
tags:
  - plan
  - aerie
  - startup
  - electron
  - windows
status: ready-for-review
aliases:
  - Aerie Startup Fix Plan
---

# 开机自启与静默启动修复 Implementation Plan

> [!important] 执行约束
> 当前文档是 `/plan` 阶段产物。执行前不得修改业务代码；用户确认后，按本文逐项实现。

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补全 Aerie · 云栖 的真实 Windows 开机自启写入/删除逻辑，并修复 `start-dev-silent.vbs` 静默启动失败、重复启动、日志误判等问题。

**Architecture:** 由 Electron 主进程负责 OS 级开机启动项，因为 Electron 能正确区分开发态与打包态路径，并可使用官方 `app.setLoginItemSettings()`。设置页继续保存 YAML 配置，但保存成功后额外调用 Electron IPC 同步 Windows 启动项；静默启动脚本只负责可靠调用 `start-dev.bat` 并输出可审计日志。

**Tech Stack:** Electron 28、Node.js、Windows Login Item、VBScript、Batch、FastAPI settings API、YAML 配置。

---

## Summary

本次修复包含四条闭环：

1. `开机自启` checkbox 不再只是保存 `config/settings.yaml`，而是同步写入/删除 Windows Login Item。
2. `启动时最小化` 字段接入 Electron 启动参数，开机自启时以后台/最小化方式启动。
3. `start-dev-silent.vbs` 改为显式注入 `AERIE_SILENT=1`、稳定调用 `start-dev.bat`、写入带时间戳的日志，避免静默启动时仍触发 pause 或日志误判。
4. Electron 增加单实例锁，降低重复 Electron、端口占用、GPU cache 拒绝访问、Python backend `code=3` 的概率。

## Current State Analysis

### 已确认现状

- `start-dev-silent.vbs` 当前通过 `cmd.exe /c ""start-dev.bat" > "start-dev.log" 2>&1"` 调用批处理，见 `e:\Agent_reply\start-dev-silent.vbs:31-34`。
- `start-dev.bat` 会检查 Python venv、requirements、Electron 依赖并执行 `npm start`，见 `e:\Agent_reply\start-dev.bat:18-75`。
- `start-dev.bat` 理论上会在 `AERIE_SILENT=1` 时跳过 pause，见 `e:\Agent_reply\start-dev.bat:91-98`。
- 设置页会加载并保存 `startup.auto_start` / `startup.start_minimized`，见 `e:\Agent_reply\electron\src\renderer\js\settings.js:328-395`。
- 后端 `/api/settings` 只负责读写 YAML，见 `e:\Agent_reply\core\api_server.py:2301-2318`。
- `config/settings.yaml` 当前没有 `startup` 段，见 `e:\Agent_reply\config\settings.yaml:1-8`。
- `persona_loader.py` 默认值里有 `startup`，但 `load_settings()` 不做默认值合并，见 `e:\Agent_reply\config\persona_loader.py:20-50`。
- Electron 主进程没有 `app.setLoginItemSettings()`、`app.getLoginItemSettings()`、注册表 Run 写入逻辑。
- Electron 主窗口默认创建后显示，没有接入 `start_minimized`，见 `e:\Agent_reply\electron\src\main.js:246-281`。
- Electron 生命周期没有单实例锁，见 `e:\Agent_reply\electron\src\main.js:1382-1437`。

### 根因判断

> [!bug] 根因
> 当前 `开机自启` UI 只保存配置，不触发任何 Windows 启动项写入；`start-dev-silent.vbs` 静默启动失败主要与命令引号脆弱、环境变量传递不可审计、重复实例造成端口/cache 冲突有关。

### 不做的事

- 不把 Windows 启动项写入放到 Python 后端，避免后端承担 OS 桌面生命周期职责。
- 不强杀端口或进程，避免误杀用户手动运行的服务。
- 不大规模重构设置系统，只做最小闭环修复。

---

## Proposed Changes

### Task 1: 在 Electron 主进程补 Windows Login Item helper

**Files:**
- Modify: `e:\Agent_reply\electron\src\main.js`

**What:** 新增开机启动项读取/写入 helper，并兼容开发态与打包态。

**Why:** Windows 启动项必须由 Electron 主进程这类 OS 边界层处理，不能只停留在 YAML。

**How:**

- [ ] **Step 1: 在 `main.js` 顶部状态区后添加启动参数常量与状态函数**

在 `e:\Agent_reply\electron\src\main.js` 的 `let BACKEND_LOG_DIR = null;` 后追加：

```javascript
const START_MINIMIZED_ARG = "--start-minimized";

function isStartMinimizedArgPresent() {
  return process.argv.includes(START_MINIMIZED_ARG) || process.argv.includes("--hidden");
}

function getWindowsScriptHostPath() {
  const systemRoot = process.env.SystemRoot || "C:\\Windows";
  return path.join(systemRoot, "System32", "wscript.exe");
}

function getDevSilentLauncherPath() {
  return path.join(PROJECT_ROOT, "start-dev-silent.vbs");
}

function getStartupLaunchConfig(startMinimized) {
  if (app.isPackaged) {
    return {
      path: app.getPath("exe"),
      args: startMinimized ? [START_MINIMIZED_ARG] : [],
    };
  }

  const args = [getDevSilentLauncherPath()];
  if (startMinimized) args.push(START_MINIMIZED_ARG);
  return {
    path: getWindowsScriptHostPath(),
    args,
  };
}

function getStartupSettings() {
  const loginItem = app.getLoginItemSettings();
  return {
    autoStart: loginItem.openAtLogin === true,
    openAtLogin: loginItem.openAtLogin === true,
    wasOpenedAtLogin: loginItem.wasOpenedAtLogin === true,
    wasOpenedAsHidden: loginItem.wasOpenedAsHidden === true,
    startMinimized: isStartMinimizedArgPresent(),
  };
}

function setStartupSettings(options) {
  const autoStart = options && options.autoStart === true;
  const startMinimized = options && options.startMinimized === true;
  const launchConfig = getStartupLaunchConfig(startMinimized);

  app.setLoginItemSettings({
    openAtLogin: autoStart,
    path: launchConfig.path,
    args: launchConfig.args,
  });

  return {
    ok: true,
    autoStart,
    startMinimized,
    path: launchConfig.path,
    args: launchConfig.args,
    state: getStartupSettings(),
  };
}
```

- [ ] **Step 2: 在 IPC 区添加 `startup:get` / `startup:set`**

在 `e:\Agent_reply\electron\src\main.js` 的 `settings:reset` handler 后追加：

```javascript
ipcMain.handle("startup:get", async () => {
  try {
    return { ok: true, ...getStartupSettings() };
  } catch (e) {
    return { ok: false, error: String((e && e.message) || e) };
  }
});

ipcMain.handle("startup:set", async (_event, options) => {
  try {
    return setStartupSettings(options || {});
  } catch (e) {
    return { ok: false, error: String((e && e.message) || e) };
  }
});
```

- [ ] **Step 3: 手动静态检查**

确认 `main.js` 中已有 `path` 与 `app` 引入，无需新增依赖。

---

### Task 2: 在 preload 暴露 startup IPC

**Files:**
- Modify: `e:\Agent_reply\electron\src\preload.js`

**What:** 给 renderer 暴露 `window.aerie.startup.get()` 与 `window.aerie.startup.set()`。

**Why:** 设置页运行在隔离上下文，不能直接访问 Electron 主进程。

**How:**

- [ ] **Step 1: 在 `settings` API 后添加 `startup` API**

把 `e:\Agent_reply\electron\src\preload.js:99-103` 附近改为：

```javascript
  settings: {
    get: () => ipcRenderer.invoke("settings:get"),
    set: (data) => ipcRenderer.invoke("settings:set", data),
    reset: () => ipcRenderer.invoke("settings:reset"),
  },
  startup: {
    get: () => ipcRenderer.invoke("startup:get"),
    set: (options) => ipcRenderer.invoke("startup:set", options || {}),
  },
```

- [ ] **Step 2: 确认不会影响既有 API**

`window.aerie.settings` 保持不变，只新增同级 `window.aerie.startup`。

---

### Task 3: 设置页保存后同步 Windows 启动项

**Files:**
- Modify: `e:\Agent_reply\electron\src\renderer\js\settings.js`

**What:** `load()` 时读取系统真实启动项状态；`save()` 时保存 YAML 成功后同步 OS 启动项。

**Why:** UI 状态、YAML 状态、Windows 启动项状态必须一致。

**How:**

- [ ] **Step 1: 修改 `load()`，在 YAML 加载后校准系统状态**

在设置 checkbox 后添加：

```javascript
      if (window.aerie && window.aerie.startup && window.aerie.startup.get) {
        const startupState = await window.aerie.startup.get();
        if (startupState && startupState.ok) {
          document.getElementById("setting-auto-start").checked = startupState.autoStart === true;
        }
      }
```

保留 `start_minimized` 从 YAML 加载，因为系统 API 返回的是当前进程是否由最小化参数打开，不等价于配置值。

- [ ] **Step 2: 修改 `save()`，API 保存成功后调用系统启动项同步**

把成功分支从：

```javascript
      if (r.data && !r.data.error) {
        st.textContent = "设置已保存";
        st.style.color = "var(--success)";
      } else {
```

改为：

```javascript
      if (r.data && !r.data.error) {
        if (window.aerie && window.aerie.startup && window.aerie.startup.set) {
          const startupResult = await window.aerie.startup.set({
            autoStart: data.startup.auto_start,
            startMinimized: data.startup.start_minimized,
          });
          if (!startupResult || startupResult.ok === false) {
            st.textContent = "设置已保存，但开机启动项写入失败: " + (startupResult?.error || "unknown");
            st.style.color = "var(--error)";
            setTimeout(() => { st.textContent = ""; }, 5000);
            return;
          }
        }
        st.textContent = "设置已保存";
        st.style.color = "var(--success)";
      } else {
```

- [ ] **Step 3: 修改 `reset()` 同步关闭系统启动项**

在 `await window.aerie.api.request({ method: "POST", path: "/api/settings/reset" });` 后添加：

```javascript
      if (window.aerie && window.aerie.startup && window.aerie.startup.set) {
        await window.aerie.startup.set({ autoStart: false, startMinimized: false });
      }
```

---

### Task 4: 接入启动时最小化

**Files:**
- Modify: `e:\Agent_reply\electron\src\main.js`

**What:** Electron 主窗口支持由 `--start-minimized` 或 `--hidden` 参数控制首启隐藏/最小化。

**Why:** UI 已有 `启动时最小化` checkbox，但当前没有实际效果。

**How:**

- [ ] **Step 1: 给 BrowserWindow 增加 `show: false`**

在 `createMainWindow()` 的 BrowserWindow options 内添加：

```javascript
    show: false,
```

- [ ] **Step 2: 在 `loadFile` 后按启动参数显示或隐藏**

在 `mainWindow.loadFile(...)` 后添加：

```javascript
  mainWindow.once("ready-to-show", () => {
    if (isStartMinimizedArgPresent()) {
      mainWindow.hide();
    } else {
      mainWindow.show();
    }
  });
```

- [ ] **Step 3: 确认托盘可重新打开窗口**

检查 `createTray()` 中已有打开主窗口逻辑；若已有 `mainWindow.show()` / `focus()`，不额外改动。

---

### Task 5: 增加 Electron 单实例锁

**Files:**
- Modify: `e:\Agent_reply\electron\src\main.js`

**What:** 防止静默启动、手动启动、开机启动同时拉起多个 Electron。

**Why:** 多实例会导致端口 7890 冲突、GPU cache 权限错误、Python backend `code=3`。

**How:**

- [ ] **Step 1: 在生命周期前添加单实例锁**

在 `// ── Lifecycle` 前添加：

```javascript
const gotSingleInstanceLock = app.requestSingleInstanceLock();

if (!gotSingleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });
}
```

- [ ] **Step 2: 确保 `app.whenReady()` 只在获得锁后启动**

把现有：

```javascript
app.whenReady().then(() => {
```

改为：

```javascript
if (gotSingleInstanceLock) {
  app.whenReady().then(() => {
```

并在原 `});` 后补一个 `}`，形成：

```javascript
  });
}
```

---

### Task 6: 修复 `start-dev-silent.vbs` 命令构造和日志可审计性

**Files:**
- Modify: `e:\Agent_reply\start-dev-silent.vbs`

**What:** 使用更稳定的 `cmd.exe /d /s /c`，显式设置 `AERIE_SILENT=1`，添加启动时间戳日志。

**Why:** 当前日志显示静默时可能没有正确识别 `AERIE_SILENT`，且旧日志难以区分是哪次启动产生。

**How:**

- [ ] **Step 1: 调整变量声明**

把：

```vbscript
Dim strScriptDir, strLauncher, strLogsDir, strLogFile, strCommand, q
```

改为：

```vbscript
Dim strScriptDir, strLauncher, strLogsDir, strLogFile, strCommand, q, objLog
```

- [ ] **Step 2: 写入启动时间戳**

在创建 logs 目录后添加：

```vbscript
Set objLog = objFSO.OpenTextFile(strLogFile, 8, True)
objLog.WriteLine ""
objLog.WriteLine "============================================================"
objLog.WriteLine "Silent launcher started: " & Now
objLog.WriteLine "ScriptDir: " & strScriptDir
objLog.WriteLine "Launcher: " & strLauncher
objLog.Close
```

- [ ] **Step 3: 改成显式注入环境变量的命令**

把当前：

```vbscript
objShell.CurrentDirectory = strScriptDir
objShell.Environment("PROCESS")("AERIE_SILENT") = "1"
strCommand = "cmd.exe /c " & q & q & strLauncher & q & " > " & q & strLogFile & q & " 2>&1" & q
objShell.Run strCommand, 0, False
```

改为：

```vbscript
objShell.CurrentDirectory = strScriptDir
objShell.Environment("PROCESS")("AERIE_SILENT") = "1"
strCommand = "cmd.exe /d /s /c " & q & "set AERIE_SILENT=1 && call " & q & strLauncher & q & " >> " & q & strLogFile & q & " 2>&1" & q
objShell.Run strCommand, 0, False
```

> [!note]
> 这里使用 `>>` 追加日志，配合时间戳便于多次测试对比；不使用强制覆盖，避免丢失失败证据。

---

### Task 7: 给 `start-dev.bat` 添加静默状态与时间戳日志

**Files:**
- Modify: `e:\Agent_reply\start-dev.bat`

**What:** 输出 `AERIE_SILENT` 与启动时间，便于判断是否来自静默脚本。

**Why:** 当前曾出现静默启动日志仍显示 `Press any key`，需要可审计证据确认环境变量是否传入。

**How:**

- [ ] **Step 1: 在 banner 后输出静默状态**

在：

```bat
echo Root: %ROOT_DIR%
echo.
```

后添加：

```bat
echo Started: %DATE% %TIME%
echo AERIE_SILENT=%AERIE_SILENT%
echo.
```

- [ ] **Step 2: 保持失败 pause 条件不变**

保留现有：

```bat
if /i not "%AERIE_SILENT%"=="1" (
    echo Press any key to close this window.
    pause >nul
)
```

不额外改动失败策略。

---

## Assumptions & Decisions

- 采用 Electron `app.setLoginItemSettings()`，不直接写注册表。
- 开发态开机启动目标为 `wscript.exe e:\Agent_reply\start-dev-silent.vbs`。
- 打包态开机启动目标为 `app.getPath("exe")`。
- `start_minimized` 通过 `--start-minimized` 参数实现。
- 单实例锁是必须项，用于规避重复启动引发的端口/cache 问题。
- 不在启动脚本里强制关闭旧进程，避免破坏用户当前会话。
- 不修改 `config/settings.yaml` 作为计划阶段动作；执行后由 UI 保存流程自然写入。

---

## Verification Steps

> [!todo] 执行完成后必须验证
> 每个验证项都要记录结果；如果失败，先定位日志，不要重复盲跑。

### 1. 静态检查

- [ ] 运行 Electron 检查脚本：

```powershell
npm run check:all
```

工作目录：`e:\Agent_reply\electron`

预期：命令退出码为 `0`。

- [ ] 运行 Electron lint：

```powershell
npm run lint
```

工作目录：`e:\Agent_reply\electron`

预期：输出 `No JS lint configured`，退出码为 `0`。

### 2. 依赖环境检查

- [ ] 检查 Python venv 存在：

```powershell
Test-Path "e:\Agent_reply\.venv\Scripts\python.exe"
```

预期：`True`。

- [ ] 检查核心 Python 包：

```powershell
& "e:\Agent_reply\.venv\Scripts\python.exe" -c "import importlib.util,sys; mods=['fastapi','uvicorn','aiohttp','websockets','psutil','yaml','dotenv','loguru']; missing=[m for m in mods if importlib.util.find_spec(m) is None]; print('MISSING:'+','.join(missing) if missing else 'OK'); sys.exit(1 if missing else 0)"
```

预期：`OK`。

- [ ] 检查 Electron 依赖：

```powershell
Test-Path "e:\Agent_reply\electron\node_modules\.bin\electron.cmd"
```

预期：`True`。

### 3. 开机自启写入验证

- [ ] 启动应用，勾选 `开机自启` 和按需勾选 `启动时最小化`，点击保存。
- [ ] 检查 Windows Run/Login Item 状态：

```powershell
Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
```

预期：存在 Aerie/Electron 对应启动项，开发态指向 `wscript.exe` 并带 `e:\Agent_reply\start-dev-silent.vbs` 参数。

- [ ] 取消勾选 `开机自启` 并保存。
- [ ] 再次检查 Run/Login Item。

预期：对应启动项被关闭或删除。

### 4. 静默脚本启动验证

- [ ] 确保没有重复手动启动多个 Electron 后，执行：

```powershell
wscript.exe "e:\Agent_reply\start-dev-silent.vbs"
```

预期：无控制台窗口弹出。

- [ ] 查看 `e:\Agent_reply\logs\start-dev.log`。

预期包含：

```text
Silent launcher started:
AERIE_SILENT=1
[4/4] Starting Electron...
```

且不再出现：

```text
Press any key to close this window.
'n' 不是内部或外部命令
```

### 5. 后端健康验证

- [ ] 检查健康接口：

```powershell
Invoke-RestMethod "http://127.0.0.1:7890/api/health"
```

预期：返回 `healthy` 或 `degraded`。

### 6. 多次重复启动验证

- [ ] 连续运行 `wscript.exe "e:\Agent_reply\start-dev-silent.vbs"` 两到三次。
- [ ] 检查进程数量。

预期：不会产生多个主 Electron 实例；已有窗口被唤起/聚焦，日志不再出现端口冲突引起的 Python `code=3`。

---

## Rollback Plan

若开机启动项写入异常：

1. 在 UI 中取消 `开机自启` 并保存。
2. 如仍存在启动项，使用 Windows 任务管理器「启动应用」禁用 Aerie。
3. 回退本次修改的文件：
   - `e:\Agent_reply\electron\src\main.js`
   - `e:\Agent_reply\electron\src\preload.js`
   - `e:\Agent_reply\electron\src\renderer\js\settings.js`
   - `e:\Agent_reply\start-dev-silent.vbs`
   - `e:\Agent_reply\start-dev.bat`

---

## Self-Review

- [x] 覆盖真实 Windows 开机启动项写入/删除。
- [x] 覆盖 UI、YAML、系统启动项一致性。
- [x] 覆盖 `start-dev-silent.vbs` 静默启动失败分析与修复。
- [x] 覆盖依赖环境验证。
- [x] 覆盖重复启动、端口冲突、cache 权限问题的最小修复。
- [x] 没有新增不必要的抽象或跨层重构。
- [x] 没有计划直接强杀进程或端口。

^startup-fix-plan
