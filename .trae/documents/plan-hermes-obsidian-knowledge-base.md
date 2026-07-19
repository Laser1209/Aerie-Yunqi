---
title: Hermes + Obsidian 关系向量知识库搭建计划
date: 2026-07-19
tags:
  - implementation-plan
  - knowledge-base
  - vector-db
  - obsidian
  - hermes
  - aerie-yunqi
aliases:
  - 向量知识库搭建计划
  - Obsidian RAG 实施方案
status: draft
version: 1.0
phase: phase-1
cssclasses:
  - implementation-plan
---

# Hermes + Obsidian 关系向量知识库搭建计划

> [!info] 文档说明
> 本计划面向 Aerie · 云栖 v0.1.0-beta.1 项目，目标是集成 Hermes 本地大模型 + Obsidian Vault 构建关系型向量知识库，实现语义搜索、RAG 增强对话、知识图谱等能力。
> 所有改动遵循 **零破坏性原则**：新模块与现有 `knowledge/kb.py` 完全独立，通过开关控制启用。

---

## 0. 前置条件检查清单

> [!todo] 启动前确认
> - [ ] Python 版本 ≥ 3.10（当前项目已满足）
> - [ ] Node.js 环境可用（Electron 端 chokidar 安装）
> - [ ] 确认用户 Obsidian Vault 路径（或提供配置入口让用户选择）
> - [ ] 预留磁盘空间：模型文件 ~1-2GB，向量索引 ~100MB/万条笔记
> - [ ] 现有功能回归测试基线已建立

---

## 1. 整体架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                     Electron 前端层                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ 知识库面板   │  │ 聊天引用展示 │  │  Obsidian 联动跳转   │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              chokidar 文件监听（主进程）              │    │
│  └─────────────────────────────────────────────────────┘    │
└──────────────────────────┬──────────────────────────────────┘
                           │ IPC / HTTP API
┌──────────────────────────▼──────────────────────────────────┐
│                    Python 智能内核层                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐ │
│  │ 向量检索  │  │ RAG 编排  │  │ Hermes   │  │  关系抽取     │ │
│  │  引擎    │  │  管线    │  │  LLM     │  │  器          │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────┘ │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              watchdog 文件监听（冗余备份）            │    │
│  └─────────────────────────────────────────────────────┘    │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                      存储与索引层                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ LanceDB      │  │ SQLite       │  │ 图关系索引       │   │
│  │ 向量库       │  │ 元数据+旧KB  │  │ (Phase 3)       │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
└──────────────────────────┬──────────────────────────────────┘
                           │ 双轨监听 + CLI 增强
┌──────────────────────────▼──────────────────────────────────┐
│                     Obsidian Vault                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │ Markdown │  │ Wikilinks│  │ Front-   │  │ 附件资源  │     │
│  │ 笔记     │  │ 双向链接  │  │ matter   │  │          │     │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │
└─────────────────────────────────────────────────────────────┘
```

### 1.1 核心设计原则

1. **嵌入式优先**：LanceDB 无需独立服务，随应用启动
2. **双轨监听**：Electron chokidar + Python watchdog 冗余保证事件不丢
3. **混合检索**：向量相似度 + BM25 全文 + 时间权重 + 图关系（Phase 3）融合排序
4. **优雅降级**：本地模型不可用时自动回退到云端 API，向量库不可用时回退到关键词搜索
5. **渐进式交付**：三个阶段独立可用，无需等全部完成

---

## 2. Phase 1：基础向量检索（预计 1-2 周）

> [!tip] Phase 1 目标
> 跑通完整链路：Obsidian Vault 扫描 → Markdown 解析 → 分块嵌入 → LanceDB 索引 → 语义搜索 API → 前端面板展示。
> 此阶段不引入 RAG 和 LLM，先把基础检索能力做扎实。

### 2.1 依赖安装

> [!warning] 操作步骤
> 1. 修改 `requirements.txt`，在"Heavy / optional packages"区块上方新增：

```text
# ============================================================
# 向量知识库（Phase 1 新增）--------------------------- verified=no
# ============================================================
lancedb>=0.10.0                 # 嵌入式向量数据库
sentence-transformers>=3.0.0    # BGE 等中文嵌入模型框架
python-frontmatter>=1.1.0       # Obsidian Frontmatter YAML 解析
watchdog>=4.0.0                 # Python 端文件系统监听
numpy>=1.26.0                   # 向量计算基础
```

> 2. Electron 端安装 chokidar：在 `electron/` 目录执行

```bash
cd electron
npm install chokidar@3.6.0 --save
```

### 2.2 新增文件清单

```
knowledge/
├── __init__.py                  # 修改：导出新模块
├── kb.py                        # 现有文件，保持不动
├── vector_store.py              # 🆕 LanceDB 向量存储引擎
├── vault_watcher.py             # 🆕 Vault 文件监听器（Python watchdog）
├── md_parser.py                 # 🆕 Obsidian Markdown 解析器
├── embedders.py                 # 🆕 嵌入模型封装（本地/API双模式）
└── embeddings/                  # 🆕 模型缓存目录（gitignore）
    └── .gitkeep
```

### 2.3 模块详细设计

#### 2.3.1 `knowledge/embedders.py` — 嵌入模型封装

```python
"""嵌入模型封装，支持本地 BGE 模型和云端 API 双模式。"""
from __future__ import annotations
import logging
from typing import Protocol
import numpy as np

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    """嵌入器统一接口。"""
    dim: int  # 向量维度

    def encode(self, texts: list[str]) -> np.ndarray:
        """将文本列表编码为向量数组，shape=(len(texts), dim)。"""
        ...


