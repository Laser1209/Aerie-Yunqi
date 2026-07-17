"""Aerie · 云栖 v11.2 — S3 M3.2 长期记忆迁移验证.

验证迁移脚本的幂等性、数据完整性、回滚等功能。
用法: python e2e_s3_migration_verify.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import json

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


def _create_legacy_db(db_path: str) -> None:
    """创建一个模拟旧版本的数据库（只有旧字段）."""
    import sqlite3
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 旧版 long_term_memory 表（只有旧字段）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS long_term_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            memory_type TEXT NOT NULL,
            content TEXT NOT NULL,
            importance INTEGER DEFAULT 5,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            accessed_at TEXT
        )
    """)

    # 插入一些旧数据
    sample_data = [
        (1, "preference", "用户喜欢喝咖啡", 8, None),
        (1, "fact", "用户住在北京", 6, None),
        (1, "event", "2024年一起去了日本", 9, None),
        (2, "preference", "用户喜欢猫", 7, None),
        (2, "fact", "用户是程序员", 5, None),
    ]
    for uid, mtype, content, imp, accessed in sample_data:
        cursor.execute(
            "INSERT INTO long_term_memory (user_id, memory_type, content, importance, accessed_at) VALUES (?, ?, ?, ?, ?)",
            (uid, mtype, content, imp, accessed),
        )

    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────
# T1 · 迁移状态检测
# ─────────────────────────────────────────────────────

def test_t1_status_check() -> bool:
    """验证迁移状态检测."""
    print("\n[T1] 迁移状态检测")
    all_ok = True

    from scripts.migrate_long_term_memory import get_migration_status

    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test.db")

    # 1.1 空数据库状态 — 直接检查文件和 sqlite_master，不通过 Database
    import sqlite3
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='long_term_memory'"
    )
    row = cursor.fetchone()
    conn.close()
    ok = row is None
    _check("1.1 空库：表不存在", ok)
    if not ok:
        all_ok = False

    # 1.2 旧版数据库（缺少字段）
    from core.database import Database
    _create_legacy_db(db_path)
    db2 = Database(db_path)
    status2 = get_migration_status(db2)
    ok = status2["table_exists"] is True
    ok = ok and status2["total_records"] == 5
    ok = ok and len(status2["missing_columns"]) > 0
    ok = ok and status2["needs_migration"] is True
    _check("1.2 旧库：检测到需要迁移", ok,
           f"total={status2['total_records']}, missing={len(status2['missing_columns'])}")
    if not ok:
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# T2 · 迁移执行
# ─────────────────────────────────────────────────────

def test_t2_migration() -> bool:
    """验证迁移执行（schema + data）."""
    print("\n[T2] 迁移执行")
    all_ok = True

    from scripts.migrate_long_term_memory import (
        get_migration_status, migrate_schema, migrate_data,
    )

    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test.db")
    _create_legacy_db(db_path)

    from core.database import Database
    db = Database(db_path)

    # 2.1 迁移表结构
    actions = migrate_schema(db, dry_run=False)
    ok = len(actions) == 5  # metadata, source, access_count, updated_at, has_embedding
    _check("2.1 新增 5 个字段", ok, f"actions={len(actions)}")
    if not ok:
        all_ok = False

    status = get_migration_status(db)
    ok = len(status["missing_columns"]) == 0
    _check("2.1b 字段不再缺失", ok)
    if not ok:
        all_ok = False

    # 2.2 迁移数据
    stats = migrate_data(db, dry_run=False)
    ok = stats["total"] == 5 and stats["updated"] == 5 and stats["skipped"] == 0
    _check("2.2 5 条记录全部迁移", ok,
           f"total={stats['total']}, updated={stats['updated']}, skipped={stats['skipped']}")
    if not ok:
        all_ok = False

    # 2.3 验证字段值
    rows = db.query("SELECT * FROM long_term_memory WHERE user_id = 1 ORDER BY id")
    ok = len(rows) == 3
    _check("2.3a 查询用户 1 的 3 条记忆", ok)
    if not ok:
        all_ok = False

    # 验证迁移后的字段
    r0 = rows[0]
    ok = r0.get("source") == "migration"
    _check("2.3b source 字段 = migration", ok, f"source={r0.get('source')}")
    if not ok:
        all_ok = False

    ok = r0.get("access_count") == 0
    _check("2.3c access_count = 0", ok)
    if not ok:
        all_ok = False

    ok = r0.get("has_embedding") == 0
    _check("2.3d has_embedding = 0", ok)
    if not ok:
        all_ok = False

    metadata = json.loads(r0.get("metadata", "{}"))
    ok = metadata.get("legacy_import") is True
    _check("2.3e metadata 包含 legacy_import 标记", ok, f"metadata={metadata}")
    if not ok:
        all_ok = False

    # 2.4 旧字段保留完整
    ok = r0.get("content") == "用户喜欢喝咖啡"
    ok = ok and r0.get("importance") == 8
    ok = ok and r0.get("memory_type") == "preference"
    _check("2.4 旧字段数据完整保留", ok,
           f"content={r0.get('content')}, importance={r0.get('importance')}")
    if not ok:
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# T3 · 幂等性
# ─────────────────────────────────────────────────────

