---
title: Phase 05 - 事件统一、SSE 恢复与 Renderer 去重
kind: phase
phase: Phase 05
status: done
tags: [aerie, phase, phase05]
---
# Phase 05：事件统一、SSE 恢复与 Renderer 去重
> [!info] 执行边界
> 只按获批实施计划执行；当前阶段未通过验收时停止后续阶段。

## 目标
SSE id、恢复窗口、Renderer 去重排序与游标续连；保持兼容、可观测与可回滚。

## 非目标
不整体重写 Pipeline；不删除旧表或旧文件；不创建平行 v2；不复制疑似凭据。

## 依赖
- Phase 04
- [[05_Feature_Flag与回滚矩阵]]、[[06_AI_Vibe_Coding批次规约]]

## 当前代码证据
- [event_stream.py](file:///E:/Agent_reply/core/event_stream.py)
- [main.js](file:///E:/Agent_reply/electron/src/main.js)
- [pipeline.py](file:///E:/Agent_reply/core/pipeline.py)
- [api_server.py](file:///E:/Agent_reply/core/api_server.py)

## 文件范围
- 计划修改或演进：`core/event_stream.py`、`electron/src/main.js`
- 新文件仅限计划列明的模块、迁移和测试。
- 执行任务：[[Task 05-baseline]]

## 数据/API 合同
- Feature Flag：`chat_stream_v1`。
- SSE id、恢复窗口、Renderer 去重排序与游标续连。
- ID、状态、sequence、幂等键和所有权边界必须可审计。
- 涉及迁移时支持 backup、dry-run、checksum、幂等、cursor、断点续跑与守恒。

## TDD 步骤
1. 先新增失败测试覆盖主路径、异常路径与回滚路径。
2. 实现最小变更使测试通过，保留兼容适配器。
3. 运行受影响模块测试与完整回归。
4. 验证 Flag 关闭、迁移/协议恢复和 Evidence 脱敏。

## 验收
- [x] stderr、IPC、SSE、poll 不重复气泡
- [x] Feature Flag 关闭恢复旧路径且不丢新数据
- [x] 不产生重复副作用、历史串线或敏感值泄漏

## 回滚
关闭 `chat_stream_v1`，恢复备份或旧读路径；保留新表、元数据、Outbox、旧表和旧文件。

## 指标
成功率、延迟、重复计数、守恒差异、恢复时间和回滚耗时；禁止记录消息正文、个人数据或凭据。

## 提交边界
只提交 Phase 05 相关源码、测试、迁移与文档；不混入无关重构、格式化或构建产物。

## Evidence
- [实施计划](file:///E:/Agent_reply/.trae/documents/Aerie_AI_Vibe_Coding_全面升级实施计划.md)
- [event_stream.py](file:///E:/Agent_reply/core/event_stream.py)
- [main.js](file:///E:/Agent_reply/electron/src/main.js)
- [[90_全局验收清单]] · [[92_回滚演练]]

### Task 05 Evidence（2026-07-20）

- Red：新增 `tests/test_phase5_event_stream.py` 后，后端目标测试因缺少 `_reset_for_tests`、stream replay 参数和 API Flag 传参失败：`5 errors in 3.55s`；新增 `electron/tests/sse-bridge.test.js` 后，Electron 目标测试因缺少 `buildSseHeaders` / `parseSseFrame` 失败：`3 failed`。
- Green：`core/event_stream.py` 增加进程内 bounded replay window、`id:` SSE 帧和 legacy data-only 默认路径；`core/api_server.py` 仅在 `chat_stream_v1=true` 时读取 `Last-Event-ID`/query cursor 并启用 replay；`electron/src/main.js` 解析 SSE `id:`/payload `event_id`、保存 renderer cursor，并在重连时发送 `Last-Event-ID`。
- Flag 回滚：`chat_stream_v1=false` 时 `/api/events/stream` 继续以无参数方式调用旧 `event_stream_generator()`；legacy `stream()` 仍输出 `data: ...`，不强制 replay、不加入 `id:`。
- Renderer 去重：沿用 Task 10 的 `_seenEventIds`、legacy numeric id 和 `request_id + sequence` 缓冲；Electron Node 回归验证 IPC/SSE/poll 共用 ingest、event_id 跨通道去重和 SSE 断线后状态查询恢复。
- 验证：Phase 00–05 显式门禁 `264 passed, 4 warnings in 27.60s`；完整 `tests` 收集 `477 passed, 6 warnings in 35.77s`；Electron Node `16 passed`；`python -m py_compile core/event_stream.py core/api_server.py` 通过；`node --check electron/src/main.js`、`node --check electron/src/preload.js` 通过；`git diff --check` 仅有 LF→CRLF 提示；无残留项目 Electron/Python/Node 进程。
- 迁移：本阶段 `migration=false`，未创建新迁移，未修改生产数据库，未修改 004/005/006 checksum，未引入 ACK/Outbox/Sidecar 可靠总线语义。
