---
name: hyperframes-registry
description: HyperFrames 块注册 / HF registry
provider_hint: text
read_only: true
kind: instruction
triggers:
- hyperframes 组件
- hyperframes 块
- hyperframes-registry
- 装个 hyperframes
- 引入 hyperframes
- hyperframes 模板组件
- hyperframes 注册
---

# HyperFrames 块注册（hyperframes-registry）

当你要往 HyperFrames 项目里安装并接入现成的块或组件（字幕、转场、动效等）时走这份流程。产出是**装好且已接入**的组件，以及它在 composition 里的正确用法。

## 铁律

1. **先查 registry 再自己写**：需要的效果先看 registry 有没有现成组件，有就装，别重复造。
2. **只装当前需要的**：不要为了"以后可能用"预装一堆组件，既增加体积也增加维护面。
3. **按文档给的接入方式接**：组件有其约定的挂载点与参数，照文档接，不要自己改内部实现。
4. **版本对齐**：组件的兼容版本要与本项目依赖对得上，避免接口变更后行为异常。
5. **接入即验证**：装完立刻在 composition 里用一次，确认渲染无报错、效果符合预期。
6. **记录来源**：把组件名与版本记下来，方便后续升级和排查。

## 步骤

1. **明确需求**：要的是哪类效果（字幕样式、转场、粒子背景等），用一个具体例子的标准描述。
2. **检索 registry**：按关键词找候选组件，对比描述与截图选最合适的。
3. **确认依赖**：看它的兼容版本、是否需要额外的运行时或素材。
4. **安装**：按 registry 给的方式装到项目里。
5. **接入 composition**：把组件放进对应场景与时间点，填好参数。
6. **预览验证**：渲染或预览一次，确认无报错且效果正确。
7. **登记**：在项目文档里记下组件名与版本。

## 输出形态

```
## 需求
- 需要"逐字出现的字幕动效"

## 选型
- 组件：<name>@<version>  理由：自带逐字动画、支持时间戳输入

## 安装
- 命令：<install command>

## 接入
- 位置：场景2  参数：{ text, start, stagger }

## 验证
- 预览结果：逐字出现，无报错  ✓
```

## 反面例子（不要这样）

- 不看 registry 直接手写一个已有的字幕组件。
- 一次性装十几个组件，最后大部分没用到。
- 绕过组件公开参数去改它的内部文件，升级即冲突。
- 装完不验证，等到渲染才发现参数填错、报错。
