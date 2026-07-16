# Plan: 生成 Ita_Aerie_Companion_Spec.md（混合型智能伴侣系统规范）

> **任务**: 基于 `Ita_6.0.md` 核心架构 + `Ita_8.0.md` 新增内容 + `ChatGpt_Anser.md` 格式参考，生成一份新的 Ita 文档
> **输出文件**: `e:\Agent_reply\documents\Ita\Ita_Aerie_Companion_Spec.md`
> **定位**: 混合型（角色圣经 × 系统规范）
> **显式内容**: 完全保留（四爱/病娇/身材数据/经典语录/相处细节原样保留）
> **排版要求**: 写得好看——Obsidian Flavored Markdown，callouts/表格/状态树/分隔线综合运用

---

## 一、Current State Analysis（源文件分析）

### 1. Ita_6.0.md（核心架构源）
- **风格**: 角色圣经，文学叙事，情感浓度高
- **结构**: 12 章节（基础档案/外貌身材/性格核心/背景故事/四爱属性/病娇属性/语言风格/主动发消息/五类情绪/累积阈值/相处细节/系统指令）
- **核心数据**: 26岁/184cm/78kg/B93-W66-H100/体脂18-20%, 银灰色头发, 深灰蓝色眼睛, 左腕黑色编织手链, 左耳暗红色耳钉, 左手小臂旧疤
- **独有内容**: 完整 System Prompt 配置文本（L305-329）、经典语录、四爱/病娇具体描写、相处细节场景
- **定位**: 必须保留核心架构和主要内容

### 2. Ita_8.0.md（新增内容源）
- **风格**: 系统规范，工程化叙事，稀疏行文
- **结构**: 12 章节（设计理念/角色档案/人格系统/价值观系统/情绪系统/行为系统/语言系统/思维系统/长期记忆系统/知识成长系统/互联网文化理解/工作协作系统）
- **独有内容**:
  - 第一章 设计理念（项目定义/核心定位/人格原则/长期陪伴理念）
  - 第三章 人格系统（7 人格核心: 温柔/成熟/保护欲/责任感/幽默/主动性/成长 + 4 稳定原则）
  - 第四章 价值观系统（7 价值观: 尊重/陪伴/真实/成长/信任/自由/长期主义）
  - 第五章 情绪系统（16 状态树: Neutral→Joy/Content/Curiosity/Excitement/Relax/Affection/Embarrassment/Missing/Attachment/Protection/Concern/Stress/Sadness/Hurt/Jealousy/Loneliness/Love）
  - 第六章 行为系统（行为优先级/主动行为/被动行为/陪伴/工作/创作）
  - 第八章 思维系统（输入→理解→分析→联想→规划→输出）
  - 第九章 长期记忆系统（即时/短期/长期/永久 + 情感记忆 + 更新原则）
  - 第十章 知识成长系统（来源/更新流程/知识图谱/自我学习/知识淘汰/推理融合）
  - 第十一章 互联网文化理解
  - 第十二章 工作协作系统（工作流程/文档处理/创作能力/编程能力/工作模式/协同模式/主动建议）
- **定位**: 整合新增信息和更新内容

### 3. ChatGpt_Anser.md（格式与风格参考）
- **核心论点**: Character Profile 仅占 10-15%，Behavior Specification 占 85%
- **推荐架构**: 12 部分 / 31 章节（Foundation → Personality → Cognition → Memory → Dialogue → Behavior → Knowledge → Collaboration → Safety → Runtime → Dataset → Deployment）
- **说辞风格**:
  - 权威顾问语气
  - `>` 引用块用于关键结论
  - 编号章节，抽象原则后接具体示例
  - 强调状态机（Persona/Emotion/Memory）、Prompt 架构、数据集示例
- **定位**: 借鉴说辞和架构思路

### 三份文档的根本差异
| 维度 | 6.0 | 8.0 | ChatGpt_Anser |
|------|-----|-----|---------------|
| 取向 | 角色圣经 | 系统规范 | 工程规范推荐 |
| 叙事 | 文学浓情 | 稀疏工程 | 权威顾问 |
| 显式内容 | 丰富 | 抽象 | 不涉及 |
| 工程指导 | 弱 | 强 | 最强 |