class LocalBGELargeEmbedder:
    """本地 BAAI/bge-large-zh-v1.5 嵌入模型（1024维，中文优秀）。"""
    dim = 1024

    def __init__(self, model_path: str | None = None):
        self._model = None
        self._model_path = model_path or "BAAI/bge-large-zh-v1.5"

    def _load(self):
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer
        logger.info("Loading embedding model: %s", self._model_path)
        self._model = SentenceTransformer(self._model_path, device="cpu")

    def encode(self, texts: list[str]) -> np.ndarray:
        self._load()
        vecs = self._model.encode(texts, normalize_embeddings=True)
        return vecs.astype(np.float32)


class LocalBGEM3Embedder:
    """本地 BAAI/bge-m3 多语言多粒度嵌入模型（1024维，支持稠密+稀疏+多向量）。"""
    dim = 1024
    # Phase 2 再实现，Phase 1 先用 bge-large-zh


class OpenAICompatibleEmbedder:
    """OpenAI 兼容 API 嵌入（用于云端兜底，支持硅基流动、DeepSeek 兼容端点）。"""
    dim = 1024  # text-embedding-v3 是 1024 维，其他模型按需调整

    def __init__(self, api_key: str, base_url: str, model: str = "text-embedding-v3"):
        self._client = None
        self._api_key = api_key
        self._base_url = base_url
        self._model_name = model

    def _load(self):
        if self._client is not None:
            return
        from openai import OpenAI
        self._client = OpenAI(api_key=self._api_key, base_url=self._base_url)

    def encode(self, texts: list[str]) -> np.ndarray:
        self._load()
        resp = self._client.embeddings.create(input=texts, model=self._model_name)
        vecs = [item.embedding for item in resp.data]
        return np.array(vecs, dtype=np.float32)


def create_embedder(config: dict) -> Embedder:
    """根据配置创建嵌入器，优先本地，失败回退 API。"""
    mode = config.get("mode", "local")
    try:
        if mode == "local":
            model_name = config.get("local_model", "BAAI/bge-large-zh-v1.5")
            if "bge-m3" in model_name:
                return LocalBGEM3Embedder(model_name)
            return LocalBGELargeEmbedder(model_name)
        elif mode == "api":
            return OpenAICompatibleEmbedder(
                api_key=config.get("api_key", ""),
                base_url=config.get("base_url", ""),
                model=config.get("model", "text-embedding-v3"),
            )
    except Exception as e:
        logger.warning("Failed to create %s embedder, falling back: %s", mode, e)
        # 兜底：如果本地模型加载失败（比如内存不够），尝试 API
        if mode == "local" and config.get("fallback_api"):
            return create_embedder({**config, "mode": "api"})
        raise
