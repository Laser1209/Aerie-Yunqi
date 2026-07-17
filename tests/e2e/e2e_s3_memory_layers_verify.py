"""Aerie · 云栖 v11.2 — S3 M3.1 四层记忆架构验证.

验证四层记忆的 CRUD、检索、巩固、衰减等功能。
纯本地（不依赖 ChromaDB，自动降级到 SQLite 模式）。
用法: python e2e_s3_memory_layers_verify.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _check(label: str, ok: bool, detail: str = "") -> None:
    sym = "✓" if ok else "✗"
    print(f"  {sym} {label}  {detail}")


# ── 简易 DB mock ────────────────────────────────────

class MockDB:
    """简易 SQLite 模拟，用 dict 存数据."""

    def __init__(self) -> None:
        self.tables: dict[str, dict[str, dict]] = {}

    def execute(self, sql: str, params: tuple = ()) -> None:
        import re
        # CREATE TABLE
        if "CREATE TABLE IF NOT EXISTS" in sql:
            match = re.search(r"CREATE TABLE IF NOT EXISTS (\w+)", sql)
            if match:
                table = match.group(1)
                if table not in self.tables:
                    self.tables[table] = {}
            return

        # UPDATE table SET col = ?, ... WHERE id = ?
        update_match = re.match(r"UPDATE (\w+) SET (.+?) WHERE (.+)$", sql, re.IGNORECASE)
        if update_match:
            table = update_match.group(1)
            set_clause = update_match.group(2).strip()
            where_clause = update_match.group(3).strip()
            if table not in self.tables:
                return

            # 解析 SET 子句
            set_pairs = [p.strip() for p in set_clause.split(",")]
            set_fields = []
            for p in set_pairs:
                m = re.match(r"(\w+)\s*=\s*\?", p)
                if m:
                    set_fields.append(m.group(1))

            # 解析 WHERE
            where_m = re.match(r"(\w+)\s*=\s*\?", where_clause)
            where_field = where_m.group(1) if where_m else "id"

            # 找到匹配的行并更新
            p_idx = 0
            set_values = params[:len(set_fields)]
            where_value = params[len(set_fields)] if len(params) > len(set_fields) else None

            for row in self.tables[table].values():
                if str(row.get(where_field)) == str(where_value):
                    for f, v in zip(set_fields, set_values):
                        row[f] = v
            return

        # DELETE FROM table WHERE id = ?
        delete_match = re.match(r"DELETE FROM (\w+) WHERE (.+)$", sql, re.IGNORECASE)
        if delete_match:
            table = delete_match.group(1)
            where_clause = delete_match.group(2).strip()
            if table not in self.tables:
                return

            where_m = re.match(r"(\w+)\s*=\s*\?", where_clause)
            where_field = where_m.group(1) if where_m else "id"
            where_value = params[0] if params else None

            to_delete = []
            for key, row in self.tables[table].items():
                if str(row.get(where_field)) == str(where_value):
                    to_delete.append(key)
            for key in to_delete:
                del self.tables[table][key]
            return

    def insert(self, table: str, data: dict) -> int:
        if table not in self.tables:
            self.tables[table] = {}
        mid = data.get("id") or str(len(self.tables[table]) + 1)
        row = dict(data)
        row["id"] = mid
        self.tables[table][mid] = row
        return mid

    def upsert(self, table: str, data: dict, key: str = "id") -> None:
        if table not in self.tables:
            self.tables[table] = {}
        mid = data.get(key)
        self.tables[table][mid] = dict(data)

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        # 极简解析：只处理 SELECT ... FROM table WHERE user_id = ? ORDER BY ... LIMIT ?
        import re
        table_match = re.search(r"FROM (\w+)", sql)
        if not table_match:
            return []
        table = table_match.group(1)
        if table not in self.tables:
            return []

        rows = list(self.tables[table].values())

        # WHERE user_id = ? AND memory_type = ? AND content LIKE ?
        param_idx = 0
        where_match = re.search(
            r"WHERE (.+?) ORDER|WHERE (.+?)$",
            sql, re.IGNORECASE | re.DOTALL,
        )
        if where_match:
            where_clause = (where_match.group(1) or where_match.group(2)).strip()
            # 把换行和多余空白换成空格
            where_clause = re.sub(r"\s+", " ", where_clause)
            conditions = [c.strip() for c in where_clause.split("AND")]
            filtered = []
            for row in rows:
                match = True
                p_idx = 0
                for cond in conditions:
                    if "user_id = ?" in cond:
                        if row.get("user_id") != params[p_idx]:
                            match = False
                        p_idx += 1
                    elif "memory_type = ?" in cond:
                        if row.get("memory_type") != params[p_idx]:
                            match = False
                        p_idx += 1
                    elif "content LIKE ?" in cond:
                        pattern = params[p_idx].replace("%", "")
                        if pattern not in row.get("content", ""):
                            match = False
                        p_idx += 1
                    elif "id = ?" in cond:
                        if str(row.get("id")) != str(params[p_idx]):
                            match = False
                        p_idx += 1
                if match:
                    filtered.append(row)
            rows = filtered

        # ORDER BY importance DESC, created_at DESC
        if "ORDER BY" in sql:
            order_match = re.search(
                r"ORDER BY (.+?) LIMIT|ORDER BY (.+?)$",
                sql, re.IGNORECASE | re.DOTALL,
            )
            if order_match:
                order_clause = (order_match.group(1) or order_match.group(2)).strip()
                order_clause = re.sub(r"\s+", " ", order_clause)
                orders = [o.strip() for o in order_clause.split(",")]
                def sort_key(row: dict) -> tuple:
                    keys = []
                    for o in orders:
                        parts = o.split()
                        field = parts[0]
                        desc = len(parts) > 1 and parts[1].upper() == "DESC"
                        val = row.get(field, 0)
                        if desc:
                            if isinstance(val, (int, float)):
                                keys.append(-val)
                            else:
                                keys.append(val)
                                keys.append("_desc")
                        else:
                            keys.append(val)
                    return tuple(keys)
                rows.sort(key=sort_key)

        # LIMIT
        limit_match = re.search(r"LIMIT (\d+)", sql)
        if limit_match:
            limit = int(limit_match.group(1))
            rows = rows[:limit]

        return rows

    def query_one(self, sql: str, params: tuple = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None


# ─────────────────────────────────────────────────────
# T1 · Transient 记忆层
# ─────────────────────────────────────────────────────

async def test_t1_transient() -> bool:
    """验证瞬时记忆层."""
    print("\n[T1] Transient 瞬时记忆层")
    all_ok = True

    from memory.layers import TransientMemory, MemoryItem, MemoryType, MemoryLayer

    mem = TransientMemory()

    # 1.1 存储
    item = MemoryItem(
        user_id=1,
        memory_type=MemoryType.FACT,
        content="临时变量 x = 42",
        importance=1.0,
        metadata={"session_id": "sess_001", "key": "tmp_x"},
    )
    mid = await mem.store(item)
    ok = mid is not None
    _check("1.1 存储成功", ok, f"id={mid}")
    if not ok:
        all_ok = False

    # 1.2 检索
    results = await mem.retrieve(user_id=1, query="x = 42")
    ok = len(results) >= 1
    _check("1.2 检索返回结果", ok, f"count={len(results)}")
    if not ok:
        all_ok = False

    # 1.3 按 ID 获取
    got = await mem.get(mid)
    ok = got is not None and got.content == "临时变量 x = 42"
    _check("1.3 按 ID 获取", ok)
    if not ok:
        all_ok = False

    # 1.4 更新
    ok = await mem.update(mid, content="临时变量 x = 99")
    got = await mem.get(mid)
    ok = ok and got and got.content == "临时变量 x = 99"
    _check("1.4 更新成功", ok)
    if not ok:
        all_ok = False

    # 1.5 删除
    ok = await mem.delete(mid)
    got = await mem.get(mid)
    ok = ok and got is None
    _check("1.5 删除成功", ok)
    if not ok:
        all_ok = False

    # 1.6 清空会话
    item2 = MemoryItem(
        user_id=1, memory_type=MemoryType.FACT,
        content="会话内临时数据",
        metadata={"session_id": "sess_002"},
    )
    await mem.store(item2)
    mem.clear_session("sess_002")
    results2 = await mem.retrieve(user_id=1, query="临时")
    # 不应该有 sess_002 的了
    has_sess2 = any("sess_002" in str(r.item.metadata) for r in results2)
    _check("1.6 清空会话后数据消失", not has_sess2)
    if has_sess2:
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# T2 · Working 记忆层
# ─────────────────────────────────────────────────────

async def test_t2_working() -> bool:
    """验证工作记忆层 + LRU 淘汰."""
    print("\n[T2] Working 工作记忆层")
    all_ok = True

    from memory.layers import WorkingMemory, MemoryItem, MemoryType

    mem = WorkingMemory(max_items_per_user=5)

    # 2.1 存储 + LRU
    for i in range(7):  # 超过 max_items
        item = MemoryItem(
            user_id=1,
            memory_type=MemoryType.FACT,
            content=f"工作记忆 #{i}",
            importance=5.0,
        )
        await mem.store(item)

    items = await mem.list_by_user(1)
    ok = len(items) == 5  # LRU 淘汰到 5 条
    _check("2.1 LRU 淘汰生效", ok, f"count={len(items)}")
    if not ok:
        all_ok = False

    # 2.2 最新的在最前
    ok = items[0].content == "工作记忆 #6"
    _check("2.2 最新记忆优先", ok, f"first={items[0].content}")
    if not ok:
        all_ok = False

    # 2.3 访问后提升到最新
    oldest_id = items[-1].id
    await mem.get(oldest_id)  # 访问最旧的
    items2 = await mem.list_by_user(1)
    ok = items2[0].id == oldest_id
    _check("2.3 访问后 LRU 提升", ok, f"newest_id={items2[0].id}")
    if not ok:
        all_ok = False

    # 2.4 检索
    results = await mem.retrieve(user_id=1, query="工作记忆")
    ok = len(results) > 0 and results[0].score > 0
    _check("2.4 检索返回结果", ok, f"count={len(results)}, top_score={results[0].score if results else 0}")
    if not ok:
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# T3 · Long-term 记忆层
# ─────────────────────────────────────────────────────

async def test_t3_long_term() -> bool:
    """验证长期记忆层（SQLite 模式，ChromaDB 可选）."""
    print("\n[T3] Long-term 长期记忆层")
    all_ok = True

    from memory.layers import LongTermMemoryLayer, MemoryItem, MemoryType, MemoryLayer

    db = MockDB()
    mem = LongTermMemoryLayer(db=db, chroma_persist_dir=tempfile.mkdtemp())

    # 3.1 存储
    item = MemoryItem(
        user_id=1,
        memory_type=MemoryType.PREFERENCE,
        content="用户喜欢喝咖啡，不加糖",
        importance=8.0,
        source="conversation",
    )
    mid = await mem.store(item)
    ok = mid is not None
    _check("3.1 存储成功", ok, f"id={mid}")
    if not ok:
        all_ok = False

    # 3.2 按 ID 获取
    got = await mem.get(mid)
    ok = got is not None and got.memory_type == MemoryType.PREFERENCE
    _check("3.2 按 ID 获取", ok, f"type={got.memory_type.value if got else 'None'}")
    if not ok:
        all_ok = False

    # 3.3 关键词检索
    results = await mem.retrieve(user_id=1, query="咖啡")
    ok = len(results) >= 1
    _check("3.3 关键词检索", ok, f"count={len(results)}")
    if not ok:
        all_ok = False

    # 3.4 按重要度排序
    item_low = MemoryItem(
        user_id=1, memory_type=MemoryType.FACT,
        content="今天天气不错", importance=3.0,
    )
    await mem.store(item_low)
    results2 = await mem.retrieve(user_id=1, limit=10)
    ok = len(results2) >= 2 and results2[0].item.importance >= results2[1].item.importance
    _check("3.4 按重要度排序", ok,
           f"top_importance={results2[0].item.importance if results2 else 0}")
    if not ok:
        all_ok = False

    # 3.5 更新
    ok = await mem.update(mid, importance=9.0, content="用户喜欢喝咖啡，不加糖，加奶")
    got = await mem.get(mid)
    ok = ok and got and got.importance == 9.0
    _check("3.5 更新成功", ok, f"importance={got.importance if got else 0}")
    if not ok:
        all_ok = False

    # 3.6 按类型过滤
    results3 = await mem.retrieve(user_id=1, memory_type=MemoryType.PREFERENCE)
    all_pref = all(r.item.memory_type == MemoryType.PREFERENCE for r in results3)
    _check("3.6 按类型过滤", all_pref, f"count={len(results3)}")
    if not all_pref:
        all_ok = False

    # 3.7 删除
    ok = await mem.delete(mid)
    got = await mem.get(mid)
    ok = ok and got is None
    _check("3.7 删除成功", ok)
    if not ok:
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# T4 · Permanent 记忆层
# ─────────────────────────────────────────────────────

async def test_t4_permanent() -> bool:
    """验证永久记忆层（Markdown + Git）."""
    print("\n[T4] Permanent 永久记忆层")
    all_ok = True

    from memory.layers import PermanentMemoryLayer, MemoryItem, MemoryType

    tmp_dir = tempfile.mkdtemp()
    mem = PermanentMemoryLayer(storage_dir=tmp_dir)

    # 4.1 存储
    item = MemoryItem(
        user_id=0,
        memory_type=MemoryType.PERSONA,
        content="# 核心人格设定\n\n你是 Etta，用户的专属恋人。\n",
        importance=10.0,
        source="manual",
    )
    mid = await mem.store(item)
    ok = mid is not None
    _check("4.1 存储成功", ok, f"id={mid}")
    if not ok:
        all_ok = False

    # 4.2 检索
    results = await mem.retrieve(user_id=0, query="Etta")
    ok = len(results) >= 1 and results[0].score >= 0.9
    _check("4.2 检索命中", ok,
           f"count={len(results)}, top_score={results[0].score if results else 0}")
    if not ok:
        all_ok = False

    # 4.3 按 ID 获取
    got = await mem.get(mid)
    ok = got is not None and "Etta" in got.content
    _check("4.3 按 ID 获取", ok)
    if not ok:
        all_ok = False

    # 4.4 文件实际写入磁盘
    filepath = os.path.join(tmp_dir, f"{mid}.md")
    ok = os.path.exists(filepath)
    _check("4.4 Markdown 文件已写入", ok, f"path={filepath}")
    if not ok:
        all_ok = False

    # 4.5 重要度最高
    ok = got and got.importance == 10.0
    _check("4.5 重要度 = 10.0", ok)
    if not ok:
        all_ok = False

    # 4.6 更新
    ok = await mem.update(mid, content="# 核心人格设定\n\n你是 Etta，用户的专属恋人。温柔且专业。\n")
    got = await mem.get(mid)
    ok = ok and got and "温柔且专业" in got.content
    _check("4.6 更新成功", ok)
    if not ok:
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# T5 · LayeredMemory 统一调度
# ─────────────────────────────────────────────────────

async def test_t5_layered_memory() -> bool:
    """验证统一调度器的多层检索、自动分层、巩固等."""
    print("\n[T5] LayeredMemory 统一调度")
    all_ok = True

    from memory.layers import LayeredMemory, MemoryType, MemoryLayer, MemoryItem

    db = MockDB()
    permanent_dir = tempfile.mkdtemp()
    chroma_dir = tempfile.mkdtemp()

    mem = LayeredMemory(
        db=db,
        chroma_persist_dir=chroma_dir,
        permanent_dir=permanent_dir,
        max_working_items=20,
    )

    # 5.1 自动分层存储（重要度低 → transient/working）
    mid1 = await mem.store(
        user_id=1, content="临时想法", importance=1.0,
    )
    mid2 = await mem.store(
        user_id=1, content="当前话题", importance=5.0,
    )
    mid3 = await mem.store(
        user_id=1, content="用户喜欢猫", importance=8.0,
        memory_type=MemoryType.PREFERENCE,
    )

    # 验证分别在不同层
    item1 = await mem.get(mid1)
    item2 = await mem.get(mid2)
    # 重要度 8 的同时存在于 long_term 和 working（working 有引用）
    item3_working = await mem.working.get(mid3)
    item3_long = await mem.long_term.get(mid3)

    ok1 = item1 and item1.layer == MemoryLayer.TRANSIENT
    _check("5.1a importance=1 → transient", ok1,
           f"layer={item1.layer.value if item1 else 'None'}")
    if not ok1:
        all_ok = False

    ok2 = item2 and item2.layer == MemoryLayer.WORKING
    _check("5.1b importance=5 → working", ok2,
           f"layer={item2.layer.value if item2 else 'None'}")
    if not ok2:
        all_ok = False

    ok3 = item3_long is not None and item3_long.layer == MemoryLayer.LONG_TERM and item3_working is not None
    _check("5.1c importance=8 → long_term (+ working 引用)", ok3,
           f"long_term={item3_long is not None}, working_ref={item3_working is not None}")
    if not ok3:
        all_ok = False

    # 5.2 多层联合检索
    results = await mem.search(user_id=1, query="喜欢")
    ok = len(results) >= 1
    _check("5.2 多层联合检索返回结果", ok, f"count={len(results)}")
    if not ok:
        all_ok = False

    # 5.3 按类型过滤
    results_pref = await mem.search(
        user_id=1, query="", memory_type=MemoryType.PREFERENCE,
    )
    all_pref = all(r.item.memory_type == MemoryType.PREFERENCE for r in results_pref)
    _check("5.3 按类型过滤", all_pref, f"count={len(results_pref)}")
    if not all_pref:
        all_ok = False

    # 5.4 永久记忆优先级最高
    await mem.permanent.store(
        MemoryItem(
            id="core_persona",
            user_id=0,
            memory_type=MemoryType.PERSONA,
            content="核心人格：你是 Etta",
            importance=10.0,
            layer=MemoryLayer.PERMANENT,
        )
    )
    results_all = await mem.search(user_id=1, query="Etta", limit=10)
    # 永久记忆应该排在前面（如果有的话）
    has_perm = any(r.layer == MemoryLayer.PERMANENT for r in results_all)
    _check("5.4 永久记忆参与检索", has_perm,
           f"top_layer={results_all[0].layer.value if results_all else 'None'}")
    if not has_perm:
        all_ok = False

    # 5.5 旧接口兼容
    old_results = await mem.memory_search("猫", top_k=3, user_id=1)
    ok = isinstance(old_results, list) and len(old_results) > 0
    ok = ok and "content" in old_results[0]
    _check("5.5 旧接口 memory_search 兼容", ok,
           f"count={len(old_results)}")
    if not ok:
        all_ok = False

    # 5.6 维护任务（巩固 + 衰减）
    # 先加几条高重要度的 working 记忆
    for i in range(3):
        await mem.store(
            user_id=1,
            content=f"重要工作记忆 #{i}",
            importance=8.5,
            memory_type=MemoryType.FACT,
        )
    # 让它们被访问 2 次以上（满足 consolidate 条件）
    working_items = await mem.working.list_by_user(1)
    for item in working_items[:3]:
        await mem.working.get(item.id)
        await mem.working.get(item.id)

    maintenance = await mem.run_maintenance()
    _check("5.6 维护任务执行", True,
           f"consolidated={maintenance.get('consolidated', 0)}, decayed={maintenance.get('decayed', 0)}")

    return all_ok


# ─────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────

async def main() -> int:
    print("=" * 60)
    print("Aerie v11.2 · S3 M3.1 四层记忆架构验证")
    print("=" * 60)

    results: list[tuple[str, bool]] = []

    results.append(("T1 Transient", await test_t1_transient()))
    results.append(("T2 Working", await test_t2_working()))
    results.append(("T3 Long-term", await test_t3_long_term()))
    results.append(("T4 Permanent", await test_t4_permanent()))
    results.append(("T5 LayeredMemory", await test_t5_layered_memory()))

    print("\n" + "=" * 60)
    print("汇总")
    print("=" * 60)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        sym = "✓ PASS" if ok else "✗ FAIL"
        print(f"  {sym}  {name}")

    print(f"\n结果: {passed}/{total} 通过")

    if passed == total:
        print("\n🎉 M3.1 四层记忆架构全部通过！")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 项未通过，请检查。")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
