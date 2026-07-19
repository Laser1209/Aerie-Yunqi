---
title: ADR - 图片副作用归 Core
kind: adr
status: accepted
tags: [aerie, adr, architecture]
---
# ADR：图片副作用归 Core
> [!decision] 已接受
> World 只输出 ImageCandidate；Core 统一执行 Judge、生成、审核、持久化、Delivery 与 ACK。

## 背景
现有生产链、数据兼容和插件边界要求渐进迁移，不能通过整体重写或跨边界共享数据库解决。

## 决策
World 只输出 ImageCandidate；Core 统一执行 Judge、生成、审核、持久化、Delivery 与 ACK。

## 后果
- 保留旧路径与 Feature Flag，先契约测试再切换读写。
- 通过迁移守恒、幂等、故障恢复和回滚证据验收。
- 主要阶段：[[Phase 14]]；全局约束见 [[03_数据所有权与迁移纪律]]。

## Evidence
- [实施计划](file:///E:/Agent_reply/.trae/documents/Aerie_AI_Vibe_Coding_全面升级实施计划.md)
- [[05_Feature_Flag与回滚矩阵]]
