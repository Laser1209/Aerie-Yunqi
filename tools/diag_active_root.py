#!/usr/bin/env python3
"""冒烟:验证 active_root API 设置/读取/拒绝逻辑。"""
import sys

sys.path.insert(0, ".")

from fastapi.testclient import TestClient

from core.api_server import app

c = TestClient(app)

# 读取 roots + active
r = c.get("/api/workspace/roots")
d = r.json()
print("roots:", len(d["roots"]), "active:", d["active_root"])

# 设置激活
r = c.post("/api/workspace/active", json={"path": r"D:\T08171634"})
print("set active:", r.status_code, r.json())

# 读取确认
r = c.get("/api/workspace/roots")
print("active after:", r.json()["active_root"])

# 未注册目录应拒绝(保持原值)
r = c.post("/api/workspace/active", json={"path": r"Z:\NotRegistered"})
print("reject:", r.status_code, r.json())
r = c.get("/api/workspace/roots")
print("active unchanged:", r.json()["active_root"])
