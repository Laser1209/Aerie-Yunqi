---
name: web-artifacts-builder
description: 复杂 artifact 构建 / Web artifacts
provider_hint: text
read_only: true
kind: instruction
triggers:
- artifact
- 交互式小应用
- 带状态的小工具
- react 组件库
- 多组件页面
- 单文件应用
---
# 复杂 Artifact 构建（web-artifacts-builder）

需要交付**带状态、带交互、多组件**的网页小应用（不是一张静态展示页）时，套用这套工程化流程：React + Tailwind + shadcn/ui 风格组件，最终收敛成**一个自包含 HTML**。

## 什么时候用它

- 有真实交互状态：表单校验、列表增删改、筛选排序、图表联动
- 组件数 ≥ 5，或存在复用需求
- 用户要的是"一个能用的工具"，不是"一张好看的图"

只是静态展示页时走 frontend-design，不要动用这套重流程。

## 技术约束

- React 18 + Tailwind，产物内联，不依赖构建服务器
- 组件风格对齐 shadcn/ui（Button / Input / Card / Dialog / Table）
- 产物是**一个 HTML 文件**，双击即开
- 状态优先用 React 内置 hook；确实需要跨层共享才上 Context

## 步骤

1. 拆组件树：画出页面 → 区块 → 原子组件三层，标注每层各自持有什么状态
2. 定数据模型：把状态形状先写出来，避免边写边改
3. 定样式 token：复用手头设计系统；没有就一次定死色 / 间距 / 圆角，之后不随手加
4. 自底向上实现：原子组件 → 区块 → 页面
5. 每个交互都补齐加载 / 空 / 出错三态
6. 打包成单个 HTML，本地双击验证一遍再交付

## 自检

- 控制台无报错，没有未使用的 import
- 键盘可操作、焦点可见
- 缩到手机宽度不溢出
- 断网后功能完整

## 反面例子

- 交付五六个互相跳转的独立 HTML
- 把所有状态塞进一个巨型组件，改一处牵动全身
- 只有成功态，空列表和报错时一片空白
- 引一堆 CDN，离线直接白屏
