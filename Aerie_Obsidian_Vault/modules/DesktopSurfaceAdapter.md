---
title: DesktopSurfaceAdapter
kind: module_note
status: Review
updated_at: 2026-07-27
owners:
  - ARCH
related_decisions:
  - ADR-TC-008
related_risks:
  - R-TC-006
related_validations:
  - C1.4
  - C1.5
  - C4.6
---

# DesktopSurfaceAdapter

## 定义

DesktopSurfaceAdapter 是 Aerie 连接桌面状态、动态岛、截图问图、剪贴板候选、网络电池状态和可确认动作的适配层，目标是吸收 Pyisland/eIsland 的桌面触达思想，但不直接突破 Electron 安全边界。

## 当前事实

- Echo-Pyisland-Aerie 融合方案建议先实现 OfficeContext 与 DesktopSurfaceAdapter 的只读状态查询，再接需要确认的动作。
- 当前桌面端具备 Electron 动态岛、世界面板、窗口生命周期和若干系统能力入口。
- 关键实现候选包括 [main.js](file:///e:/Agent_reply/electron/src/main.js)、[dynamic-island.js](file:///e:/Agent_reply/electron/src/renderer/js/dynamic-island.js)、[screen_tools.py](file:///e:/Agent_reply/core/screen_tools.py) 与 [computer_control.py](file:///e:/Agent_reply/core/computer_control.py)。

## 目标状态

- 只读状态优先：时间、网络、电池、活动窗口、剪贴板 URL 候选。
- 动作必须经 ACL、参数校验和用户确认，不让 Agent 直接操作窗口句柄或系统敏感资源。
- 允许将截图问图输出接入 [[ImageObservation]]，将环境状态提供给 [[VisualIntentRouter]]。

## 实现入口

- 计划任务：[tasks.md Task 1.3.2](../../.trae/specs/execute-third-correction-p0-fusion/tasks.md#L21-L24)
- 体验审计：[tasks.md Task 4.4](../../.trae/specs/execute-third-correction-p0-fusion/tasks.md#L117-L121)
- 代码入口：[dynamic-island.js](file:///e:/Agent_reply/electron/src/renderer/js/dynamic-island.js)、[screen_tools.py](file:///e:/Agent_reply/core/screen_tools.py)、[screen_action_sanitizer.py](file:///e:/Agent_reply/core/screen_action_sanitizer.py)

## 依赖关系

- 上游：[[../dependencies/Pyisland-eIsland-Desktop-Touch]]、Electron 主进程、OfficeContext、系统状态 API。
- 下游：[[VisualIntentRouter]]、[[ImageObservation]]、动态岛 UI、桌面体验审计。
- 外部依赖：Pyisland/eIsland 参考材料、操作系统权限、截图与剪贴板安全边界。

## 风险与待确认

- [[../risks/Unresolved-Risks#R-TC-006：Pyisland-helper-直接移植带来许可和安全问题]]
- [[../risks/Unresolved-Risks#R-TC-004：QQ-真实账号被误触发发送或读取]]
- 决策依据：[02_第三次修正计划决策记录.md ADR-TC-008](../../documents/第三次修正计划/02_第三次修正计划决策记录.md#L153-L162)

## 验证方式

- C1.4：本概念具备实现、依赖、风险/决策、验证四类链接。
- C1.5：矩阵覆盖 Pyisland/eIsland、Electron/动态岛、OfficeContext 与风险。
- C4.6：Electron 真实体验审计覆盖桌面触达入口、控制台、网络、截图和元素状态。
- 验证索引：[[../06_验证索引#核心概念链接验证]]、[[../06_验证索引#功能点与技术方案矩阵验证]]

## 反向链接

- 模块索引：[[../01_模块总览#核心概念模块]]
- 技术索引：[[../02_技术总览#核心技术笔记]]
- 依赖索引：[[../03_依赖清单#核心概念依赖]]
- 风险索引：[[../risks/Unresolved-Risks]]
- 矩阵索引：[[../matrices/Function-To-Implementation]]

