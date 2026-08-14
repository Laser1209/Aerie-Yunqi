"""清理 chat_log 里的孤儿主动消息/图片消息（一次性运维工具）。

孤儿行 = 直接写 chat_log 但从未进入 normalized messages 层的历史遗留行
（route_mode='PROACTIVE' 且没有任何 messages.legacy_chat_log_id 指向它）。

用法：
    python tools/cleanup_orphan_proactive.py            # 预览（dry-run，不删除）
    python tools/cleanup_orphan_proactive.py --apply    # 物理删除 + VACUUM 回收空间

运行前请先停止后端，避免 SQLite 文件锁。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "aerie.db"

ORPHAN_SQL = """
SELECT id, user_id, persona_id, role, content, created_at,
       length(content) AS bytes
FROM chat_log
WHERE route_mode = 'PROACTIVE'
  AND id NOT IN (
      SELECT legacy_chat_log_id FROM messages
      WHERE legacy_chat_log_id IS NOT NULL
  )
ORDER BY id
"""

DELETE_SQL = """
DELETE FROM chat_log
WHERE route_mode = 'PROACTIVE'
  AND id NOT IN (
      SELECT legacy_chat_log_id FROM messages
      WHERE legacy_chat_log_id IS NOT NULL
  )
"""


def main() -> None:
    if not DB.exists():
        print(f"找不到数据库：{DB}")
        sys.exit(1)
    apply = "--apply" in sys.argv

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute(ORPHAN_SQL).fetchall()
    total = len(rows)
    total_bytes = sum(int(r["bytes"] or 0) for r in rows)
    print(f"孤儿主动消息/图片消息：{total} 条，正文约 {total_bytes} 字节")
    for r in rows[:20]:
        content = (r["content"] or "").replace("\n", " ")[:60]
        print(f"  id={r['id']} persona={r['persona_id']} role={r['role']} {content!r}")
    if total > 20:
        print(f"  ... 其余 {total - 20} 条省略")

    if not apply:
        print("\n未执行删除（dry-run）。确认无误后加 --apply 参数物理删除。")
        conn.close()
        return

    if total == 0:
        print("\n没有需要清理的孤儿行。")
        conn.close()
        return

    cur.execute(DELETE_SQL)
    deleted = cur.rowcount
    conn.commit()
    print(f"\n已物理删除 {deleted} 条孤儿行。")

    before = DB.stat().st_size
    conn.execute("VACUUM")
    after = DB.stat().st_size
    conn.close()
    print(f"VACUUM 完成：{before} -> {after} 字节")


if __name__ == "__main__":
    main()
