# Aerie · 云栖 打包逻辑重构文档

> 目标：解决打包产物在干净机器上「核心功能失效」的问题，用自包含嵌入式 Python 运行时替代 venv 重定向器 + 运行时联网下载的临时方案。

## 一、问题分析

### 1.1 旧打包架构

旧方案由 [electron-builder.yml](file:///e:/Agent_reply/electron/electron-builder.yml) 把开发机的 `.venv` 原样塞进 `resources/python/.venv`，Electron 直接 spawn `.venv/Scripts/python.exe`。

### 1.2 致命缺陷

| # | 缺陷 | 影响 |
|---|---|---|
| 1 | **`.venv/Scripts/python.exe` 是重定向器**，按 `pyvenv.cfg` 的 `home` 字段去找开发机的 `C:\Python314\python.exe`。干净机器无此解释器 → 后端 `ECONNREFUSED 127.0.0.1:7890` | 整个后端无法启动（致命） |
| 2 | 旧方案只能靠 [runtime-bootstrap.js](file:///e:/Agent_reply/electron/src/runtime-bootstrap.js) 在用户**首次启动时联网下载** embeddable Python，并改写 `._pth` 指向随包 site-packages | 依赖网络 + ABI 版本匹配，属于不可靠临时方案 |
| 3 | `extraResources` filter **回退丢失** `skills/**`、`NapCat/**`、`emotion/**`、`persona/**`、`scheduler/**`（对照 [debug-packaged-backend-resources.md](file:///e:/Agent_reply/docs/debug-packaged-backend-resources.md) 曾修复过） | 技能路由失效、QQ 登录失效 |
| 4 | 开发机 `.venv` **本身不完整**：`pywin32`、`pywinauto`、`pyautogui`、`weasyprint`、`apscheduler`、`sounddevice`、`soundfile` 等声明依赖实际装在用户全局 `%APPDATA%\Python\Python314\site-packages`，未进 venv | 打包时漏掉这些依赖，干净机器上 `import win32api` 等直接失败 |
| 5 | `post-build-rcedit.js` 硬编码 `Aerie-Cloud.exe`，但 electron-builder 实际产物为 `Aerie · 云栖.exe` | EXE 图标注入失败 |

### 1.3 关键约束

本应用是**源码型架构**：`skill_loader.py` 动态 import `skills/*/run.py`，config 热重载监听 YAML，`Path(__file__)` 定位资源。因此 **PyInstaller 打包会破坏动态 import 与热重载，不适用**。

## 二、新打包逻辑设计

采用 **自包含嵌入式 Python 运行时**：

```
resources/
  app.asar                      Electron 壳
  python/
    main.py + core/ + config/ + ...   源码保持 .py 文件形态（兼容动态 import）
    runtime/                    自包含 CPython（真实可迁移，非重定向器）
      python.exe / python314.dll / DLLs / Lib/site-packages
```

设计要点：

1. **构建期生成运行时**：`scripts/build_python_runtime.py` 从 `.venv/pyvenv.cfg` 读取基础解释器 `C:\Python314`，整目录拷贝为 `electron/runtime-build/`，再用 `.venv/Lib/site-packages` 覆盖三方依赖（剔除 pip/setuptools/wheel/pytest）。
2. **Electron 直接 spawn 真实解释器**：`PYTHON_EXE = resources/python/runtime/python.exe`，无重定向、无运行时下载。
3. **打包态禁用用户站点包**：spawn 环境加 `PYTHONNOUSERSITE=1`，确保后端只用随包依赖，不被目标机器全局 Python 包污染。
4. **补全 filter**：重新加入 `skills/**`、`NapCat/**`、`emotion/**`、`persona/**`、`scheduler/**`，移除 `.venv`。
5. **rcedit 改为扫描 exe**：不再硬编码文件名，扫描 `win-unpacked/*.exe`。

## 三、实现步骤

### 3.1 新增文件

- [scripts/build_python_runtime.py](file:///e:/Agent_reply/scripts/build_python_runtime.py) — 构建自包含运行时，含 `-s`（禁用用户站点）导入自检。
- [scripts/verify_packaged_backend.py](file:///e:/Agent_reply/scripts/verify_packaged_backend.py) — 集成测试 + 生产模拟脚本。

### 3.2 修改文件

| 文件 | 改动 |
|---|---|
| [electron/electron-builder.yml](file:///e:/Agent_reply/electron/electron-builder.yml) | extraResources 新增 `runtime-build` → `python/runtime`；filter 补全缺失模块、移除 `.venv`、排除 `data/logs/NapCat config+cache`；清理重复 nsis 块 |
| [electron/package.json](file:///e:/Agent_reply/electron/package.json) | `build:win` 前置 `build:runtime`；`build.extraResources` 同步 yml |
| [electron/src/main.js](file:///e:/Agent_reply/electron/src/main.js) | `PYTHON_EXE` → `runtime/python.exe`；spawn env 打包态加 `PYTHONNOUSERSITE=1` |
| [electron/src/runtime-bootstrap.js](file:///e:/Agent_reply/electron/src/runtime-bootstrap.js) | 站点包路径指向 `runtime/Lib/site-packages`；注释更新为「安全网」语义 |
| [electron/scripts/post-build-rcedit.js](file:///e:/Agent_reply/electron/scripts/post-build-rcedit.js) | exe 查找改为扫描顶层 `*.exe` |
| [.gitignore](file:///e:/Agent_reply/.gitignore) | 新增 `electron/runtime-build/` |
| [requirements.txt](file:///e:/Agent_reply/requirements.txt) | 未改（依赖补齐通过 venv 安装） |

### 3.3 venv 依赖补齐

发现开发机 `.venv` 缺失 4 个声明依赖 + 若干传递依赖，通过以下命令补齐（本次会话已执行）：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install "pywin32==312" "pywinauto==0.6.9" "pyautogui==0.9.54" "weasyprint==69.0" "apscheduler==3.11.3" "sounddevice==0.5.5" "soundfile==0.14.0"
```

## 四、测试验证

### 4.1 单元验证（build 脚本内置）

`build_python_runtime.py` 的 `verify()` 用 `-s`（禁用用户站点）导入核心依赖 + `win32api/win32com/pywinauto/pyautogui`，全部通过。

### 4.2 运行时自包含验证

```
runtime-build/python.exe -s -c "import core.companion, core.api_server,
  communication.qq_client, core.multimodal_input, voice.tts_engine; ..."
→ APP_IMPORTS_OK
```

并确认 `sys.prefix` 指向 runtime-build、sys.path 不含 `C:\Python314` 与 `.venv`。

### 4.3 electron-builder 打包验证

`electron-builder --win --x64 --dir` 产物 `dist/win-unpacked/resources/python/` 布局正确：

- `runtime/python.exe` ✅
- `skills/local/*/run.py`（13+ 技能）✅
- `NapCat/NapCat.Shell/NapCatWinBootMain.exe` ✅
- `emotion/`、`persona/`、`scheduler/` ✅
- `.venv` 已移除 ✅

### 4.4 集成测试 + 生产模拟（核心验证）

运行 `scripts/verify_packaged_backend.py`，用隔离 `AERIE_DATA_DIR` + `PYTHONNOUSERSITE=1`（模拟干净机器）从打包目录 spawn 后端：

```
PASS: /api/health -> 200
PASS: /api/skills/list -> 18 skills
  sample: ['asr', 'computer-use', 'git-commit', 'img2img', 'markitdown', 'mineru']
RESULT: OK
```

### 4.5 rcedit 图标注入验证

`node scripts/post-build-rcedit.js` → `[rcedit] OK`，退出码 0。

## 五、待办与说明

- **完整 NSIS/Portable 安装器**：本次用 `--dir` 验证了 `win-unpacked`（安装器的打包源），完整安装器可用 `npm run build:win` 生成（含 `build:runtime` + `electron-builder --win --x64` + rcedit 三段，均已分别验证通过）。
- **ffmpeg 缺失**：`ffmpeg/ffmpeg.zip` 是无效文件（非 zip），且代码引用未解压的 `ffmpeg/ffmpeg-7.1-essentials_build/bin/ffmpeg.exe`。音频转码需补一个有效 ffmpeg 二进制（独立于本次打包逻辑，属资源缺口）。
- **weasyprint 需 GTK**：`weasyprint` 的 PDF 导出需 GTK 运行时（`libgobject-2.0-0.dll`），[doc_writer.py](file:///e:/Agent_reply/core/doc_writer.py) 已做惰性降级，无 GTK 时优雅降级，不影响其余功能。
- **体积**：运行时约 500 MB（含 markitdown/chromadb/onnxruntime/pandas 等重依赖），为功能完整性所需，未做瘦身。
