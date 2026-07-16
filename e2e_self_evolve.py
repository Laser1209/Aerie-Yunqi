"""Aerie · 云栖 v9.0 — Phase 9 Batch 6 E2E: 自进化全链路冒烟测试.

End-to-end smoke test for the capability-gap → proposal → sandbox
preview → approve → tool-registration flow.

This is the **blocker-friendly** counterpart of ``verify_self_evolve.py``
(which is the granular unit/integration/HTTP sweep).  The intent here is
"can a real user message trigger the whole chain and leave a working
tool behind".

Steps:
  1. Reset self_evolve_log + sandbox state
  2. Construct a real react_trace + failed tool result
  3. maybe_propose()   → must return a non-None row id
  4. DB check          → user_decision='pending'
  5. get()             → schema parses as valid JSON
  6. sandbox preview   → must produce a non-empty safety verdict
  7. approve()         → user_decision='approved' + tool registered
  8. idempotency       → re-approve is a no-op
  9. list_proposals    → status=approved contains the row
  10. cleanup          → remove the registered tool + delete the row

Usage:
  python e2e_self_evolve.py
"""
from __future__ import annotations

import json
import sys

from core.cognition import CognitionEngine
from core.database import Database
from core.self_evolver import SelfEvolver
from core.tool_registry import ToolRegistry


# ── helpers ────────────────────────────────────────────────
def _check(label: str, ok: bool, detail: str = "") -> None:
    sym = "✓" if ok else "✗"
    suffix = f"  {detail}" if detail else ""
    print(f"  {sym} {label}{suffix}")


def _stage(name: str) -> None:
    print(f"\n── {name} ──")


