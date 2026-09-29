---
name: douyin-interact-creation
description: 抖音互动 H5 / Interact creation
provider_hint: text
read_only: true
kind: instruction
triggers:
- 互动空间
- 抖音互动 h5
- 互动小游戏 h5
- 可上传的 h5
- 离线 h5
---
# 抖音互动空间 H5 制作（douyin-interact-creation）

为"互动空间"制作可上传的互动 H5。最硬的约束：**产物是一个完全离线的 zip**，平台侧不允许任何外链请求。

## 交付物

- `index.html`：单文件，HTML / CSS / JS 全部内联
- 可选 `icon.png`：发布时的封面图
- 打包成 `.zip`，`index.html` 直接放在 zip 根目录

## 硬约束

1. 零网络依赖：不许 CDN、不许外链字体和图片、不许请求外部接口。需要素材就 base64 内联
2. 只用平台允许的 SDK 能力；不确定的能力先不做，别赌
3. 竖屏优先（9:16），控件避让底部安全区
4. 首屏在弱网或断网下必须可玩

## 步骤

1. 一句话说清玩法：玩家做什么、看到什么反馈、什么时候结束
2. 定状态机：ready → playing → settled，把每个状态的界面分别写清楚
3. 先写交互骨架，没有美术也要能跑通一遍
4. 再补视觉与动效（Canvas 或 CSS 都行，注意性能）
5. 自检离线可用后打包 zip
6. 打包完**解压再跑一遍**，确认 zip 内的相对路径没写错

## 自检清单

- 断网打开 `index.html`，玩法完整
- 无 404：所有资源都在 zip 里
- 触控和鼠标都能操作
- 控制台无报错

## 反面例子

- 用 CDN 引 React / Tailwind，平台侧直接加载失败
- zip 里多套了一层目录，平台找不到入口文件
- 只在桌面浏览器测过，移动端触控失效
