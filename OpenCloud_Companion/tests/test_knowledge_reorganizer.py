"""知识重组器测试"""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest
import pytest_asyncio

from knowledge.store import KnowledgeStore
from knowledge.reorganizer import KnowledgeReorganizer


@pytest_asyncio.fixture
async def store():
    tmpdir = tempfile.mkdtemp()
    db_path = str(Path(tmpdir) / "test_reorg.db")
    s = KnowledgeStore(db_path=db_path, embedding_dim=8)
    await s.initialize()
    yield s
    await s.close()
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


def _make_emb(values):
    arr = np.zeros(8, dtype=np.float32)
    for i, v in enumerate(values):
        if i < 8:
            arr[i] = v
    return arr


class TestKnowledgeReorganizer:
    """知识重组器测试"""

    @pytest.mark.asyncio
    async def test_skip_when_few_entries(self, store):
        """条目少时不触发重组"""
        await store.add_entry("测试")
        reorganizer = KnowledgeReorganizer(store)
        result = await reorganizer.check_and_reorganize()
        assert result["action"] == "skip"

    @pytest.mark.asyncio
    async def test_deduplicate(self, store):
        """去重测试"""
        emb1 = _make_emb([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        emb2 = _make_emb([1.0, 0.01, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        emb3 = _make_emb([1.0, 0.02, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

        eid1 = await store.add_entry("内容A", embedding=emb1, confidence=0.5)
        eid2 = await store.add_entry("内容B", embedding=emb2, confidence=0.9)
        eid3 = await store.add_entry("内容C", embedding=emb3, confidence=0.7)

        groups = await store.find_duplicates(threshold=0.9)
        assert len(groups) >= 1  # 3 similar entries should form at least 1 group

    @pytest.mark.asyncio
    async def test_archive_cold_data(self, store):
        """冷数据归档"""
        eid = await store.add_entry("旧数据")
        from datetime import datetime, timedelta
        old_time = (datetime.now() - timedelta(days=100)).isoformat()
        store._conn.execute(
            "UPDATE knowledge_entries SET last_accessed=? WHERE id=?",
            (old_time, eid),
        )
        store._conn.commit()

        reorganizer = KnowledgeReorganizer(store)
        count = await reorganizer._archive_cold_data(days=90)
        assert count >= 1

        entry = await store.get_entry(eid)
        assert entry["status"] == "archived"

    @pytest.mark.asyncio
    async def test_get_reorg_log(self, store):
        """获取重组日志"""
        await store.add_changelog("dedup", "合并测试", 2)
        reorganizer = KnowledgeReorganizer(store)
        logs = await reorganizer.get_reorg_log(limit=5)
        assert len(logs) == 1
        assert logs[0]["action"] == "dedup"
