---
title: Echo情绪价值
kind: dependency_note
status: Review
updated_at: 2026-07-27
owners:
  - ARCH
related_decisions:
  - ADR-TC-001
related_risks:
  - R-TC-001
related_validations:
  - C1.4
  - C1.5
---

# Echo情绪价值

## 定义

Echo情绪价值是 Aerie 第三次修正计划的产品体验输入来源，用于约束陪伴感、主动性、图片理解、角色一致性、桌面触达与知识记忆的优先级，而不是直接替代 P0 工程闭环。

## 当前事实

- Echo 调研明确提到图片理解、主动图片、情绪回应、桌面触达和长期记忆之间的体验组合。
- P0 范围已由 ADR-TC-001 锁定，Echo 价值只能映射到当前模块和待修复模块，不能无门禁扩展到 P1/P2。
- 主要来源：[Echo情绪价值调研与Aerie结合方案.md](../../documents/Echo情绪价值调研与Aerie结合方案.md)

## 目标状态

- Echo 功能点被拆成可实现、可验证、可降级的工程条目。
- 情绪价值通过 [[../matrices/Function-To-Implementation]] 映射到 AttachmentEnvelope、ImageObservation、VisualIntentRouter、DesktopSurfaceAdapter 和专用向量知识库。
- 不把体验愿景直接写成已完成能力。

## 实现入口

- 计划任务：[tasks.md Task 1.1.3 与 Task 1.3.1](../../.trae/specs/execute-third-correction-p0-fusion/tasks.md#L10-L23)
- 矩阵入口：[[../matrices/Function-To-Implementation#Echo-情绪价值映射]]
- 模块入口：[[../modules/ImageObservation]]、[[../modules/VisualIntentRouter]]、[[../modules/DesktopSurfaceAdapter]]、[[../modules/KnowledgeBase]]

## 依赖关系

- 上游：Echo 调研文档、统一融合方案、用户体验目标。
- 下游：[[../modules/ImageObservation]]、[[../modules/VisualIntentRouter]]、[[../modules/DesktopSurfaceAdapter]]、[[../modules/KnowledgeBase]]。
- 外部依赖：VLM/OCR、桌面适配、向量检索和审计证据。

## 风险与待确认

- [[../risks/Unresolved-Risks#R-TC-001：范围膨胀破坏-P0-闭环]]
- [[../risks/Unresolved-Risks#R-TC-003：真实模型调用泄露隐私或产生成本]]
- 决策依据：[02_第三次修正计划决策记录.md ADR-TC-001](../../documents/第三次修正计划/02_第三次修正计划决策记录.md#L70-L80)

## 验证方式

- C1.4：本概念具备实现、依赖、风险/决策、验证四类链接。
- C1.5：矩阵覆盖 Echo、Pyisland/eIsland、Aerie 当前模块、P0 修复项、代码文件、测试入口和风险。
- 验证索引：[[../06_验证索引#核心概念链接验证]]、[[../06_验证索引#功能点与技术方案矩阵验证]]

## 反向链接

- 依赖索引：[[../03_依赖清单#核心概念依赖]]
- 模块索引：[[../01_模块总览#核心概念模块]]
- 技术索引：[[../02_技术总览#核心技术笔记]]
- 风险索引：[[../risks/Unresolved-Risks]]
- 矩阵索引：[[../matrices/Function-To-Implementation]]

