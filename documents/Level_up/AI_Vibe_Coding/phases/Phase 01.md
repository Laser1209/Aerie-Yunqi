---
title: Phase 01 - 主动消息 P0 修复
kind: phase
phase: Phase 01
status: completed
tags: [aerie, phase, phase01]
---
# Phase 01：主动消息 P0 修复
> [!info] 执行边界
> 只按获批实施计划执行；当前阶段未通过验收时停止后续阶段。

## 目标
统一 trigger、生命周期、Desire 属性与独立 Delivery；保持兼容、可观测与可回滚。

## 非目标
不整体重写 Pipeline；不删除旧表或旧文件；不创建平行 v2；不复制疑似凭据。

## 依赖
- Phase 00
- [[05_Feature_Flag与回滚矩阵]]、[[06_AI_Vibe_Coding批次规约]]

## 当前代码证据
- [push_scheduler.py](file:///E:/Agent_reply/core/push_scheduler.py)
- [companion.py](file:///E:/Agent_reply/core/companion.py)
- [pipeline.py](file:///E:/Agent_reply/core/pipeline.py)
- [api_server.py](file:///E:/Agent_reply/core/api_server.py)

## 文件范围
- 计划修改或演进：`core/push_scheduler.py`、`core/companion.py`
- 新文件仅限计划列明的模块、迁移和测试。
- 执行任务：[[Task 01-baseline]]

## 数据/API 合同
- Feature Flag：`proactive_delivery_v2`。
- 统一 trigger、生命周期、Desire 属性与独立 Delivery。
- ID、状态、sequence、幂等键和所有权边界必须可审计。
- 涉及迁移时支持 backup、dry-run、checksum、幂等、cursor、断点续跑与守恒。

## TDD 步骤
1. 先新增失败测试覆盖主路径、异常路径与回滚路径。
2. 实现最小变更使测试通过，保留兼容适配器。
3. 运行受影响模块测试与完整回归。
4. 验证 Flag 关闭、迁移/协议恢复和 Evidence 脱敏。

## 验收
- [x] Cron、手动、Desire、Idle、quiet、exempt、force 与 QQ 断线通过
- [x] Feature Flag 关闭恢复旧 QQ-only 路径，V2 本地持久化仅在开关启用时生效
- [x] 聊天页过滤非聊天事件；Delivery Evidence 仅记录场景与通道状态，不包含正文、个人数据或凭据

## 回滚
关闭 `proactive_delivery_v2`，恢复备份或旧读路径；保留新表、元数据、Outbox、旧表和旧文件。

## 指标
成功率、延迟、重复计数、守恒差异、恢复时间和回滚耗时；禁止记录消息正文、个人数据或凭据。

## 提交边界
只提交 Phase 01 相关源码、测试、迁移与文档；不混入无关重构、格式化或构建产物。

## Evidence
- 2026-07-20 重新审计：Phase 1 专项 `19 passed, 4 warnings in 1.28s`。
- Phase 0 + Phase 1 + API + Pipeline 当前定向回归：`83 passed, 4 warnings in 2.58s`。
- 当前完整 Python 回归：`353 passed, 6 warnings in 9.99s`，历史 `10 failed` 已清零。
- Electron `node --check`：`chat.js`、`dynamic-island.js`、`main.js`、`preload.js` 全部通过。
- 自动化重新覆盖 V2 三通道、QQ 离线本地降级、quiet、系统通知开关，以及 Flag 关闭的 QQ-only 与离线暂停旧路径。
- 本轮仅记录场景与通道合同，不记录主动消息正文、账号或凭据；`rollback_ready=true`。
- [实施计划](file:///E:/Agent_reply/documents/Level_up/实施计划.md)
- [push_scheduler.py](file:///E:/Agent_reply/core/push_scheduler.py)
- [companion.py](file:///E:/Agent_reply/core/companion.py)
- [api_server.py](file:///E:/Agent_reply/core/api_server.py)
- [chat.js](file:///E:/Agent_reply/electron/src/renderer/js/chat.js)
- [test_phase1_proactive_baseline.py](file:///E:/Agent_reply/tests/test_phase1_proactive_baseline.py)
- [[90_全局验收清单]] · [[92_回滚演练]]
