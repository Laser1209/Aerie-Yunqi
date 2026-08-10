---
title: ImageObservation
kind: module_note
status: Review
updated_at: 2026-07-27
owners:
  - ARCH
related_decisions:
  - ADR-TC-005
related_risks:
  - R-TC-008
related_validations:
  - C1.4
  - C3.6
  - C3.7
---

# ImageObservation

## 定义

ImageObservation 是图片理解后的结构化观察对象，承载 scene、objects、OCR text、relations、confidence、uncertainty、provider metadata 和 memory eligibility，不等同于长期记忆事实。

## 当前事实

- 规格要求图片识别结果必须转为 ImageObservation，并且未经确认或记忆准入不得写入长期记忆。
- Echo 调研建议采用“两级路由”：托管 VLM 作为联调基线，本地 VLM/OCR 作为隐私或网络降级路径。
- 当前可参考入口包括 [image_service.py](file:///e:/Agent_reply/core/image_service.py)、[multimodal_input.py](file:///e:/Agent_reply/core/multimodal_input.py)、[llm_caller.py](file:///e:/Agent_reply/core/llm_caller.py) 与 [memory_store.py](file:///e:/Agent_reply/memory/memory_store.py)。

## 目标状态

- 图片上传后生成可审计的 ImageObservation JSON。
- 低置信度与不确定性显式进入结果，而不是编造事实。
- 长期记忆写入必须经过用户确认或明确 memory eligibility 规则。

## 实现入口

- 计划任务：[tasks.md Task 3.3](../../.trae/specs/execute-third-correction-p0-fusion/tasks.md#L73-L78)
- 需求入口：[spec.md Structured image observation](../../.trae/specs/execute-third-correction-p0-fusion/spec.md#L162-L170)
- 代码入口：[image_service.py](file:///e:/Agent_reply/core/image_service.py)、[multimodal_input.py](file:///e:/Agent_reply/core/multimodal_input.py)、[llm_caller.py](file:///e:/Agent_reply/core/llm_caller.py)

## 依赖关系

- 上游：[[AttachmentEnvelope]]、[[../technology/VLM-OCR-Provider]]、图片上传与 OCR provider。
- 下游：[[VisualIntentRouter]]、短期上下文、World/OfficeContext 场景摘要、可选记忆准入。
- 外部依赖：VLM/OCR 模型、图片脱敏策略、provider 调用授权。

## 风险与待确认

- [[../risks/Unresolved-Risks#R-TC-008：图片观察污染长期记忆]]
- [[../risks/Unresolved-Risks#R-TC-003：真实模型调用泄露隐私或产生成本]]
- 决策依据：[02_第三次修正计划决策记录.md ADR-TC-005](../../documents/第三次修正计划/02_第三次修正计划决策记录.md#L120-L129)

## 验证方式

- C1.4：本概念具备实现、依赖、风险/决策、验证四类链接。
- C3.6：识别结果包含 scene、objects、ocr_text、relations、uncertainties、provider metadata、memory eligibility。
- C3.7：上传图片并识别后，长期记忆未新增未经准入的图片事实。
- 验证索引：[[../06_验证索引#核心概念链接验证]]、[[../06_验证索引#P0-功能验证]]

## 反向链接

- 模块索引：[[../01_模块总览#核心概念模块]]
- 技术索引：[[../02_技术总览#核心技术笔记]]
- 依赖索引：[[../03_依赖清单#核心概念依赖]]
- 风险索引：[[../risks/Unresolved-Risks]]
- 矩阵索引：[[../matrices/Function-To-Implementation]]

