# Phase 4：技能市场 + 自主知识库 实施计划

> 基于 Phase 3 代码现状（67 tests green），按开发笔记扩展。
> 版本目标：v0.4.0

---

## 一、Phase 3 接口现状（审计结论）

| 模块 | 关键接口 | Phase 4 影响 |
|------|---------|-------------|
| `AIBrain` | `generate_reply()`, `generate_with_tools()`, `classify_intent()` | 无变更，call_api_raw 已支持任意 messages |
| `ToolRegistry` | `register()`, `get_openai_tools()`, `execute()` | 技能包安装后动态注册新工具 |
| `ContextBuilder` | `build(msg, capability_level, ...) ` | 新增 `capability_level="phase4"` + 知识库注入 |
| `PersonalityEngine` | `build_system_prompt(memories, capability_level)` | 新增 `CAPABILITY_PHASE4` |
| `CommandPipeline` | `execute(msg)` | 无变更（工具执行链路复用） |
| `Companion` | `handle_message()` | 新增 knowledge_base 初始化 + SkillManager 初始化 |

所有接口向上兼容，Phase 4 为纯增量开发。

---

## 二、新增文件清单（8 个核心文件 + 5 个测试文件）

### A. 知识库模块 (`knowledge/`)
| 文件 | 职责 |
|------|------|
| `knowledge/__init__.py` | KnowledgeBase facade（对外统一接口） |
| `knowledge/store.py` | SQLite 知识条目存储 + 向量索引（siliconflow embedding API） |
| `knowledge/ingest.py` | 五源采集：对话提取 / 文件吸收 / 网页提取 / 主动投喂 / 文件系统发现 |
| `knowledge/classifier.py` | 自动分类：HDBSCAN 聚类 + LLM 命名 |
| `knowledge/reorganizer.py` | 知识重组：去重 / 矛盾解决 / 碎片整理 / 冷热分离 |

### B. 技能市场 + 文档管道 (`tools/`)
| 文件 | 职责 |
|------|------|
| `tools/skill_manager.py` | 技能搜索 / 下载 / 安装 / 注册 + QQ 审批流程 |
| `tools/doc_pipeline.py` | Markitdown 文档管道：任意格式 → MD → AI → 原格式 |

### C. 修改文件
| 文件 | 变更 |
|------|------|
| `core/personality.py` | 新增 `CAPABILITY_PHASE4` + `build_system_prompt` 支持 `phase4` |
| `memory/context_builder.py` | `build()` 新增 knowledge_store 参数注入 |
| `main.py` | 初始化 KnowledgeBase + SkillManager，context_builder 注入知识库 |
| `config/settings.yaml` | 新增 `knowledge:` 和 `skills:` 配置节 |
| `requirements.txt` | 新增 `markitdown`, `hdbscan`, `scikit-learn`, `numpy` |

### D. 测试文件
| 文件 | 覆盖 |
|------|------|
| `tests/test_knowledge_store.py` | 知识存储 CRUD + 向量检索 |
| `tests/test_knowledge_ingest.py` | 对话/文件/网页 知识提取 |
| `tests/test_knowledge_reorganizer.py` | 去重 / 矛盾 / 碎片整理 / 归档 |
| `tests/test_skill_manager.py` | 技能搜索 / 安装 / 注册 |
| `tests/test_doc_pipeline.py` | Markitdown 转换 / 格式往返 |

---

## 三、连通性验证点（10 个）

| 编号 | 测试点 | 验收标准 |
|------|--------|---------|
| CV-1 | KnowledgeBase 初始化 → SQLite 建表 | 3 张表 (entries, categories, changelog) 正确创建 |
| CV-2 | 知识提取 → 向量嵌入 → 存储 | embedding 生成成功，向量正确序列化 |
| CV-3 | 语义检索 → 返回 Top-K | 输入 query → 返回相关条目，相似度排序正确 |
| CV-4 | 对话中自动提取知识 | 模拟对话 → ingest_from_conversation → 存入 entries |
| CV-5 | ContextBuilder Phase 4 注入知识库 | build(msg, capability_level="phase4") → system prompt 含知识库条目 |
| CV-6 | 去重检测 → 合并 | 两条相似度 > 0.92 → 合并为一条 |
| CV-7 | 冷数据归档 | 90 天未访问 → status="archived" |
| CV-8 | SkillManager 搜索 → 安装 → 注册 | skill 包下载 → pip install → ToolRegistry.register |
| CV-9 | DocPipeline: docx → md → AI | 文档格式转换 → token 节省 > 90% |
| CV-10 | 全量回归测试 | Phase 1-3 所有 67 个测试仍然通过 + 新增 ~15 个 Phase 4 测试 |

---

## 四、实施顺序

```
Step 1: knowledge/store.py（SQLite 存储 + 向量索引）
Step 2: knowledge/ingest.py（五种采集源）
Step 3: knowledge/classifier.py（HDBSCAN 自动分类）
Step 4: knowledge/reorganizer.py（去重/矛盾/碎片/归档）
Step 5: knowledge/__init__.py（KnowledgeBase facade）
Step 6: tools/doc_pipeline.py（Markitdown 文档管道）
Step 7: tools/skill_manager.py（技能市场 + QQ 审批）
Step 8: personality.py Phase 4 → context_builder Phase 4 → main.py 集成
Step 9: 测试 + 连通性验证
```
