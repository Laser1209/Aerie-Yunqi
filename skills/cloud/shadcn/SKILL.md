---
name: shadcn
description: shadcn/ui 组件 / shadcn
provider_hint: text
read_only: true
kind: instruction
triggers:
- shadcn 组件
- 用 shadcn
- 加个组件
- 装个组件
- 用 shadcn/ui
- 加个弹窗组件
- 表单组件
- 组件库
---

# shadcn/ui 使用规范（shadcn）

在 React 项目里用 shadcn/ui 构建界面时套用。shadcn 不是普通 npm 组件包，而是**把源码复制进项目**的组件集合：它归你所有、可自由改，因此要按"项目自己的组件"来维护，遵循它的 registry 与 CLI 约定。

## 铁律

1. **先查 registry 再加组件**：用 CLI（`npx shadcn@latest add <组件>`）添加，不要手写复制粘贴，否则样式版本会与项目里其余组件脱节。
2. **组件是源码，归你维护**：加进来后可以改，但改动要有限度；能通过 props 或组合解决的，不要直接改组件内部。
3. **一律用语义 token**：颜色写 `bg-background`、`text-foreground`、`border-border` 这类语义类名，禁止在组件里写死 `#hex`，否则换主题就崩。
4. **组合优先，不新增变体**：`Dialog` 用 `DialogTrigger/Content/Header/Title` 拼，别为了一个场景给组件加一堆布尔参数。
5. **复用而非重造**：先看 registry 里已有哪些组件，别自己再造一个 Button。

## 步骤

1. **确认初始化**：检查 `components.json` 是否存在，别名（`@/components`）、样式与 Tailwind 配置是否就绪，没有先 init。
2. **按需添加**：只 add 当前真正需要的组件，避免一次性灌入整套导致体积膨胀与样式污染。
3. **用语义 token 组合**：按官方文档给的 Compound 组合结构拼装，保持与示例一致的层级。
4. **接业务数据**：通过 props 传数据与回调，业务逻辑留在页面/容器组件，shadcn 组件保持"哑组件"。
5. **微调走 className**：需要自定义样式时用 `className` + Tailwind 工具类，或调整主题变量，不改组件源码。
6. **校验状态**：确认深色模式、焦点态、禁用态都正常（用语义 token 时理论上自动生效）。
7. **清理**：删掉未使用的组件文件与依赖，避免"僵尸组件"越积越多。

## 输出形态

```
## 要用的组件
- Dialog / Input / Button（来自 registry，已 add）

## 组合结构
（展示 Compound 组合的 JSX，使用语义 token 类名）

## 主题变量
（如需新增 token，在 globals.css 以 CSS 变量形式定义）

## 校验结果
- 深色模式：OK  焦点态：OK  禁用态：OK
```

## 反面例子（不要这样）

- 手动从网上复制组件代码，版本与项目其余组件对不上。
- 在组件里写死 `#3b82f6`，换主题时这个蓝色纹丝不动。
- 为了一个页面去改 shadcn 组件源码、塞进业务参数。
- 一次性 add 全部组件，项目里堆满用不到的文件。
