# Debug Session: dynamic-island-expand-fail

**Status**: [OPEN]
**Created**: 2026-07-18
**Symptom**: 灵动岛胶囊可见，但点击/悬停/长按都无法展开，设置切换也无效
**Environment**: Windows + Electron

## Hypotheses

| #  | Hypothesis                            | Status  | Evidence |
| -- | ------------------------------------- | ------- | -------- |
| H1 | 鼠标穿透导致点击事件未传到渲染进程    | Pending | -        |
| H2 | 点击处理函数逻辑提前 return           | Pending | -        |
| H3 | 窗口大小调整 IPC 失败，窗口太小看不见 | Pending | -        |
| H4 | CSS 问题导致展开面板不可见            | Pending | -        |
| H5 | 初始化 JS 报错，事件未绑定            | Pending | -        |

## Instrumentation Points

- `di-init`: 初始化入口，确认 JS 加载
- `di-bind-events`: 事件绑定完成
- `di-capsule-click`: 胶囊被点击
- `di-expand-called`: expand 函数被调用
- `di-expand-state`: 状态变化
- `di-ipc-setsize`: IPC 调用 setSize
- `di-ipc-setsize-result`: IPC 返回结果
- `di-css-expanded`: 检查 CSS class 是否已添加
- `main-create-window`: 主进程创建灵动岛窗口
- `main-ipc-setsize`: 主进程收到 setSize IPC

## Instrumentation Status

**DONE** - 已在以下位置添加日志：

1. **渲染进程** (`dynamic-island.js`):

   - `init()`: 初始化全流程日志
   - `onCapsuleClick()`: 点击事件日志
   - `expand()`: 展开函数日志 + CSS class 检查
2. **主进程** (`main.js`):

   - `createDynamicIsland()`: 窗口创建日志
   - `island:set-size` IPC handler: IPC 调用日志

## How to Reproduce & Collect Logs

1. 重启应用
2. 找到灵动岛窗口，按 `Ctrl+Shift+I` 打开开发者工具
3. 切换到 Console 标签
4. 点击灵动岛胶囊，尝试展开
5. 截图或复制 Console 里所有带 `[DI-debug]` 前缀的日志

同时，主进程日志可以在启动应用的终端里看到。

## Logs

_(collected from debug server)_
