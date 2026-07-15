"""知识自动分类器：LLM 驱动分类 + 自动创建类目

策略：
1. 获取现有分类树
2. 批量条目 → LLM 判断归属 → 批量更新
3. 新类别自动创建
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger

from knowledge.store import KnowledgeStore


class KnowledgeClassifier:
    """知识自动分类器"""

    def __init__(self, store: KnowledgeStore, brain=None):
        """
        Args:
            store: KnowledgeStore 实例
            brain: AIBrain 实例（用于 LLM 分类）。None 则跳过分类。
        """
        self._store = store
        self._brain = brain

    async def classify_entry(self, entry_id: str) -> Optional[str]:
        """
        给单条知识自动分类。

        Returns:
            分类名或 None
        """
        entry = await self._store.get_entry(entry_id)
        if not entry or not self._brain:
            return None

        categories = await self._store.get_categories()
        cat_names = [c["name"] for c in categories]

        prompt = self._build_classify_prompt(entry["content"], cat_names)
        try:
            result = await self._brain.classify_intent(prompt, prompt)
            category = result.strip().strip('"\'').strip()
            if category and category not in ("none", "null", "未知", "无"):
                # 确保分类存在
                if category not in cat_names:
                    await self._store.add_category(category)
                await self._store.update_entry(entry_id, category=category)
                logger.debug(f"分类: {entry_id[:8]} → {category}")
                return category
        except Exception as e:
            logger.warning(f"LLM 分类失败: {e}")

        return None

    async def classify_batch(self, limit: int = 50) -> int:
        """
        批量分类未分类的条目。

        Returns:
            分类成功的数量
        """
        # 获取未分类的活跃条目
        entries = await self._store.list_entries(status="active", limit=limit)
        unclassified = [e for e in entries if not e.get("category")]

        if not unclassified:
            logger.debug("没有待分类的条目")
            return 0

        count = 0
        for entry in unclassified:
            cat = await self.classify_entry(entry["id"])
            if cat:
                count += 1

        logger.info(f"批量分类完成: {count}/{len(unclassified)}")
        return count

    async def suggest_reorganization(self) -> Dict[str, Any]:
        """
        分析现有分类结构，建议重组方案。

        Returns:
            {"fragmented_categories": [...], "suggested_merges": [...]}
        """
        categories = await self._store.get_categories()
        cat_stats = {}

        for cat in categories:
            entries = await self._store.list_entries(
                category=cat["name"], status="active", limit=1000
            )
            cat_stats[cat["name"]] = len(entries)

        # 检测碎片化：同一类目下条目数 > 20 认为是碎片化
        fragmented = [
            name for name, count in cat_stats.items() if count > 20
        ]

        # 用 LLM 建议合并
        suggested_merges = []
        if fragmented and self._brain:
            merge_prompt = (
                f"以下分类下的条目较多（碎片化），建议如何合并或细分：\n"
                + "\n".join(f"- {name}: {count}条" for name, count in cat_stats.items())
                + "\n\n只回复合并建议，格式：'A + B → C' 每行一个。没有建议就回复'无'。"
            )
            try:
                result = await self._brain.classify_intent(merge_prompt, merge_prompt)
                if result.strip() not in ("无", "none"):
                    suggested_merges = [
                        line.strip() for line in result.strip().split("\n") if "→" in line
                    ]
            except Exception:
                pass

        return {
            "fragmented_categories": fragmented,
            "suggested_merges": suggested_merges,
            "category_stats": cat_stats,
        }

    @staticmethod
    def _build_classify_prompt(content: str, categories: List[str]) -> str:
        cats_str = "\n".join(f"- {c}" for c in categories) if categories else "（暂无分类）"
        return (
            f"你是一个知识分类器。将以下内容归类到最合适的类别中。"
            f"如果现有类别都不合适，创建一个新的简洁类别名（4-10字）。\n\n"
            f"现有类别：\n{cats_str}\n\n"
            f"内容：{content}\n\n"
            f"只回复类别名，不超过10个字。"
        )
