---
title: Task 00-baseline
tags: [aerie, task, phase00, core]
kind: task
task_id: TASK-00-001
phase: Phase 00
subsystem: core
status: completed
priority: P0
dependencies: []
risk: high
decision_required: false
feature_flag: migration_framework_v1
migration: true
files: ["core/database.py", "core/chat_events.py"]
acceptance_ids: ["A-00-01", "A-00-02"]
rollback_ready: true
owner: core-team
evidence: ["file:///E:/Agent_reply/core/database.py", "file:///E:/Agent_reply/core/chat_events.py", "file:///E:/Agent_reply/tests/test_phase0_baseline.py"]
---
# Task 00-baseline
> [!todo] Phase 00
> 迁移账本、EventEnvelope 与 Feature Flag 审计；验收目标：空库、现有库、重复运行和中断续跑通过。

- [x] 先提交失败测试证据
- [x] 完成最小实现与兼容路径
- [x] 验证 `migration_framework_v1` 关闭后的旧路径
- [x] 记录脱敏 Evidence、指标与守恒结果
- [x] 完成回滚演练并更新 `rollback_ready`

## 验证结果
- 2026-07-20 重新审计：Phase 0 基线专项 `14 passed in 0.30s`。
- 当前完整 Python 回归：`353 passed, 6 warnings in 9.99s`，历史失败已清零。
- `migration_framework_v1=false` 恢复演练：旧 `chat_log` `1/1` 行、`migration_ledger=0`、`quick_check=ok`、数据损失 `0`、总耗时 `0.060643s`。
- 本次复验未修改生产库，只使用临时脱敏数据库；新表与备份保留策略未执行破坏性删除。
- `rollback_ready: true` 与当前 Evidence 一致。

## 链接
[[Phase 00]] · [[90_全局验收清单]] · [[92_回滚演练]]
