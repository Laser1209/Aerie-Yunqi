#!/usr/bin/env python3
"""排查:查找数据库中最新的对话消息,确认用户消息是否进入 pipeline。"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

con = sqlite3.connect(str(Path(__file__).resolve().parent.parent / "data" / "aerie.db"))
cur = con.cursor()

# 直接查 messages 最近记录
cols = [r[1] for r in cur.execute("PRAGMA table_info(messages)")]
print("messages cols:", cols)
rows = cur.execute(
    "SELECT message_id, conversation_id, role, content, created_at, channel, actor_id, sequence "
    "FROM messages ORDER BY created_at DESC LIMIT 8"
).fetchall()
print(f"\n最近 {len(rows)} 条:")
for mid, conv, role, content, ts, channel, actor, seq in rows:
    print(f"[{ts}] conv={conv[-12:]} {role} ch={channel} actor={actor} seq={seq} msg={mid}: {(content or '')[:90]}")

print("\n== 19:56:32 会话全部消息 ==")
conv_id = "conv_547ca8cc83c8c5fb0173b3c639c5a214"
rows = cur.execute(
    "SELECT message_id, role, content, created_at, channel, actor_id, sequence "
    "FROM messages WHERE conversation_id=? ORDER BY created_at ASC",
    (conv_id,),
).fetchall()
lines = []
for mid, role, content, ts, channel, actor, seq in rows:
    lines.append(f"[{ts}] {role} ch={channel} actor={actor} seq={seq} msg={mid}: {(content or '')[:100]}")
report = "\n".join(lines)
print(report)
from pathlib import Path  # noqa: E402
Path("tools/diag_report.txt").write_text(report, encoding="utf-8")
