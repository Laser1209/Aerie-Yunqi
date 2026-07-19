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
- Pending: collect current packaged resources, backend health, Electron CDP snapshot, artifact list.
