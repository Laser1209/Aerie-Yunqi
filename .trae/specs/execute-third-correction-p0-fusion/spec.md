---
title: Aerie 第三次修正计划 P0 融合闭环 Spec
date: 2026-07-27
change-id: execute-third-correction-p0-fusion
status: pending-approval
tags:
  - Aerie
  - Echo
  - Pyisland
  - Obsidian
  - attachment-artifact
  - vision-observation
  - desktop-audit
---

# Aerie 第三次修正计划 P0 融合闭环 Spec

> [!summary]
> 本规格用于承接第三次修正计划的首轮执行。经决策确认，本轮范围锁定为 P0 闭环优先：信息总览知识库、乱码修复、附件 Artifact、视觉 Observation、主动图片路由、前端可读预览、严格阶段门禁审计、专用向量库接入尝试。

## Why

Aerie 已完成大量桌面端能力修复，但 Echo/Pyisland/Aerie 融合所需的多模态底座、知识源组织、视觉主体路由和审计闭环仍需要统一规划与执行。第三次修正计划需要先建立权威知识库和可验证 P0 闭环，避免继续在碎片化文档、分裂附件链路和不稳定前端展示上叠加新功能。

## What Changes

- 新建独立 Obsidian Vault 作为本次融合工作的权威知识源，按模块、技术分类、依赖关系建立双向链接回路。
- 建立功能点与技术方案对应矩阵，覆盖 Echo 情绪价值、Pyisland/eIsland 桌面触达、Aerie 当前底座与 P0 修复项。
- 输出第三次修正计划文档，阶段不超过 4 个，包含目标、任务、资源、交付物和量化验证标准。
- 建立阶段门禁确认机制，每个阶段启动前和验收后都生成审计记录，未通过不得进入下一阶段。
- 修复 Electron HTTP/SSE UTF-8 chunk 解码问题，确保中文 JSON、Markdown、SSE 流和附件文件名不出现替换字符。
- 统一桌面附件链路到 AttachmentEnvelope 与 Artifact 模型，消除旧/新解析路径分裂。
- 接入结构化 ImageObservation，图片识别结果以观察对象进入上下文，不默认污染长期记忆。
- 新增主动图片 VisualIntentRouter，区分角色自拍、角色入镜、合照、环境物件和办公截图。
- 补齐前端附件预览与聊天/数据历史展示，使图片、文本、Markdown、表格、PDF/PPT/Office 投影可读且不泄露本机路径。
- 尝试接入专用向量库方案；如现有内置知识库不具备向量能力，则形成失败证据、接口差距和后续接入设计。
- 使用真实 Electron/agent-browser 视角完成前端体验审计，使用代码质量、调试证据、安全扫描完成后端验收审计。
- **BREAKING**：本轮不得删除旧接口；如需要替换旧附件路径，必须提供兼容层与迁移记录。

## Impact

- Affected specs: `aerie-companion-v9-buildout`、桌面端完整能力修复、Echo 情绪价值融合、Echo-Pyisland-Aerie 统一融合。
- Affected docs: 独立 Obsidian Vault、第三次修正计划、决策记录、阶段审计记录、累积验证报告。
- Affected code: `electron/src/main.js`、`electron/src/preload.js`、`electron/src/renderer/js/chat.js`、`electron/src/renderer/js/chat-uploader.js`、`core/desktop_attachments.py`、`core/attachment_worker_runtime.py`、`core/attachment_handler.py`、`core/image_service.py`、`core/multimodal_input.py`、`core/context_builder.py`、`knowledge/*`、潜在新增 `core/visual_intent_router.py`、潜在新增向量知识库适配层。
- Affected runtime: Electron 主窗口、动态岛、附件 worker、知识库、测试隔离数据目录、外部 QA 证据目录。

## Decisions

### Decision: 第一轮执行范围

- Final: P0 闭环优先。
- Reason: 先修复输入、解析、视觉、展示和知识源底座，降低后续关系面板、办公入口、语音和表情包叠加时的返工风险。

