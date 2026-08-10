"""One-off: inspect recent desktop attachment records."""
from __future__ import annotations

import sqlite3

conn = sqlite3.connect("data/aerie.db")
conn.row_factory = sqlite3.Row

print("===== desktop_attachments 最近 12 条 =====")
rows = conn.execute(
    "SELECT attachment_id, original_name, category, state, error_code, "
    "substr(error_message,1,90) AS err, created_at "
    "FROM desktop_attachments ORDER BY created_at DESC LIMIT 12"
).fetchall()
if rows:
    for r in rows:
        print(dict(r))
else:
    print("(空)")

print()
print("===== chat_log 最近带附件消息 =====")
rows2 = conn.execute(
    "SELECT id, role, substr(content,1,50) AS content, attachments, created_at "
    "FROM chat_log WHERE attachments IS NOT NULL ORDER BY id DESC LIMIT 8"
).fetchall()
if rows2:
    for r in rows2:
        print(dict(r))
else:
    print("(空)")
