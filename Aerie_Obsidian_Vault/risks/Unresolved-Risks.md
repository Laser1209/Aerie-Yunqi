---
title: 未闭环风险登记册
kind: risk
status: Review
updated_at: 2026-07-27
owners:
  - ARCH
related_decisions:
  - ADR-TC-001
  - ADR-TC-003
  - ADR-TC-005
  - ADR-TC-007
  - ADR-TC-008
related_validations:
  - C1.4
  - C1.5
  - C3.3
  - C3.6
  - C3.7
  - C3.13
---

# 未闭环风险登记册

## 定义

本页同步第三次修正计划决策记录中的开放风险，并为核心概念页提供风险/决策链接入口。

## 风险总表

| 风险 ID | 风险 | 触发信号 | 影响 | 当前策略 | 关联概念 | 验证 |
| --- | --- | --- | --- | --- | --- | --- |
| R-TC-001 | 范围膨胀破坏 P0 闭环 | 计划新增超过四阶段或加入 P1/P2 产品增强 | P0 修复延期、审计失焦 | 以 ADR-TC-001 阻断 | [[../dependencies/Echo-Emotional-Value]] | C1.5 |
| R-TC-003 | 真实模型调用泄露隐私或产生成本 | 未脱敏图片、附件、知识库被发往 provider | 隐私、费用、安全风险 | 未确认前只允许模拟或本地契约验证 | [[../modules/ImageObservation]]、[[../modules/VisualIntentRouter]] | C3.6、C3.8 |
| R-TC-005 | 外部向量库引入不可控依赖 | 安装服务、写外部库、上传全文 | 数据驻留和回滚困难 | 先做能力探测，外部依赖另行确认 | [[../modules/KnowledgeBase]]、[[../technology/Dedicated-Vector-Knowledge]] | C3.13 |
| R-TC-006 | Pyisland helper 直接移植带来许可和安全问题 | 复制未知来源代码或暴露新 IPC | 法务、安全、稳定性风险 | 先做能力映射和适配层设计 | [[../modules/DesktopSurfaceAdapter]] | C1.5、C4.6 |
| R-TC-007 | 附件旧新路径继续分裂 | 同一文件出现多个 attachment id 或 artifact 来源 | AI 上下文、历史、预览不一致 | P0 要求统一 AttachmentEnvelope 与 Artifact | [[../modules/AttachmentEnvelope]] | C3.3、C3.5 |
| R-TC-008 | 图片观察污染长期记忆 | 上传图像后未确认即写入长期事实 | 记忆污染和隐私风险 | ImageObservation 默认不可长期写入 | [[../modules/ImageObservation]] | C3.7 |

## R-TC-001：范围膨胀破坏 P0 闭环

- 决策：ADR-TC-001
- 关联：[[../dependencies/Echo-Emotional-Value]]、[[../matrices/Function-To-Implementation]]
- 验证：C1.5

## R-TC-003：真实模型调用泄露隐私或产生成本

- 决策：ADR-TC-005
- 关联：[[../modules/ImageObservation]]、[[../modules/VisualIntentRouter]]、[[../technology/VLM-OCR-Provider]]
- 验证：C3.6、C3.8、C3.10

## R-TC-005：外部向量库引入不可控依赖

- 决策：ADR-TC-003、ADR-TC-007
- 关联：[[../modules/KnowledgeBase]]、[[../technology/Dedicated-Vector-Knowledge]]
- 验证：C3.13

## R-TC-006：Pyisland helper 直接移植带来许可和安全问题

- 决策：ADR-TC-008
- 关联：[[../modules/DesktopSurfaceAdapter]]、[[../dependencies/Pyisland-eIsland-Desktop-Touch]]
- 验证：C1.5、C4.6

## R-TC-007：附件旧新路径继续分裂

- 决策：ADR-TC-001
- 关联：[[../modules/AttachmentEnvelope]]、[[../dependencies/Internal-Attachment-Pipeline]]
- 验证：C3.3、C3.5

## R-TC-008：图片观察污染长期记忆

- 决策：ADR-TC-005
- 关联：[[../modules/ImageObservation]]、[[../technology/VLM-OCR-Provider]]
- 验证：C3.7

## 反向链接

- 决策记录：[[../04_决策记录#第三次修正计划决策]]
- 审计报告：[[../05_审计报告#核心概念风险发现]]
- 验证索引：[[../06_验证索引#核心概念链接验证]]
- 矩阵：[[../matrices/Function-To-Implementation]]