```

#### 2.3.2 `knowledge/md_parser.py` — Obsidian Markdown 解析器

```python
"""Obsidian 风味 Markdown 解析器：处理 frontmatter、wikilinks、标签、分块。"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
import frontmatter

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]")
TAG_RE = re.compile(r"(?<!\w)#([a-zA-Z\u4e00-\u9fa5][\w\u4e00-\u9fa5/-]*)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


@dataclass
class ParsedChunk:
    """语义分块后的片段。"""
    text: str
    heading_path: str  # 标题层级路径，如 "章节1 > 小节2"
    start_line: int
    end_line: int
    metadata: dict = field(default_factory=dict)


@dataclass
class ParsedNote:
    """解析后的笔记结构。"""
    path: str
    title: str
    content: str
    metadata: dict  # frontmatter 内容
    wikilinks: list[str]  # [[笔记名]] 列表
    tags: list[str]
    chunks: list[ParsedChunk]
    file_mtime: float
    file_hash: str  # 用于变更检测


class ObsidianMarkdownParser:
    """Obsidian Markdown 解析器。"""

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def parse(self, file_path: str) -> ParsedNote:
        """解析单个 Markdown 文件。"""
        import hashlib
        import os
        import io

        mtime = os.path.getmtime(file_path)
        with open(file_path, "r", encoding="utf-8") as f:
            raw = f.read()
        file_hash = hashlib.md5(raw.encode("utf-8")).hexdigest()

        # 解析 frontmatter
        post = frontmatter.loads(raw)
        content = post.content
        metadata = dict(post.metadata)

        # 提取标题：frontmatter title > 第一个 # 标题 > 文件名
        title = metadata.get("title", "").strip()
        if not title:
            m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
            title = m.group(1).strip() if m else os.path.splitext(os.path.basename(file_path))[0]

        # 提取 wikilinks
        wikilinks = []
        for match in WIKILINK_RE.finditer(content):
            target = match.group(1).strip()
            if target and target not in wikilinks:
                wikilinks.append(target)

        # 提取标签（frontmatter tags + 行内 #标签）
        tags = []
        fm_tags = metadata.get("tags", [])
        if isinstance(fm_tags, str):
            fm_tags = [t.strip() for t in fm_tags.split(",")]
        tags.extend([t for t in fm_tags if t])
        for match in TAG_RE.finditer(content):
            tag = match.group(1).strip()
            if tag and tag not in tags:
                tags.append(tag)

        # 语义分块
        chunks = self._semantic_chunk(content, title)

        return ParsedNote(
            path=file_path,
            title=title,
            content=content,
            metadata=metadata,
            wikilinks=wikilinks,
            tags=tags,
            chunks=chunks,
            file_mtime=mtime,
            file_hash=file_hash,
        )

    def _semantic_chunk(self, content: str, doc_title: str) -> list[ParsedChunk]:
        """按标题层级进行语义分块，保持上下文完整。"""
        lines = content.split("\n")
        chunks: list[ParsedChunk] = []
        heading_stack: list[tuple[int, str]] = []  # (level, text)
        current_chunk_lines: list[str] = []
        chunk_start_line = 0
        current_heading_path = doc_title

        def flush_chunk(end_line: int):
            if not current_chunk_lines:
                return
            text = "\n".join(current_chunk_lines).strip()
            if text:
                chunks.append(ParsedChunk(
                    text=text,
                    heading_path=current_heading_path,
                    start_line=chunk_start_line,
                    end_line=end_line,
                ))

        for idx, line in enumerate(lines):
            heading_match = HEADING_RE.match(line)
            if heading_match:
                # 遇到新标题，先 flush 当前块
                flush_chunk(idx - 1)
                level = len(heading_match.group(1))
                heading_text = heading_match.group(2).strip()
                # 维护标题栈
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, heading_text))
                current_heading_path = " > ".join([doc_title] + [h[1] for h in heading_stack])
                current_chunk_lines = [line]
                chunk_start_line = idx
            else:
                current_chunk_lines.append(line)

            # 超长块在段落边界切分
            current_len = sum(len(l) for l in current_chunk_lines)
            if current_len > self.chunk_size and line.strip() == "":
                flush_chunk(idx)
                current_chunk_lines = []
                chunk_start_line = idx + 1

        flush_chunk(len(lines) - 1)
        return chunks
```

#### 2.3.3 `knowledge/vector_store.py` — LanceDB 向量存储

```python
"""LanceDB 嵌入式向量存储引擎，支持混合检索。"""
from __future__ import annotations
import logging
import os
from typing import Any
import numpy as np

logger = logging.getLogger(__name__)


class LanceDBVectorStore:
    """LanceDB 嵌入式向量存储。"""

    def __init__(self, db_path: str, embedder: Any):
        self.db_path = db_path
        self.embedder = embedder
        self._db = None
        self._table = None
        self._file_index_meta: dict[str, dict] = {}  # path -> {hash, mtime, chunk_count}

    def _init_db(self):
        if self._db is not None:
            return
        import lancedb
        os.makedirs(self.db_path, exist_ok=True)
        self._db = lancedb.connect(self.db_path)
        self._init_table()
        self._load_meta()

    def _init_table(self):
        table_name = "knowledge_chunks"
        dim = self.embedder.dim
        schema = [
            {"id": "", "path": "", "title": "", "chunk_text": "",
             "chunk_index": 0, "tags": "", "links": "", "heading_path": "",
             "created_at": 0.0, "updated_at": 0.0,
             "vector": np.zeros(dim, dtype=np.float32)},
        ]
        if table_name in self._db.table_names():
            self._table = self._db.open_table(table_name)
        else:
            self._table = self._db.create_table(table_name, schema)

    def _load_meta(self):
        """加载已索引文件元信息，用于增量更新判断。"""
        try:
            # 从表中聚合每个 path 的最新状态
            # 简化实现：实际用 group by 聚合
            pass
        except Exception:
            self._file_index_meta = {}

    async def index_note(self, note) -> int:
        """索引单个笔记（增量：hash 未变则跳过）。"""
        self._init_db()
        # 检查是否需要重新索引
        existing = self._file_index_meta.get(note.path)
        if existing and existing.get("hash") == note.file_hash:
            return 0  # 无变化

        import time
        now = time.time()

        # 删除该文件旧分块
        if existing:
            self._table.delete(f"path = '{note._escape(note.path)}'")

        # 生成新分块向量
        records = []
        chunks = note.chunks
        if not chunks:
            self._file_index_meta[note.path] = {
                "hash": note.file_hash, "mtime": note.file_mtime, "chunk_count": 0
            }
            return 0

        texts = [c.text for c in chunks]
        vectors = self.embedder.encode(texts)

        for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
            records.append({
                "id": f"{note.path}#chunk{i}",
                "path": note.path,
                "title": note.title,
                "chunk_text": chunk.text,
                "chunk_index": i,
                "tags": ",".join(note.tags),
                "links": ",".join(note.wikilinks),
                "heading_path": chunk.heading_path,
                "created_at": now,
                "updated_at": now,
                "vector": vec,
            })

        if records:
            self._table.add(records)

        self._file_index_meta[note.path] = {
            "hash": note.file_hash,
            "mtime": note.file_mtime,
            "chunk_count": len(records),
        }
        return len(records)

    async def delete_note(self, path: str) -> bool:
        """删除笔记所有分块。"""
        self._init_db()
        try:
            self._table.delete(f"path = '{self._escape(path)}'")
            self._file_index_meta.pop(path, None)
            return True
        except Exception:
            logger.exception("delete_note failed: %s", path)
            return False

    async def vector_search(self, query: str, limit: int = 5) -> list[dict]:
        """纯向量相似度搜索。"""
        self._init_db()
        q_vec = self.embedder.encode([query])[0]
        results = (
            self._table.search(q_vec)
            .limit(limit * 2)
            .to_list()
        )
        # 去重（同一路径只保留最相关的1-2个块）
        seen_paths: dict[str, float] = {}
        filtered = []
        for r in sorted(results, key=lambda x: x.get("_distance", 0)):
            p = r["path"]
            dist = r.get("_distance", 1.0)
            if p not in seen_paths or (seen_paths[p] > dist and len([x for x in filtered if x["path"] == p]) < 2):
                r["score"] = 1.0 - dist  # 转换为相似度分数
                filtered.append(r)
                seen_paths[p] = dist
            if len(filtered) >= limit:
                break
        return filtered

    async def hybrid_search(self, query: str, limit: int = 5) -> list[dict]:
        """混合检索：向量相似度 + 关键词匹配（Phase 1 简化版，Phase 2 加 BM25）。"""
        vector_results = await self.vector_search(query, limit=limit * 2)

        # 简单关键词加权：标题或 chunk_text 包含查询词的加分
        keywords = [w for w in query.strip().split() if len(w) > 1]
        for r in vector_results:
            bonus = 0.0
            for kw in keywords:
                if kw in r.get("title", ""):
                    bonus += 0.15
                if kw in r.get("chunk_text", ""):
                    bonus += 0.05
                if kw in r.get("tags", ""):
                    bonus += 0.1
            r["score"] = min(1.0, r.get("score", 0) + bonus)

        vector_results.sort(key=lambda x: x["score"], reverse=True)
        return vector_results[:limit]

    def get_stats(self) -> dict:
        """获取索引统计信息。"""
        self._init_db()
        try:
            total = self._table.count_rows()
        except Exception:
            total = 0
        return {
            "total_chunks": total,
            "indexed_notes": len(self._file_index_meta),
            "embedder_dim": self.embedder.dim,
        }

    @staticmethod
    def _escape(s: str) -> str:
        return s.replace("'", "''").replace("\\", "\\\\")
```

#### 2.3.4 `knowledge/vault_watcher.py` — Vault 文件监听器

```python
"""Obsidian Vault 文件监听器，基于 watchdog。Electron 端 chokidar 作为主监听，这里做冗余备份。"""
from __future__ import annotations
import logging
import os
import threading
import time
from typing import Callable, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent, FileDeletedEvent, FileMovedEvent

logger = logging.getLogger(__name__)


class VaultEventHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[str, str], None]):
        self.callback = callback
        self._last_events: dict[str, float] = {}  # 去抖

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".md"):
            self._debounce("create", event.src_path)

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".md"):
            self._debounce("modify", event.src_path)

    def on_deleted(self, event):
        if not event.is_directory and event.src_path.endswith(".md"):
            self._debounce("delete", event.src_path)

    def on_moved(self, event):
        if not event.is_directory and event.dest_path.endswith(".md"):
            self._debounce("delete", event.src_path)
            self._debounce("create", event.dest_path)

    def _debounce(self, event_type: str, path: str):
        # 1秒内重复事件忽略（编辑器保存会触发多次 modify）
        key = f"{event_type}:{path}"
        now = time.time()
        if key in self._last_events and now - self._last_events[key] < 1.0:
            return
        self._last_events[key] = now
        try:
            self.callback(event_type, path)
        except Exception:
            logger.exception("vault event callback error")


class VaultWatcher:
    """Vault 监听器，支持初始全量扫描 + 增量监听。"""

    def __init__(self, vault_path: str, on_file_event: Callable[[str, str], None]):
        self.vault_path = vault_path
        self.on_file_event = on_file_event
        self._observer: Optional[Observer] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self, full_scan: bool = True):
        """启动监听，可选执行初始全量扫描。"""
        if self._running:
            return
        if full_scan:
            self._full_scan()
        handler = VaultEventHandler(self._handle_event)
        self._observer = Observer()
        self._observer.schedule(handler, self.vault_path, recursive=True)
        self._observer.start()
        self._running = True
        logger.info("Vault watcher started: %s", self.vault_path)

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
        self._running = False

    def _full_scan(self):
        """全量扫描所有 .md 文件，触发 create 事件。"""
        logger.info("Starting full scan of vault: %s", self.vault_path)
        count = 0
        for root, dirs, files in os.walk(self.vault_path):
            # 跳过 .obsidian、.git、node_modules 等目录
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules"]
            for f in files:
                if f.endswith(".md"):
                    path = os.path.join(root, f)
                    self._handle_event("create", path)
                    count += 1
        logger.info("Full scan complete: %d markdown files found", count)

    def _handle_event(self, event_type: str, path: str):
        # 忽略 .obsidian 目录下的文件
        if ".obsidian" in path or os.path.basename(path).startswith("."):
            return
        self.on_file_event(event_type, path)
```

### 2.4 Companion 层集成

修改 `core/companion.py`：

```python
# 在现有 KnowledgeBase 初始化之后，增加向量库初始化
from knowledge.kb import KnowledgeBase
from knowledge.vector_store import LanceDBVectorStore
from knowledge.embedders import create_embedder
from knowledge.vault_watcher import VaultWatcher
from knowledge.md_parser import ObsidianMarkdownParser

# ... 现有代码 ...

self.knowledge = KnowledgeBase(self.db)

# 向量知识库初始化（可通过 settings 开关控制）
kb_config = self.settings.get("knowledge_base", {}) if hasattr(self, "settings") else {}
self.vector_kb = None
self.vault_watcher = None
self.md_parser = None

if kb_config.get("enabled", False):
    try:
        vault_path = kb_config.get("vault_path", "")
        if vault_path and os.path.isdir(vault_path):
            embedder = create_embedder(kb_config.get("embedder", {"mode": "local"}))
            vector_db_path = os.path.join(self.data_dir, "vector_store")
            self.vector_kb = LanceDBVectorStore(vector_db_path, embedder)
            self.md_parser = ObsidianMarkdownParser()

            # 启动文件监听器
            async def on_vault_event(event_type: str, path: str):
                if not self.vector_kb or not self.md_parser:
                    return
                try:
                    if event_type in ("create", "modify"):
                        note = self.md_parser.parse(path)
                        await self.vector_kb.index_note(note)
                    elif event_type == "delete":
                        await self.vector_kb.delete_note(path)
                except Exception:
                    logger.exception("vault event processing error: %s %s", event_type, path)

            # 注意：watchdog 回调在子线程，需要调度到 asyncio 事件循环
            loop = asyncio.get_event_loop()
            def thread_callback(event_type, path):
                asyncio.run_coroutine_threadsafe(on_vault_event(event_type, path), loop)

            self.vault_watcher = VaultWatcher(vault_path, thread_callback)
            self.vault_watcher.start(full_scan=kb_config.get("full_scan_on_start", True))
            logger.info("Vector knowledge base initialized (vault: %s)", vault_path)
    except Exception as e:
        logger.warning("Failed to initialize vector knowledge base: %s", e)
        self.vector_kb = None
```

### 2.5 Agent 层集成

修改 `core/agent.py` 的 `perceive()` 方法，在 memory_hits 之后增加知识检索：

```python
# 在 memory_hits = ... 之后添加：
knowledge_hits = []
knowledge_enabled = False
try:
    if hasattr(self.companion, "vector_kb") and self.companion.vector_kb:
        knowledge_enabled = True
        knowledge_hits = await self.companion.vector_kb.hybrid_search(
            msg.content, limit=3
        )
except Exception:
    logger.exception("knowledge retrieval failed in perceive")
```

然后在 `ctx_builder.build()` 调用时传入 knowledge_hits，在 system prompt 中注入相关知识片段（类似 memory_hits 的处理方式）。

### 2.6 API 接口新增

在 `core/api_server.py` 中新增以下端点：

```python
# 知识库配置
POST /api/knowledge/config          # 保存知识库配置（vault路径、嵌入模式等）
GET  /api/knowledge/status          # 获取索引状态（文档数、分块数、索引进度）
POST /api/knowledge/reindex         # 手动触发全量/指定路径重建索引

# 搜索
POST /api/knowledge/search          # 语义+关键词混合搜索
GET  /api/knowledge/stats           # 索引统计
```

### 2.7 配置文件新增

在 `config/settings.yaml` 中增加知识库配置区块：

```yaml
knowledge_base:
  enabled: false                    # 总开关，默认关闭，等用户配置 Vault 路径后开启
  vault_path: ""                    # Obsidian Vault 路径，用户配置后填写
  embedder:
    mode: "local"                   # local | api
    local_model: "BAAI/bge-large-zh-v1.5"
    fallback_api: true              # 本地失败时回退到 API
    api_key: ""
    base_url: ""
    model: "text-embedding-v3"
  full_scan_on_start: true          # 启动时全量扫描
  auto_reindex: true                # 监听文件变更自动重索引
  search_limit: 5                   # 默认返回结果数
  chunk_size: 512                   # 分块大小（字符数）
  chunk_overlap: 50                 # 分块重叠
```

### 2.8 Phase 1 验收标准

- [ ] 配置 Vault 路径后，启动应用自动扫描所有 .md 文件并建立索引
- [ ] 在 Obsidian 中新增/修改/删除笔记，10秒内向量索引同步更新
- [ ] `/api/knowledge/search` 接口返回语义相关结果，相关度评分合理
- [ ] 关闭知识库功能时，应用行为与当前版本完全一致
- [ ] 首次索引大 Vault（>1000笔记）时有进度提示，不阻塞主流程
- [ ] 模型加载失败时有明确错误提示，自动降级到 API 模式或关键词搜索

---

## 3. Phase 2：RAG 对话增强（预计 2 周）

> [!tip] Phase 2 目标
> 在 Phase 1 基础检索能力之上，实现 RAG 增强对话、Ollama 本地 Hermes 模型集成、聊天引用来源跳转、混合检索重排。

### 3.1 新增依赖

```text
# requirements.txt 新增
rank-bm25>=0.2.2               # BM25 全文检索，用于混合检索
llama-cpp-python>=0.2.0        # 可选：运行量化 GGUF 模型（轻量备选）
```

### 3.2 新增文件

```
knowledge/
├── rag.py                       # 🆕 RAG 检索增强生成管线
├── knowledge_tools.py           # 🆕 Agent 工具注册（search_knowledge 等）
└── reranker.py                  # 🆕 结果重排器（Phase 2 简化版）
```

### 3.3 核心模块设计

#### 3.3.1 `knowledge/rag.py` — RAG 编排管线

```python
"""RAG 检索增强生成管线。"""
from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)


class RAGPipeline:
    """RAG 管线：Query 改写 → 检索 → 重排 → 上下文构建 → 生成。"""

    def __init__(self, vector_store, llm_brain=None):
        self.vector_store = vector_store
        self.llm = llm_brain
        self.greetings = {"你好", "您好", "hi", "hello", "在吗", "在不在"}

    def _should_retrieve(self, query: str) -> bool:
        """判断是否需要检索：纯问候、闲聊不需要。"""
        q = query.strip().lower()
        if len(q) < 4:
            return False
        if q in self.greetings:
            return False
        return True

    async def retrieve(self, query: str, limit: int = 5) -> tuple[list[dict], str]:
        """检索相关文档并构建上下文字符串。返回 (结果列表, 上下文字符串)。"""
        if not self._should_retrieve(query):
            return [], ""

        results = await self.vector_store.hybrid_search(query, limit=limit)

        if not results:
            return [], ""

        # 构建上下文
        context_parts = []
        for i, r in enumerate(results, 1):
            source = f"[{i}] {r['title']}"
            if r.get("heading_path"):
                source += f" > {r['heading_path']}"
            context_parts.append(
                f"{source}\n{r['chunk_text']}"
            )
        context = "\n\n---\n\n".join(context_parts)
        return results, context

    async def answer(self, query: str, history: list[dict] | None = None) -> dict:
        """端到端 RAG 问答。"""
        results, context = await self.retrieve(query)
        if not context:
            return {"answer": None, "sources": [], "used_rag": False}

        # 构建 RAG 提示词
        system_prompt = f"""你是 Aerie · 云栖，用户的个人 AI 助手。
