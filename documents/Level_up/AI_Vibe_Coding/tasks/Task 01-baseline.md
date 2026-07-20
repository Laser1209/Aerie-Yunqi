---
title: Task 01-baseline
tags: [aerie, task, phase01, core]
kind: task
task_id: TASK-01-001
phase: Phase 01
subsystem: core
status: completed
priority: P0
dependencies: ["TASK-00-001"]
risk: medium
decision_required: false
feature_flag: proactive_delivery_v2
migration: false
files: ["core/push_scheduler.py", "core/companion.py"]
acceptance_ids: ["A-01-01", "A-01-02"]
rollback_ready: true
owner: core-team
evidence: ["file:///E:/Agent_reply/core/push_scheduler.py", "file:///E:/Agent_reply/core/companion.py"]
---
# Task 01-baseline
> [!todo] Phase 01
> 统一 trigger、生命周期、Desire 属性与独立 Delivery；验收目标：Cron、手动、Desire、Idle、quiet、force 与 QQ 断线通过。

- [x] 先提交失败测试证据
- [x] 完成最小实现与兼容路径
- [x] 验证 `proactive_delivery_v2` 关闭后的旧路径
- [x] 记录脱敏 Evidence、指标与守恒结果
- [x] 完成回滚演练并更新 `rollback_ready`

## 实施结果
- 所有外部触发统一调用 `PushScheduler.trigger()`，并补齐公开状态、场景和 Policy 合同供 API 使用。
- `Companion` 管理 `PushEventEngine` 生命周期及用户活动记录；Desire、Idle、情绪阈值和手动 API 均使用同一入口。
- V2 对同一内容独立尝试 QQ、桌面气泡和系统通知，并发送不含正文的 `proactive_delivery` 通道结果。
- QQ 离线时桌面与通知继续投递；关闭 Feature Flag 后恢复旧 QQ-only 和离线暂停行为。
- 主动气泡写入兼容 `chat_log`；聊天页仅消费 `user` / `assistant` 角色事件，避免通知与遥测形成重复气泡。

## 验证 Evidence
- Phase 1 专项：`19 passed, 4 warnings`
- Phase 0 + Phase 1 + API + Pipeline：`72 passed, 4 warnings`
- Electron 四个 JS 入口 `node --check` 全部通过；相关编辑器诊断为 0。
- 全量：`272 passed, 10 failed, 6 warnings`；失败集合与实施前一致，主动消息无新增回归。
- 回滚合同：`proactive_delivery_v2=false` 时不持久化本地主动气泡、不发本地事件，只调用 QQ，并恢复 QQ 断线暂停。

## 链接
[[Phase 01]] · [[90_全局验收清单]] · [[92_回滚演练]]
