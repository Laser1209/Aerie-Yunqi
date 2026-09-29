---
name: vercel-composition
description: Vercel 组合模式 / Vercel composition
provider_hint: text
read_only: true
kind: instruction
triggers:
- 组件组合
- 复合组件
- 组合模式
- render props
- 怎么写组件
- 组件设计模式
- 组件复用
- 重构组件 API
---

# React 组合模式（vercel-composition）

当组件开始变复杂、出现一堆 props 变体时，用组合模式重构。核心思想：**用组合代替配置**——把"传一堆 flag props"改成"把子元素拼进去"。参考 React 19 / Radix / shadcn 的成熟做法，不要自创一套。

## 铁律

1. **组合优于配置**：当一个组件出现 `showHeader`、`variant="withIcon"` 这类布尔或枚举 props 时，说明它该拆成可组合的多个子组件。
2. **Compound 组件共享隐式状态**：用 Context 把父组件状态隐式传给子组件（如 `Tabs` + `TabList` + `Tab` + `TabPanel`），调用方无需手动传状态。
3. **插槽用节点而非字符串**：自定义内容通过 `children` 或 `ReactNode` 类型的具名 props 传入，而不是传字符串再在内部 if 分支渲染。
4. **Context 只放必要状态**：Context 放真正要跨层共享的数据，避免把整个 store 塞进去导致无谓重渲染。
5. **受控/非受控二选一**：要么受控（`value` + `onChange`），要么非受控（`defaultValue` + 内部状态），不要两者都做一半导致状态打架。

## 步骤

1. **识别坏味道**：找出 props 数量膨胀、变体分支多、调用方需要了解内部结构的组件。
2. **拆骨架**：把容器与各语义部分拆成 `Parent` / `Parent.Sub` 形式，定义每部分职责。
3. **接 Context**：由父组件提供状态，子组件从 Context 读取，保证调用方零配置组装。
4. **定 API**：明确哪些是必填插槽、哪些可省略，给出默认行为。
5. **保证可组合性**：允许嵌套、允许只放部分子组件、允许传入自定义节点。
6. **写示例**：给出"最简用法"与"完全自定义用法"两个例子，证明 API 够用。
7. **回归检查**：确认受控/非受控行为一致，卸载时清理订阅，避免内存泄漏。

## 输出形态

```
## 重构前（坏味道）
（展示 props 膨胀的旧 API）

## 重构后（组合式 API）
（父组件 + 子组件 + Context 的代码）

## 用法示例
（最简用法 / 自定义用法）

## 迁移说明
- 旧 API → 新 API 的对应关系（不保留兼容层）
```

## 反面例子（不要这样）

- 用 `renderHeader`、`renderFooter` 拼出五个插槽，比组合还难懂。
- 把所有状态塞进一个大 Context，任何改动都让全树重渲染。
- 一边接受受控的 `value`，一边又用内部 state 覆盖，出现状态不同步。
- 用数组下标当列表 key，重排后组件状态错位。