def main() -> int:
    print("=" * 60)
    print("Phase 9 Batch 6 E2E — self-evolve 全链路冒烟")
    print("=" * 60)

    passed = failed = 0

    def expect(name: str, ok: bool, detail: str = "") -> None:
        nonlocal passed, failed
        if ok:
            passed += 1
        else:
            failed += 1
        _check(name, ok, detail)

    db = Database()
    cog = CognitionEngine(db)
    reg = ToolRegistry(db)
    ev = SelfEvolver(db=db, tool_registry=reg, brain=None)

    # ── 1. reset DB (only test rows) ────────────────────────
    _stage("1. reset self_evolve_log")
    try:
        db.execute("DELETE FROM self_evolve_log WHERE user_id = ?", (9999,))
        expect("test rows cleared", True)
    except Exception as e:
        expect("test rows cleared", False, f"err={e}")
        return 2

    # ── 2. construct real react_trace + failed tool result ───
    _stage("2. construct react_trace + tool_results")
    user_message = "帮我读一下本地的 data/aerie.db 看看表"
    react_trace = {
        "thought": "我无法读取本地文件，没有这个工具可以做到。",
        "action": "tool_call",
        "observation": "no_local_file_reader",
        "react_source": "model",
    }
    tool_results = [
        {
            "name": "read_local_file",
            "success": False,
            "arguments": {"path": "data/aerie.db"},
            "result": {"error": "no_such_tool"},
            "duration_ms": 12,
        }
    ]
    expect("react_trace.thought contains gap keyword",
           "无法" in react_trace["thought"])
    expect("tool_results has at least one failure",
           any(not t.get("success", True) for t in tool_results))

    # ── 3. maybe_propose ────────────────────────────────────
    _stage("3. maybe_propose")
    row_id = ev.maybe_propose(
        user_id=9999,
        user_message=user_message,
        react_trace=react_trace,
        tool_results=tool_results,
    )
    expect("maybe_propose returns int", isinstance(row_id, int) and row_id > 0,
           f"got {row_id!r}")

    # ── 4. DB check ─────────────────────────────────────────
    _stage("4. self_evolve_log row")
    row = db.query_one(
        "SELECT * FROM self_evolve_log WHERE id = ?", (row_id,)
    ) if row_id else None
    expect("row exists in self_evolve_log", bool(row), f"row={row!r}")
    expect("user_decision == 'pending'",
           bool(row) and row.get("user_decision") == "pending",
           f"got {row.get('user_decision') if row else None!r}")
    expect("trigger_kind == 'capability_gap'",
           bool(row) and row.get("trigger_kind") == "capability_gap",
           f"got {row.get('trigger_kind') if row else None!r}")
    expect("description has gap context",
           bool(row) and ("无法" in (row.get("description") or "")
                          or "做不到" in (row.get("description") or "")),
           f"desc={row.get('description') if row else None!r}")

    # ── 5. get() schema parses ──────────────────────────────
    _stage("5. proposed_tool_schema parses as valid JSON")
    raw_schema = row.get("proposed_tool_schema") if row else None
    parsed = None
    if raw_schema:
        if isinstance(raw_schema, str):
            try:
                parsed = json.loads(raw_schema)
            except Exception as e:
                expect("schema JSON parse", False, f"err={e}")
        else:
            parsed = raw_schema
    expect("schema JSON parse", parsed is not None)
    expect("schema has 'name'",
           isinstance(parsed, dict) and bool(parsed.get("name")),
           f"name={parsed.get('name') if isinstance(parsed, dict) else None!r}")
    expect("schema has 'description'",
           isinstance(parsed, dict) and bool(parsed.get("description")),
           f"desc={parsed.get('description') if isinstance(parsed, dict) else None!r}")

    # ── 6. sandbox preview ──────────────────────────────────
    _stage("6. sandbox preview")
    preview = ev._sandbox.preview(parsed) if parsed else {"ok": False, "error": "no_schema"}
    expect("preview.ok", preview.get("ok") is True, f"got {preview!r}")
    expect("preview has safety_check field",
           "safety_check" in preview,
           f"keys={list(preview.keys())}")

    # ── 7. approve → tool registered ────────────────────────
    _stage("7. approve + tool registered")
    tool_name = parsed.get("name") if isinstance(parsed, dict) else None

    approve_result = ev.approve(row_id) if row_id else None
    expect("approve returns ok dict",
           isinstance(approve_result, dict) and approve_result.get("status") == "ok",
           f"got {approve_result!r}")

    row_after = db.query_one(
        "SELECT user_decision FROM self_evolve_log WHERE id = ?", (row_id,)
    ) if row_id else None
    expect("user_decision == 'approved' after approve",
           bool(row_after) and row_after.get("user_decision") == "approved",
           f"got {row_after.get('user_decision') if row_after else None!r}")

    if tool_name:
        # ToolRegistry has no list_names/get/get_all; use get_openai_schema() and _tools.
        registered = False
        try:
            schemas = reg.get_openai_schema() if hasattr(reg, "get_openai_schema") else []
            names = [s.get("function", {}).get("name") for s in (schemas or [])]
            if tool_name in names:
                registered = True
        except Exception:
            pass
        if not registered and hasattr(reg, "_tools"):
            registered = tool_name in (reg._tools or {})
        expect(f"tool {tool_name!r} is registered", registered,
               "not found via get_openai_schema / _tools")

    # ── 8. idempotency ──────────────────────────────────────
    _stage("8. idempotency")
    second = ev.approve(row_id) if row_id else None
    expect("re-approve returns ok+already=True dict",
           isinstance(second, dict)
           and second.get("status") == "ok"
           and second.get("already") is True,
           f"got {second!r}")
    row_after2 = db.query_one(
        "SELECT user_decision FROM self_evolve_log WHERE id = ?", (row_id,)
    ) if row_id else None
    expect("user_decision still 'approved'",
           bool(row_after2) and row_after2.get("user_decision") == "approved",
           f"got {row_after2.get('user_decision') if row_after2 else None!r}")

    # ── 9. list_proposals approved ──────────────────────────
    _stage("9. list_proposals(status=approved)")
    items = ev.list_proposals(user_id=9999, status="approved", limit=10)
    ids = [it.get("id") for it in items if isinstance(it, dict)]
    expect("approved list contains our row", row_id in ids,
           f"ids={ids} row_id={row_id}")

    # ── 10. cleanup ─────────────────────────────────────────
    _stage("10. cleanup test artefacts")
    try:
        if tool_name and hasattr(reg, "_tools") and tool_name in reg._tools:
            try:
                del reg._tools[tool_name]
            except Exception:
                pass
        elif tool_name and hasattr(reg, "unregister"):
            try:
                reg.unregister(tool_name)
            except Exception:
                pass
        db.execute("DELETE FROM self_evolve_log WHERE id = ?", (row_id,))
        expect("test row deleted", True)
    except Exception as e:
        expect("cleanup succeeded", False, f"err={e}")

    # ── summary ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"  Total: passed={passed}  failed={failed}")
    if failed == 0:
        print("  ✓ e2e_self_evolve 全部通过")
    print("=" * 60)
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
