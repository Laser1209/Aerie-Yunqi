#!/usr/bin/env python3
"""排查:检查最近聊天历史,确认用户消息是否进入 pipeline 并产出回复。"""
import sys

sys.path.insert(0, ".")

from fastapi.testclient import TestClient

from core.api_server import app

c = TestClient(app)
r = c.get("/api/chat/history", params={"user_id": 3998874040, "limit": 30})
if r.status_code != 200:
    print("status", r.status_code, r.text[:300])
    sys.exit(1)
d = r.json()
msgs = d if isinstance(d, list) else d.get("messages", [])
print(f"total={len(msgs)}")
for m in msgs[-20:]:
    who = m.get("role") or m.get("sender") or m.get("msg_type")
    content = (m.get("content") or "")[:120]
    print(f"[{who}] {content}")
