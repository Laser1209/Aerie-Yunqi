---
title: Task 08-baseline
tags: [aerie, task, phase08, core]
kind: task
task_id: TASK-08-001
phase: Phase 08
subsystem: core
status: done
priority: P1
dependencies: ["TASK-07-001"]
risk: medium
decision_required: false
feature_flag: proactive_delivery_v2
migration: false
files: ["core/proactive_judge.py", "core/push_scheduler.py", "core/api_server.py", "config/proactive.yaml", "tests/test_phase8_proactive_feedback.py"]
acceptance_ids: ["A-08-01", "A-08-02"]
rollback_ready: true
owner: core-team
evidence: ["file:///E:/Agent_reply/core/proactive_judge.py", "file:///E:/Agent_reply/core/push_scheduler.py", "file:///E:/Agent_reply/core/api_server.py", "file:///E:/Agent_reply/config/proactive.yaml", "file:///E:/Agent_reply/tests/test_phase8_proactive_feedback.py"]
progress_note: "2026-07-21: optional JSON state persistence covers daily_count/last_push_at, negative feedback cooldown, mute/postpone, and proactive policy APIs; rollback rehearsal passed."
---
# Task 08-baseline
> [!todo] Phase 08
> 持久化 cooldown、反馈、mute、postpone 与用户设置；验收目标：设置与频控跨重启，负反馈降频。

- [x] 先提交失败测试证据
- [x] 完成最小实现与兼容路径
- [x] 验证 `proactive_delivery_v2` 关闭后的旧路径
- [x] 记录脱敏 Evidence、指标与守恒结果
- [x] 完成回滚演练并更新 `rollback_ready`

## Evidence
- Red：`pytest -q tests/test_phase8_proactive_feedback.py` → `3 failed`，缺少频控状态持久化、`record_feedback()` 与 `set_enabled()`。
- Green：`pytest -q tests/test_phase8_proactive_feedback.py` → `4 passed`；关联 `pytest -q tests/test_phase8_proactive_feedback.py tests/test_phase1_proactive_baseline.py` → `24 passed, 4 warnings`。
- 静态：`python -m py_compile core/push_scheduler.py core/api_server.py` 通过；`config/proactive.yaml` 可被 YAML 正常加载并解析 `state_path`。

## 链接
[[Phase 08]] · [[90_全局验收清单]] · [[92_回滚演练]]
