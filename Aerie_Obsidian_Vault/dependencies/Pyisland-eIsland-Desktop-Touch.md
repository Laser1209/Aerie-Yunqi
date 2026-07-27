---
title: Pyisland-eIsland桌面触达依赖
kind: dependency_note
status: Draft
updated_at: 2026-07-27
owners:
  - ARCH
related_decisions:
  - ADR-TC-008
related_risks:
  - R-TC-006
related_validations:
  - C1.5
---

# Pyisland-eIsland桌面触达依赖

## 定义

Pyisland/eIsland 桌面触达依赖是动态岛、状态感知、截图和轻量桌面动作的参考来源，只能作为能力映射和适配层设计依据。

## 当前事实

- 决策记录将 Pyisland helper 直接移植标为 Needs Confirmation。
- 未确认前不得直接复制第三方 helper 代码或新增未知许可证风险。

## 目标状态

- [[../modules/DesktopSurfaceAdapter]] 用自有安全边界承接可审计能力。
- 只读状态先行，确认动作后置。

## 实现入口

- [[../modules/DesktopSurfaceAdapter#实现入口]]
- [tasks.md Task 1.3.2](../../.trae/specs/execute-third-correction-p0-fusion/tasks.md#L21-L24)

## 依赖关系

- 上游：Pyisland/eIsland 能力研究、Electron 动态岛现状。
- 下游：OfficeContext、截图问图、动态岛状态展示。

## 风险与待确认

- [[../risks/Unresolved-Risks#R-TC-006：Pyisland-helper-直接移植带来许可和安全问题]]
- 决策依据：[02_第三次修正计划决策记录.md ADR-TC-008](../../documents/第三次修正计划/02_第三次修正计划决策记录.md#L153-L162)

## 验证方式

- C1.5：矩阵覆盖 Pyisland/eIsland、Electron/动态岛、OfficeContext 与风险。
- C4.6：真实 Electron 体验审计覆盖桌面触达入口。

## 反向链接

- [[../modules/DesktopSurfaceAdapter]]
- [[../03_依赖清单#核心概念依赖]]

