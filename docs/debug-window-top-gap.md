# Debug Session: window-top-gap

- 状态：[CLOSED]
- 现象：Electron 主窗口顶部出现约 20px 的灰色程序内区域，页面内容整体看似下移
- 预期：`#app` 从视口 y=0 开始渲染，顶部未被页面覆盖的区域保持透明

## 根因

`electron/src/renderer/index.html` 中 `<body>` 顶部的内联 SVG sprite 默认是内联元素，位于块级 `#app` 之前，导致生成匿名行盒，把 `#app` 整体下移约一行行高（约 20.67px）。透明 + acrylic 窗口让这段空白显示为程序内灰色区域。

## 证据

- pre-fix：`body.top = 0`，`app.top = 20.666667938232422`
- 主进程 `contentOffsetY = 0`，排除 Electron 原生窗口标题栏/客户区偏移
- post-fix：`app.top = 0`，修复有效

## 修复

在 SVG sprite 的内联样式中增加 `display:none`，使其不参与布局流，但 `<defs>/<symbol>` 仍可通过 `use` 引用。

修改位置：
- electron/src/renderer/index.html:18

## 验证结果

| 假设 | 状态 | 说明 |
|------|------|------|
| A：acrylic 材质留白 | 否 | contentBounds 无偏移；但它是视觉放大因素 |
| B：圆角视觉空隙 | 否 | 实际是 20px 行盒偏移 |
| C：运行旧打包产物 | 否 | loadedUrl 指向 src/renderer/index.html |
| D：WebContents 视口原点下移 | 否 | contentOffsetY = 0 |
| E：页面顶部匿名行盒 | 是 | SVG 内联元素 + block 级 #app 组合导致 |

## 清理

- 已移除 `electron/src/main.js` debug 插桩
- 已移除 `electron/src/renderer/js/app.js` debug 插桩
- 已停止 debug server
