---
name: vercel-react
description: Vercel React 最佳实践 / Vercel React
provider_hint: text
read_only: true
kind: instruction
triggers:
- React 性能优化
- Next.js 优化
- React 最佳实践
- 优化这个组件
- 服务端组件
- React 代码审查
- 减少重渲染
- Next.js 项目
---

# Vercel React 最佳实践（vercel-react）

写或审 React / Next.js 代码时套用。核心是**减少客户端 JS、消除不必要的重渲染、把数据取在正确的地方**。每一条都对应可观测的性能收益，不是风格偏好，能说出收益才写进结论。

## 铁律

1. **默认服务端组件**：Next.js App Router 下组件默认是 Server Component，只有需要交互、状态或浏览器 API 时才加 `"use client"`，并把客户端边界压到最小。
2. **数据获取下沉到服务端**：能并行的数据用 `Promise.all`，不要瀑布式 await；避免"客户端 `useEffect` 里 fetch"导致首屏空白。
3. **消除串行等待**：独立请求并行发起，路由级用 `loading.tsx` 或 `Suspense` 给出加载态。
4. **状态就近**：状态放在真正需要它的最低层级，别一股脑提到顶层造成整树重渲染。
5. **列表 key 稳定**：用业务唯一 id 作 key，禁止用数组下标，否则重排会出错且性能差。

## 步骤

1. **划边界**：标出哪些组件必须 `"use client"`，把客户端组件尽量移到叶子节点。
2. **查数据流**：核对是否并行取数、是否有客户端请求、是否重复请求；能放服务端的全部上移。
3. **查重渲染**：定位大列表、高频输入引发的重渲染，用 `memo`、派生状态、`useMemo/useCallback`（仅在实测有收益时才加，不滥用）。
4. **查图片与资源**：用 `next/image` 做尺寸与懒加载，字体用 `next/font` 自托管。
5. **查动态导入**：体积大且非首屏必需的组件用 `dynamic(() => import(...))` 拆分。
6. **给结论**：只报**有证据**的问题，注明文件行号、原因、改法与预期收益。

## 输出形态

```
## 关键问题
| 文件:行 | 问题 | 影响 | 修法 |

## 重渲染热点
- 组件 X：因 … 导致每次 … 重渲染 → 改为 …

## 数据获取
- 当前：串行 3 个请求 → 改为 Promise.all 并行

## 修改后片段
（给出关键 diff，而非整文件重写）
```

## 反面例子（不要这样）

- 无脑给所有函数包 `useCallback`，没有实测收益反而增加复杂度。
- 在服务端组件顶上加 `"use client"`，把整棵树拖到客户端。
- 用数组下标做 key，列表重排时组件状态错位。
- 在客户端 `useEffect` 里串行 fetch 三个接口，首屏长时间白屏。
