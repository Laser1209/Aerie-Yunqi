"""knowledge 功能包 —— 本地向量知识库（chromadb）。

契约要点（见 `plugins/README.md`）：

- **顶层不 import chromadb**：发现阶段只扫目录 + 读清单，重库推迟到
  `start(companion)`；
- **失败软着陆**：chromadb 没装 / 集合建不起来时，工具返回
  `{"status": "unavailable", ...}` 而不是抛异常、也不是假装空结果 ——
  模型据此能如实告诉用户"缺什么、去哪儿装"（配合 core/capability_catalog）；
- **路径走 ctx**：持久化目录从包配置读，落在 data_dir 下的隔离子目录，
  绝不写死绝对路径。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 进程内状态：集合句柄与失败原因（register 阶段先建好闭包，start 里填）。
_COLLECTION: Optional[Any] = None
_ERROR: str = ""
_CTX: Optional[Any] = None
_DEFAULT_COLLECTION = "aerie_knowledge"
_DEFAULT_SUBDIR = "chroma_plugins/knowledge"


def _state() -> dict[str, Any]:
    return {"ready": _COLLECTION is not None, "error": _ERROR}


def _unavailable(reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "error": reason,
        "hint": "在「模块中心」确认 knowledge 功能包已安装；缺失 chromadb 时核心会退回确定性哈希索引",
    }


def _embedding_fn() -> Optional[Any]:
    """复用核心已有的 embedding 解析链（远程 > chromadb 本地 ONNX > 哈希兜底）。

    只 import 核心的**公共**入口（`core.knowledge_indexer`），不碰内部实现。
    """
    try:
        from core.knowledge_indexer import resolve_embedding_fn

        return resolve_embedding_fn()
    except Exception:
        logger.warning("knowledge pack: embedding 解析失败", exc_info=True)
        return None


def start(companion: Any) -> None:
    """惰性装配 chromadb 集合；失败只记录原因，核心继续跑。

    配置从 `ctx.get_config()` 读（宿主五件套之一，每次现读、跟随热重载）——
    ctx 在 register 阶段被本模块持有，因为宿主的 `start(companion)` 只传 companion。
    """
    global _COLLECTION, _ERROR

    config: dict[str, Any] = {}
    try:
        if _CTX is not None:
            config = _CTX.get_config() or {}
    except Exception:
        logger.debug("knowledge pack: 读取插件配置失败，用默认值", exc_info=True)

    collection_name = str(config.get("collection") or _DEFAULT_COLLECTION)
    subdir = str(config.get("persist_subdir") or _DEFAULT_SUBDIR)

    try:
        import chromadb
        from chromadb.config import Settings

        from core.paths import data_dir

        persist_dir = data_dir() / subdir
        persist_dir.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(
            path=str(persist_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        _COLLECTION = client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        _ERROR = ""
        logger.info("knowledge pack: 集合就绪 (%s @ %s)", collection_name, persist_dir)
    except Exception as exc:  # noqa: BLE001
        _COLLECTION = None
        _ERROR = f"{type(exc).__name__}: {exc}"
        logger.warning("knowledge pack: chromadb 不可用，向量检索降级（%s）", _ERROR)


def stop() -> None:
    global _COLLECTION
    _COLLECTION = None


# ── 工具实现 ────────────────────────────────────────────

def _coerce_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if str(v).strip()]
    return []


def knowledge_vector_search(query: str, k: int = 5) -> dict[str, Any]:
    """语义检索本地向量知识库。"""
    text = str(query or "").strip()
    if not text:
        return {"error": "missing query"}
    if _COLLECTION is None:
        return _unavailable(_ERROR or "向量集合未就绪")

    try:
        top_k = max(1, min(int(k or 5), 50))
    except (TypeError, ValueError):
        top_k = 5

    embed = _embedding_fn()
    if embed is None:
        return _unavailable("embedding 解析失败")

    try:
        result = _COLLECTION.query(
            query_embeddings=[embed(text)],
            n_results=top_k,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("knowledge pack: 检索失败", exc_info=True)
        return {"status": "error", "error": str(exc)[:300]}

    ids = (result.get("ids") or [[]])[0]
    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    return {
        "status": "ok",
        "count": len(ids),
        "items": [
            {"id": str(i), "text": str(d), "metadata": dict(m or {})}
            for i, d, m in zip(ids, docs, metas)
        ],
    }


def knowledge_vector_upsert(items: Any) -> dict[str, Any]:
    """写入 / 更新知识块。`items` 为 ``[{"id", "text", "metadata"?}]``。"""
    if _COLLECTION is None:
        return _unavailable(_ERROR or "向量集合未就绪")

    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list) or not items:
        return {"error": "missing items"}

    ids: list[str] = []
    texts: list[str] = []
    metas: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        text = str(item.get("text") or "").strip()
        if not item_id or not text:
            continue
        ids.append(item_id)
        texts.append(text)
        meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        metas.append({str(k): v for k, v in meta.items() if isinstance(v, (str, int, float, bool))})

    if not ids:
        return {"error": "items 里没有合法的 {id,text} 组合"}

    embed = _embedding_fn()
    if embed is None:
        return _unavailable("embedding 解析失败")

    try:
        _COLLECTION.upsert(
            ids=ids,
            documents=texts,
            embeddings=[embed(t) for t in texts],
            metadatas=metas or None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("knowledge pack: 写入失败", exc_info=True)
        return {"status": "error", "error": str(exc)[:300]}

    return {"status": "ok", "upserted": len(ids)}


# ── 注册 ────────────────────────────────────────────────

def register(ctx: Any) -> None:
    """只注册工具；不 import 任何重库（见 plugins/README.md 约束 1）。"""
    global _CTX
    _CTX = ctx

    ctx.tool_registry.register(
        "knowledge_vector_search",
        knowledge_vector_search,
        {
            "name": "knowledge_vector_search",
            "description": "在本地向量知识库里做语义检索，返回最相近的知识块（含来源 metadata）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索问题或关键词"},
                    "k": {"type": "integer", "description": "返回条数，默认 5，最多 50"},
                },
                "required": ["query"],
            },
        },
        provider_hint="text",
        category="utility",
    )
    ctx.tool_registry.register(
        "knowledge_vector_upsert",
        knowledge_vector_upsert,
        {
            "name": "knowledge_vector_upsert",
            "description": "把一个或多个知识块写入本地向量知识库（按 id 覆盖）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "[{id, text, metadata?}]，metadata 只保留标量字段",
                        "items": {"type": "object"},
                    },
                },
                "required": ["items"],
            },
        },
        provider_hint="text",
        category="utility",
    )