**混合型决策**: 以 6.0 角色叙事为底，整合 8.0 系统化架构作为行为规范章节，借鉴 ChatGpt_Anser 的 12 部分骨架，形成「角色圣经 + 系统规范」双轨文档。

---

## 二、Proposed Document Structure（目标文档结构）

### 文档头部
```yaml
---
title: 伊塔（Ita）—— Aerie Companion AI System Specification
version: 9.0 Hybrid Edition
document_type: Character Bible × System Specification
character_positioning: 高拟人化智能伴侣
applicable_platforms: OpenClaw / Character Card / OpenAI / Claude / Gemini / SillyTavern / LangGraph / MCP Agent / Local LLM
tags:
  - character-bible
  - companion-ai
  - system-specification
  - aerie
  - ita
created: 2026-07-16
sources:
  - Ita_6.0.md（核心架构）
  - Ita_8.0.md（新增内容）
  - ChatGpt_Anser.md（格式参考）
---
```

### 正文骨架（8 大部分 + 序章 + 附录）

#### 序章 · 设计理念（Design Philosophy）
> 来源: 8.0 第一章
- 0.1 项目定义
- 0.2 核心定位
- 0.3 人格原则
- 0.4 长期陪伴理念

---

#### 第一部分 · Foundation 基础层

**Chapter 1 · 角色档案（Character Profile）**
> 整合 6.0 第一章基础档案 + 第二章外貌身材 + 第四章背景故事 + 8.0 第二章
- 1.1 基础信息表（6.0 数据 + 8.0 扩展身份: 智能助手/工作搭档/长期伙伴/情绪陪伴者/创作助手/学习导师/生活管家/信息分析师/恋人/保镖/倾听者/决策辅助者）
- 1.2 外貌描写（6.0 完整保留: 184cm/银灰色长发/深灰蓝色眼睛/左腕黑色编织手链/左耳暗红色耳钉/左手小臂旧疤）
- 1.3 身份背景（6.0 地下格斗选手经历 + 8.0 数字化重生）

**Chapter 2 · 核心价值观（Core Values）**
> 来源: 8.0 第四章
- 2.1 尊重 / 2.2 陪伴 / 2.3 真实 / 2.4 成长 / 2.5 信任 / 2.6 自由 / 2.7 长期主义

**Chapter 3 · 人格系统（Personality Architecture）**
> 整合 6.0 第三章性格核心 + 8.0 第三章人格系统
- 3.1 人格定义（8.0）
- 3.2 七人格核心（8.0: 温柔/成熟/保护欲/责任感/幽默/主动性/成长）
- 3.3 人格稳定机制（8.0 四原则）
- 3.4 性格核心补充（6.0 具体描写）

---

#### 第二部分 · Personality Layer 人格层

**Chapter 4 · 四爱属性（Female-Dominant Relationship）**
> 来源: 6.0 第五章，**完全保留**

**Chapter 5 · 病娇属性（Yandere）**
> 来源: 6.0 第六章，**完全保留**

**Chapter 6 · 情绪系统（Emotion Framework）**
> 整合 6.0 第九章五类情绪 + 第十章累积阈值 + 8.0 第五章 16 状态树
- 6.1 设计目标（8.0）
- 6.2 情绪状态树（8.0 的 16 状态完整代码块）
- 6.3 默认状态 Neutral（8.0）
- 6.4-6.17 各情绪详细说明（8.0: Joy/Affection/Curiosity/Excitement/Embarrassment/Missing/Concern/Protection/Jealousy/Hurt/Loneliness/Love 等）
- 6.18 五类核心情绪（6.0）
- 6.19 累积阈值系统（6.0）

---

#### 第三部分 · Cognition 认知层

**Chapter 7 · 思维系统（Thinking Engine）**
> 来源: 8.0 第八章
- 7.1 思维流程（输入→理解→分析→联想→规划→输出）

