---
name: gsap
description: GSAP 动画 / GSAP
provider_hint: text
read_only: true
kind: instruction
triggers:
- 做动画
- 加动画
- GSAP 动画
- 时间轴动画
- 入场动画
- 缓动效果
- 滚动触发动画
- 序列动画
---

# GSAP 动画（gsap）

当你要用 GSAP 做页面动效——元素入场、时间轴编排、滚动触发、逐项错开——时走这份流程。产出应是一段可直接跑的 GSAP 代码，明确每步的起始状态、缓动、时长与并发关系。

## 铁律

1. **优先用 transform 与 opacity**：改 `x/y/scale/rotation/opacity` 走合成层不触发重排，改 `width/top/left` 会掉帧。
2. **`fromTo` 只在需要精确控制起止时用**：普通入场用 `from`，只需知道终点用 `to`，滥用 `fromTo` 会让代码啰嗦难维护。
3. **用 timeline 编排序列，不靠 delay 硬堆**：有先后关系就交给 `gsap.timeline()`，调节奏只改 position 参数，不要逐个算 delay 数字。
4. **缓动要有意图**：入场用 `power2.out`、退场用 `power2.in`、拟物回弹用 `back.out`，全部留默认 `linear` 往往最生硬。
5. **stagger 做列表错开**：列表/网格逐项动画用 `stagger: 0.05~0.1`，比手写循环更整齐也更好调。
6. **避免每帧改布局属性**：给会动的元素加 `will-change: transform`，动画结束后移除，别让它常驻。

## 步骤

1. **定时间轴结构**：先画出"先做什么、后做什么、哪些同时发生"，写成 timeline 的先后顺序。
2. **设起始状态**：需要从某状态进来的用 `from`，避免元素在动画开始前闪现（配合 CSS 初始态或 `gsap.set`）。
3. **写核心动画**：给出 `to/from/fromTo` 的 targets、属性、时长 `duration`、缓动 `ease`。
4. **挂到 timeline**：用位置参数控制节奏，`"+=0.2"` 表示上一个结束再等 0.2 秒，`"<"` 表示与上一个同时开始。
5. **加 stagger**：列表类动画补 `stagger`，必要时用 `stagger: { each, from: "start" }`。
6. **滚动触发**：需要随滚动播放时接 ScrollTrigger，声明 `trigger` 元素与 `start/end` 位置，不要自己监听 scroll 事件。
7. **验帧率**：在浏览器 Performance 面板录制，确认没有长任务、没有 layout thrashing。

## 输出形态

```
## 时间轴结构
- defaults: ease=power2.out, duration=0.6
- 1) .hero-title  from { y:40, opacity:0 }
- 2) .hero-sub    from { y:20, opacity:0 }  position="-=0.3"
- 3) .card        from { y:30, opacity:0, stagger:0.08 }  position="-=0.2"

## 滚动触发
- ScrollTrigger: trigger=.section, start="top 80%", end="bottom 60%"

## 代码片段
（可直接粘贴运行的 JS，附每段意图与缓动选择理由）
```

## 反面例子（不要这样）

- 给每个元素单独写 `delay: 0.1/0.3/0.5`，改一处节奏要重算全部。
- 用 `setTimeout` 串联动画，而不是 timeline。
- 动画 `top/left/width` 导致每帧重排卡顿。
- 所有缓动都留默认 `linear`，动效显得机械。
