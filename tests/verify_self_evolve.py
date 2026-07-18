"""Aerie · 云栖 v13.9.8 — Phase 9 Batch 6 verify: self-evolution mechanism.

Verifies the high-sensitivity capability-gap detector and the
5 new HTTP endpoints end-to-end. Tests:

  1. SandboxRunner.preview() with a normal tool name → safe verdict
  2. SandboxRunner.preview() with a network call → caution/high_risk
  3. SandboxRunner.preview() rejects empty tool name (ok=False)
  4. SelfEvolver.maybe_propose() returns None when there's no gap
  5. SelfEvolver.maybe_propose() returns a row id on a real gap
  6. SelfEvolver.maybe_propose() returns None when tool_results all succeed
  7. The new row is persisted in self_evolve_log (user_decision=pending)
  8. SelfEvolver.approve() registers the tool, marks approved, is idempotent
  9. SelfEvolver.reject() marks rejected, is idempotent
  10. The /api/self_evolve/list endpoint returns pending items + stats
  11. The /api/self_evolve/{id} endpoint returns the full row + parsed schema
  12. The /api/self_evolve/{id}/preview endpoint re-renders the sandbox
  13. The /api/self_evolve/{id}/approve endpoint marks approved
  14. The /api/self_evolve/{id}/reject endpoint marks rejected
  15. Re-approve a rejected proposal is refused (already_rejected)
"""

from __future__ import annotations

import json
import os
import sys
import time
import socket
import tempfile
from pathlib import Path

# Use a throwaway DB so we don't pollute production data.
TMP_DB = Path(tempfile.gettempdir()) / "aerie_verify_b6.db"
if TMP_DB.exists():
    try:
        TMP_DB.unlink()
    except OSError:
        pass
os.environ["AERIE_DB_PATH"] = str(TMP_DB)

# Make sure the project root is importable.
ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

# Patch Database to honour AERIE_DB_PATH before any other import touches it.
import core.database as _dbmod  # noqa: E402
_orig_db_init = _dbmod.Database.__init__


def _patched_db_init(self, db_path="data/aerie.db"):
    override = os.environ.get("AERIE_DB_PATH")
    if override:
        db_path = override
    _orig_db_init(self, db_path=db_path)


_dbmod.Database.__init__ = _patched_db_init  # type: ignore[assignment]

from core.database import Database  # noqa: E402
from core.sandbox_runner import SandboxRunner  # noqa: E402
from core.self_evolver import SelfEvolver  # noqa: E402
from core.tool_registry import ToolRegistry  # noqa: E402


PORT = 7890
BASE = f"http://127.0.0.1:{PORT}"


def _check_port() -> bool:
    deadline = time.time() + 45
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def _request(method: str, path: str, body: bytes | None = None,
             content_type: str = "application/json") -> tuple[int, object]:
    import urllib.request
    url = BASE + path
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, method=method, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            ct = r.headers.get("Content-Type", "")
            raw = r.read()
            if "application/json" in ct:
                return r.status, json.loads(raw.decode("utf-8"))
            return r.status, raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {"error": str(e)}
    except Exception as e:
        return 0, {"error": str(e)}


# ── Section 1: SandboxRunner unit tests ─────────────
def test_sandbox_runner() -> tuple[int, int]:
    passed = failed = 0

    def expect(name: str, cond: bool, detail: str = ""):
        nonlocal passed, failed
        if cond:
            print(f"  ✓ {name}")
            passed += 1
        else:
            print(f"  ✗ {name}  {detail}")
            failed += 1

    runner = SandboxRunner()
    # 1. Normal tool name → safe
    p = runner.preview({"name": "weather_lookup",
                         "description": "查询本地天气",
                         "parameters": {"type": "object",
                                        "properties": {"city": {"type": "string"}}}})
    expect("sandbox normal → safe verdict",
           p.get("ok") and p.get("safety_check") == "safe"
           and not p.get("risk_points"),
           f"got {p!r}")
    # 2. Network call → caution
    p = runner.preview({"name": "fetch_url",
                         "description": "通过 https://example.com 拉取资源",
                         "parameters": {"type": "object"}})
    expect("sandbox https → caution or high_risk",
           p.get("ok") and p.get("safety_check") in ("caution", "high_risk")
           and len(p.get("risk_points", [])) >= 1,
           f"got safety={p.get('safety_check')} risks={p.get('risk_points')}")
    # 3. Empty name → not ok
    p = runner.preview({"name": "  ", "description": "x"})
    expect("sandbox empty name → not ok",
           (not p.get("ok")) and p.get("error"),
           f"got {p!r}")
    # 4. render() round-trip doesn't crash
    text = runner.render({"ok": True, "name": "x", "description": "y",
                          "parameters": {}, "simulated_input": {"arguments": {}},
                          "simulated_output": "out", "risk_points": [],
                          "safety_check": "safe", "requires_approval": False})
    expect("sandbox render() works",
           "工具: x" in text and "安全检查" in text,
           f"got {text[:100]!r}")
    return passed, failed


