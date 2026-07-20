---
title: Task 02-baseline
tags: [aerie, task, phase02, core]
kind: task
task_id: TASK-02-001
phase: Phase 02
subsystem: core
status: done
priority: P1
dependencies: ["TASK-01-001"]
risk: medium
decision_required: false
feature_flag: identity_contract_v1
migration: true
files: ["communication/message.py", "core/identity", "core/pipeline.py", "memory/memory_store.py", "core/persona_hub", "core/api_server.py", "electron/src/renderer/js/persona-hub.js"]
acceptance_ids: ["A-02-01", "A-02-02"]
rollback_ready: true
owner: core-team
evidence: ["file:///E:/Agent_reply/tests/test_phase2_identity.py", "file:///E:/Agent_reply/tests/test_phase2_persona_source.py", "file:///E:/Agent_reply/electron/tests/persona-hub.test.js"]
---
# Task 02-baseline
> [!todo] Phase 02
> IncomingMessage 增加 Actor/Channel 身份合同，Persona Hub 为真源；验收目标：同 Actor 跨 Channel 只共享长期记忆。

- [x] 先提交失败测试证据
- [x] 完成最小实现与兼容路径
- [x] 验证 `identity_contract_v1` 关闭后的旧路径
- [x] 记录脱敏 Evidence、指标与守恒结果
- [x] 完成回滚合同并更新 `rollback_ready`
- [x] 清零完整 Python 回归的 10 个既有失败

## Evidence

> [!success] 2026-07-20 重新审计通过
> - 身份与 Persona 专项：`41 passed, 4 warnings in 1.99s`
> - Phase 0–2 + API + Pipeline：`124 passed, 4 warnings in 3.35s`
> - 完整 Python：`353 passed, 6 warnings in 9.99s`
> - Electron Persona Hub：`3 passed`；`persona-hub.js` 语法检查通过
> - Actor Emotion、主动消息、情绪 API、后台 idle/decay 与 Actor 持久化闭环均由当前测试重新覆盖
> - `status: done`、全部验收勾选与 `rollback_ready: true` 当前一致

### TDD Red 证据
- 长期记忆：`LongTermMemory.store/retrieve()` 不接受 `actor_id`，2 failed、6 passed。
- Persona API：未知 ID 返回默认 Persona，未冲突导入被改名，2 failed、8 passed。

### 守恒与回滚
- 旧 `chat_log` 与 `long_term_memory` 的 `actor_id` 保持 `NULL`，不猜测历史 Channel/Actor。
- 新记录双写 legacy `user_id` 与规范 `actor_id`；关闭 `identity_contract_v1` 后继续按 legacy `user_id` 查询。
- Persona Hub 开启时为规范写源；关闭 `persona_hub_source_v1` 后旧 YAML 路径仍可用。
- 新表、新列和 Persona JSON 在 Flag 关闭时保留，不执行破坏性删除。

## 链接
[[Phase 02]] · [[90_全局验收清单]] · [[92_回滚演练]]
