---
title: Task 10-baseline
tags: [aerie, task, phase10, image]
kind: task
task_id: TASK-10-001
phase: Phase 10
subsystem: image
status: planned
priority: P1
dependencies: ["TASK-09-001"]
risk: medium
decision_required: false
feature_flag: image_assets_v1
migration: false
files: ["core/pipeline.py", "core/api_server.py"]
acceptance_ids: ["A-10-01", "A-10-02"]
rollback_ready: false
owner: image-team
evidence: ["file:///E:/Agent_reply/core/pipeline.py", "file:///E:/Agent_reply/core/api_server.py"]
---
# Task 10-baseline
> [!todo] Phase 10
> Vision/Generation Provider、审核、资产与 Delivery 分离；验收目标：超时、失败、拒绝不产生重复外部副作用。

- [ ] 先提交失败测试证据
- [ ] 完成最小实现与兼容路径
- [ ] 验证 `image_assets_v1` 关闭后的旧路径
- [ ] 记录脱敏 Evidence、指标与守恒结果
- [ ] 完成回滚演练并更新 `rollback_ready`

## 链接
[[Phase 10]] · [[90_全局验收清单]] · [[92_回滚演练]]