# ── Section 2: SelfEvolver unit tests ───────────────
def test_self_evolver_class() -> tuple[int, int]:
    passed = failed = 0

    def expect(name: str, cond: bool, detail: str = ""):
        nonlocal passed, failed
        if cond:
            print(f"  ✓ {name}")
            passed += 1
        else:
            print(f"  ✗ {name}  {detail}")
            failed += 1

    db = Database()
    # Wipe the table so we have a clean count.
    try:
        db.execute("DELETE FROM self_evolve_log")
    except Exception:
        pass
    reg = ToolRegistry(db)
    ev = SelfEvolver(db=db, tool_registry=reg, brain=None)

    # 4. No gap → None
    rid0 = ev.maybe_propose(
        user_id=1,
        user_message="你好",
        react_trace={"thought": "她问好，我开心。", "action": "reply"},
        tool_results=[],
    )
    expect("no gap → no proposal", rid0 is None, f"got {rid0!r}")

    # 5. Real gap (keyword + tool failure) → row id
    rid = ev.maybe_propose(
        user_id=1,
        user_message="帮我关电脑",
        react_trace={
            "thought": "我无法关闭电脑，没有工具可以做到。",
            "action": "reply",
        },
        tool_results=[{"name": "shutdown_pc", "success": False,
                        "result": {"error": "no_such_tool"}}],
    )
    expect("gap+fail → row id", isinstance(rid, int) and rid > 0,
           f"got {rid!r}")

    # 6. keyword but no failure → None
    rid_no_fail = ev.maybe_propose(
        user_id=1,
        user_message="x",
        react_trace={"thought": "I cannot do this", "action": "reply"},
        tool_results=[{"name": "t", "success": True, "result": {}}],
    )
    expect("keyword without failure → None", rid_no_fail is None,
           f"got {rid_no_fail!r}")

    # 7. Persisted with user_decision=pending
    row = db.query_one(
        "SELECT * FROM self_evolve_log WHERE user_id = ? AND id = ?",
        (1, rid),
    )
    expect("proposal row persisted",
           row is not None and row.get("user_decision") == "pending",
           f"got {row!r}")

    # 8. Approve → registered + decision approved + idempotent
    before = list(reg.get_openai_schema()) if hasattr(reg, "get_openai_schema") else []
    res1 = ev.approve(rid)
    expect("approve returns ok", res1.get("status") == "ok",
           f"got {res1!r}")
    after = list(reg.get_openai_schema()) if hasattr(reg, "get_openai_schema") else []
    expect("approve registered a new tool", len(after) == len(before) + 1,
           f"before={len(before)} after={len(after)}")
    res2 = ev.approve(rid)
    expect("approve is idempotent",
           res2.get("status") == "ok" and res2.get("already") is True,
           f"got {res2!r}")

    # 9. Reject a new proposal (separate row)
    rid2 = ev.maybe_propose(
        user_id=2,
        user_message="给我订外卖",
        react_trace={"thought": "无法订外卖，没有这个工具。", "action": "reply"},
        tool_results=[{"name": "order_food", "success": False,
                        "result": {"error": "no_such_tool"}}],
    )
    expect("second proposal created", isinstance(rid2, int) and rid2 > 0,
           f"got {rid2!r}")
    res3 = ev.reject(rid2)
    expect("reject returns ok", res3.get("status") == "ok", f"got {res3!r}")
    res4 = ev.reject(rid2)
    expect("reject is idempotent",
           res4.get("status") == "ok" and res4.get("already") is True,
           f"got {res4!r}")

    # 10. Re-approve a rejected proposal is refused
    res5 = ev.approve(rid2)
    expect("re-approve of rejected is refused",
           res5.get("status") == "error" and "already_rejected" in (res5.get("reason") or ""),
           f"got {res5!r}")

    # 11. list_proposals filters
    pending = ev.list_proposals(status="pending")
    expect("list pending filters correctly",
           all((p.get("user_decision") == "pending") for p in pending),
           f"got decisions={[p.get('user_decision') for p in pending]}")
    approved = ev.list_proposals(status="approved")
    expect("list approved returns approved",
           all((p.get("user_decision") == "approved") for p in approved),
           f"got decisions={[p.get('user_decision') for p in approved]}")
    rejected = ev.list_proposals(status="rejected")
    expect("list rejected returns rejected",
           all((p.get("user_decision") == "rejected") for p in rejected),
           f"got decisions={[p.get('user_decision') for p in rejected]}")

    # 12. stats
    s = ev.stats()
    expect("stats has all 4 buckets",
           all(k in s for k in ("total", "pending", "approved", "rejected"))
           and s["approved"] >= 1 and s["rejected"] >= 1,
           f"got {s!r}")

    return passed, failed


