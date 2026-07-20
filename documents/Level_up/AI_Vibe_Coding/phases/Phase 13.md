---
title: Phase 13 - world.db、Outbox 与 Remote Sidecar
kind: phase
phase: Phase 13
status: done
progress_note: "2026-07-21: Phase 13 sidecar baseline is green for world.db ownership, Outbox idempotency, ACK cursor replay, heartbeat/checkpoint redaction, RemoteWorldAdapter crash degradation, Electron plugin supervisor crash-loop fuse, and Core world-event dedupe."
tags: [aerie, phase, phase13]
---
# Phase 13：world.db、Outbox 与 Remote Sidecar
> [!info] 执行边界
> 只按获批实施计划执行；当前阶段未通过验收时停止后续阶段。

## 目标
world.db 单一所有者、Outbox、ACK cursor、heartbeat 与监管；保持兼容、可观测与可回滚。

## 非目标
不整体重写 Pipeline；不删除旧表或旧文件；不创建平行 v2；不复制疑似凭据。

## 依赖
- Phase 12
- [[05_Feature_Flag与回滚矩阵]]、[[06_AI_Vibe_Coding批次规约]]

## 当前代码证据
- [world_service/main.py](file:///E:/Agent_reply/world_service/main.py)
- [sqlite_store.py](file:///E:/Agent_reply/world_service/storage/sqlite_store.py)
- [remote.py](file:///E:/Agent_reply/core/world_adapters/remote.py)
- [main.js](file:///E:/Agent_reply/electron/src/main.js)
- [plugin-supervisor.js](file:///E:/Agent_reply/electron/src/plugin-supervisor.js)
- [event_stream.py](file:///E:/Agent_reply/core/event_stream.py)
- [test_phase13_world_sidecar.py](file:///E:/Agent_reply/tests/test_phase13_world_sidecar.py)

## 文件范围
- 已修改或演进：`electron/src/main.js`、`core/event_stream.py`、`core/world_port.py`
- 已新增：`world_service/main.py`、`world_service/storage/sqlite_store.py`、`core/world_adapters/remote.py`、`electron/src/plugin-supervisor.js`、`tests/test_phase13_world_sidecar.py`
- 未把 Renderer 直连 Sidecar；未提前实现图片候选或仪表盘。
- 执行任务：[[Task 13-baseline]]

## 数据/API 合同
- Feature Flag：`world_sidecar_v1`。
- world.db 单一所有者、Outbox、ACK cursor、heartbeat 与监管。
- ID、状态、sequence、幂等键和所有权边界必须可审计。
- 涉及迁移时支持 backup、dry-run、checksum、幂等、cursor、断点续跑与守恒。

## TDD 步骤
1. 先新增失败测试覆盖主路径、异常路径与回滚路径。
2. 实现最小变更使测试通过，保留兼容适配器。
3. 运行受影响模块测试与完整回归。
4. 验证 Flag 关闭、迁移/协议恢复和 Evidence 脱敏。

## 验收
- [x] Sidecar 崩溃聊天继续，重启续传不重复
- [x] Feature Flag 关闭恢复旧路径且不丢新数据
- [x] 不产生重复副作用、历史串线或敏感值泄漏

## 回滚
关闭 `world_sidecar_v1`，恢复备份或旧读路径；保留新表、元数据、Outbox、旧表和旧文件。

## 指标
成功率、延迟、重复计数、守恒差异、恢复时间和回滚耗时；禁止记录消息正文、个人数据或凭据。

## 提交边界
只提交 Phase 13 相关源码、测试、迁移与文档；不混入无关重构、格式化或构建产物。

## Evidence
- [实施计划](file:///E:/Agent_reply/.trae/documents/Aerie_AI_Vibe_Coding_全面升级实施计划.md)
- [world_service/main.py](file:///E:/Agent_reply/world_service/main.py)
- [sqlite_store.py](file:///E:/Agent_reply/world_service/storage/sqlite_store.py)
- [remote.py](file:///E:/Agent_reply/core/world_adapters/remote.py)
- [main.js](file:///E:/Agent_reply/electron/src/main.js)
- [plugin-supervisor.js](file:///E:/Agent_reply/electron/src/plugin-supervisor.js)
- [event_stream.py](file:///E:/Agent_reply/core/event_stream.py)
- [test_phase13_world_sidecar.py](file:///E:/Agent_reply/tests/test_phase13_world_sidecar.py)
- [[90_全局验收清单]] · [[92_回滚演练]]
- 2026-07-21 Red: `python -m pytest tests/test_phase13_world_sidecar.py -q` -> expected failures for missing `world_service`, `core.world_adapters.remote`, and `electron/src/plugin-supervisor.js`.
- 2026-07-21 Green: `python -m pytest tests/test_phase13_world_sidecar.py -q` -> `6 passed`.
- 2026-07-21 Regression: `python -m pytest tests/test_phase13_world_sidecar.py tests/test_phase12_world_domain.py tests/test_phase11_world_port.py tests/test_phase10_image_workflow.py tests/test_upload.py tests/test_api.py tests/test_phase4_chat_request_service.py tests/test_phase4_api.py tests/test_phase8_proactive_feedback.py tests/test_phase1_proactive_baseline.py -q` -> `126 passed, 4 warnings`.
- 2026-07-21 Syntax: `python -m py_compile world_service/main.py world_service/storage/sqlite_store.py core/world_adapters/remote.py core/world_port.py core/event_stream.py core/companion.py core/pipeline.py core/context_builder.py` passed; `node --check electron/src/plugin-supervisor.js` passed; `node --check electron/src/main.js` passed.
