---
title: 专用向量知识库
kind: module_note
status: Blocked-with-evidence
updated_at: 2026-07-28
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

# 专用向量知识库

## 定义

专用向量知识库是 Echo/Pyisland/Aerie 融合知识的语义检索底座，不能把关键词知识库或普通 Markdown 索引等同为已具备向量检索能力。

## 当前事实

- ADR-TC-003 已确认本轮按专用向量库方向设计和尝试接入。
- 代码中存在长期记忆层 ChromaDB 可选路径和 embedding provider 适配，但仍需能力探测确认是否能服务独立 Vault 摘要索引。
- 关键实现候选包括 [long_permanent.py](file:///e:/Agent_reply/memory/layers/long_permanent.py)、[brain.py](file:///e:/Agent_reply/core/brain.py) 与 [kb.py](file:///e:/Agent_reply/knowledge/kb.py)。
- **Task 3.6 探测结论（2026-07-28T00:00:00）**：阻塞——ChromaDB 依赖未安装（`requirements.txt` 中被注释）、Embedding API 环境变量全部未配置、生产代码未接入 `LayeredMemory`、`data/chroma` 目录不存在。
- 完整阻塞证据见 [Task3.6-向量知识库连接尝试报告.md](../../.trae/specs/execute-third-correction-p0-fusion/Task3.6-向量知识库连接尝试报告.md)。

## 目标状态

- 若存在可用向量实现，将 Vault 总览摘要写入索引并验证至少 3 个融合概念可语义检索。
- 若不存在可用实现，记录能力探测、缺失接口、阻塞原因和后续 adapter 边界。
- 外部向量服务、付费 embedding、知识库全文上传必须另行确认。

## 实现入口

- 计划任务：[tasks.md Task 3.6](../../.trae/specs/execute-third-correction-p0-fusion/tasks.md#L93-L97)
- 需求入口：[spec.md Dedicated vector knowledge connection attempt](../../.trae/specs/execute-third-correction-p0-fusion/spec.md#L198-L211)
- 代码入口：[long_permanent.py](file:///e:/Agent_reply/memory/layers/long_permanent.py)、[brain.py](file:///e:/Agent_reply/core/brain.py)、[kb.py](file:///e:/Agent_reply/knowledge/kb.py)

## 依赖关系

- 上游：[[../technology/Dedicated-Vector-Knowledge]]、embedding provider、长期记忆层、Vault 摘要。
- 下游：语义检索测试、知识源链接、累积验证报告、最终交付物索引。
- 外部依赖：ChromaDB 可用性、embedding provider 授权、本地或外部向量库部署策略。

## 风险与待确认

- [[../risks/Unresolved-Risks#R-TC-005：外部向量库引入不可控依赖]]
- 决策依据：[02_第三次修正计划决策记录.md ADR-TC-003](../../documents/第三次修正计划/02_第三次修正计划决策记录.md#L94-L104)
- 待确认：[02_第三次修正计划决策记录.md ADR-TC-007](../../documents/第三次修正计划/02_第三次修正计划决策记录.md#L142-L151)

## 验证方式

- C1.4：本概念具备实现、依赖、风险/决策、验证四类链接。
- C3.13：若成功，至少 3 个融合概念可语义检索；若失败，报告包含能力探测、缺失接口、阻塞原因和后续设计。
- 验证索引：[[../06_验证索引#核心概念链接验证]]、[[../06_验证索引#P0-功能验证]]

## 反向链接

- 模块索引：[[../01_模块总览#核心概念模块]]
- 技术索引：[[../02_技术总览#核心技术笔记]]
- 依赖索引：[[../03_依赖清单#核心概念依赖]]
- 风险索引：[[../risks/Unresolved-Risks]]
- 矩阵索引：[[../matrices/Function-To-Implementation]]

