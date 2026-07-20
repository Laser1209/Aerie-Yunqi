---
title: Phase 06 - 完整 Turn Context、Token Budget、摘要与长期记忆
kind: phase
phase: Phase 06
status: done
tags: [aerie, phase, phase06]
---
# Phase 06：完整 Turn Context、Token Budget、摘要与长期记忆
> [!info] 执行边界
> 只按获批实施计划执行；当前阶段未通过验收时停止后续阶段。

## 目标
按固定优先级构建完整 Turn 上下文并审计 token；保持兼容、可观测与可回滚。

## 非目标
不整体重写 Pipeline；不删除旧表或旧文件；不创建平行 v2；不复制疑似凭据。

## 依赖
- Phase 05
- [[05_Feature_Flag与回滚矩阵]]、[[06_AI_Vibe_Coding批次规约]]

## 当前代码证据
- [context_builder.py](file:///E:/Agent_reply/core/context_builder.py)
- [pipeline.py](file:///E:/Agent_reply/core/pipeline.py)
- [brain.py](file:///E:/Agent_reply/core/brain.py)
- [api_server.py](file:///E:/Agent_reply/core/api_server.py)
- [test_brain_provider_routing.py](file:///E:/Agent_reply/tests/test_brain_provider_routing.py)

## 文件范围
- 计划修改或演进：`core/context_builder.py`、`core/pipeline.py`
- 新文件仅限计划列明的模块、迁移和测试。
- 执行任务：[[Task 06-baseline]]

## 数据/API 合同
- Feature Flag：`context_budget_v1`。
- 按固定优先级构建完整 Turn 上下文并审计 token。
- ID、状态、sequence、幂等键和所有权边界必须可审计。
- 涉及迁移时支持 backup、dry-run、checksum、幂等、cursor、断点续跑与守恒。

## TDD 步骤
1. 先新增失败测试覆盖主路径、异常路径与回滚路径。
2. 实现最小变更使测试通过，保留兼容适配器。
3. 运行受影响模块测试与完整回归。
4. 验证 Flag 关闭、迁移/协议恢复和 Evidence 脱敏。

## 验收
- [x] 多气泡合并为完整 assistant 响应，短期不跨 Channel
- [x] Feature Flag 关闭恢复旧路径且不丢新数据
- [x] 不产生重复副作用、历史串线或敏感值泄漏

## 回滚
关闭 `context_budget_v1`，恢复备份或旧读路径；保留新表、元数据、Outbox、旧表和旧文件。

## 指标
成功率、延迟、重复计数、守恒差异、恢复时间和回滚耗时；禁止记录消息正文、个人数据或凭据。

## 提交边界
只提交 Phase 06 相关源码、测试、迁移与文档；不混入无关重构、格式化或构建产物。

## Evidence
- [实施计划](file:///E:/Agent_reply/.trae/documents/Aerie_AI_Vibe_Coding_全面升级实施计划.md)
- [context_builder.py](file:///E:/Agent_reply/core/context_builder.py)
- [pipeline.py](file:///E:/Agent_reply/core/pipeline.py)
- [[90_全局验收清单]] · [[92_回滚演练]]

### Task 06 Evidence（2026-07-21）

- Red：新增 `tests/test_phase6_context_budget.py` 后，目标测试失败 `3 failed, 1 passed in 1.92s`；失败点为 `ContextBuilder.build()` 缺少 `actor_id/context_budget_enabled` 等 Phase 06 参数，Pipeline 在 `context_budget_v1=true` 时未传 context budget identity，也未记录 audit。
- Green：`core/context_builder.py` 增加 `context_budget_enabled` 兼容参数、actor/channel 标识、长期记忆与知识库检索注入、assistant 连续多气泡合并、估算 token/字符 budget 与脱敏 audit；`core/pipeline.py` 仅在 `context_budget_v1=true` 时传入 identity 并将 allowlist 后的 audit 写入 cognition context 阶段。
- Flag 回滚：`context_budget_v1=false` 时 Pipeline 不传新增 kwargs、不读取 `get_last_context_audit()`，ContextBuilder 可继续按旧签名/旧行为使用；无 schema/data migration。
- 验证：Phase 06 专项 `4 passed in 1.57s`；Context/Pipeline/Phase4/Phase5 关联 `66 passed, 4 warnings in 3.29s`；Phase 00–06 显式门禁 `289 passed, 4 warnings in 28.10s`；完整 `tests` 收集 `481 passed, 6 warnings in 36.25s`；Electron Node `16 passed`；`python -m py_compile core/context_builder.py core/pipeline.py` 通过；`git diff --check` 仅有 LF→CRLF 提示；无残留项目 Electron/Python/Node 进程。
- 迁移：本阶段 `migration=false`，未创建新迁移，未修改生产数据库，未修改 004/005/006 checksum；audit 只记录计数、标识、字符和估算 token，不记录消息正文、记忆正文、知识正文或凭据。

### Provider Hardening Evidence（2026-07-21）

- Red：新增 `tests/test_brain_provider_routing.py::test_bge_embed_uses_explicit_openai_compatible_embedding_provider` 后，目标测试按预期失败，`Brain.bge_embed()` 仍返回 `status="stub"`。
- Green：`core/brain.py` 增加显式 `AERIE_EMBEDDING_*` / `OPENAI_EMBEDDING_*` OpenAI-compatible `/embeddings` 接线；未配置显式 embedding key 时继续返回 `bge_embedding` stub，且即使存在通用 `OPENAI_API_KEY` 也不调用 `httpx.post`。
- 回滚：删除 monkey-patch 接线或移除显式 embedding env 即回到旧 stub 路径；本批无 schema/data migration，无生产 DB 写入。
- 验证：`python -m py_compile core/brain.py` 通过；`python -m pytest tests/test_brain_provider_routing.py -q` → `11 passed`；`python -m pytest tests -q` → `542 passed, 6 warnings`；`node --test electron/tests/*.test.js` → `23 passed`；`npm run check:all` 通过；`python tools/scan_provider_key_patterns.py` → `PROVIDER_KEY_SCAN_OK`。
