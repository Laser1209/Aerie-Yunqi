---
title: Aerie 第三次修正计划 P1 陪伴融合与能力扩展 Spec
date: 2026-07-28
change-id: execute-p1-companion-fusion
status: pending-approval
tags:
  - Aerie
  - Echo
  - Pyisland
  - companion-state
  - relationship-panel
  - office-context
  - voice
  - sticker
  - vector-knowledge
---

# Aerie 第三次修正计划 P1 陪伴融合与能力扩展 Spec

> [!summary]
> 本规格承接 P0 融合闭环成果，开启 P1 阶段。P1 范围覆盖 P0 deferred 项（C3.5 Artifact 边界）、向量知识库激活、关系/成长/记忆面板、桌面办公入口、主动消息升级、语音/表情包/通道扩展。执行严格度与 P0 一致：阶段门禁、双自审计、累积验证、决策记录、Obsidian 知识库更新。

## Why

P0 已完成多模态输入底座、附件管线、视觉路由和前端预览，但 AI 上下文仍缺少 Artifact 边界（C3.5 deferred），向量知识库仍阻塞，关系/记忆/成长面板尚未可见，主动消息仍围绕单一触发点，语音/表情包/办公入口尚未接入。P1 需要在 P0 底座上建立用户可感知的陪伴状态层、办公入口和主动能力，同时激活向量检索，使 Echo/Pyisland/Aerie 融合从"能用"进入"可陪伴"。

## What Changes

- 补全 C3.5：AI 上下文使用 Artifact 边界，附件进入上下文时包含 trusted boundary、part id、页码/sheet/slide/range、parser warning。
- 新增 CompanionState 陪伴状态模型，包含 relationship_stage、care_followups、pending_topics、recent_pain_points、recent_joy_points。
- 新增共情响应策略链：validate_input → reflect → clarify → support → next_step。
- 扩展记忆可见性：source_message_id、confidence、user_confirmed、expires_at、deleted_at；前端提供"记住了什么"只读列表与删除操作。
- 新增角色配置版本化 PersonaConfig：identity_facts → visual_identity → background → speaking_style → active_rules → current_state 六类输入合并，每次保存记录 revision。
- 新增关系/成长/记忆面板前端：七面板中的聊天记录、成长、关系、记忆、向量星云可视化。
- 新增 DesktopSurfaceAdapter 与 OfficeContext：悬浮窗状态机、系统上下文、工具注册表、模式切换。
- 接入办公最小闭环：剪贴板翻译、截图问图、时间天气状态。
- 新增 ActionRegistry：低风险工具注册，危险动作二次确认。
- 新增 WorldSimulation tick → WorldSnapshot → 主动候选意图 → 候选打分 → 主动关怀治理。
- 主动消息 + 主动图片联合调度，复用 P0 VisualIntentRouter。
- 新增语音转文本（ASR）+ 语音表达（TTS）三服务边界：VoiceProfile、SpeechMarkup、VoiceDeliveryPolicy。
- 新增表情包入口：情绪/场景标签检索 + 发送审计 + 用户可关闭。
- 新增克隆音色：上传/试听/授权/撤销/删除/审计，单独走高敏感生物特征评审。
- 新增 CompanionChannel 抽象：QQ、移动网关、ClawBot 适配器，先做健康与回显。
- 激活专用向量知识库（推荐方案 A：安装 ChromaDB、配置 Embedding API、切换 LayeredMemory、传入 embedding_fn）。
- **BREAKING**：PersonaConfig 结构变更，旧配置需迁移；CompanionState 为新增模型，不影响现有数据。

## Impact

- Affected specs: `execute-third-correction-p0-fusion`（P0 deferred 项补全）、`aerie-companion-v9-buildout`（陪伴状态扩展）。
- Affected docs: Obsidian Vault 新增 P1 模块笔记、P1 计划文档、P1 决策记录、P1 审计记录。
- Affected code:
  - `core/context_builder.py`（C3.5 Artifact 边界）
  - `core/companion_state.py`（新增）
  - `core/empathy_strategy.py`（新增）
  - `core/memory_visibility.py`（新增或扩展）
  - `core/persona_config.py`（新增或扩展）
  - `core/world_simulation.py`（新增或扩展）
  - `core/push_scheduler.py`（扩展）
  - `core/voice_service.py`（新增）
  - `core/sticker_service.py`（新增）
  - `core/clone_voice_service.py`（新增）
  - `core/companion_channel.py`（新增）
  - `electron/src/desktop_surface/`（新增目录）
  - `electron/src/renderer/js/panels/`（新增目录）
  - `memory/layers/long_permanent.py`（向量库激活）
  - `core/brain.py`（embedding_fn 接入）
  - `knowledge/kb.py`（向量检索接入）
