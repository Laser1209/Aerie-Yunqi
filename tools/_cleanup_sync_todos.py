"""Remove the temporary sync test todos I created against the live DB.
Run: python tools/_cleanup_sync_todos.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.database import Database  # noqa: E402

db = Database()
cursor = db.execute("DELETE FROM todo WHERE title LIKE 'sync%' OR title LIKE '__sync%'")
print("deleted", cursor.rowcount, "sync test todos")
