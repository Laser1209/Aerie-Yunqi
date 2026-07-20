---
title: Phase 14 - 世界图片候选与主动消息审批闭环
kind: phase
phase: Phase 14
status: done
progress_note: "2026-07-21: Phase 14 is green for world ImageCandidate publish/replay, Core-side flag gating, proactive policy/judge approval, idempotent image workflow planning, terminal ACK, non-terminal no-ACK recovery, and redacted candidate evidence."
tags: [aerie, phase, phase14]
---
# Phase 14：世界图片候选与主动消息审批闭环
> [!info] 执行边界
> 只按获批实施计划执行；当前阶段未通过验收时停止后续阶段。

## 目标
World 只产 ImageCandidate，Core 执行 Judge 到 ACK；保持兼容、可观测与可回滚。

## 非目标
不整体重写 Pipeline；不删除旧表或旧文件；不创建平行 v2；不复制疑似凭据。

## 依赖
- Phase 13
- [[05_Feature_Flag与回滚矩阵]]、[[06_AI_Vibe_Coding批次规约]]

## 当前代码证据
- [proactive_judge.py](file:///E:/Agent_reply/core/proactive_judge.py)
- [attachment_handler.py](file:///E:/Agent_reply/core/attachment_handler.py)
- [pipeline.py](file:///E:/Agent_reply/core/pipeline.py)
- [api_server.py](file:///E:/Agent_reply/core/api_server.py)
- [world_image_candidates.py](file:///E:/Agent_reply/core/world_image_candidates.py)
- [world_service/main.py](file:///E:/Agent_reply/world_service/main.py)
- [sqlite_store.py](file:///E:/Agent_reply/world_service/storage/sqlite_store.py)
- [companion.py](file:///E:/Agent_reply/core/companion.py)
- [test_phase14_world_image_candidates.py](file:///E:/Agent_reply/tests/test_phase14_world_image_candidates.py)

## 文件范围
- 已新增：`core/world_image_candidates.py`、`tests/test_phase14_world_image_candidates.py`
- 已修改或演进：`world_service/main.py`、`world_service/storage/sqlite_store.py`、`core/companion.py`
- 复用但未重写：`core/proactive_judge.py`、`core/image_service.py`、`core/attachment_handler.py`
- 未启动后台消费循环；未让 World 或 Renderer 直发图片/消息；未创建新数据库迁移。
- 执行任务：[[Task 14-baseline]]

## 数据/API 合同
- Feature Flag：`world_image_candidates_v1`。
- World 只产 ImageCandidate，Core 执行 Judge 到 ACK。
- ID、状态、sequence、幂等键和所有权边界必须可审计。
- 涉及迁移时支持 backup、dry-run、checksum、幂等、cursor、断点续跑与守恒。

## TDD 步骤
1. 先新增失败测试覆盖主路径、异常路径与回滚路径。
2. 实现最小变更使测试通过，保留兼容适配器。
3. 运行受影响模块测试与完整回归。
4. 验证 Flag 关闭、迁移/协议恢复和 Evidence 脱敏。

## 验收
- [x] 重复、过期、静音、拒绝、失败、离线均无重复副作用
- [x] Feature Flag 关闭恢复旧路径且不丢新数据
- [x] 不产生重复副作用、历史串线或敏感值泄漏

## 回滚
关闭 `world_image_candidates_v1`，恢复备份或旧读路径；保留新表、元数据、Outbox、旧表和旧文件。

## 指标
成功率、延迟、重复计数、守恒差异、恢复时间和回滚耗时；禁止记录消息正文、个人数据或凭据。

## 提交边界
只提交 Phase 14 相关源码、测试、迁移与文档；不混入无关重构、格式化或构建产物。

## Evidence
- [实施计划](file:///E:/Agent_reply/.trae/documents/Aerie_AI_Vibe_Coding_全面升级实施计划.md)
- [proactive_judge.py](file:///E:/Agent_reply/core/proactive_judge.py)
- [attachment_handler.py](file:///E:/Agent_reply/core/attachment_handler.py)
- [world_image_candidates.py](file:///E:/Agent_reply/core/world_image_candidates.py)
- [world_service/main.py](file:///E:/Agent_reply/world_service/main.py)
- [sqlite_store.py](file:///E:/Agent_reply/world_service/storage/sqlite_store.py)
- [companion.py](file:///E:/Agent_reply/core/companion.py)
- [test_phase14_world_image_candidates.py](file:///E:/Agent_reply/tests/test_phase14_world_image_candidates.py)
- [[90_全局验收清单]] · [[92_回滚演练]]
- 2026-07-21 Red: `python -m pytest tests/test_phase14_world_image_candidates.py -q` -> expected failures for missing `core.world_image_candidates` and `LocalWorldSidecarService.publish_image_candidate`.
- 2026-07-21 Red: `python -m pytest tests/test_phase14_world_image_candidates.py::test_companion_exposes_one_shot_candidate_consumer -q` -> expected failure for missing `Companion.process_world_image_candidates_once`.
- 2026-07-21 Red: `python -m pytest tests/test_phase14_world_image_candidates.py::test_image_workflow_disabled_does_not_ack_or_record_candidate -q` -> expected `failed` before no-ACK workflow-disabled guard.
- 2026-07-21 Green: `python -m pytest tests/test_phase14_world_image_candidates.py -q` -> `7 passed`.
- 2026-07-21 Sidecar regression: `python -m pytest tests/test_phase14_world_image_candidates.py tests/test_phase13_world_sidecar.py -q` -> `13 passed`.
- 2026-07-21 Regression: `python -m pytest tests/test_phase14_world_image_candidates.py tests/test_phase13_world_sidecar.py tests/test_phase12_world_domain.py tests/test_phase11_world_port.py tests/test_phase10_image_workflow.py tests/test_upload.py tests/test_api.py tests/test_phase4_chat_request_service.py tests/test_phase4_api.py tests/test_phase8_proactive_feedback.py tests/test_phase1_proactive_baseline.py -q` -> `133 passed, 4 warnings`.
- 2026-07-21 Syntax: `python -m py_compile core/world_image_candidates.py world_service/main.py world_service/storage/sqlite_store.py core/companion.py` passed.
