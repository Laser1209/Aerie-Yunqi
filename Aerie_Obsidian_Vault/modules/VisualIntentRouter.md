---
title: VisualIntentRouter
kind: module_note
status: Implemented
updated_at: 2026-07-28
owners:
  - ARCH
related_decisions:
  - ADR-TC-005
related_risks:
  - R-TC-003
related_validations:
  - C1.4
  - C3.8
  - C3.9
  - C3.10
---
# VisualIntentRouter

## 定义

VisualIntentRouter 是主动图片生成前的意图路由器，用于区分 role_selfie、role_in_scene、couple_photo、environment_object、document_snapshot 与 meme_sticker，并决定是否允许挂载角色参考资产。

## 当前事实

- 规格要求任何 image provider 收到 reference assets 前，必须先经过 VisualIntentRouter。
- environment_object 必须让 reference_assets 为空，并从 WorldSnapshot 或 OfficeContext 派生环境细节。
- role_selfie 和 role_in_scene 必须冻结 PersonaConfig visual identity revision。
- 已实现于 [image_service.py L102-L218](../../core/image_service.py)，使用确定性关键词匹配，不调用真实模型。
- 集成于 `ImageWorkflow.generate_image`，低置信度时返回 `rejected` + `visual_intent_low_confidence`，不调用 provider。

## 目标状态

- 环境图不混入角色身份参考图。
- 角色自拍和入镜图保持身份版本可追溯。
- 置信度不足时不直接调用生图 provider，而是询问、回退文本或要求补充约束。

## 实现入口

- 计划任务：[tasks.md Task 3.4](../../.trae/specs/execute-third-correction-p0-fusion/tasks.md#L80-L85)
- 需求入口：[spec.md Visual intent routing](../../.trae/specs/execute-third-correction-p0-fusion/spec.md#L172-L186)
- 代码候选：[world_image_candidates.py](file:///e:/Agent_reply/core/world_image_candidates.py)、[image_service.py](file:///e:/Agent_reply/core/image_service.py)、[persona_manager.py](file:///e:/Agent_reply/core/persona_hub/persona_manager.py)

## 依赖关系

- 上游：[[ImageObservation]]、PersonaConfig.visual_identity、WorldSnapshot、OfficeContext。
- 下游：生图 provider、角色资产选择、环境图提示词、生成后身份一致性检查。
- 外部依赖：真实模型调用授权、角色资产许可、世界状态可信度。

## 风险与待确认

- [[../risks/Unresolved-Risks#R-TC-003：真实模型调用泄露隐私或产生成本]]
- [[../risks/Unresolved-Risks#R-TC-008：图片观察污染长期记忆]]
- 决策依据：[02_第三次修正计划决策记录.md ADR-TC-005](../../documents/第三次修正计划/02_第三次修正计划决策记录.md#L120-L129)

## 验证方式

- C1.4：本概念具备实现、依赖、风险/决策、验证四类链接。
- C3.8：environment_object 请求的 reference_assets 为空。
  - 证据：`test_generation_environment_object_routes_without_reference_assets`
- C3.9：role_selfie 或 role_in_scene 请求包含 PersonaConfig visual identity revision。
  - 证据：`test_generation_role_selfie_freezes_visual_identity_revision`
- C3.10：低置信度分类不直接调用生图 provider。
  - 证据：`test_generation_low_confidence_visual_intent_does_not_call_provider`
- 回归：`python -m pytest tests/test_phase10_image_workflow.py -q` 通过 16/16
- 验证索引：[[../06_验证索引#核心概念链接验证]]、[[../06_验证索引#P0-功能验证]]

## 审计结论

- 代码质量：类结构清晰，`route` 与 `_build_visual_request` 职责分离，类型注解完整。
- 安全：不调用真实模型，`reference_assets` 仅含 asset ID 不含本地路径，不写入长期记忆。
- 审计日期：2026-07-28
- 审计人：TRAE

## 反向链接

- 模块索引：[[../01_模块总览#核心概念模块]]
- 技术索引：[[../02_技术总览#核心技术笔记]]
- 依赖索引：[[../03_依赖清单#核心概念依赖]]
- 风险索引：[[../risks/Unresolved-Risks]]
- 矩阵索引：[[../matrices/Function-To-Implementation]]
