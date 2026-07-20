---
title: Phase 00 - 安全基线、迁移器与标识合同
kind: phase
phase: Phase 00
status: completed
tags: [aerie, phase, phase00]
---
# Phase 00：安全基线、迁移器与标识合同
> [!info] 执行边界
> 只按获批实施计划执行；当前阶段未通过验收时停止后续阶段。

## 目标
迁移账本、EventEnvelope 与 Feature Flag 审计；保持兼容、可观测与可回滚。

## 非目标
不整体重写 Pipeline；不删除旧表或旧文件；不创建平行 v2；不复制疑似凭据。

## 依赖
- 无前置阶段
- [[05_Feature_Flag与回滚矩阵]]、[[06_AI_Vibe_Coding批次规约]]

## 当前代码证据
- [database.py](file:///E:/Agent_reply/core/database.py)
- [chat_events.py](file:///E:/Agent_reply/core/chat_events.py)
- [pipeline.py](file:///E:/Agent_reply/core/pipeline.py)
- [api_server.py](file:///E:/Agent_reply/core/api_server.py)

## 文件范围
- 计划修改或演进：`core/database.py`、`core/chat_events.py`
- 新文件仅限计划列明的模块、迁移和测试。
- 执行任务：[[Task 00-baseline]]

## 数据/API 合同
- Feature Flag：`migration_framework_v1`。
- 迁移账本、EventEnvelope 与 Feature Flag 审计。
- ID、状态、sequence、幂等键和所有权边界必须可审计。
- 涉及迁移时支持 backup、dry-run、checksum、幂等、cursor、断点续跑与守恒。

## TDD 步骤
1. 先新增失败测试覆盖主路径、异常路径与回滚路径。
2. 实现最小变更使测试通过，保留兼容适配器。
3. 运行受影响模块测试与完整回归。
4. 验证 Flag 关闭、迁移/协议恢复和 Evidence 脱敏。

## 验收
- [x] 空库、现有库、重复运行和中断续跑通过
- [x] Feature Flag 关闭恢复旧路径且不丢新数据
- [x] 不产生重复副作用、历史串线或敏感值泄漏

## 回滚
关闭 `migration_framework_v1`，恢复备份或旧读路径；保留新表、元数据、Outbox、旧表和旧文件。

## 指标
成功率、延迟、重复计数、守恒差异、恢复时间和回滚耗时；禁止记录消息正文、个人数据或凭据。

## 提交边界
只提交 Phase 00 相关源码、测试、迁移与文档；不混入无关重构、格式化或构建产物。

## Evidence
- 2026-07-20 重新审计：Phase 0 基线专项 `14 passed in 0.30s`。
- 2026-07-20 当前完整 Python 回归：`353 passed, 6 warnings in 9.99s`，历史 `10 failed` 已清零。
- Flag 关闭与恢复演练：`migration_framework_v1=false` 时恢复后的旧 `chat_log` 为 `1/1` 行，`migration_ledger` 表数量为 `0`，`quick_check=ok`，数据损失 `0`，演练总耗时 `0.060643s`。
- 历史 TDD Red/Green 过程由 [[Task 00-baseline]] 记录；本次为阶段推进前复验，不倒写或伪造历史失败输出。
- 本轮仅使用脱敏占位内容，未记录消息正文、个人数据或凭据。
- [实施计划](file:///E:/Agent_reply/documents/Level_up/实施计划.md)
- [database.py](file:///E:/Agent_reply/core/database.py)
- [chat_events.py](file:///E:/Agent_reply/core/chat_events.py)
- [test_phase0_baseline.py](file:///E:/Agent_reply/tests/test_phase0_baseline.py)
- [[90_全局验收清单]] · [[92_回滚演练]]
