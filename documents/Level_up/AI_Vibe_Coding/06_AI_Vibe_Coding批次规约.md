---
title: AI Vibe Coding 批次规约
kind: control
tags: [aerie, tdd, workflow]
---
# AI Vibe Coding 批次规约
> [!important] 顺序
> 每批先重读计划与对应阶段笔记；先失败测试，再最小实现；当前批次失败立即停止。

- 运行受影响模块测试与完整回归。
- 验证迁移 dry-run、幂等、cursor、守恒与回滚。
- 检查日志、Fixture、截图和 Evidence 无凭据、正文或多余个人数据。
- 只提交当前阶段文件，不混入格式化、无关重构或构建产物。
