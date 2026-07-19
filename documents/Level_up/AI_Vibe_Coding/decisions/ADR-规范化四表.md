---
title: ADR - 规范化四表
kind: adr
status: accepted
tags: [aerie, adr, architecture]
---
# ADR：规范化四表
> [!decision] 已接受
> 采用 Conversation、Turn、Message、Request 四表作为聊天真源，chat_log 保留一个可观测兼容周期。

## 背景
现有生产链、数据兼容和插件边界要求渐进迁移，不能通过整体重写或跨边界共享数据库解决。

## 决策
采用 Conversation、Turn、Message、Request 四表作为聊天真源，chat_log 保留一个可观测兼容周期。

## 后果
- 保留旧路径与 Feature Flag，先契约测试再切换读写。
- 通过迁移守恒、幂等、故障恢复和回滚证据验收。
- 主要阶段：[[Phase 03]]；全局约束见 [[03_数据所有权与迁移纪律]]。

## Evidence
- [实施计划](file:///E:/Agent_reply/.trae/documents/Aerie_AI_Vibe_Coding_全面升级实施计划.md)
- [[05_Feature_Flag与回滚矩阵]]
