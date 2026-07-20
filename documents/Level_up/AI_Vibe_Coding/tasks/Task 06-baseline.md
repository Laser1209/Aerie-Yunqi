---
title: Task 06-baseline
tags: [aerie, task, phase06, core]
kind: task
task_id: TASK-06-001
phase: Phase 06
subsystem: core
status: done
priority: P1
dependencies: ["TASK-05-001"]
risk: medium
decision_required: false
feature_flag: context_budget_v1
migration: false
files: ["core/context_builder.py", "core/pipeline.py", "core/brain.py"]
acceptance_ids: ["A-06-01", "A-06-02"]
rollback_ready: true
owner: core-team
evidence: ["file:///E:/Agent_reply/core/context_builder.py", "file:///E:/Agent_reply/core/pipeline.py", "file:///E:/Agent_reply/core/brain.py", "file:///E:/Agent_reply/tests/test_phase6_context_budget.py", "file:///E:/Agent_reply/tests/test_brain_provider_routing.py"]
---
# Task 06-baseline
> [!todo] Phase 06
> 按固定优先级构建完整 Turn 上下文并审计 token；验收目标：多气泡合并为完整 assistant 响应，短期不跨 Channel。

- [x] 先提交失败测试证据
- [x] 完成最小实现与兼容路径
- [x] 验证 `context_budget_v1` 关闭后的旧路径
- [x] 记录脱敏 Evidence、指标与守恒结果
- [x] 完成回滚演练并更新 `rollback_ready`

## Evidence（2026-07-21）

- Red：`tests/test_phase6_context_budget.py` 初跑 `3 failed, 1 passed in 1.92s`，失败点为 ContextBuilder 未支持 actor-scoped memory/knowledge/context budget 参数，以及 Pipeline Flag-on 未接 identity/audit。
- Green：Phase 06 专项 `4 passed in 1.57s`；关联 `66 passed, 4 warnings in 3.29s`。
- Provider hardening：`Brain.bge_embed()` 在显式 `AERIE_EMBEDDING_*`/`OPENAI_EMBEDDING_*` 配置存在时调用 OpenAI-compatible `/embeddings` 并返回 embeddings；未显式配置 embedding key 时保持 `bge_embedding` stub，通用 `OPENAI_API_KEY` 不触发外呼；目标测试 `11 passed`。
- 关联门禁：Phase 00–06/API/Pipeline 显式范围 `289 passed, 4 warnings in 28.10s`；完整 `tests` 收集 `481 passed, 6 warnings in 36.25s`；Electron Node `16 passed`。
- 本批复验：`python -m py_compile core/brain.py` 通过；`python -m pytest tests -q` → `542 passed, 6 warnings`；`node --test electron/tests/*.test.js` → `23 passed`；`npm run check:all` 通过；`python tools/scan_provider_key_patterns.py` → `PROVIDER_KEY_SCAN_OK`。
- 静态/收尾：`py_compile core/context_builder.py core/pipeline.py` 通过；`node --check electron/src/main.js`、`node --check electron/src/preload.js` 通过；`git diff --check` 只有 Windows LF→CRLF 提示；项目进程检查无残留。
- 回滚：关闭 `context_budget_v1` 后 Pipeline 不传新增 kwargs、不读取 context audit，旧 ContextBuilder 调用路径保持；本阶段没有 schema/data migration，也没有生产 DB 写入。

## 链接
[[Phase 06]] · [[90_全局验收清单]] · [[92_回滚演练]]