### Decision: Obsidian 知识库位置

- Final: 独立 Vault。
- Reason: 避免将大量知识节点直接混入代码仓库，同时便于建立独立双向链接系统和后续同步机制。

### Decision: 向量接入策略

- Final: 专用向量库。
- Reason: 本轮需要验证“内置向量知识库”能力边界；现有关键词知识库不足以承载语义检索目标，应按专用向量库设计差距和接入尝试。

### Decision: 决策确认严格度

- Final: 阶段门禁确认。
- Reason: 用户要求严格双自审计和阶段门禁；每阶段启动与验收都必须形成可追溯记录。

## ADDED Requirements

### Requirement: Obsidian 权威知识库

The system SHALL create an independent Obsidian-compatible knowledge vault for the third correction plan, with frontmatter, wikilinks, callouts, module pages, technical pages, dependency pages, decision pages, audit pages, and validation pages.

#### Scenario: Knowledge overview is complete

- **WHEN** the knowledge vault is generated
- **THEN** it SHALL include overview, module map, technical stack map, dependency map, function-to-implementation matrix, unresolved risks, and update mechanism notes.
- **AND** every core concept SHALL link to at least one implementation note, one dependency note, and one validation note.

#### Scenario: Knowledge source is authoritative

- **WHEN** a later task needs project context
- **THEN** it SHALL reference the Obsidian overview first before modifying code.
- **AND** new findings SHALL be appended to the relevant linked note instead of creating unlinked fragments.

### Requirement: Third correction plan document

The system SHALL produce a standalone third correction plan document with version, date, owner, change log, phases, task list, resources, deliverables, validation standards, risks, and rollback prevention strategy.

#### Scenario: Phase structure is bounded

- **WHEN** the plan is generated
- **THEN** it SHALL contain no more than four major phases.
- **AND** each phase SHALL define measurable acceptance criteria.

### Requirement: Decision records

The system SHALL record every critical decision that affects scope, technology selection, UI/UX direction, performance policy, privacy boundary, model/provider usage, vector database strategy, QQ behavior, or destructive operation.

#### Scenario: A decision is needed

- **WHEN** a technical boundary or user experience direction has multiple viable options
- **THEN** the system SHALL ask for confirmation with at least two options.
- **AND** the selected option SHALL be written to the decision record before implementation.

### Requirement: Double self-audit gate

The system SHALL run a start audit and an acceptance audit for every phase.

#### Scenario: Start audit passes

- **WHEN** a phase is about to begin
- **THEN** the audit SHALL answer whether the plan covers all objectives, whether the technical solution is feasible, whether resources are sufficient, and whether risks are controlled.
- **AND** implementation SHALL begin only when the conclusion is passed.

#### Scenario: Acceptance audit passes

- **WHEN** a phase claims completion
- **THEN** code quality, runtime debugging evidence, security review, Electron/user-experience evidence, and checklist results SHALL be recorded.
- **AND** failed audit items SHALL generate remediation tasks before the next phase begins.

### Requirement: Accumulative validation

The system SHALL validate completed modules cumulatively instead of only testing the latest module.

#### Scenario: Module B completes after Module A

- **WHEN** Module B is completed
- **THEN** the validation report SHALL verify Module A independently and A+B integration together.
- **AND** any regression in Module A SHALL stop the current work and create a regression problem report.

### Requirement: UTF-8 chunk-safe Electron networking

The system SHALL decode HTTP JSON and SSE streams in Electron without corrupting multibyte UTF-8 characters.

#### Scenario: Chinese JSON crosses chunk boundary

- **WHEN** a Chinese JSON response is split in the middle of a multibyte character
- **THEN** the renderer SHALL receive the original text without `�`.

#### Scenario: Chinese SSE crosses chunk boundary

- **WHEN** SSE frames contain Chinese text split across chunks
- **THEN** frame parsing SHALL preserve complete characters and frame boundaries.

