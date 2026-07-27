---
title: VLM-OCR-Provider
kind: technology_note
status: Draft
updated_at: 2026-07-27
owners:
  - ARCH
related_decisions:
  - ADR-TC-005
related_risks:
  - R-TC-003
related_validations:
  - C3.6
  - C3.7
---

# VLM-OCR-Provider

## 定义

VLM/OCR Provider 是 [[../modules/ImageObservation]] 的外部或本地视觉理解能力边界。

## 当前事实

- 未确认前不得调用真实付费模型或上传真实私有图片。
- 可先用模拟 provider 或本地契约验证固定 ImageObservation schema。

## 目标状态

- provider 输出结构化 ImageObservation。
- 低置信度、OCR 失败、模型不可用都有显式降级。

## 实现入口

- [tasks.md Task 3.3](../../.trae/specs/execute-third-correction-p0-fusion/tasks.md#L73-L78)
- [image_service.py](file:///e:/Agent_reply/core/image_service.py)

## 依赖关系

- 上游：[[../modules/AttachmentEnvelope]]、图片上传。
- 下游：[[../modules/ImageObservation]]、[[../modules/VisualIntentRouter]]。

## 风险与待确认

- [[../risks/Unresolved-Risks#R-TC-003：真实模型调用泄露隐私或产生成本]]
- 决策依据：[02_第三次修正计划决策记录.md ADR-TC-005](../../documents/第三次修正计划/02_第三次修正计划决策记录.md#L120-L129)

## 验证方式

- C3.6：ImageObservation 结构完整。
- C3.7：图片观察不默认污染长期记忆。

## 反向链接

- [[../modules/ImageObservation]]
- [[../02_技术总览#核心技术笔记]]