- Affected runtime: Electron 主窗口、动态岛、悬浮窗、附件 worker、知识库、向量库、测试隔离数据目录。

## Decisions

### Decision: P1 阶段划分

- Final: 四阶段——P1-A 陪伴状态与关系面板底座、P1-B 桌面办公入口与 Pyisland 融合、P1-C 主动消息升级与世界模拟联动、P1-D 语音表情包与通道扩展。
- Reason: 先补 P0 deferred 与陪伴底座，再做办公入口与主动升级，最后做语音表情包；依赖关系清晰，降低返工风险。

### Decision: 向量知识库激活方案

- Final: 推荐方案 A（激活 ChromaDB 路径）。
- Reason: 改动最小，P0 已探测到 ChromaDB 代码路径和 embedding 接口，只需安装依赖、配置环境变量、切换 LayeredMemory 并传入 embedding_fn。
- Alternatives: 方案 B（LanceDB + RAG，工作量大）、方案 C（sqlite-vec，成熟度较低）。

### Decision: 克隆音色评审边界

- Final: 克隆音色单独走高敏感生物特征评审，不与普通语音混在同一交付物中。
- Reason: 生物特征数据涉及隐私法规，需要独立的授权/撤销/删除/审计流程。

### Decision: 执行严格度

- Final: 与 P0 一致——阶段门禁确认、双自审计、累积验证、决策记录、Obsidian 知识库更新。
- Reason: 用户明确要求 P1 与 P0 一致。

## ADDED Requirements

### Requirement: AI 上下文 Artifact 边界（C3.5 补全）

The system SHALL include trusted boundary, part id, page/sheet/slide/range, and parser warning metadata when attachments enter AI context.

#### Scenario: Attachment with multiple pages enters context

- **WHEN** a ready PDF attachment with 10 pages enters AI context
- **THEN** the context SHALL include attachment_id, trusted_boundary, part_id per page, page range, and parser warnings.
- **AND** the model SHALL see structured boundaries instead of flat text.

#### Scenario: Spreadsheet with multiple sheets enters context

- **WHEN** a ready Excel attachment with 3 sheets enters AI context
- **THEN** the context SHALL include sheet names, cell ranges, and parser status per sheet.

### Requirement: CompanionState 陪伴状态模型

The system SHALL maintain a CompanionState model that tracks relationship_stage, care_followups, pending_topics, recent_pain_points, and recent_joy_points.

#### Scenario: User mentions a pain point

- **WHEN** the user describes a difficult situation
- **THEN** the system SHALL record it in recent_pain_points.
- **AND** a care_followup SHALL be scheduled for future check-in.

#### Scenario: Conversation topic is unfinished

- **WHEN** a topic is interrupted before resolution
- **THEN** the system SHALL add it to pending_topics.
- **AND** the next session SHALL surface it as a candidate continuation.

### Requirement: 共情响应策略链

The system SHALL apply a structured empathy response chain: validate_input → reflect → clarify → support → next_step.

#### Scenario: User expresses frustration

- **WHEN** the user sends a frustrated message
- **THEN** the system SHALL validate the emotion first.
- **AND** SHALL reflect the feeling back before offering solutions.

### Requirement: 记忆可见性与用户控制

The system SHALL expose what it remembers to the user, with source_message_id, confidence, user_confirmed, expires_at, and deleted_at fields.

#### Scenario: User asks what the system remembers

- **WHEN** the user opens the memory panel
- **THEN** the system SHALL show a read-only list of active memories with source, confidence, and expiry.
- **AND** the user SHALL be able to delete any memory.

#### Scenario: User deletes a memory

- **WHEN** the user deletes a memory
- **THEN** the system SHALL set deleted_at timestamp.
- **AND** the memory SHALL not appear in future context.

### Requirement: 角色配置版本化 PersonaConfig

The system SHALL version PersonaConfig with identity_facts, visual_identity, background, speaking_style, active_rules, and current_state, recording a revision on each save.

#### Scenario: Persona config is updated

- **WHEN** any field in PersonaConfig is changed
- **THEN** a new revision SHALL be recorded.
- **AND** old revision references SHALL become invalid for new generation requests.

### Requirement: 关系/成长/记忆面板前端

The system SHALL render relationship, growth, and memory panels with real data from CompanionState and memory layers.

#### Scenario: User opens relationship panel

- **WHEN** the user navigates to the relationship panel
- **THEN** the panel SHALL show familiarity, trust, affection, friction, current mood, and recent changes.
- **AND** no raw model scores or internal paths SHALL be exposed.

### Requirement: DesktopSurfaceAdapter 与 OfficeContext

The system SHALL provide a DesktopSurfaceAdapter with a floating window state machine and OfficeContext tracking active window, focused task, clipboard candidate, network state, battery state, calendar due, and notification budget.