### Requirement: Unified attachment Artifact pipeline

The system SHALL normalize desktop attachments into AttachmentEnvelope and typed Artifact records before they enter rendering, history, or AI context.

#### Scenario: Same file is parsed once

- **WHEN** a file is uploaded from the desktop chat UI
- **THEN** it SHALL use one authoritative pipeline and one attachment id.
- **AND** legacy handlers SHALL not create a second divergent representation.

#### Scenario: Attachment enters AI context

- **WHEN** a ready attachment is included in a message
- **THEN** the AI context SHALL include trusted-boundary metadata, artifact parts, source ranges, parser status, and warnings.

### Requirement: Structured image observation

The system SHALL convert image understanding results into ImageObservation objects with object list, OCR text, scene, relations, confidence, uncertainty, provider metadata, and memory eligibility.

#### Scenario: Image is recognized

- **WHEN** a user uploads an image and requests understanding
- **THEN** the system SHALL produce a structured ImageObservation.
- **AND** it SHALL not write the observation to long-term memory unless explicitly confirmed or admitted by memory rules.

### Requirement: Visual intent routing

The system SHALL route generated image requests through VisualIntentRouter before any image provider receives reference assets.

#### Scenario: Environment object image

- **WHEN** the visual intent is `environment_object`
- **THEN** `reference_assets` SHALL be empty.
- **AND** the prompt SHALL derive environment details from WorldSnapshot or OfficeContext.

#### Scenario: Role selfie image

- **WHEN** the visual intent is `role_selfie` or `role_in_scene`
- **THEN** the request SHALL freeze the current PersonaConfig visual identity revision.
- **AND** generation SHALL be rejected or retried if identity consistency checks fail.

### Requirement: Frontend attachment preview

The system SHALL render attachment state and artifacts with readable previews and safe actions.

#### Scenario: Attachment is ready

- **WHEN** an attachment status becomes `ready`
- **THEN** the chat bubble and history view SHALL show filename, size, type, parser status, preview affordance, retry/remove/open/download actions where applicable.
- **AND** no local absolute path SHALL be exposed to the renderer UI.

### Requirement: Dedicated vector knowledge connection attempt

The system SHALL attempt to connect the generated knowledge base to a dedicated vector knowledge architecture, or record why this cannot be completed in the current repository state.

#### Scenario: Vector infrastructure is available

- **WHEN** a vector database or embedding adapter exists
- **THEN** the knowledge vault summary SHALL be indexed or prepared through that adapter.
- **AND** a search test SHALL verify semantic retrieval of at least three fusion concepts.

#### Scenario: Vector infrastructure is unavailable

- **WHEN** no vector database or embedding adapter exists
- **THEN** the report SHALL record detected capabilities, missing interfaces, proposed adapter boundary, and blocked reason.

## MODIFIED Requirements

### Requirement: Existing desktop full audit

The existing desktop audit SHALL be extended to include Echo/Pyisland/Aerie P0 fusion surfaces: attachment previews, image observation state, visual intent routing evidence, knowledge source links, and vector connection attempt evidence.

### Requirement: Existing attachment handling

The existing attachment handling SHALL preserve current safe states and status APIs while normalizing all new desktop uploads through the unified artifact contract.

### Requirement: Existing World lifecycle

The existing World lifecycle SHALL remain default-off on first launch, but its WorldSnapshot SHALL be available to visual intent routing and proactive image planning when enabled and healthy.

## REMOVED Requirements

### Requirement: Unbounded first-round scope

**Reason**: The first round is explicitly limited to P0 closure to reduce regression risk.
**Migration**: P1 relationship panels, desktop office entry, voice, stickers, and clone voice remain follow-up scopes after P0 acceptance.

### Requirement: Markdown-only attachment truth source

**Reason**: Markdown projection loses tables, page numbers, sheets, slides, images, warnings, and trust boundaries.
**Migration**: Markdown remains a display projection; Artifact is the authoritative internal representation.