def test_t3_idempotent() -> bool:
    """验证迁移幂等性（重复运行不破坏数据）."""
    print("\n[T3] 迁移幂等性")
    all_ok = True

    from scripts.migrate_long_term_memory import (
        get_migration_status, migrate_schema, migrate_data,
    )

    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test.db")
    _create_legacy_db(db_path)

    from core.database import Database
    db = Database(db_path)

    # 第一次迁移
    migrate_schema(db)
    stats1 = migrate_data(db)

    # 第二次迁移
    actions2 = migrate_schema(db)
    stats2 = migrate_data(db)

    # 第三次迁移
    stats3 = migrate_data(db)

    ok = len(actions2) == 0
    _check("3.1 第二次 schema 迁移无操作", ok, f"actions={len(actions2)}")
    if not ok:
        all_ok = False

    ok = stats2["updated"] == 0 and stats2["skipped"] == 5
    _check("3.2 第二次数据迁移全部跳过", ok,
           f"updated={stats2['updated']}, skipped={stats2['skipped']}")
    if not ok:
        all_ok = False

    ok = stats3["updated"] == 0
    _check("3.3 第三次数据迁移仍全部跳过", ok)
    if not ok:
        all_ok = False

    # 数据完整性
    rows = db.query("SELECT COUNT(*) as cnt FROM long_term_memory")
    ok = rows[0]["cnt"] == 5
    _check("3.4 记录数保持 5 条", ok, f"count={rows[0]['cnt']}")
    if not ok:
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# T4 · 回滚
# ─────────────────────────────────────────────────────

def test_t4_rollback() -> bool:
    """验证回滚功能."""
    print("\n[T4] 回滚功能")
    all_ok = True

    from scripts.migrate_long_term_memory import (
        get_migration_status, migrate_schema, migrate_data, rollback_migration,
    )

    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test.db")
    _create_legacy_db(db_path)

    from core.database import Database
    db = Database(db_path)

    # 先迁移
    migrate_schema(db)
    migrate_data(db)

    # 验证迁移成功
    rows_before = db.query("SELECT * FROM long_term_memory LIMIT 1")
    ok_before = rows_before[0].get("source") == "migration"
    _check("4.1 迁移后 source = migration", ok_before)
    if not ok_before:
        all_ok = False

    # 回滚
    rollback_stats = rollback_migration(db, dry_run=False)
    ok = rollback_stats["rolled_back"] == 5
    _check("4.2 回滚 5 条记录", ok, f"rolled_back={rollback_stats['rolled_back']}")
    if not ok:
        all_ok = False

    # 验证回滚后
    rows_after = db.query("SELECT * FROM long_term_memory LIMIT 1")
    source_after = rows_after[0].get("source")
    ok = source_after is None or source_after == ""
    _check("4.3 回滚后 source 清空", ok, f"source={source_after}")
    if not ok:
        all_ok = False

    # 数据完整性
    ok = rows_after[0].get("content") == "用户喜欢喝咖啡"
    ok = ok and rows_after[0].get("importance") == 8
    _check("4.4 回滚后旧数据完整", ok)
    if not ok:
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# T5 · 新记忆系统兼容
# ─────────────────────────────────────────────────────

def test_t5_new_memory_compat() -> bool:
    """验证迁移后的数据可以被新的 LayeredMemory 读取."""
    print("\n[T5] 新记忆系统兼容性")
    all_ok = True

    from scripts.migrate_long_term_memory import migrate_schema, migrate_data

    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test.db")
    _create_legacy_db(db_path)

    from core.database import Database
    db = Database(db_path)

    # 先迁移
    migrate_schema(db)
    migrate_data(db)

    # 用新的 LongTermMemoryLayer 读取
    from memory.layers.long_permanent import LongTermMemoryLayer
    import asyncio

    async def _test():
        layer = LongTermMemoryLayer(db=db, chroma_persist_dir=os.path.join(tmpdir, "chroma"))

        # 检索
        results = await layer.retrieve(user_id=1, query="", limit=10)
        return results

    results = asyncio.run(_test())
    ok = len(results) == 3  # 用户 1 有 3 条
    _check("5.1 新系统读取迁移后数据", ok, f"count={len(results)}")
    if not ok:
        all_ok = False

    # 验证类型
    from memory.layers.base import MemoryType
    all_correct_type = all(r.item.memory_type in (MemoryType.PREFERENCE, MemoryType.FACT, MemoryType.EVENT) for r in results)
    _check("5.2 memory_type 正确解析", all_correct_type)
    if not all_correct_type:
        all_ok = False

    # 按重要度排序
    ok = results[0].item.importance >= results[1].item.importance
    _check("5.3 按重要度排序正确", ok,
           f"top_importance={results[0].item.importance}")
    if not ok:
        all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────

def main() -> int:
    print("=" * 60)
    print("Aerie v11.2 · S3 M3.2 长期记忆迁移验证")
    print("=" * 60)

    results: list[tuple[str, bool]] = []

    results.append(("T1 状态检测", test_t1_status_check()))
    results.append(("T2 迁移执行", test_t2_migration()))
    results.append(("T3 幂等性", test_t3_idempotent()))
    results.append(("T4 回滚", test_t4_rollback()))
    results.append(("T5 新系统兼容", test_t5_new_memory_compat()))

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
        print("\n🎉 M3.2 长期记忆迁移全部通过！")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 项未通过，请检查。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
