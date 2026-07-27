---
title: 内部附件管线依赖
kind: dependency_note
status: Draft
updated_at: 2026-07-27
owners:
  - ARCH
related_decisions:
  - ADR-TC-001
related_risks:
  - R-TC-007
related_validations:
  - C3.3
---

# 内部附件管线依赖

## 定义

内部附件管线依赖记录 AttachmentEnvelope 所依赖的旧附件处理、新桌面附件服务、worker 解析、状态查询、历史水合与 AI 上下文入口。

## 当前事实

- 附件入口至少涉及 [attachment_handler.py](file:///e:/Agent_reply/core/attachment_handler.py)、[desktop_attachments.py](file:///e:/Agent_reply/core/desktop_attachments.py)、[attachment_worker_runtime.py](file:///e:/Agent_reply/core/attachment_worker_runtime.py)。
- P0 要求禁止同一文件形成多个事实源。

## 目标状态

- [[../modules/AttachmentEnvelope]] 成为附件事实源边界。
- worker 输出只通过统一 Artifact 进入下游。

## 实现入口

- [[../modules/AttachmentEnvelope#实现入口]]
- [tasks.md Task 3.2](../../.trae/specs/execute-third-correction-p0-fusion/tasks.md#L66-L71)

## 依赖关系

- 上游：桌面 UI 上传、本地文件读取、解析 worker。
- 下游：[[../modules/ImageObservation]]、Renderer 预览、AI context。

## 风险与待确认

- [[../risks/Unresolved-Risks#R-TC-007：附件旧新路径继续分裂]]
- 决策依据：[02_第三次修正计划决策记录.md ADR-TC-001](../../documents/第三次修正计划/02_第三次修正计划决策记录.md#L70-L80)

## 验证方式

- C3.3：同一合成文件上传后只产生一个 attachment id 和一个 artifact 来源。
- C3.5：AI 上下文使用 Artifact 边界。

## 反向链接

- [[../modules/AttachmentEnvelope]]
- [[../03_依赖清单#核心概念依赖]]

