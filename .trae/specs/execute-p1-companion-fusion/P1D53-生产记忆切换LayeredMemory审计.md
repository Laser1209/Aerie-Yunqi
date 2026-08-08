---
title: P1-D.5.3 生产记忆切换 LayeredMemory 审计
date: 2026-08-09T01:00:55
change-id: execute-p1-companion-fusion
doc-type: audit-record
audit-type: capability-activation
phase: P1-D.5.3
status: wired-with-evidence
tags:
  - Aerie
  - P1 计划
  - 向量知识库
  - LayeredMemory
---

# P1-D.5.3 生产代码切换 LayeredMemory 并注入 embedding_fn——验收审计

## 验收时间

2026-08-09T00:52 ~ 2026-08-09T01:00:55

## 结论

**切换成功（wired-with-evidence）**。生产记忆从旧 `LongTermMemory` 切换到四层 `LayeredMemory`，
并注入 `embedding_fn`（复用 P1-D.5 激活的 `resolve_embedding_fn()`，走 ChromaDB 本地 ONNX 离线 embedding），
实现长期记忆的向量语义检索。context_builder / pipeline 调用方零改动。

## 变更清单

| 文件 | 变更 |
| --- | --- |
| `memory/layers/sync_adapter.py` | **新增** `LayeredMemorySyncAdapter`：把异步 `LayeredMemory` 桥接到旧同步 `LongTermMemory` 接口（store/retrieve/decay），在独立后台线程事件循环上执行协程 |
| `core/companion.py` | 导入改为 `LayeredMemory` + `LayeredMemorySyncAdapter` + `resolve_embedding_fn`；`self.memory = LayeredMemorySyncAdapter(LayeredMemory(db, chroma_persist_dir, embedding_fn=resolve_embedding_fn()))` |
| `tests/test_p1_d5_3_layered_adapter.py` | **新增** 4 个 TDD 用例 |

## 接口桥接说明

`LongTermMemory`（memory/memory_store.py）暴露同步 `store(user_id, memory_type, content, importance, *, actor_id)` / `retrieve(user_id, query, limit, *, actor_id)` / `decay()`。
`LayeredMemory` 为异步四层调度器。适配器保持旧接口不变，内部转调 `LayeredMemory.search/store/decay_long_term`。

**事件循环安全**：`context_builder.build` 是同步方法却在异步 pipeline 的事件循环内被调用，
直接 `asyncio.run()` 会抛 "already running"。适配器通过 `asyncio.run_coroutine_threadsafe` 将协程投递到
进程级共享的后台线程事件循环（`aerie-memory-bg`），从同步上下文或运行中的异步循环内调用均安全、不死锁。

**线程安全**：`core.database.Database` 每次 CRUD 都新建 SQLite 连接（`connection()` 上下文 + 锁），
后台线程访问安全；ChromaDB `PersistentClient` 原生支持多线程访问。

## TDD 验证

`tests/test_p1_d5_3_layered_adapter.py`（4 用例）：

```
pytest tests/test_p1_d5_3_layered_adapter.py -q
4 passed, 1 warning in 1.86s
```

| 用例 | 覆盖 |
| --- | --- |
| store/retrieve 往返 | store(importance=8) → retrieve 返回含 content/importance/memory_type 的 dict |
| 运行中事件循环同步调用 | 模拟 context_builder 在 async pipeline 内同步 retrieve，无死锁/无 "already running" |
| decay 不崩溃 | 维护任务可安全调用 |
| 空检索 | 无记忆时返回空 list |

## 编译与回归

- `py_compile core/companion.py memory/layers/sync_adapter.py` → 0
- `import core.companion` → OK
- `tests/e2e/e2e_s3_memory_layers_verify.py` → **5/5 通过**（T1 Transient / T2 Working / T3 Long-term / T4 Permanent / T5 LayeredMemory，无回归）

## 生产启动验证（补录）

审计完成后，通过 `python main.py` 全应用生产启动验证接线真实生效：

```
knowledge indexer: using chromadb local embedding   ← embedding_fn 复用 resolve_embedding_fn() 生效
ChromaDB initialized: data/chroma                   ← LayeredMemory 长层向量库初始化成功
```

- `/api/health` → `backend=healthy`、`stale_code=false`（运行最新代码，无陈旧二进制）
- 主 API `127.0.0.1:7890` + mobile gateway `127.0.0.1:7891` 稳定运行
- 附件依赖栈（Pillow/markitdown 等）完整加载，启动无降级警告

**环境就绪备注**：dev `.venv` 此前仅装测试依赖，启动时补装了声明的运行时依赖
`fastapi==0.139.2`、`uvicorn[standard]==0.51.0`、`argon2-cffi==25.1.0`、`Pillow==12.2.0`、
`markitdown[audio-transcription,docx,outlook,pdf,pptx,xls,xlsx,youtube-transcription]==0.1.6`。
这些与 LayeredMemory 接线正确性无关，但反映实际验证环境状态。

## 安全边界

- 未配置任何远程 embedding API Key，`embedding_fn` 走 ChromaDB 本地 ONNX 离线模型，无对外请求。
- 保持 `LongTermMemory` 对外接口不变，调用方零改动，避免大范围回归风险。