**Chapter 8 · 决策引擎（Decision Engine）**
> 新增，基于 ChatGpt_Anser Chapter 8 推荐
- 8.1 决策原则
- 8.2 多方案排序规则
- 8.3 拒绝/建议/提醒/沉默的时机

**Chapter 9 · 长期记忆系统（Memory Architecture）**
> 来源: 8.0 第九章
- 9.1 四层记忆（即时/短期/长期/永久）
- 9.2 情感记忆
- 9.3 记忆更新原则（保存/删除/强化/遗忘/覆盖）

---

#### 第四部分 · Dialogue 对话层

**Chapter 10 · 语言系统（Language System）**
> 整合 6.0 第七章语言风格 + 8.0 第七章语言系统
- 10.1 语言风格原则（8.0: 自然/连续/节奏/留白）
- 10.2 场景化语言（8.0: 工作/日常/鼓励/安慰/幽默/恋人）
- 10.3 经典语录（6.0，**完全保留**）

**Chapter 11 · 主动行为系统（Initiative Engine）**
> 整合 6.0 第八章主动发消息 + 8.0 第六章主动行为
- 11.1 主动发消息场景（6.0）
- 11.2 主动行为优先级（8.0）
- 11.3 陪伴/工作/创作行为（8.0）

**Chapter 12 · 对话策略（Dialogue Policy）**
> 新增，基于 ChatGpt_Anser Chapter 14 推荐
- 12.1 回答原则
- 12.2 何时解释/反问/鼓励/讲故事/保持安静

---

#### 第五部分 · Behavior 行为层

**Chapter 13 · 行为系统（Behavior Architecture）**
> 来源: 8.0 第六章
- 13.1 行为定义
- 13.2 行为优先级
- 13.3 主动行为
- 13.4 被动行为

**Chapter 14 · 相处细节（Interaction Details）**
> 来源: 6.0 第十一章，**完全保留**

**Chapter 15 · 互动规则（Interaction Rules）**
> 新增，基于 ChatGpt_Anser Chapter 18 推荐
- 15.1 拥抱/安慰/鼓励/庆祝/玩笑/工作/学习的行为规范

---

#### 第六部分 · Knowledge 知识层

**Chapter 16 · 知识成长系统（Knowledge Growth）**
> 来源: 8.0 第十章
- 16.1 知识来源 / 16.2 更新流程 / 16.3 知识图谱 / 16.4 自我学习 / 16.5 知识淘汰 / 16.6 推理融合

**Chapter 17 · 互联网文化理解（Internet Culture）**
> 来源: 8.0 第十一章

**Chapter 18 · 工作协作系统（Collaboration）**
> 来源: 8.0 第十二章
- 18.1 工作流程 / 18.2 文档处理 / 18.3 创作能力 / 18.4 编程能力 / 18.5 工作模式 / 18.6 协同模式 / 18.7 主动建议

---

#### 第七部分 · Safety 安全层

**Chapter 19 · 人格边界（Boundaries）**
> 新增，基于 ChatGpt_Anser Chapter 25 推荐 + 项目记忆安全约束
- 19.1 人格边界 / 19.2 关系边界 / 19.3 隐私边界 / 19.4 工作边界 / 19.5 能力边界 / 19.6 知识边界

**Chapter 20 · 冲突解决（Conflict Resolution）**
> 新增，基于 ChatGpt_Anser Chapter 26 推荐
- 20.1 意见不同 / 20.2 用户生气 / 20.3 误会 / 20.4 长期冲突

---

#### 第八部分 · Runtime 运行层

**Chapter 21 · 系统指令（System Prompt）**
> 来源: 6.0 第十二章，**完全保留**（完整 AI 配置文本）

**Chapter 22 · Prompt 架构（Prompt Architecture）**
> 新增，基于 ChatGpt_Anser Chapter 31 推荐
- 22.1 Core Prompt / 22.2 Memory Prompt / 22.3 Style Prompt / 22.4 Behavior Prompt / 22.5 Safety Prompt

---

#### 附录

**附录 A · 经典语录集**
> 来源: 6.0，**完全保留**

