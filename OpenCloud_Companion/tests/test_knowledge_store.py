"""知识库存储测试"""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest
import pytest_asyncio

from knowledge.store import KnowledgeStore


@pytest_asyncio.fixture
async def store():
    """创建临时知识库实例"""
    tmpdir = tempfile.mkdtemp()
    db_path = str(Path(tmpdir) / "test_knowledge.db")
    s = KnowledgeStore(db_path=db_path, embedding_dim=8)
    await s.initialize()
    yield s
    await s.close()
    # Cleanup
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


def _make_embedding(values=None, dim=8):
    """创建测试用嵌入向量"""
    if values is None:
        values = np.random.randn(dim).astype(np.float32)
    else:
        arr = np.zeros(dim, dtype=np.float32)
        for i, v in enumerate(values):
            if i < dim:
                arr[i] = v
        values = arr
    return values


class TestKnowledgeStore:
    """知识库存储测试"""

    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self, store):
        """初始化创建三张表"""
        # 验证表存在
        tables = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {r[0] for r in tables}
        assert "knowledge_entries" in table_names
        assert "knowledge_categories" in table_names
        assert "knowledge_changelog" in table_names

    @pytest.mark.asyncio
    async def test_add_and_get_entry(self, store):
        """添加和获取条目"""
        eid = await store.add_entry("测试知识", source="test")
        assert eid
        entry = await store.get_entry(eid)
        assert entry is not None
        assert entry["content"] == "测试知识"
        assert entry["source"] == "test"
        assert entry["status"] == "active"

    @pytest.mark.asyncio
    async def test_add_entry_with_embedding(self, store):
        """添加带嵌入向量的条目"""
        emb = _make_embedding([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        eid = await store.add_entry("向量知识", embedding=emb)
        entry = await store.get_entry(eid)
        assert entry["content"] == "向量知识"
        # embedding is stored but not returned in dict

    @pytest.mark.asyncio
    async def test_add_entry_with_tags(self, store):
        """标签存储和检索"""
        eid = await store.add_entry("标签测试", tags=["测试", "知识"])
        entry = await store.get_entry(eid)
        assert entry["tags"] == ["测试", "知识"]

    @pytest.mark.asyncio
    async def test_update_entry(self, store):
        """更新条目"""
        eid = await store.add_entry("原始内容")
        ok = await store.update_entry(eid, content="更新内容", confidence=0.5)
        assert ok
        entry = await store.get_entry(eid)
        assert entry["content"] == "更新内容"
        assert entry["confidence"] == 0.5

    @pytest.mark.asyncio
    async def test_delete_entry_soft(self, store):
        """软删除"""
        eid = await store.add_entry("待删除")
        ok = await store.delete_entry(eid)
        assert ok
        entry = await store.get_entry(eid)
        assert entry["status"] == "deleted"

    @pytest.mark.asyncio
    async def test_list_entries_filter(self, store):
        """按分类过滤列表"""
        await store.add_entry("条目A", category="cat1")
        await store.add_entry("条目B", category="cat2")
        await store.add_entry("条目C", category="cat1")

        cat1_entries = await store.list_entries(category="cat1", status="active")
        assert len(cat1_entries) == 2

    @pytest.mark.asyncio
    async def test_search_semantic(self, store):
        """语义检索"""
        # 创建 3 个不同方向的向量
        emb_a = _make_embedding([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        emb_b = _make_embedding([0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        emb_c = _make_embedding([0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0])

        await store.add_entry("AI 相关", embedding=emb_a)
        await store.add_entry("美食相关", embedding=emb_b)
        await store.add_entry("旅行相关", embedding=emb_c)

        # 搜索与 emb_a 相似的内容
        results = await store.search(emb_a, top_k=2)
        assert len(results) >= 1
        assert results[0]["content"] == "AI 相关"
        assert results[0]["similarity"] > 0.9

    @pytest.mark.asyncio
    async def test_find_duplicates(self, store):
        """查找重复条目"""
        emb1 = _make_embedding([1.0, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        emb2 = _make_embedding([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])  # very similar
        emb3 = _make_embedding([0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0])  # different

        await store.add_entry("相同A", embedding=emb1)
        await store.add_entry("相同B", embedding=emb2)
        await store.add_entry("不同C", embedding=emb3)

        groups = await store.find_duplicates(threshold=0.9)
        assert len(groups) >= 1

    @pytest.mark.asyncio
    async def test_find_cold_entries(self, store):
        """查找冷数据"""
        eid = await store.add_entry("冷数据")
        # 手动将 last_accessed 设为 100 天前
        from datetime import datetime, timedelta
        old_time = (datetime.now() - timedelta(days=100)).isoformat()
        store._conn.execute(
            "UPDATE knowledge_entries SET last_accessed=? WHERE id=?",
            (old_time, eid),
        )
        store._conn.commit()

        cold = await store.find_cold_entries(days=90)
        assert len(cold) >= 1
        assert cold[0]["content"] == "冷数据"

    @pytest.mark.asyncio
    async def test_get_stats(self, store):
        """统计数据"""
        await store.add_entry("条目1")
        await store.add_entry("条目2", embedding=_make_embedding())

        stats = await store.get_stats()
        assert stats["total_active"] == 2
        assert stats["with_embedding"] == 1
        assert stats["total_archived"] == 0

    @pytest.mark.asyncio
    async def test_categories_crud(self, store):
        """分类增删查"""
        cat_id = await store.add_category("技术")
        assert cat_id > 0
        cats = await store.get_categories()
        assert any(c["name"] == "技术" for c in cats)

    @pytest.mark.asyncio
    async def test_batch_update_category(self, store):
        """批量更新分类"""
        eid1 = await store.add_entry("内容1")
        eid2 = await store.add_entry("内容2")
        count = await store.batch_update_category([eid1, eid2], "新分类")
        assert count == 2
        e1 = await store.get_entry(eid1)
        assert e1["category"] == "新分类"

    @pytest.mark.asyncio
    async def test_changelog(self, store):
        """变更日志"""
        await store.add_changelog("dedup", "合并3条", 3)
        logs = await store.get_changelog(limit=5)
        assert len(logs) == 1
        assert logs[0]["action"] == "dedup"
        assert logs[0]["affected_count"] == 3
