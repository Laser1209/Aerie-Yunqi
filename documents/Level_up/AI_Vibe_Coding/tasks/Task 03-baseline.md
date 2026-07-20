---
title: Task 03-baseline
tags: [aerie, task, phase03, core]
kind: task
task_id: TASK-03-001
phase: Phase 03
subsystem: core
status: in_progress
priority: P0
dependencies: ["TASK-02-001"]
risk: high
decision_required: false
feature_flag: conversation_model_v1
migration: true
files: ["core/database.py", "core/pipeline.py"]
acceptance_ids: ["A-03-01", "A-03-02"]
rollback_ready: false
owner: core-team
evidence: ["file:///E:/Agent_reply/core/database.py", "file:///E:/Agent_reply/core/pipeline.py"]
---
# Task 03-baseline
> [!todo] Phase 03
> 四表、状态机、response_group_id、sequence 与幂等回填；验收目标：记录、附件、角色顺序和 Channel 守恒。

- [x] 先提交失败测试证据
- [ ] 完成最小实现与兼容路径
- [ ] 验证 `conversation_model_v1` 关闭后的旧路径
- [x] 记录脱敏 Evidence、指标与守恒结果
- [ ] 完成回滚演练并更新 `rollback_ready`

- Green：Migration Ledger `004_conversation_model` 创建四表骨架；独立 `005_conversation_backfill` 保持 004 checksum 不变并执行兼容补列、保守历史转换。
- 回填合同：按 legacy id 保序；附件原样复制；连续 assistant 分段共享 Response Group；QQ/Desktop 短期会话隔离；未知身份保持 NULL；重复运行不复制 Message。
- live 双写：`ConversationRepository` 兼容 `Database` 连接提供者；Companion 由 `conversation_model_v1` 控制注入；FULL/BASIC 在 legacy 完整持久化后各镜像一次，镜像失败不破坏旧响应。
- 完整 Turn 读取：规范仓储按最近 N 个完整 Turn 返回全部 Message 分段；FULL/BASIC 均切换到规范历史；读取异常回退 legacy。
- Flag 自动化合同：`enabled=false` 时 Pipeline 绕过规范读写并保留旧 SQL 参数合同；该证据不等同于真实 Companion 组合根演练，因此任务仍未完成。
- 迁移安全：固定 004 已发布 checksum；最小旧库缺失附件/身份列时 005 先幂等补列；缺少 `chat_log` 时迁移失败而非伪完成。
- Turn 事务：Conversation、Turn、Request、用户 Message 与全部助手 Message 置于同一 SQLite SAVEPOINT；任一 Message 写失败时四表均无残留。
- 历史读取批次回归：Phase 3 + Pipeline `33 passed`；Phase 0/2/3 + Pipeline `78 passed, 4 warnings`；完整 Python `346 passed, 6 warnings`。
- 事务批次回归：Phase 3 + Pipeline `34 passed`；Phase 0/2/3 + Pipeline `79 passed, 4 warnings`；完整 Python `347 passed, 6 warnings`；修改文件诊断为空。
- 未完成：真实库 backup/dry-run/cursor 守恒报告、`conversation_model_v1` 关闭后的真实组合根回滚与迁移回滚；不得将本 Task 标记为 done。

## 链接
[[Phase 03]] · [[90_全局验收清单]] · [[92_回滚演练]]
