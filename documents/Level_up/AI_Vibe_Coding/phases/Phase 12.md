---
title: Phase 12 - 确定性世界、关系与 SelfModel
kind: phase
phase: Phase 12
status: done
progress_note: "2026-07-21: Phase 12 domain baseline is green for deterministic world tick, action registry fallback, persona-scoped relationship reset, computed SelfModel, FULL-only context injection, optional Pipeline providers, and flag-off rollback."
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
- [world_simulation.py](file:///E:/Agent_reply/core/world_simulation.py)
- [action_registry.py](file:///E:/Agent_reply/core/action_registry.py)
- [relationship_engine.py](file:///E:/Agent_reply/core/relationship_engine.py)
- [self_model.py](file:///E:/Agent_reply/core/self_model.py)
- [world_port.py](file:///E:/Agent_reply/core/world_port.py)
- [companion.py](file:///E:/Agent_reply/core/companion.py)
- [context_builder.py](file:///E:/Agent_reply/core/context_builder.py)
- [pipeline.py](file:///E:/Agent_reply/core/pipeline.py)
- [test_phase12_world_domain.py](file:///E:/Agent_reply/tests/test_phase12_world_domain.py)

## 文件范围
- 已修改或演进：`core/companion.py`、`core/context_builder.py`、`core/pipeline.py`、`core/world_port.py`
- 已新增：`core/world_simulation.py`、`core/action_registry.py`、`core/relationship_engine.py`、`core/self_model.py`、`tests/test_phase12_world_domain.py`
- 未创建 world.db、Sidecar、图片候选或真实投递副作用。
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
- [x] 同 seed/时钟同快照，关系按 Persona 隔离且可重置
- [x] Feature Flag 关闭恢复旧路径且不丢新数据
- [x] 不产生重复副作用、历史串线或敏感值泄漏

## 回滚
关闭 `world_inprocess_v1`，恢复备份或旧读路径；保留新表、元数据、Outbox、旧表和旧文件。

## 指标
成功率、延迟、重复计数、守恒差异、恢复时间和回滚耗时；禁止记录消息正文、个人数据或凭据。

## 提交边界
只提交 Phase 12 相关源码、测试、迁移与文档；不混入无关重构、格式化或构建产物。

## Evidence
- [实施计划](file:///E:/Agent_reply/.trae/documents/Aerie_AI_Vibe_Coding_全面升级实施计划.md)
- [world_simulation.py](file:///E:/Agent_reply/core/world_simulation.py)
- [relationship_engine.py](file:///E:/Agent_reply/core/relationship_engine.py)
- [self_model.py](file:///E:/Agent_reply/core/self_model.py)
- [companion.py](file:///E:/Agent_reply/core/companion.py)
- [context_builder.py](file:///E:/Agent_reply/core/context_builder.py)
- [pipeline.py](file:///E:/Agent_reply/core/pipeline.py)
- [test_phase12_world_domain.py](file:///E:/Agent_reply/tests/test_phase12_world_domain.py)
- [[90_全局验收清单]] · [[92_回滚演练]]
- 2026-07-21 Red: `python -m pytest tests/test_phase12_world_domain.py -q` -> expected failures for missing `core.world_simulation`, `core.action_registry`, `core.relationship_engine`, `core.self_model`, ContextBuilder world args, and Pipeline provider passthrough.
- 2026-07-21 Green: `python -m pytest tests/test_phase12_world_domain.py -q` -> `7 passed`.
- 2026-07-21 Regression: `python -m pytest tests/test_phase12_world_domain.py tests/test_phase11_world_port.py tests/test_phase10_image_workflow.py tests/test_upload.py tests/test_api.py tests/test_phase4_chat_request_service.py tests/test_phase4_api.py tests/test_phase8_proactive_feedback.py tests/test_phase1_proactive_baseline.py -q` -> `120 passed, 4 warnings`.
- 2026-07-21 Syntax: `python -m py_compile core/world_simulation.py core/action_registry.py core/relationship_engine.py core/self_model.py core/world_port.py core/companion.py core/context_builder.py core/pipeline.py` passed.
