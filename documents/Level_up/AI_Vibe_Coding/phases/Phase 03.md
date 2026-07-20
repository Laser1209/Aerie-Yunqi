---
title: Phase 03 - Conversation、Turn、Message、Request 四表与回填
kind: phase
phase: Phase 03
status: in_progress
tags: [aerie, phase, phase03]
---
# Phase 03：Conversation、Turn、Message、Request 四表与回填
> [!info] 执行边界
> 只按获批实施计划执行；当前阶段未通过验收时停止后续阶段。

## 目标
四表、状态机、response_group_id、sequence 与幂等回填；保持兼容、可观测与可回滚。

## 非目标
不整体重写 Pipeline；不删除旧表或旧文件；不创建平行 v2；不复制疑似凭据。

## 依赖
- Phase 02
- [[05_Feature_Flag与回滚矩阵]]、[[06_AI_Vibe_Coding批次规约]]

## 当前代码证据
- [database.py](file:///E:/Agent_reply/core/database.py)
- [pipeline.py](file:///E:/Agent_reply/core/pipeline.py)
- [pipeline.py](file:///E:/Agent_reply/core/pipeline.py)
- [api_server.py](file:///E:/Agent_reply/core/api_server.py)

## 文件范围
- 计划修改或演进：`core/database.py`、`core/pipeline.py`
- 新文件仅限计划列明的模块、迁移和测试。
- 执行任务：[[Task 03-baseline]]

## 数据/API 合同
- Feature Flag：`conversation_model_v1`。
- 四表、状态机、response_group_id、sequence 与幂等回填。
- ID、状态、sequence、幂等键和所有权边界必须可审计。
- 涉及迁移时支持 backup、dry-run、checksum、幂等、cursor、断点续跑与守恒。

## TDD 步骤
1. 先新增失败测试覆盖主路径、异常路径与回滚路径。
2. 实现最小变更使测试通过，保留兼容适配器。
3. 运行受影响模块测试与完整回归。
4. 验证 Flag 关闭、迁移/协议恢复和 Evidence 脱敏。

## 实施进展
- 首批 Green：`004_conversation_model` 创建四表规范化骨架；随后以独立 `005_conversation_backfill` 保持 004 checksum 稳定并执行保守回填。
- 自动化守恒：记录数、正文、附件、角色顺序、Actor/Channel 原值、QQ/Desktop 隔离和重复运行幂等已在隔离数据库验证。
- 迁移安全：最小旧库缺少附件/身份列时 005 先补可空列；未知身份保持 NULL；缺少 `chat_log` 时显式失败。
- live 双写：`ConversationRepository` 支持 SQLite connection 与 `Database.connection()` 提供者；`Companion` 按 `conversation_model_v1` 注入；FULL/BASIC 仅在 legacy 用户行与全部助手分段成功后镜像一次完整 Turn。
- 兼容路径：规范镜像异常只记录错误，不中断已成功的 legacy 回复、事件或投递；legacy 持久化失败时不制造孤立规范 Turn。
- 本批 TDD Evidence：先观察 `Pipeline.__init__()` 不接受 Repository 的 Red，以及 legacy 失败时仍镜像的行为 Red；最小实现后 Phase 3 + Pipeline 定向回归 `28 passed`，修改文件诊断为空。
- 历史 Evidence：相关回归 `51 passed, 4 warnings`；完整 Python `334 passed, 6 warnings`。
- 当前未对真实生产库执行迁移，且完整 Turn 历史读取、真实 Flag 回滚、cursor 与迁移回滚尚未完成，Phase 03 保持 `in_progress`。

## 验收
- [ ] 记录、附件、角色顺序和 Channel 守恒
- [ ] Feature Flag 关闭恢复旧路径且不丢新数据
- [ ] 不产生重复副作用、历史串线或敏感值泄漏

## 回滚
关闭 `conversation_model_v1`，恢复备份或旧读路径；保留新表、元数据、Outbox、旧表和旧文件。

## 指标
成功率、延迟、重复计数、守恒差异、恢复时间和回滚耗时；禁止记录消息正文、个人数据或凭据。

## 提交边界
只提交 Phase 03 相关源码、测试、迁移与文档；不混入无关重构、格式化或构建产物。

## Evidence
- [实施计划](file:///E:/Agent_reply/.trae/documents/Aerie_AI_Vibe_Coding_全面升级实施计划.md)
- [database.py](file:///E:/Agent_reply/core/database.py)
- [pipeline.py](file:///E:/Agent_reply/core/pipeline.py)
- [[90_全局验收清单]] · [[92_回滚演练]]