# ── Section 3: HTTP endpoint tests (TestClient, self-contained) ──
def test_http_endpoints() -> tuple[int, int]:
    """Test the 5 self_evolve HTTP endpoints via FastAPI's TestClient.

    Uses a stub companion so we don't depend on a live backend. This
    makes section 3 hermetic and faster than hitting port 7890.
    """
    passed = failed = 0

    def expect(name: str, cond: bool, detail: str = ""):
        nonlocal passed, failed
        if cond:
            print(f"  ✓ {name}")
            passed += 1
        else:
            print(f"  ✗ {name}  {detail}")
            failed += 1

    # Lazy import TestClient so missing dep doesn't break sections 1/2.
    try:
        from fastapi.testclient import TestClient
    except Exception as e:
        print(f"  ! fastapi.testclient unavailable: {e}")
        return 0, 0

    # Reset the table so we have a known seed.
    db = Database()
    try:
        db.execute("DELETE FROM self_evolve_log")
    except Exception:
        pass
    reg = ToolRegistry(db)
    ev = SelfEvolver(db=db, tool_registry=reg, brain=None)

    # Build a stub companion that returns our self_evolver.
    class _StubCompanion:
        pass
    stub = _StubCompanion()
    stub.self_evolver = ev
    stub.db = db
    # Monkey-patch get_companion to return our stub.
    import core.companion as _comp
    _orig_get_companion = _comp.get_companion
    _comp.get_companion = lambda: stub
    _comp._get_companion_orig = _orig_get_companion

    try:
        from core.api_server import app  # noqa: E402
        client = TestClient(app)

        # 13. list endpoint (empty)
        r = client.get("/api/self_evolve/list?status=all&limit=50")
        expect("GET /api/self_evolve/list returns 200 + items + stats",
               r.status_code == 200
               and isinstance(r.json(), dict)
               and "items" in r.json() and "stats" in r.json()
               and isinstance(r.json()["items"], list),
               f"code={r.status_code} body={r.text[:200]!r}")

        # Seed a pending proposal directly.
        rid = db.insert("self_evolve_log", {
            "ts": int(time.time() * 1000),
            "user_id": 1,
            "trigger_kind": "manual_test",
            "description": "test proposal for verify",
            "proposed_tool_schema": json.dumps({
                "name": "ita_test_tool",
                "description": "test",
                "parameters": {"type": "object", "properties": {}},
            }, ensure_ascii=False),
            "safety_check": "caution",
            "user_decision": "pending",
        })

        # 14. detail endpoint
        r = client.get(f"/api/self_evolve/{rid}")
        body = r.json()
        expect("GET /api/self_evolve/{id} returns row + parsed schema",
               r.status_code == 200
               and isinstance(body, dict)
               and body.get("id") == rid
               and isinstance(body.get("proposed_tool_schema"), dict),
               f"code={r.status_code} body={r.text[:200]!r}")

        # 15. preview endpoint
        r = client.post(f"/api/self_evolve/{rid}/preview")
        body = r.json()
        expect("POST /api/self_evolve/{id}/preview returns ok preview",
               r.status_code == 200
               and isinstance(body, dict)
               and body.get("ok") is True
               and "simulated_input" in body
               and "risk_points" in body,
               f"code={r.status_code} body={r.text[:200]!r}")

        # 16. approve endpoint
        r = client.post(f"/api/self_evolve/{rid}/approve")
        body = r.json()
        expect("POST /api/self_evolve/{id}/approve marks approved",
               r.status_code == 200
               and isinstance(body, dict)
               and body.get("status") == "ok"
               and body.get("decision") == "approved",
               f"code={r.status_code} body={r.text[:200]!r}")

        # 17. re-approve is idempotent
        r = client.post(f"/api/self_evolve/{rid}/approve")
        body = r.json()
        expect("re-approve is idempotent",
               r.status_code == 200
               and body.get("status") == "ok"
               and body.get("already") is True,
               f"code={r.status_code} body={r.text[:200]!r}")

        # 18. reject a new pending row
        rid2 = db.insert("self_evolve_log", {
            "ts": int(time.time() * 1000),
            "user_id": 1,
            "trigger_kind": "manual_test_2",
            "description": "another test",
            "proposed_tool_schema": json.dumps({
                "name": "ita_test_tool_2",
                "description": "test 2",
                "parameters": {"type": "object", "properties": {}},
            }, ensure_ascii=False),
            "safety_check": "safe",
            "user_decision": "pending",
        })
        r = client.post(f"/api/self_evolve/{rid2}/reject")
        body = r.json()
        expect("POST /api/self_evolve/{id}/reject marks rejected",
               r.status_code == 200
               and body.get("status") == "ok"
               and body.get("decision") == "rejected",
               f"code={r.status_code} body={r.text[:200]!r}")

        # 19. 404 on missing id
        r = client.get("/api/self_evolve/9999999")
        expect("missing proposal → 404", r.status_code == 404,
               f"code={r.status_code}")

        # 20. list with status=approved returns the approved one
        r = client.get("/api/self_evolve/list?status=approved&limit=10")
        body = r.json()
        items = body.get("items", [])
        expect("list status=approved contains the approved id",
               any((it.get("id") == rid) for it in items),
               f"ids={[it.get('id') for it in items]}")

        # 21. list with status=rejected contains the rejected one
        r = client.get("/api/self_evolve/list?status=rejected&limit=10")
        body = r.json()
        items = body.get("items", [])
        expect("list status=rejected contains the rejected id",
               any((it.get("id") == rid2) for it in items),
               f"ids={[it.get('id') for it in items]}")

        # 22. invalid status → 422
        r = client.get("/api/self_evolve/list?status=garbage")
        expect("invalid status → 422",
               r.status_code in (400, 422),
               f"code={r.status_code}")
    finally:
        # Always restore get_companion.
        _comp.get_companion = _orig_get_companion

    return passed, failed


def main() -> int:
    print("=" * 60)
    print("Phase 9 Batch 6 — Self-evolution verify")
    print("=" * 60)

    # ── Section 1 ──
    print("\n[1] SandboxRunner unit tests")
    p1, f1 = test_sandbox_runner()
    print(f"    passed={p1} failed={f1}")

    # ── Section 2 ──
    print("\n[2] SelfEvolver class unit tests")
    p2, f2 = test_self_evolver_class()
    print(f"    passed={p2} failed={f2}")

    # ── Section 3 (TestClient, self-contained) ──
    print("\n[3] HTTP endpoint tests (FastAPI TestClient, hermetic)")
    p3, f3 = test_http_endpoints()
    print(f"    passed={p3} failed={f3}")

    total_p = p1 + p2 + p3
    total_f = f1 + f2 + f3
    print("\n" + "=" * 60)
    print(f"TOTAL: {total_p} passed / {total_f} failed")
    print("=" * 60)
    return 0 if total_f == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
