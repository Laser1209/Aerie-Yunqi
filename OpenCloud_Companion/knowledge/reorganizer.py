"""知识重组器：去重、矛盾解决、碎片整理、冷热分离

触发条件（满足任一）：
1. 活跃条目 > 100
2. 碎片化检测：某类目下 > 20 条
3. 矛盾检测：语义相似但结论相反
4. 冷数据归档：90 天未被检索
5. 手动触发
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from knowledge.store import KnowledgeStore


class KnowledgeReorganizer:
    """知识重组器"""

    def __init__(self, store: KnowledgeStore, brain=None):
        self._store = store
        self._brain = brain

    async def check_and_reorganize(self) -> Dict[str, Any]:
        """
        检查是否需要重组，需要就执行。

        Returns:
            {"action": str, "details": [...], "total_changes": int}
        """
        stats = await self._store.get_stats()
        total = stats["total_active"]
        log_entries = []

        # 检查触发条件
        need_reorg = False

        if total > 100:
            need_reorg = True
            log_entries.append(f"条目数 {total} > 100，触发全量审计")

        # 检查碎片化
        fragmented = await self._detect_fragmentation()
        if fragmented:
            need_reorg = True
            log_entries.append(f"检测到 {len(fragmented)} 个碎片化分类")

        if not need_reorg:
            logger.debug("知识库无需重组")
            return {"action": "skip", "details": [], "total_changes": 0}

        changes = []
        total_changes = 0

        # 1. 去重
        try:
            dup_count = await self._deduplicate()
            if dup_count > 0:
                changes.append(f"合并 {dup_count} 条重复知识")
                total_changes += dup_count
                await self._store.add_changelog("dedup", f"合并 {dup_count} 条", dup_count)
        except Exception as e:
            logger.warning(f"去重失败: {e}")

        # 2. 碎片整理
        try:
            frag_count = await self._defragment_categories()
            if frag_count > 0:
                changes.append(f"整理 {frag_count} 条碎片知识")
                total_changes += frag_count
                await self._store.add_changelog("defrag", f"整理 {frag_count} 条", frag_count)
        except Exception as e:
            logger.warning(f"碎片整理失败: {e}")

        # 3. 冷数据归档
        try:
            arch_count = await self._archive_cold_data(days=90)
            if arch_count > 0:
                changes.append(f"归档 {arch_count} 条冷数据")
                total_changes += arch_count
                await self._store.add_changelog("archive", f"归档 {arch_count} 条", arch_count)
        except Exception as e:
            logger.warning(f"冷数据归档失败: {e}")

        result = {
            "action": "reorganized",
            "details": changes,
            "total_changes": total_changes,
        }
        logger.info(f"知识重组完成: {changes}")
        return result

    async def _deduplicate(self) -> int:
        """去重：合并相似度 > 0.92 的条目"""
        duplicate_groups = await self._store.find_duplicates(threshold=0.92)
        if not duplicate_groups:
            return 0

        count = 0
        for group in duplicate_groups:
            if len(group) < 2:
                continue

            # 按 confidence + 时间排序，保留最佳的
            entries = []
            for eid in group:
                entry = await self._store.get_entry(eid)
                if entry:
                    entries.append(entry)

            if len(entries) < 2:
                continue

            entries.sort(
                key=lambda e: (e.get("confidence", 0), e.get("updated_at", "")),
                reverse=True,
            )
            primary = entries[0]

            # 标记其他为 superseded
            for dup in entries[1:]:
                await self._store.update_entry(
                    dup["id"],
                    status="superseded",
                    previous_id=primary["id"],
                )
                count += 1

        return count

    async def _detect_fragmentation(self, max_per_category: int = 20) -> List[str]:
        """检测碎片化分类"""
        entries = await self._store.get_active_entries()
        cat_counts: Dict[str, int] = {}
        for entry in entries:
            cat = entry.get("category", "")
            if cat:
                cat_counts[cat] = cat_counts.get(cat, 0) + 1

        return [cat for cat, count in cat_counts.items() if count > max_per_category]

    async def _defragment_categories(self) -> int:
        """
        碎片整理：用 LLM 将碎片化类目下的条目重新提炼。
        简单策略：将类目下所有条目的内容合并，让 LLM 提炼成更少的精炼条目。
        """
        fragmented = await self._detect_fragmentation()
        if not fragmented or not self._brain:
            return 0

        count = 0
        for cat in fragmented[:3]:  # 一次最多处理 3 个类目
            entries = await self._store.list_entries(
                category=cat, status="active", limit=100
            )
            if len(entries) < 20:
                continue

            # 收集所有内容
            contents = [e["content"] for e in entries if e.get("content")]
            if not contents:
                continue

            combined = "\n---\n".join(contents)
            prompt = (
                f"以下是一个知识类目「{cat}」下的所有知识条目。"
                f"请将它们提炼成 3-5 条更精炼的知识点，去除重复和冗余信息。"
                f"每条知识点一行，不超过100字。\n\n"
                f"{combined[:4000]}"  # 限制 token
            )
            
            try:
                result = await self._brain.generate_reply([
                    {"role": "system", "content": "你是知识提炼助手。提炼知识要点，每行一条。"},
                    {"role": "user", "content": prompt},
                ])
                # 将原始条目标记为 superseded
                for entry in entries:
                    await self._store.update_entry(entry["id"], status="superseded")
                count += len(entries)
                logger.info(f"碎片整理: {cat} ({len(entries)} → 提炼)")
            except Exception as e:
                logger.warning(f"碎片整理失败 ({cat}): {e}")

        return count

    async def _archive_cold_data(self, days: int = 90) -> int:
        """归档冷数据"""
        cold_entries = await self._store.find_cold_entries(days)
        count = 0
        for entry in cold_entries:
            await self._store.update_entry(entry["id"], status="archived")
            count += 1

        if count > 0:
            logger.info(f"归档 {count} 条冷数据 (>{days}天未访问)")

        return count

    async def get_reorg_log(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取最近的变更日志"""
        return await self._store.get_changelog(limit)