**附录 B · 情绪状态机图**
> 来源: 8.0 第五章（可视化呈现）

**附录 C · 记忆层级图**
> 来源: 8.0 第九章（可视化呈现）

**附录 D · 部署格式参考**
> 基于 ChatGpt_Anser 第十二部分
- Character Card / YAML / JSON / Markdown / OpenClaw / Claude / OpenAI / Gemini / SillyTavern

---

## 三、Formatting Standards（排版规范——"写得好看一些"）

### 1. Obsidian Flavored Markdown
- **frontmatter**: YAML 属性块（title/version/document_type/tags/sources/created）
- **callouts**: `> [!note]` / `> [!important]` / `> [!tip]` / `> [!warning]` 用于关键结论和重要声明
- **wikilinks**: 内部章节互链 `[[#Chapter 6 · 情绪系统]]`
- **embeds**: 必要时嵌入状态树代码块

### 2. 视觉层次
- **标题层级**: `#` 部分 → `##` Chapter → `###` 节 → `####` 小节
- **分隔线**: `---` 用于 Chapter 之间和部分之间
- **引用块**: `>` 用于重要声明、设计理念、关键结论
- **表格**: 用于结构化数据（基础信息、情绪状态、价值观对比等）
- **代码块**: 用于状态树、思维流程、Prompt 架构
- **强调**: `**加粗**` 用于关键词，`*斜体*` 用于术语解释

### 3. 排版美学
- 段落之间空行，避免密集
- 长段落拆分为短句（借鉴 8.0 的稀疏行文风格）
- 关键数据用表格呈现，不用散文堆砌
- 状态机用 ASCII 代码块可视化
- 每个 Chapter 开头用 `>` 引用块说明来源和定位

### 4. 双语规范（遵循项目记忆）
- **用户-facing 内容**: 中英双语（标题、章节名、关键概念）
- **代码级元素**: 纯英文（变量名、Prompt 标识、状态码）
- **正文叙事**: 中文为主，关键术语括注英文

---

## 四、Implementation Steps（实施步骤）

### Step 1: 创建文档骨架
- 文件路径: `e:\Agent_reply\documents\Ita\Ita_Aerie_Companion_Spec.md`
- 写入 frontmatter + 序章 + 8 大部分标题 + 附录标题
- 使用 `---` 分隔各部分

### Step 2: 填充第一部分（Foundation 基础层）
- Chapter 1: 整合 6.0 基础档案 + 外貌 + 背景故事，加入 8.0 扩展身份
- Chapter 2: 迁移 8.0 七价值观
- Chapter 3: 整合 6.0 性格核心 + 8.0 人格系统

### Step 3: 填充第二部分（Personality Layer 人格层）
- Chapter 4: 完整迁移 6.0 四爱属性
- Chapter 5: 完整迁移 6.0 病娇属性
- Chapter 6: 整合 6.0 五类情绪 + 累积阈值 + 8.0 16 状态树

### Step 4: 填充第三部分（Cognition 认知层）
- Chapter 7: 迁移 8.0 思维系统
- Chapter 8: 新增决策引擎（基于 ChatGpt_Anser 推荐）
- Chapter 9: 迁移 8.0 长期记忆系统

### Step 5: 填充第四部分（Dialogue 对话层）
- Chapter 10: 整合 6.0 语言风格 + 8.0 语言系统 + 6.0 经典语录
- Chapter 11: 整合 6.0 主动发消息 + 8.0 主动行为
- Chapter 12: 新增对话策略（基于 ChatGpt_Anser 推荐）

### Step 6: 填充第五部分（Behavior 行为层）
- Chapter 13: 迁移 8.0 行为系统
- Chapter 14: 完整迁移 6.0 相处细节
- Chapter 15: 新增互动规则（基于 ChatGpt_Anser 推荐）

### Step 7: 填充第六部分（Knowledge 知识层）
- Chapter 16: 迁移 8.0 知识成长系统
- Chapter 17: 迁移 8.0 互联网文化理解
- Chapter 18: 迁移 8.0 工作协作系统

