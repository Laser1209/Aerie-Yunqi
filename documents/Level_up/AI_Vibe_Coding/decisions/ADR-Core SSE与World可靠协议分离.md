---
title: ADR - Core SSE 与 World 可靠协议分离
kind: adr
status: accepted
tags: [aerie, adr, architecture]
---
# ADR：Core SSE 与 World 可靠协议分离
> [!decision] 已接受
> Core UI 事件使用 SSE；World 使用独立带 ACK、cursor、checkpoint 的可靠协议。

## 背景
现有生产链、数据兼容和插件边界要求渐进迁移，不能通过整体重写或跨边界共享数据库解决。

## 决策
Core UI 事件使用 SSE；World 使用独立带 ACK、cursor、checkpoint 的可靠协议。

## 后果
- 保留旧路径与 Feature Flag，先契约测试再切换读写。
- 通过迁移守恒、幂等、故障恢复和回滚证据验收。
- 主要阶段：[[Phase 05]]；全局约束见 [[03_数据所有权与迁移纪律]]。

## Evidence
- [实施计划](file:///E:/Agent_reply/.trae/documents/Aerie_AI_Vibe_Coding_全面升级实施计划.md)
- [[05_Feature_Flag与回滚矩阵]]
