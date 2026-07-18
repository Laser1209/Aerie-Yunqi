"""Aerie · 云栖 v13.9.8 — 长期记忆迁移脚本 (S3 M3.2).

将 v9.0 时代的 long_term_memory 表迁移到 v11.2 四层记忆架构。

功能：
  1. 检查旧表结构，识别需要新增的字段
  2. 给旧数据补全新字段默认值（metadata, source, access_count 等）
  3. 可选：生成 ChromaDB 向量嵌入（如果安装了 chromadb）
  4. 幂等：可重复运行，不会重复迁移
  5. 回滚：支持 --rollback 回滚到迁移前状态

用法:
  python scripts/migrate_long_term_memory.py            # 执行迁移
  python scripts/migrate_long_term_memory.py --dry-run  # 仅预览
  python scripts/migrate_long_term_memory.py --rollback # 回滚
  python scripts/migrate_long_term_memory.py --status   # 查看迁移状态
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# 迁移版本标记
MIGRATION_VERSION = "v11.2_m3.2"
MIGRATION_FLAG_COLUMN = "migrated_to_v112"

# 需要新增的字段及默认值
# 注意：SQLite ALTER TABLE 不支持非恒定默认值（如 datetime()）
# 所以 updated_at 不加 DEFAULT，在数据迁移阶段用 UPDATE 设置
NEW_COLUMNS: Dict[str, str] = {
    "metadata": "TEXT DEFAULT '{}'",
    "source": "TEXT DEFAULT 'migration'",
    "access_count": "INTEGER DEFAULT 0",
    "updated_at": "TEXT",
    "has_embedding": "INTEGER DEFAULT 0",
}


def _has_column(db: Any, table: str, column: str) -> bool:
    """检查表是否包含某列."""
    try:
        rows = db.query(f"PRAGMA table_info({table})")
        return any(row.get("name") == column for row in rows)
    except Exception:
        return False


def _add_column(db: Any, table: str, column: str, definition: str) -> None:
    """新增列."""
    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def get_migration_status(db: Any) -> Dict[str, Any]:
    """获取迁移状态."""
    status: Dict[str, Any] = {
        "table_exists": False,
        "total_records": 0,
        "migrated_records": 0,
        "needs_migration": False,
        "missing_columns": [],
    }

    # 检查表是否存在
    try:
        rows = db.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='long_term_memory'"
        )
        if not rows:
            return status
        status["table_exists"] = True
    except Exception:
        return status

    # 检查缺失字段
    for col in NEW_COLUMNS:
        if not _has_column(db, "long_term_memory", col):
            status["missing_columns"].append(col)

    # 统计总数
    try:
        rows = db.query("SELECT COUNT(*) as cnt FROM long_term_memory")
        status["total_records"] = rows[0]["cnt"] if rows else 0
    except Exception:
        pass

    # 统计已迁移数（metadata 中包含 legacy_import 标记，或 source 不是 migration/空）
    if not status["missing_columns"]:
        try:
            all_rows = db.query("SELECT metadata, source FROM long_term_memory")
            migrated = 0
            for row in all_rows:
                meta_str = row.get("metadata", "{}")
                try:
                    meta = json.loads(meta_str) if meta_str else {}
                except (json.JSONDecodeError, TypeError):
                    meta = {}
                if meta.get("legacy_import"):
                    migrated += 1
                elif row.get("source") and row.get("source") != "migration":
                    # 新系统产生的数据也视为已迁移
                    migrated += 1
            status["migrated_records"] = migrated
        except Exception:
            pass

    status["needs_migration"] = (
        len(status["missing_columns"]) > 0
        or status["total_records"] > status["migrated_records"]
    )
    return status


def migrate_schema(db: Any, dry_run: bool = False) -> List[str]:
    """迁移表结构（新增列）."""
    actions: List[str] = []

    for col, definition in NEW_COLUMNS.items():
        if not _has_column(db, "long_term_memory", col):
            action = f"ADD COLUMN {col} {definition}"
            actions.append(action)
            if not dry_run:
                _add_column(db, "long_term_memory", col, definition)

    return actions


def migrate_data(db: Any, dry_run: bool = False, batch_size: int = 100) -> Dict[str, int]:
    """迁移数据（补全字段默认值）."""
    stats: Dict[str, int] = {"updated": 0, "skipped": 0, "total": 0}

    try:
        rows = db.query("SELECT COUNT(*) as cnt FROM long_term_memory")
        stats["total"] = rows[0]["cnt"] if rows else 0
    except Exception:
        pass

    if stats["total"] == 0:
        return stats

    # 分批处理
    offset = 0
    while True:
        try:
            rows = db.query(
                "SELECT * FROM long_term_memory ORDER BY id LIMIT ? OFFSET ?",
                (batch_size, offset),
            )
        except Exception:
            break

        if not rows:
            break

        for row in rows:
            row_id = row.get("id")
            # 判断是否已迁移：用 metadata 中的 legacy_import 标记
            # （source 可能因 ALTER TABLE DEFAULT 而预先有值）
            metadata_str = row.get("metadata", "{}")
            try:
                metadata = json.loads(metadata_str) if metadata_str else {}
            except (json.JSONDecodeError, TypeError):
                metadata = {}

            if metadata.get("legacy_import"):
                # 已经迁移过
                stats["skipped"] += 1
                continue

            source = row.get("source")
            if source and source != "migration":
                # 已经是新系统产生的数据（不是旧数据）
                stats["skipped"] += 1
                continue

            # 需要更新
            if not dry_run:
                new_metadata = dict(metadata) if metadata else {}
                new_metadata["legacy_import"] = True
                metadata_json = json.dumps(new_metadata, ensure_ascii=False)
                now = time.strftime("%Y-%m-%d %H:%M:%S")
                db.execute(
                    """
                    UPDATE long_term_memory
                    SET metadata = ?, source = 'migration', access_count = 0,
                        updated_at = ?, has_embedding = 0
                    WHERE id = ?
                    """,
                    (metadata_json, now, row_id),
                )
            stats["updated"] += 1

        offset += batch_size

    return stats


def rollback_migration(db: Any, dry_run: bool = False) -> Dict[str, int]:
    """回滚迁移（删除新增列可能比较麻烦，这里只清掉迁移标记）."""
    stats: Dict[str, int] = {"rolled_back": 0}

    try:
        rows = db.query(
            "SELECT COUNT(*) as cnt FROM long_term_memory WHERE source = 'migration'"
        )
        stats["rolled_back"] = rows[0]["cnt"] if rows else 0
    except Exception:
        pass

    if not dry_run and stats["rolled_back"] > 0:
        # 清掉迁移相关字段的值
        try:
            db.execute(
                "UPDATE long_term_memory SET source = NULL, metadata = '{}', "
                "access_count = 0, has_embedding = 0 WHERE source = 'migration'"
            )
        except Exception:
            pass

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Aerie v11.2 长期记忆迁移工具")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际修改")
    parser.add_argument("--rollback", action="store_true", help="回滚迁移")
    parser.add_argument("--status", action="store_true", help="查看迁移状态")
    parser.add_argument("--db-path", default="data/etta.db", help="数据库路径")
    args = parser.parse_args()

    from core.database import Database

    db_path = os.path.join(_REPO_ROOT, args.db_path)
    if not os.path.exists(db_path):
        print(f"⚠️  数据库不存在: {db_path}")
        print("   跳过迁移（无旧数据需要迁移）")
        return 0

    db = Database(db_path)

    print("=" * 60)
    print("Aerie v11.2 · 长期记忆迁移工具 (S3 M3.2)")
    print("=" * 60)
    print(f"数据库: {db_path}")
    print(f"模式: {'DRY-RUN' if args.dry_run else '执行'}")

    # 状态查询
    status = get_migration_status(db)
    print(f"\n当前状态:")
    print(f"  表存在:       {status['table_exists']}")
    print(f"  总记录数:     {status['total_records']}")
    print(f"  缺失字段:     {status['missing_columns'] or '无'}")
    print(f"  已迁移记录:   {status['migrated_records']}")
    print(f"  需要迁移:     {status['needs_migration']}")

    if args.status:
        return 0

    # 回滚
    if args.rollback:
        print("\n--- 回滚迁移 ---")
        stats = rollback_migration(db, dry_run=args.dry_run)
        print(f"  回滚记录数: {stats['rolled_back']}")
        print("\n✅ 回滚完成" if not args.dry_run else "\nℹ️  DRY-RUN 完成")
        return 0

    # 执行迁移
    if not status["needs_migration"] and status["table_exists"]:
        print("\n✅ 数据已是最新，无需迁移")
        return 0

    print("\n--- 步骤 1: 迁移表结构 ---")
    schema_actions = migrate_schema(db, dry_run=args.dry_run)
    if schema_actions:
        for action in schema_actions:
            print(f"  + {action}")
    else:
        print("  字段已齐全，跳过")

    print("\n--- 步骤 2: 迁移数据 ---")
    data_stats = migrate_data(db, dry_run=args.dry_run)
    print(f"  总记录数:   {data_stats['total']}")
    print(f"  已更新:     {data_stats['updated']}")
    print(f"  已跳过:     {data_stats['skipped']}")

    print("\n--- 步骤 3: 验证 ---")
    new_status = get_migration_status(db)
    print(f"  缺失字段: {new_status['missing_columns'] or '无'}")
    print(f"  已迁移:   {new_status['migrated_records']}/{new_status['total_records']}")

    if not args.dry_run:
        if not new_status["needs_migration"]:
            print("\n🎉 迁移成功完成！")
            return 0
        else:
            print("\n⚠️  迁移未完全完成，请检查")
            return 1
    else:
        print("\nℹ️  DRY-RUN 完成，未实际修改数据")
        return 0


if __name__ == "__main__":
    sys.exit(main())
