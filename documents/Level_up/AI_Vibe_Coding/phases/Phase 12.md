---
title: Phase 12 - 确定性世界、关系与 SelfModel
kind: phase
phase: Phase 12
status: planned
tags: [aerie, phase, phase12]
---
# Phase 12：确定性世界、关系与 SelfModel
> [!info] 执行边界
> 只按获批实施计划执行；当前阶段未通过验收时停止后续阶段。

## 目标
确定性 Tick、Action Registry、关系与 SelfModel；保持兼容、可观测与可回滚。

## 非目标
不整体重写 Pipeline；不删除旧表或旧文件；不创建平行 v2；不复制疑似凭据。

## 依赖
- Phase 11
- [[05_Feature_Flag与回滚矩阵]]、[[06_AI_Vibe_Coding批次规约]]

## 当前代码证据
- [companion.py](file:///E:/Agent_reply/core/companion.py)
- [context_builder.py](file:///E:/Agent_reply/core/context_builder.py)
- [pipeline.py](file:///E:/Agent_reply/core/pipeline.py)
- [api_server.py](file:///E:/Agent_reply/core/api_server.py)

## 文件范围
- 计划修改或演进：`core/companion.py`、`core/context_builder.py`
- 新文件仅限计划列明的模块、迁移和测试。
- 执行任务：[[Task 12-baseline]]

## 数据/API 合同
- Feature Flag：`world_inprocess_v1`。
- 确定性 Tick、Action Registry、关系与 SelfModel。
- ID、状态、sequence、幂等键和所有权边界必须可审计。
- 涉及迁移时支持 backup、dry-run、checksum、幂等、cursor、断点续跑与守恒。

## TDD 步骤
1. 先新增失败测试覆盖主路径、异常路径与回滚路径。
2. 实现最小变更使测试通过，保留兼容适配器。
3. 运行受影响模块测试与完整回归。
4. 验证 Flag 关闭、迁移/协议恢复和 Evidence 脱敏。

## 验收
- [ ] 同 seed/时钟同快照，关系按 Persona 隔离且可重置
- [ ] Feature Flag 关闭恢复旧路径且不丢新数据
- [ ] 不产生重复副作用、历史串线或敏感值泄漏

## 回滚
关闭 `world_inprocess_v1`，恢复备份或旧读路径；保留新表、元数据、Outbox、旧表和旧文件。

## 指标
成功率、延迟、重复计数、守恒差异、恢复时间和回滚耗时；禁止记录消息正文、个人数据或凭据。

## 提交边界
只提交 Phase 12 相关源码、测试、迁移与文档；不混入无关重构、格式化或构建产物。

## Evidence
- [实施计划](file:///E:/Agent_reply/.trae/documents/Aerie_AI_Vibe_Coding_全面升级实施计划.md)
- [companion.py](file:///E:/Agent_reply/core/companion.py)
- [context_builder.py](file:///E:/Agent_reply/core/context_builder.py)
- [[90_全局验收清单]] · [[92_回滚演练]]
