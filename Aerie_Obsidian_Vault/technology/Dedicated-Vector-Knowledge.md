---
title: Dedicated-Vector-Knowledge
kind: technology_note
status: Review
updated_at: 2026-07-27
owners:
  - ARCH
related_decisions:
  - ADR-TC-003
  - ADR-TC-007
related_risks:
  - R-TC-005
related_validations:
  - C1.4
  - C3.13
---

# Dedicated-Vector-Knowledge

## 定义

Dedicated-Vector-Knowledge 是专用向量知识库的技术实现视图，关注 embedding、向量存储、索引更新、语义检索测试和数据驻留边界。

## 当前事实

- 现有长期记忆层提到 ChromaDB 向量与 SQLite 元数据组合，但是否可用于当前 Vault 摘要索引仍需 Task 3.6 探测。
- [brain.py](file:///e:/Agent_reply/core/brain.py) 中存在 openai-compatible embedding 适配逻辑，但真实 provider 调用受 ADR-TC-005 与 ADR-TC-007 约束。

## 目标状态

- 有可用 adapter 时，Vault 摘要可索引、可更新、可检索。
- 无可用 adapter 时，输出明确的缺失接口与后续边界，不伪造成功。

## 实现入口

- 模块入口：[[../modules/KnowledgeBase]]
- 计划任务：[tasks.md Task 3.6](../../.trae/specs/execute-third-correction-p0-fusion/tasks.md#L93-L97)
- 代码入口：[long_permanent.py](file:///e:/Agent_reply/memory/layers/long_permanent.py)、[brain.py](file:///e:/Agent_reply/core/brain.py)、[kb.py](file:///e:/Agent_reply/knowledge/kb.py)

## 依赖关系

- 上游：Vault 摘要、embedding provider、长期记忆层。
- 下游：[[../modules/KnowledgeBase]]、语义检索验证、最终交付索引。
- 外部依赖：ChromaDB、本地或远端 embedding、向量数据库。

## 风险与待确认

- [[../risks/Unresolved-Risks#R-TC-005：外部向量库引入不可控依赖]]
- 决策依据：[02_第三次修正计划决策记录.md ADR-TC-003](../../documents/第三次修正计划/02_第三次修正计划决策记录.md#L94-L104)
- 待确认：[02_第三次修正计划决策记录.md ADR-TC-007](../../documents/第三次修正计划/02_第三次修正计划决策记录.md#L142-L151)

## 验证方式

- C1.4：本概念具备实现、依赖、风险/决策、验证四类链接。
- C3.13：完成专用向量知识库连接尝试或阻塞报告。
- 验证索引：[[../06_验证索引#P0-功能验证]]

## 反向链接

- [[../modules/KnowledgeBase]]
- [[../02_技术总览#核心技术笔记]]
- [[../matrices/Function-To-Implementation]]

