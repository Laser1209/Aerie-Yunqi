# 重写开发启动程序计划

## 仓库调研结论

当前项目根目录已有两个开发启动入口：

- `start-dev.bat`：可见控制台启动入口，当前会检查部分 Python 依赖、全局强杀 `python.exe/pythonw.exe`，然后进入 `electron` 目录执行 `npm start`。
- `start-dev-silent.vbs`：静默启动入口，当前只检查 Electron 命令是否存在，然后隐藏执行 `npm start`。

Electron 项目启动脚本位于 `electron/package.json`，`start` 命令为：

```json
"start": "electron ."
```

后端由 Electron 主进程自动启动，因此启动器不需要单独启动 Python 后端。当前主要问题是：

1. `start-dev.bat` 会强制杀掉系统所有 Python 进程，风险较高。
2. 静默启动缺少 Python 虚拟环境、requirements、Electron 依赖等前置检查。
3. 静默启动没有日志，失败时很难排查。
4. 两个启动入口逻辑不一致，容易出现“bat 能启动、vbs 启动失败”的情况。

## 需要编辑的文件

1. `start-dev.bat`
   - 重写为统一开发启动脚本。
   - 保留可见控制台输出。
   - 增加更清晰的环境检查和失败提示。

2. `start-dev-silent.vbs`
   - 改为静默调用 `start-dev.bat`。
   - 将输出重定向到 `logs/start-dev.log`。
   - 不重复实现依赖检查逻辑。

## 修改步骤

### 1. 重写 `start-dev.bat`

目标行为：

1. 切换到脚本所在根目录。
2. 检查 `.venv\Scripts\python.exe` 是否存在。
   - 不存在时提示用户先创建虚拟环境。
   - 不擅自创建 venv，避免误用错误 Python 版本。
3. 检查 `requirements.txt` 是否存在。
4. 检查核心 Python 依赖。
   - 缺失时执行 `.venv\Scripts\python.exe -m pip install -r requirements.txt`。
5. 检查 `electron\package.json` 是否存在。
6. 检查 `electron\node_modules\.bin\electron.cmd` 是否存在。
   - 不存在时进入 `electron` 执行 `npm install`。
7. 进入 `electron` 执行 `npm start`。
8. 如果启动命令返回错误码，显示错误码并暂停。

明确不做：

- 不再全局 `taskkill python.exe/pythonw.exe`。
- 不单独启动 Python 后端。
- 不新增额外启动文件。

### 2. 重写 `start-dev-silent.vbs`

目标行为：

1. 定位项目根目录。
2. 确保 `logs` 目录存在。
3. 检查 `start-dev.bat` 是否存在。
4. 通过隐藏窗口执行：

```bat
cmd.exe /c ""<root>\start-dev.bat" > "<root>\logs\start-dev.log" 2>&1"
```

5. 失败时只弹出必要错误框。

## 风险处理

1. **依赖安装失败**
   - bat 会保留控制台并输出错误码。
   - silent vbs 会把错误写入 `logs/start-dev.log`。

2. **Electron 未安装**
   - 自动执行 `npm install`。
   - 如果 `npm` 不存在，控制台或日志会显示对应错误。

3. **后端端口残留**
   - 本次不使用全局杀 Python 的方式处理。
   - 如果后端端口残留，应由 Electron 主进程/后端健康检查逻辑处理，避免误杀其他程序。

4. **中文路径/空格路径**
   - bat 和 vbs 全部使用引号包裹路径。

## 验证方式

1. 执行 `start-dev.bat`，确认能进入 Electron 启动流程。
2. 执行 `start-dev-silent.vbs`，确认不弹出控制台。
3. 检查 `logs/start-dev.log` 是否生成。
4. 确认没有使用 `taskkill /f /im python.exe` 这类全局杀进程逻辑。
