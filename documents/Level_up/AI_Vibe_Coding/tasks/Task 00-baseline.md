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
- Phase 0 基线专项：`14 passed in 0.25s`。
- Phase 0 定向门禁：`56 passed, 4 warnings in 2.35s`。
- 全量 Python 基线：`254 passed, 10 failed, 6 warnings in 7.83s`；既有失败已按模块记录，不作为 Phase 0 新增回归。
- Flag 关闭时旧 Schema 正常初始化，迁移账本不创建；新表与备份保留策略未执行破坏性删除。

## 链接
[[Phase 00]] · [[90_全局验收清单]] · [[92_回滚演练]]