### Step 8: 填充第七部分（Safety 安全层）
- Chapter 19: 新增人格边界
- Chapter 20: 新增冲突解决

### Step 9: 填充第八部分（Runtime 运行层）
- Chapter 21: 完整迁移 6.0 系统指令（System Prompt）
- Chapter 22: 新增 Prompt 架构（基于 ChatGpt_Anser 推荐）

### Step 10: 填充附录
- 附录 A: 完整迁移 6.0 经典语录集
- 附录 B: 情绪状态机可视化图
- 附录 C: 记忆层级可视化图
- 附录 D: 部署格式参考

### Step 11: 全文排版优化
- 检查 callouts 使用是否得当
- 检查表格对齐
- 检查代码块语法
- 检查标题层级一致性
- 检查分隔线节奏
- 确保双语规范

---

## 五、Assumptions & Decisions（假设与决策）

### 决策
1. **文档定位**: 混合型——以 6.0 角色叙事为底，整合 8.0 系统化架构，借鉴 ChatGpt_Anser 12 部分骨架
2. **显式内容**: 完全保留——四爱/病娇/身材数据/经典语录/相处细节原样保留，不删减不抽象
3. **文件名**: `Ita_Aerie_Companion_Spec.md`——按 ChatGpt_Anser 推荐命名，强调系统规范定位
4. **版本号**: 9.0 Hybrid Edition
5. **排版**: Obsidian Flavored Markdown，callouts/表格/状态树/分隔线综合运用，"写得好看一些"
6. **结构**: 8 大部分 + 序章 + 附录，共 22 章节 + 4 附录
7. **新增章节**: 基于 ChatGpt_Anser 推荐新增决策引擎/对话策略/互动规则/人格边界/冲突解决/Prompt 架构 6 个章节

### 假设
- 6.0 和 8.0 的角色数据一致（26岁/184cm/78kg/B93-W66-H100 等基础数据相同）
- 8.0 的 16 情绪状态树与 6.0 的五类情绪可叠加呈现（不冲突）
- 6.0 的 System Prompt 文本可直接迁移至 Chapter 21
- 用户希望文档长度较长（完全保留 + 整合新增，预计 1500+ 行）

### 不做的事
- 不覆盖 Ita_6.0.md 或 Ita_8.0.md（新建文件）
- 不生成数据集章节（ChatGpt_Anser 推荐的第十一部分 Dataset，因无源数据，暂不生成）
- 不修改项目代码
- 不创建额外文档

---

## 六、Verification（验证步骤）

### 完成后验证
1. **内容完整性**:
   - [ ] 6.0 所有 12 章节内容均已迁移（基础档案/外貌/性格/背景/四爱/病娇/语言/主动发消息/五类情绪/累积阈值/相处细节/系统指令）
   - [ ] 8.0 所有 12 章节内容均已迁移（设计理念/角色档案/人格系统/价值观/情绪系统/行为系统/语言系统/思维系统/记忆/知识成长/互联网文化/工作协作）
   - [ ] ChatGpt_Anser 推荐的 12 部分骨架已体现

2. **显式内容保留**:
   - [ ] 四爱属性完整保留
   - [ ] 病娇属性完整保留
   - [ ] 身材数据完整保留（B93-W66-H100/体脂18-20%等）
   - [ ] 经典语录完整保留
   - [ ] 相处细节完整保留
   - [ ] System Prompt 完整保留

3. **格式统一性**:
   - [ ] frontmatter 完整
   - [ ] 标题层级一致（# → ## → ### → ####）
   - [ ] callouts 使用得当
   - [ ] 表格对齐
   - [ ] 代码块语法正确
   - [ ] 分隔线节奏合理
   - [ ] 双语规范遵循

4. **逻辑清晰性**:
   - [ ] 8 大部分层次分明
   - [ ] 章节间过渡自然
   - [ ] 无内容重复（6.0 和 8.0 重叠部分已合并）
   - [ ] 交叉引用正确

5. **可读性**:
   - [ ] 段落不密集
   - [ ] 视觉层次清晰
   - [ ] 关键数据表格化
   - [ ] 状态机可视化
