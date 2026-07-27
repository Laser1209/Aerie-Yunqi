---
title: 功能点与技术方案矩阵
kind: matrix
status: Review
updated_at: 2026-07-27
owners:
  - ARCH
related_decisions:
  - ADR-TC-001
  - ADR-TC-003
  - ADR-TC-005
  - ADR-TC-008
related_risks:
  - R-TC-001
  - R-TC-003
  - R-TC-005
  - R-TC-006
  - R-TC-007
  - R-TC-008
related_validations:
  - C1.5
---

# 功能点与技术方案矩阵

## 定义

本矩阵把 Echo 情绪价值、Pyisland/eIsland 桌面触达、Aerie 当前模块、P0 修复项、代码入口、测试入口和风险统一映射，作为 Task 1.3 与 C1.5 的证据页。

## Echo 情绪价值映射

| 功能点 | Aerie 模块 | 技术方案 | 实现入口 | 依赖 | 风险/决策 | 验证 |
| --- | --- | --- | --- | --- | --- | --- |
| 图片理解后自然回应 | [[../modules/ImageObservation]] | VLM/OCR 输出结构化观察 | [image_service.py](file:///e:/Agent_reply/core/image_service.py)、[multimodal_input.py](file:///e:/Agent_reply/core/multimodal_input.py) | [[../technology/VLM-OCR-Provider]] | [[../risks/Unresolved-Risks#R-TC-008：图片观察污染长期记忆]]、ADR-TC-005 | C3.6、C3.7 |
| 主动生成角色或环境图片 | [[../modules/VisualIntentRouter]] | 意图路由控制 reference assets | [world_image_candidates.py](file:///e:/Agent_reply/core/world_image_candidates.py) | [[../modules/ImageObservation]]、WorldSnapshot | [[../risks/Unresolved-Risks#R-TC-003：真实模型调用泄露隐私或产生成本]]、ADR-TC-005 | C3.8、C3.9、C3.10 |
| 陪伴知识可语义召回 | [[../modules/KnowledgeBase]] | 专用向量知识库连接尝试 | [long_permanent.py](file:///e:/Agent_reply/memory/layers/long_permanent.py)、[brain.py](file:///e:/Agent_reply/core/brain.py) | [[../technology/Dedicated-Vector-Knowledge]] | [[../risks/Unresolved-Risks#R-TC-005：外部向量库引入不可控依赖]]、ADR-TC-003 | C3.13 |

## Pyisland/eIsland 桌面触达映射

| 功能点 | Aerie 模块 | 技术方案 | 实现入口 | 依赖 | 风险/决策 | 验证 |
| --- | --- | --- | --- | --- | --- | --- |
| 动态岛状态展示 | [[../modules/DesktopSurfaceAdapter]] | Electron 动态岛承接只读状态 | [dynamic-island.js](file:///e:/Agent_reply/electron/src/renderer/js/dynamic-island.js)、[main.js](file:///e:/Agent_reply/electron/src/main.js) | [[../dependencies/Pyisland-eIsland-Desktop-Touch]] | [[../risks/Unresolved-Risks#R-TC-006：Pyisland-helper-直接移植带来许可和安全问题]]、ADR-TC-008 | C1.5、C4.6 |
| 截图问图 | [[../modules/DesktopSurfaceAdapter]]、[[../modules/ImageObservation]] | 截图进入 ImageObservation | [screen_tools.py](file:///e:/Agent_reply/core/screen_tools.py)、[image_service.py](file:///e:/Agent_reply/core/image_service.py) | [[../technology/VLM-OCR-Provider]] | R-TC-003、R-TC-008 | C3.6、C4.6 |
| 剪贴板候选与安全动作 | [[../modules/DesktopSurfaceAdapter]] | OfficeContext 只读状态与 ACL 动作 | [screen_action_sanitizer.py](file:///e:/Agent_reply/core/screen_action_sanitizer.py)、[computer_control.py](file:///e:/Agent_reply/core/computer_control.py) | Electron IPC、系统权限 | R-TC-006 | C4.6 |

## P0 修复项映射

| P0 修复项 | 核心概念 | 代码入口 | 测试入口 | 风险 | 验证 |
| --- | --- | --- | --- | --- | --- |
| 统一附件 Artifact 管线 | [[../modules/AttachmentEnvelope]] | [desktop_attachments.py](file:///e:/Agent_reply/core/desktop_attachments.py)、[attachment_worker_runtime.py](file:///e:/Agent_reply/core/attachment_worker_runtime.py) | [test_desktop_attachments.py](file:///e:/Agent_reply/tests/test_desktop_attachments.py) | R-TC-007 | C3.3、C3.5 |
| 结构化图片识别 | [[../modules/ImageObservation]] | [image_service.py](file:///e:/Agent_reply/core/image_service.py)、[multimodal_input.py](file:///e:/Agent_reply/core/multimodal_input.py) | 待新增中文截图、实物图、低置信度测试 | R-TC-008 | C3.6、C3.7 |
| 主动图片路由 | [[../modules/VisualIntentRouter]] | [world_image_candidates.py](file:///e:/Agent_reply/core/world_image_candidates.py) | 待新增角色自拍、环境图、置信度不足测试 | R-TC-003 | C3.8、C3.9、C3.10 |
| 前端附件预览与安全动作 | [[../modules/AttachmentEnvelope]]、[[../modules/DesktopSurfaceAdapter]] | [chat-uploader.js](file:///e:/Agent_reply/electron/src/renderer/js/chat-uploader.js)、[chat.js](file:///e:/Agent_reply/electron/src/renderer/js/chat.js) | [desktop-audit.js](file:///e:/Agent_reply/electron/tests/e2e/desktop-audit.js) | R-TC-007、R-TC-006 | C3.11、C3.12、C4.6 |
| 专用向量知识库连接尝试 | [[../modules/KnowledgeBase]] | [long_permanent.py](file:///e:/Agent_reply/memory/layers/long_permanent.py)、[kb.py](file:///e:/Agent_reply/knowledge/kb.py) | 待新增语义检索探测记录 | R-TC-005 | C3.13 |

## 反向链接

- 首页：[[../00_首页#核心概念入口]]
- 模块：[[../01_模块总览#核心概念模块]]
- 技术：[[../02_技术总览#核心技术笔记]]
- 依赖：[[../03_依赖清单#核心概念依赖]]
- 风险：[[../risks/Unresolved-Risks]]
- 验证：[[../06_验证索引#功能点与技术方案矩阵验证]]

