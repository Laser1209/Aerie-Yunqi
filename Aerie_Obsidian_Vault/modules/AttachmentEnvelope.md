---
title: AttachmentEnvelope
kind: module_note
status: Review
updated_at: 2026-07-27
owners:
  - ARCH
related_decisions:
  - ADR-TC-001
related_risks:
  - R-TC-007
related_validations:
  - C1.4
  - C3.3
  - C3.5
---

# AttachmentEnvelope

## 定义

AttachmentEnvelope 是桌面附件进入渲染、历史和 AI 上下文前的统一封装边界，用于把上传文件、解析状态、Artifact 分片、可信边界和来源 ID 固定成唯一事实源。

## 当前事实

- 规格要求附件先归一化为 AttachmentEnvelope 与 typed Artifact，再进入 renderer、history 或 AI context。
- 当前代码中存在 [[../dependencies/Internal-Attachment-Pipeline|旧附件处理、新桌面附件服务与 worker]] 多入口，风险是同一文件产生多个 attachment id 或 artifact 来源。
- 关键实现候选包括 [desktop_attachments.py](file:///e:/Agent_reply/core/desktop_attachments.py)、[attachment_handler.py](file:///e:/Agent_reply/core/attachment_handler.py)、[attachment_worker_runtime.py](file:///e:/Agent_reply/core/attachment_worker_runtime.py) 与 [context_builder.py](file:///e:/Agent_reply/core/context_builder.py)。

## 目标状态

- 桌面上传、状态查询、历史水合、聊天气泡和 AI context_snippets 都只读取一个权威 AttachmentEnvelope。
- 旧接口保留兼容，但不得生成第二套事实源。
- 每个 Artifact part 都带有 source id、part id、页码或范围、parser status、warning 与安全边界。

## 实现入口

- 计划任务：[tasks.md Task 3.2](../../.trae/specs/execute-third-correction-p0-fusion/tasks.md#L66-L71)
- 需求入口：[spec.md Unified attachment Artifact pipeline](../../.trae/specs/execute-third-correction-p0-fusion/spec.md#L147-L160)
- 代码入口：[desktop_attachments.py](file:///e:/Agent_reply/core/desktop_attachments.py)、[attachment_worker_runtime.py](file:///e:/Agent_reply/core/attachment_worker_runtime.py)、[api_server.py](file:///e:/Agent_reply/core/api_server.py)

## 依赖关系

- 上游：[[../dependencies/Internal-Attachment-Pipeline]]、桌面上传 UI、附件 worker。
- 下游：[[ImageObservation]]、[[../matrices/Function-To-Implementation]]、聊天历史、AI 上下文组装。
- 外部依赖：本地文件系统、解析工具链、Renderer 预览状态。

## 风险与待确认

- [[../risks/Unresolved-Risks#R-TC-007：附件旧新路径继续分裂]]
- [[../risks/Unresolved-Risks#R-TC-003：真实模型调用泄露隐私或产生成本]]
- 决策依据：[02_第三次修正计划决策记录.md ADR-TC-001](../../documents/第三次修正计划/02_第三次修正计划决策记录.md#L70-L80)

## 验证方式

- C1.4：本概念具备实现、依赖、风险/决策、验证四类链接。
- C3.3：同一合成文件上传后只产生一个 attachment id 和一个 artifact 来源。
- C3.5：附件进入上下文时包含 trusted boundary、part id、页码或范围、parser warning。
- 验证索引：[[../06_验证索引#核心概念链接验证]]、[[../06_验证索引#P0-功能验证]]

## 反向链接

- 模块索引：[[../01_模块总览#核心概念模块]]
- 技术索引：[[../02_技术总览#核心技术笔记]]
- 依赖索引：[[../03_依赖清单#核心概念依赖]]
- 风险索引：[[../risks/Unresolved-Risks]]
- 矩阵索引：[[../matrices/Function-To-Implementation]]

