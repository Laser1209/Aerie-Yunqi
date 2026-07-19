# debug-packaged-backend-resources

Status: [OPEN]

## Session
- sessionId: packaged-backend-resources
- Objective: 继续修复并验证 Aerie · 云栖安装包的本地 Python 后端依赖与资源打包问题。

## Constraints
- Steps 1-4 不修改业务逻辑。
- 若需要改动现有代码，第一类改动仅允许为运行时证据采集/日志插桩。
- 修复完成后需对比 pre-fix / post-fix 证据。

## Hypotheses
1. packaged-python-missing-modules: 安装包 `resources/python` 缺少后端顶层模块，导致 `ModuleNotFoundError`。
2. packaged-venv-missing: 安装包缺少 `.venv/Scripts/python.exe`，Electron 无法 spawn Python 后端。
3. electron-path-resolution: packaged 模式下 `main.js` 计算 `PYTHON_ROOT/PY_MAIN/PYTHON_EXE` 错误。
4. installer-artifact-incomplete: NSIS/portable 产物没有基于已验证的 `win-unpacked` 目录正确封装。
5. electron-ui-backend-bridge: 后端已启动但渲染进程未正确收到健康状态，导致 UI 仍显示离线。

## Evidence Log
- Pre-fix evidence: manually starting packaged Python backend from `dist-v1/win-unpacked/resources/python` failed with `ModuleNotFoundError: No module named 'communication'`, proving hypothesis 1.
- Fix applied: package runtime source now includes `communication/**`, `knowledge/**`, `memory/**`, `emotion/**`, `persona/**`, `scheduler/**`, selected `tools/*`, `skills/local`, `skills/data`, `douyin-mcp/src/douyin_creator_mcp/**`, and `NapCat/NapCat.Shell/**`.
- Data hygiene: package filters continue excluding `data/**`, `logs/**`, `NapCat/NapCat.Shell/cache/**`, `NapCat/NapCat.Shell/config/**`, `douyin-mcp/data/**`, and `douyin-mcp/.env`.
- Post-fix resource evidence: final artifacts exist at `electron/dist-final/Aerie · 云栖-0.1.0-beta.1-Setup.exe` (187.4 MB) and `electron/dist-final/Aerie · 云栖-0.1.0-beta.1-portable.exe` (187.2 MB).
- Post-fix resource probes: `.venv/Scripts/python.exe`, `communication/message.py`, `knowledge/kb.py`, `memory/memory_store.py`, and `NapCat/NapCat.Shell/NapCatWinBootMain.exe` all exist in `dist-final/win-unpacked/resources/python`.
- Post-fix backend evidence: `GET http://127.0.0.1:7890/api/health` returned HTTP 200 with `status: healthy` and backend component healthy.
- Post-fix Electron evidence: launched packaged app with `--remote-debugging-port=9222`; CDP tab list showed `Aerie · 云栖` and renderer text included `后端已连接`.

## Hypothesis Results
1. packaged-python-missing-modules: CONFIRMED pre-fix, FIXED post-fix.
2. packaged-venv-missing: REJECTED post-fix, `.venv/Scripts/python.exe` exists.
3. electron-path-resolution: REJECTED post-fix, packaged app spawned backend from `resources/python/main.py` and health returned 200.
4. installer-artifact-incomplete: REJECTED post-fix, setup and portable artifacts exist.
5. electron-ui-backend-bridge: REJECTED post-fix, Electron UI displayed `后端已连接`.
