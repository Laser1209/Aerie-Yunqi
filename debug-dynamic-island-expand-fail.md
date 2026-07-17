# Debug Session: dynamic-island-expand-fail

**Status**: [OPEN]
**Created**: 2026-07-18
**Symptom**: 灵动岛胶囊可见，但点击/悬停/长按都无法展开，设置切换也无效
**Environment**: Windows + Electron

## Hypotheses

| # | Hypothesis | Status | Evidence |
|---|-----------|--------|----------|
| H1 | 鼠标穿透导致点击事件未传到渲染进程 | Pending | - |
| H2 | 点击处理函数逻辑提前 return | Pending | - |
| H3 | 窗口大小调整 IPC 失败，窗口太小看不见 | Pending | - |
| H4 | CSS 问题导致展开面板不可见 | Pending | - |
| H5 | 初始化 JS 报错，事件未绑定 | Pending | - |

## Instrumentation Points

- `di-init`: 初始化入口，确认 JS 加载
- `di-bind-events`: 事件绑定完成
- `di-capsule-click`: 胶囊被点击
- `di-expand-called`: expand 函数被调用
- `di-expand-state`: 状态变化
- `di-ipc-setsize`: IPC 调用 setSize
- `di-ipc-setsize-result`: IPC 返回结果
- `di-css-expanded`: 检查 CSS class 是否已添加

## Logs

_(collected from debug server)_