#### Scenario: Floating window state transitions

- **WHEN** the user interacts with the floating window
- **THEN** it SHALL transition through collapsed → peek → expanded → tool-panel states.
- **AND** invalid transitions SHALL be rejected.

#### Scenario: Office mode is activated

- **WHEN** the user switches to office mode
- **THEN** companion_mode SHALL change to office_mode.
- **AND** the mode change SHALL be written to trace.

### Requirement: 办公最小闭环

The system SHALL implement clipboard translation, screenshot inquiry, and time/weather status as the minimum office loop.

#### Scenario: Clipboard translation

- **WHEN** the user copies text while office mode is active
- **THEN** the system SHALL detect the clipboard candidate and offer translation.
- **AND** the action SHALL complete in milliseconds locally.

### Requirement: ActionRegistry 工具注册

The system SHALL register low-risk tools in an ActionRegistry, with dangerous actions requiring secondary confirmation.

#### Scenario: Low-risk action

- **WHEN** a low-risk action is triggered (e.g., open URL)
- **THEN** it SHALL execute immediately.

#### Scenario: Dangerous action

- **WHEN** a dangerous action is triggered (e.g., delete file)
- **THEN** it SHALL require secondary confirmation.

### Requirement: WorldSimulation 主动消息联动

The system SHALL drive proactive messages from WorldSimulation ticks, generating WorldSnapshot with phase, location, activity, energy, social, nearby_objects, and available_visual_topics.

#### Scenario: World simulation tick produces proactive candidate

- **WHEN** a WorldSimulation tick completes
- **THEN** a WorldSnapshot SHALL be generated.
- **AND** candidate intents SHALL be scored by world freshness, relationship relevance, emotion change, user preference, and recent repetition.

#### Scenario: User ignores proactive message

- **WHEN** the user ignores a proactive message
- **THEN** the system SHALL back off with exponential delay.
- **AND** the same world_snapshot_id SHALL not produce duplicate candidates.

### Requirement: 语音 ASR/TTS 三服务边界

The system SHALL provide VoiceProfile, SpeechMarkup, and VoiceDeliveryPolicy as three distinct service boundaries for voice.

#### Scenario: User sends voice message

- **WHEN** the user sends a voice message
- **THEN** ASR SHALL transcribe it to text.
- **AND** TTS SHALL be available for response with configurable VoiceProfile.

#### Scenario: Voice is disabled

- **WHEN** the user disables voice in settings
- **THEN** no ASR or TTS SHALL be invoked.
- **AND** the setting SHALL be auditable.

### Requirement: 表情包入口

The system SHALL provide a sticker entry with emotion/scene tag retrieval, send audit, and user-disable capability.

#### Scenario: User searches for a sticker

- **WHEN** the user searches by emotion tag
- **THEN** the system SHALL return matching stickers.
- **AND** each send SHALL be audited with timestamp, sticker_id, and context.

### Requirement: 克隆音色高敏感评审

The system SHALL handle clone voice as a high-sensitivity biometric feature with upload, preview, authorization, revocation, deletion, and audit.

#### Scenario: User uploads clone voice sample

- **WHEN** the user uploads a voice sample for cloning
- **THEN** the system SHALL require explicit authorization.
- **AND** the user SHALL be able to revoke and delete the clone at any time.

### Requirement: CompanionChannel 通道抽象

The system SHALL abstract messaging channels through CompanionChannel, with QQ, mobile gateway, and ClawBot adapters.

#### Scenario: ClawBot adapter health check

- **WHEN** the ClawBot adapter is initialized
- **THEN** it SHALL perform a health check.
- **AND** disconnection SHALL show real status without fabrication.

### Requirement: 向量知识库激活

The system SHALL activate the dedicated vector knowledge base by installing ChromaDB, configuring Embedding API, switching to LayeredMemory, and passing embedding_fn.

#### Scenario: Vector search is available

- **WHEN** the vector knowledge base is activated
- **THEN** at least 3 fusion concepts SHALL be semantically retrievable.
- **AND** search results SHALL include source, score, and metadata.

## MODIFIED Requirements

### Requirement: 累积验证扩展

The P0 cumulative validation SHALL be extended to include P1 modules. Any regression in P0 modules SHALL stop P1 work and create a regression problem report.

### Requirement: Obsidian 知识库扩展

The Obsidian Vault SHALL be extended with P1 module notes, technology notes, and dependency notes, maintaining the bidirectional link loop.

## REMOVED Requirements

### Requirement: Unbounded P1 scope

**Reason**: P1 is explicitly bounded to four phases to manage regression risk.
**Migration**: P2 items (advanced RAG, multi-agent orchestration, cross-device sync) remain follow-up scopes.
