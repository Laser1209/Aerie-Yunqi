---
title: Task 3.6 向量知识库连接尝试报告
date: 2026-07-28T00:00:00
change-id: execute-third-correction-p0-fusion
doc-type: audit-record
task: Task 3.6
status: blocked-with-evidence
tags:
  - Aerie
  - 第三次修正计划
  - 向量知识库
  - 阻塞证据
---

# Task 3.6 向量知识库连接尝试报告

## 基本信息

| 字段 | 内容 |
| --- | --- |
| 任务编号 | Task 3.6 |
| 任务名称 | 尝试连接专用向量知识库 |
| 尝试时间 | 2026-07-28T00:00:00 |
| 执行人 | TRAE |
| 结论 | 阻塞——当前环境无法激活向量知识库连接 |
| 关联检查项 | C3.13 |

## 能力探测结果

### 1. ChromaDB 集成代码（已编写但未激活）

| 探测项 | 结果 | 证据 |
| --- | --- | --- |
| 代码存在 | 是 | [long_permanent.py](../../../memory/layers/long_permanent.py) L67-L87 |
| 依赖已安装 | 否 | `requirements.txt` L114 `# chromadb>=1.5.9` 被注释；`python -c "import chromadb"` 失败 `ModuleNotFoundError` |
| 生产代码实例化 | 否 | `core/companion.py` 使用 `memory/memory_store.py`（SQLite LIKE），未使用 `LayeredMemory` |
| 持久化目录存在 | 否 | `data/chroma` 目录不存在 |
| `embedding_fn` 参数传入 | 否 | `LayeredMemory.__init__()` 的 `embedding_fn` 从未被传入实际值 |

### 2. Embedding Provider 接口（已编写但未激活）

| 探测项 | 结果 | 证据 |
| --- | --- | --- |
| 代码存在 | 是 | [brain.py](../../../core/brain.py) L1420-L1519 `_brain_bge_embed()` |
| API Key 已配置 | 否 | `AERIE_EMBEDDING_API_KEY` = (not set)；`OPENAI_EMBEDDING_API_KEY` = (not set) |
| Base URL 已配置 | 否 | `AERIE_EMBEDDING_BASE_URL` = (not set) |
| Model 已配置 | 否 | `AERIE_EMBEDDING_MODEL` = (not set) |
| 默认行为 | 返回 stub | 无 API Key 时返回空 embedding，不调用外部服务 |
| `.env.example` 暴露 | 否 | 环境变量未在 `.env.example` 中列出 |

### 3. 数据库 Schema 向量支持

| 探测项 | 结果 | 证据 |
| --- | --- | --- |
| `knowledge_base` 表有向量列 | 否 | [database.py](../../../core/database.py) L73-L82 纯文本列 |
| `long_term_memory` 表有向量列 | 否 | 有 `has_embedding` 标记列但始终为 0，无实际向量列 |
| sqlite-vec/pgvector 扩展 | 否 | 未使用任何向量扩展 |

### 4. RAG 管线

| 探测项 | 结果 | 证据 |
| --- | --- | --- |
| 关键词 RAG 骨架 | 是 | [context_builder.py](../../../core/context_builder.py) `_build_retrieval_section()` |
| 语义检索 | 否 | 无向量相似度检索 |
| 计划文档存在 | 是 | [plan-hermes-obsidian-knowledge-base.md](../../documents/plan-hermes-obsidian-knowledge-base.md) |
| LanceDB 代码实现 | 否 | `knowledge/vector_store.py` 等文件不存在 |

### 5. 关键断裂点

| 断裂点 | 说明 |
| --- | --- |
| `companion.py` 未使用 `LayeredMemory` | 生产代码使用简单 SQLite，未接入四层记忆架构 |
| `brain.bge_embed()` 未连接记忆系统 | embedding 能力与向量存储完全脱节 |
| `embedding_fn` 从未传入 | `LayeredMemory` 接受参数但所有调用方均未传入 |
| 环境变量未暴露 | 用户无法发现和配置 embedding 能力 |

## 缺失接口清单

1. **语义搜索 API**：`POST /api/knowledge/search` — 不存在
2. **向量索引管理 API**：`POST /api/knowledge/reindex`、`GET /api/knowledge/stats` — 不存在
3. **Embedding 服务连接**：`brain.bge_embed()` 存在但未连接到任何向量存储
4. **Vault 文件监听**：完全不存在
5. **知识图谱**：完全不存在
6. **结果重排器**：完全不存在

## 阻塞原因

1. **ChromaDB 依赖未安装**：`requirements.txt` 中被注释，`import chromadb` 失败
2. **Embedding API 未配置**：所有 `AERIE_EMBEDDING_*` 环境变量均未设置
3. **生产代码未接入**：`companion.py` 使用简单 SQLite，未使用 `LayeredMemory`
4. **持久化目录不存在**：`data/chroma` 从未创建

## 推荐专用向量库边界

### 方案 A：激活 ChromaDB 路径（推荐，改动最小）

- 安装 `chromadb>=1.5.9`
- 配置 `AERIE_EMBEDDING_API_KEY` 和相关环境变量
- 在 `companion.py` 中切换到 `LayeredMemory`
- 将 `brain.bge_embed()` 作为 `embedding_fn` 传入 `LayeredMemory`
- 创建 `data/chroma` 目录
- 风险：ChromaDB 安装可能引入大量依赖；API Key 配置需要外部服务

### 方案 B：实现 LanceDB 路径（计划文档已设计）

- 安装 `lancedb>=0.10.0`、`sentence-transformers>=3.0.0`
- 创建 `knowledge/vector_store.py`、`knowledge/embedders.py`、`knowledge/rag.py`
- 按计划文档实现 Obsidian Vault 索引
- 风险：工作量大，需要本地 GPU 运行 BGE 模型

### 方案 C：使用 sqlite-vec 轻量扩展

- 安装 `sqlite-vec` 扩展
- 在现有 SQLite 表中添加向量列
- 使用 `brain.bge_embed()` 生成向量
- 风险：sqlite-vec 成熟度较低，性能可能不足

## 后续设计建议

1. **短期**：在 `.env.example` 中暴露 `AERIE_EMBEDDING_*` 环境变量，让用户知道有此能力
2. **中期**：激活 ChromaDB 路径（方案 A），将 Obsidian Vault 摘要写入索引
3. **长期**：实现完整的 LanceDB + RAG 管线（方案 B），支持语义检索和知识图谱

## 验证命令记录

| 命令 | 结果 | 说明 |
| --- | --- | --- |
| `python -c "import chromadb"` | `ModuleNotFoundError: No module named 'chromadb'` | ChromaDB 未安装 |
| `python -c "import os; ..."` | 所有环境变量 = (not set) | Embedding API 未配置 |
| `ls data/chroma` | 目录不存在 | ChromaDB 从未初始化 |