请使用下面提供的知识库内容来回答用户的问题。
如果知识库内容中没有答案，请根据你的知识回答，但要说明知识库中没有相关信息。
回答时请自然地融入信息，不要生硬地说"根据知识库"。

知识库内容：
{context}
"""
        # 调用 LLM（使用现有的 brain.chat，传入构建好的上下文）
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history[-6:])  # 取最近6轮
        messages.append({"role": "user", "content": query})

        # 实际调用 brain，这里简化示意
        answer = "..."  # await self.llm.chat(messages)

        return {
            "answer": answer,
            "sources": [
                {
                    "title": r["title"],
                    "path": r["path"],
                    "heading": r.get("heading_path", ""),
                    "score": r.get("score", 0),
                    "snippet": r["chunk_text"][:200] + "...",
                }
                for r in results
            ],
            "used_rag": True,
        }
```

#### 3.3.2 `knowledge/knowledge_tools.py` — Agent 工具注册

```python
"""知识库相关 Agent 工具注册，让 Hermes/LLM 可自主调用。"""
from __future__ import annotations


def register_knowledge_tools(registry, companion):
    """注册知识库工具到 ToolRegistry。"""

    async def search_knowledge(query: str, limit: int = 5) -> dict:
        """语义搜索你的 Obsidian 知识库。当用户询问项目相关信息、历史文档内容、笔记中的知识点时使用此工具。
        返回相关笔记片段，可基于结果回答用户问题。
        """
        if not companion.vector_kb:
            return {"error": "知识库未启用，请先在设置中配置 Obsidian Vault 路径"}
        results = await companion.vector_kb.hybrid_search(query, limit=limit)
        formatted = []
        for r in results:
            formatted.append({
                "title": r["title"],
                "path": r["path"],
                "section": r.get("heading_path", ""),
                "content": r["chunk_text"],
                "relevance": round(r.get("score", 0), 3),
            })
        return {"results": formatted, "count": len(formatted)}

    async def open_in_obsidian(path: str) -> dict:
        """在 Obsidian 中打开指定笔记。path 参数为笔记文件的完整路径。
        """
        import webbrowser
        import urllib.parse
        # 提取 vault 名称和文件名
        vault_config = companion.settings.get("knowledge_base", {})
        vault_path = vault_config.get("vault_path", "")
        import os
        vault_name = os.path.basename(vault_path)
        file_name = os.path.basename(path).replace(".md", "")
        obsidian_url = f"obsidian://open?vault={urllib.parse.quote(vault_name)}&file={urllib.parse.quote(file_name)}"
        webbrowser.open(obsidian_url)
        return {"opened": True, "path": path}

    # 注册工具
    registry.register(
        "search_knowledge",
        search_knowledge,
        {
            "description": "语义搜索知识库，查找 Obsidian 笔记中相关的内容。当用户问关于笔记、文档、项目历史、已有资料的问题时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询，自然语言描述你要找的内容"},
                    "limit": {"type": "integer", "description": "返回结果数量，默认5", "default": 5}
                },
                "required": ["query"]
            }
        },
        category="knowledge",
        provider_hint="text",
    )

    registry.register(
        "open_in_obsidian",
        open_in_obsidian,
        {
            "description": "在 Obsidian 中打开指定的笔记文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "笔记文件的完整路径"}
                },
                "required": ["path"]
            }
        },
        category="knowledge",
        provider_hint="text",
    )
```

在 `tools/__init__.py` 的 `register_all_tools()` 末尾添加：

```python
# 知识库工具
try:
    from knowledge.knowledge_tools import register_knowledge_tools
    from core.companion import get_companion
    companion = get_companion()
    if companion and companion.vector_kb:
        register_knowledge_tools(registry, companion)
except Exception as e:
    import logging
    logging.getLogger(__name__).warning("knowledge tools registration failed: %s", e)
```

### 3.4 Ollama 本地 Hermes 模型集成

在 `core/brain.py` 中增加 Ollama 本地模型 Provider 支持（Ollama 暴露 OpenAI 兼容 API，所以只需添加一个 base_url 指向 `http://localhost:11434/v1` 的 provider 配置即可）。

在 `config/settings.yaml` 的 providers 区块添加：

```yaml
providers:
  # 现有 providers 保持不变
  ollama-hermes:
    type: openai_compatible
    name: "Hermes 本地 (Ollama)"
    base_url: "http://localhost:11434/v1"
    api_key: "ollama"  # Ollama 不校验 key
    model: "hermes3:latest"  # 或 hermes4:latest
    enabled: false  # 默认关闭，检测到 Ollama 运行时自动启用
    max_tokens: 4096
    temperature: 0.7
    priority: 3  # 本地模型优先级设为较低，按预算/复杂度动态路由
```

启动时自动检测 Ollama 服务是否可用：

```python
import httpx
async def _detect_ollama():
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            resp = await client.get("http://localhost:11434/api/tags")
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                if any("hermes" in m.get("name", "").lower() for m in models):
                    # 启用 ollama-hermes provider
                    pass
    except Exception:
        pass
```

### 3.5 聊天界面引用展示

在 Electron 前端聊天面板中，当回复包含 RAG 来源时，展示引用卡片：
- 每条回复下方显示"参考来源"区域
- 每个来源显示笔记标题 + 所在章节 + 相关度
- 点击引用调用 `obsidian://` URI 直接跳转到 Obsidian 对应笔记
- 鼠标悬停显示笔记内容预览（前200字）

### 3.6 Phase 2 验收标准

- [ ] 知识库相关问题回答准确率显著优于纯模型回答
- [ ] 聊天回复展示引用来源，点击可跳转 Obsidian
- [ ] Agent 自主判断何时调用 `search_knowledge` 工具，无需人工触发
- [ ] Ollama 运行且已拉取 Hermes 模型时，自动检测并可用
- [ ] 纯闲聊/问候类问题不触发检索，不浪费 token
- [ ] 检索失败/无结果时自动降级为普通对话，不报错

---

## 4. Phase 3：关系图谱与智能关联（预计 1-2 周）

> [!tip] Phase 3 目标
> 基于 wikilinks + 语义相似度构建笔记关系图谱，实现智能双向链接建议、知识社区检测、GraphRAG 多跳推理、图谱可视化。

### 4.1 新增文件

```
knowledge/
├── graph.py                     # 🆕 知识图谱关系计算（基于 networkx 轻量方案）
├── link_suggester.py            # 🆕 智能链接建议
└── obsidian_cli.py              # 🆕 Obsidian CLI/REST API 客户端（增强能力）
```

### 4.2 核心能力

1. **关系图谱构建**
   - 显式关系：从 wikilinks 直接提取 `笔记A → 笔记B` 有向边
   - 隐式关系：向量相似度 > 0.8 且无显式链接的笔记对，作为"推荐关联"边
   - 边权重：显式链接权重 1.0，语义相似按相似度分数

2. **智能链接建议**
   - 新笔记入库后，自动推荐 3-5 个应该添加的双向链接
   - 用户可一键添加 `[[链接]]` 到笔记中（通过文件系统或 Obsidian API）

3. **GraphRAG 多跳推理**
   - 检索到相关笔记后，沿图谱扩展 1-2 跳邻居，补充上下文
   - 适用于"A和B的关系是什么""这个概念和哪些主题相关"类问题

4. **知识社区检测**
   - 使用标签传播或 Louvain 算法自动发现笔记聚类
   - 前端展示知识图谱力导向图（D3.js / ForceGraph）

5. **Obsidian CLI 深度集成**
   - 当 Obsidian v1.12+ CLI 可用时，利用 CLI 获取 Obsidian 内部解析的元数据（反向链接、未解析链接等）
   - Local REST API 插件作为备选方案

### 4.3 Phase 3 验收标准

- [ ] 新笔记创建后，能推荐合理的相关笔记链接
- [ ] 关系图谱可视化在前端展示，可缩放、拖拽、点击跳转
- [ ] 多跳问题（如"A和B都和什么主题相关"）回答质量优于 Phase 2
- [ ] 自动检测 Obsidian CLI/REST API 可用性并增强能力

---

## 5. Electron 端改动清单

### 5.1 主进程（electron/src/main.js）

```javascript
// 新增：chokidar 文件监听（与 Python watchdog 双轨冗余）
const chokidar = require('chokidar');
let watcher = null;

function startVaultWatcher(vaultPath, win) {
  if (watcher) watcher.close();
  if (!vaultPath) return;

  watcher = chokidar.watch(vaultPath, {
    ignored: /(^|[\/\\])\../,  // 忽略点文件
    persistent: true,
    depth: 99,
    awaitWriteFinish: {
      stabilityThreshold: 500,
      pollInterval: 100
    }
  });

  const dispatch = (event, path) => {
    if (!path.endsWith('.md')) return;
    win.webContents.send('vault:file-event', { event, path });
    // 同时通知 Python 后端（通过 HTTP API）
    fetch('http://127.0.0.1:PORT/api/knowledge/vault-event', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event, path })
    }).catch(() => {});  // Python 端 watchdog 已在监听，失败不影响
  };

  watcher
    .on('add', path => dispatch('create', path))
    .on('change', path => dispatch('modify', path))
    .on('unlink', path => dispatch('delete', path));
}
```

### 5.2 新增 UI 页面

1. **知识库设置面板**：Vault 路径选择（系统文件选择对话框）、嵌入模型选择、索引状态显示、重建索引按钮
2. **知识库搜索面板**：独立搜索界面，支持语义搜索、筛选（标签/时间/分类）、结果列表
3. **聊天引用组件**：聊天消息下方的引用来源卡片
4. **知识图谱面板（Phase 3）**：力导向图可视化，可点击节点跳转笔记

### 5.3 IPC 新增事件

- `knowledge:set-config` — 保存知识库配置
- `knowledge:get-status` — 获取索引状态
- `knowledge:search` — 触发搜索
- `knowledge:reindex` — 手动重建索引
- `vault:file-event` — 监听文件变更事件（主进程→渲染进程）

---

## 6. 测试计划

### 6.1 单元测试

```
tests/
├── test_kb_parser.py        # Markdown 解析测试
├── test_vector_store.py     # 向量存储测试（使用小模型/随机向量）
├── test_rag_pipeline.py     # RAG 管线测试
└── e2e/
    └── e2e_knowledge.py     # 端到端知识库测试
```

关键测试点：
- Markdown 解析：frontmatter、wikilinks、标签、分块正确性
- 向量索引：新增/修改/删除文件后索引正确更新
- 去重逻辑：相同内容不重复索引
- 搜索质量：已知相关文档在前 N 条结果中
- 优雅降级：模型加载失败、vault 路径不存在时不崩溃

### 6.2 手动测试场景

1. 首次配置 Vault，观察索引导入进度
2. 在 Obsidian 中新建笔记，Aerie 中 10 秒内能搜到
3. 修改笔记内容，搜索新内容能搜到，旧内容消失
4. 删除笔记，搜索不再返回该笔记结果
5. 关闭知识库功能，应用正常使用无异常
6. 断网+本地模型未下载时，有明确提示

---

## 7. 风险与应对

| 风险 | 概率 | 影响 | 应对措施 |
|------|------|------|----------|
| 本地嵌入模型首次下载慢（~1.3GB） | 高 | 用户体验差 | 提供进度条；后台下载；支持手动放置模型文件；云端 API 兜底 |
| 大 Vault 首次索引耗时长（>5000笔记） | 中 | 启动阻塞 | 后台异步索引；分批处理；进度条；索引期间功能降级为关键词搜索 |
| 文件事件丢失/重复 | 低 | 索引不一致 | chokidar+watchdog 双轨冗余；文件 hash 校验比对；定时一致性巡检；提供手动重建按钮 |
| 低配机器运行模型卡顿 | 中 | 体验差 | 自动检测内存，<8GB 推荐使用 API 模式；模型量化选项；动态选择模型大小 |
| Obsidian 版本差异 | 低 | CLI/API 不可用 | 文件系统监听作为主路径，不依赖 Obsidian 版本；CLI 作为增强能力渐进检测 |

---

## 8. 时间线总览

```
Week 1-2  [Phase 1]
├─ Day 1-2: 依赖安装、配置结构、settings.yaml 新增配置
├─ Day 3-5: embedders.py + md_parser.py + vector_store.py 核心模块
├─ Day 6-7: vault_watcher.py + Companion 层集成 + 初始全量扫描
├─ Day 8-9: API 接口 + Electron chokidar 监听
├─ Day 10: 设置面板 UI + 基础搜索面板
└─ Day 11-12: 测试、bug 修复、性能优化

Week 3-4  [Phase 2]
├─ Day 1-3: RAG 管线 + 上下文注入（context_builder 改造）
├─ Day 4-5: knowledge_tools.py 工具注册 + Agent 集成
├─ Day 6-7: Ollama Hermes 自动检测 + Provider 接入
├─ Day 8-9: 聊天引用展示 UI + Obsidian URI 跳转
├─ Day 10: BM25 混合检索 + 结果重排
└─ Day 11-12: 测试、调优、RAG 回答质量优化

Week 5-6  [Phase 3]
├─ Day 1-3: graph.py 关系图谱构建 + 链接建议
├─ Day 4-5: GraphRAG 多跳检索
├─ Day 6-8: 知识图谱可视化面板（D3 ForceGraph）
├─ Day 9-10: Obsidian CLI 检测 + 增强集成
└─ Day 11-12: 整体优化、文档补充、内测反馈修复
```

---

## 9. 快速开始（最小可运行路径）

> [!success] 最快验证路径
> 如果想最快看到效果，可以先跳过 Electron 端改动，按以下步骤验证核心链路：

1. 安装 Python 依赖：
```bash
pip install lancedb sentence-transformers python-frontmatter watchdog numpy
```

2. 准备一个测试 Obsidian Vault，放入几个 .md 笔记

3. 运行最小验证脚本：
```python
import asyncio
from knowledge.embedders import LocalBGELargeEmbedder
from knowledge.vector_store import LanceDBVectorStore
from knowledge.md_parser import ObsidianMarkdownParser
import os

async def main():
    vault_path = r"D:\你的Obsidian库路径"
    embedder = LocalBGELargeEmbedder()
    store = LanceDBVectorStore("./test_vector_db", embedder)
    parser = ObsidianMarkdownParser()

    # 扫描并索引
    count = 0
    for root, dirs, files in os.walk(vault_path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.endswith(".md"):
                path = os.path.join(root, f)
                note = parser.parse(path)
                n = await store.index_note(note)
                count += n
                print(f"Indexed: {note.title} ({n} chunks)")

    print(f"\nTotal chunks indexed: {count}")

    # 测试搜索
    while True:
        q = input("\n搜索 (q退出): ")
        if q == "q":
            break
        results = await store.hybrid_search(q, limit=3)
        for i, r in enumerate(results, 1):
            print(f"\n[{i}] {r['title']} (score: {r['score']:.3f})")
            print(f"    {r['chunk_text'][:150]}...")

asyncio.run(main())
```

4. 验证搜索结果相关性，确认链路跑通后再逐步集成到主应用。

---

> [!note] 文档元信息
> - 创建日期：2026-07-19
> - 适用版本：Aerie · 云栖 v0.1.0-beta.1
> - 预计总工时：4-6 周（可按 Phase 分期交付）
> - 相关文档：[[hermes-obsidian-knowledge-base-research]]（可行性研究报告）
