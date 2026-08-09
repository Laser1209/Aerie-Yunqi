"""Aerie — Knowledge base write tools.

Registers ``knowledge_add`` so the LLM can save important facts into the
knowledge base (数据 → 知识库). The write reuses the same ``KnowledgeBase``
instance the companion already uses for context retrieval, so anything she
saves is immediately searchable and injectable into future prompts.

ZERO-BREAKING: adds new tool entries only; never modifies existing tools.
"""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


def _get_knowledge():
    """Return the live KnowledgeBase instance from the running companion."""
    from core.companion import get_companion

    comp = get_companion()
    kb = getattr(comp, "knowledge", None) if comp else None
    if kb is None:
        raise RuntimeError("companion knowledge base is not available")
    return kb


async def tool_knowledge_add(
    title: str = "",
    content: str = "",
    category: str = "",
    tags: str = "",
) -> dict:
    """Add (or update) one entry in the knowledge base.

    Deduplicates by exact title: if an entry with the same title already
    exists, its content is updated instead of creating a duplicate, so
    repeated saves keep facts current rather than piling up copies.
    """
    title = (title or "").strip()
    content = (content or "").strip()
    if not title or not content:
        return {"error": "title 与 content 都不能为空"}
    if len(content) > 8000:
        return {"error": "content 过长，请控制在 8000 字以内"}

    try:
        kb = _get_knowledge()
    except Exception as e:
        logger.exception("knowledge_add: cannot reach knowledge base")
        return {"error": f"知识库不可用: {e}"}

    # Exact-title dedup -> update instead of inserting a duplicate.
    rows, _ = kb.list(search=title, limit=20)
    for row in rows:
        if (row.get("title") or "").strip() == title:
            ok = kb.update(
                row["id"],
                category or row.get("category") or "",
                title,
                content,
                tags or row.get("tags") or "",
            )
            return {"status": "updated", "id": row["id"], "title": title}

    new_id = kb.add(category or "", title, content, tags or "")
    if not new_id:
        return {"error": "写入知识库失败（数据库不可用）"}
    return {"status": "added", "id": new_id, "title": title}


def register_knowledge_tools(registry) -> int:
    """Register knowledge-base write tools. Returns the number registered."""
    registry.register(
        "knowledge_add",
        tool_knowledge_add,
        {
            "name": "knowledge_add",
            "description": (
                "把重要信息写入知识库（数据 → 知识库）。用于记住需要长期保存的事实、"
                "偏好、约定或知识；写入后 AI 在未来的对话中会自动检索并引用这些信息。"
                "使用场景：用户的重要信息、明确要求记住的内容、值得长期沉淀的事实。"
                "若 title 已存在则自动更新该条目，不会重复新增。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "条目标题（用于去重和检索），如「用户的生日」",
                    },
                    "content": {
                        "type": "string",
                        "description": "条目正文，写清楚要保存的完整信息",
                    },
                    "category": {
                        "type": "string",
                        "description": "可选，分类，如「个人资料」「偏好」「约定」",
                    },
                    "tags": {
                        "type": "string",
                        "description": "可选，逗号分隔的标签，便于检索",
                    },
                },
                "required": ["title", "content"],
            },
        },
        provider_hint="text",
        category="knowledge",
    )
    logger.info("knowledge tool registered: knowledge_add")
    return 1
