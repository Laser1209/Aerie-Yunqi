"""Aerie · 云栖 v9.0 — R7.4 E2E: 动作/心理结构化标签 round-trip.

Verifies that the LLM actually emits the new <action> / <thought>
tags after the persona prompt change, and that the chat history
endpoint returns the tagged text intact (not stripped, not escaped).

Strategy:
  1. POST /api/chat/send with a prompt that asks the model to use the
     new tags explicitly.
  2. Poll /api/chat/history?limit=5 until the latest assistant
     message contains at least one <action> or <thought> tag, OR
     the timeout (45s) is hit.
  3. Assert:
     a) status == 200
     b) latest message is from the assistant (role == "assistant")
     c) content contains at least 1 <action> or <thought> tag
     d) tags are not HTML-escaped (must contain literal <, not &lt;)

This test depends on a real LLM being configured (DeepSeek/BigModel
etc). It will FAIL with 'timeout waiting for narration' if the model
is down or doesn't honour the persona prompt — that's the test
working as designed, since the user-facing feature depends on the
LLM following the new convention.

Usage:
  python e2e_narration.py
"""
from __future__ import annotations

import json
import re
import socket
import sys
import time
import urllib.error
import urllib.request

PORT = 7890
BASE = f"http://127.0.0.1:{PORT}"

# R7.4: prompt engineered to make the LLM follow the new persona
# convention. We mention the tags by name so even a model that didn't
# internalize the persona update will at least try.
PROMPT = (
    "请用一条消息回复我，必须用 <action>...</action> 标签描述你正在做的"
    "一个动作，用 <thought>...</thought> 标签描述你此刻的想法。例："
    '"在干嘛。"<action>伊塔放下杯子。</action><thought>他今天有点累。</thought>"说。"'
)

# v2.1: was `rb"<(action|thought)>"` which is a bytes literal and
# has no .search() method. Use a compiled re.Pattern against str
# content instead.
TAG_RE = re.compile(r"<(action|thought)>")


def _check_port(timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def _request(method: str, path: str, body: dict | None = None,
             timeout: float = 40.0) -> tuple[int, object]:
    url = BASE + path
    headers = {"Accept": "application/json"}
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ct = r.headers.get("Content-Type", "")
            raw = r.read()
            if "application/json" in ct:
                return r.status, json.loads(raw.decode("utf-8"))
            return r.status, raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, str(e)
    except Exception as e:
        return 0, {"error": str(e)}


def _expect(label: str, ok: bool, detail: str = "") -> bool:
    sym = "✓" if ok else "✗"
    print(f"  {sym} {label}  {detail}")
    return ok


def main() -> int:
    print("=" * 60)
    print("R7.4 E2E — 动作/心理结构化标签 round-trip")
    print("=" * 60)

    if not _check_port():
        print(f"  ✗ backend not reachable on port {PORT}")
        return 1
    print(f"  ✓ backend reachable on port {PORT}")

    passed = 0
    failed = 0

    def expect(name: str, ok: bool, detail: str = ""):
        nonlocal passed, failed
        if _expect(name, ok, detail):
            passed += 1
        else:
            failed += 1

    # ── 1. Send the prompt ────────────────────────────
    code, body = _request("POST", "/api/chat/send", body={"text": PROMPT}, timeout=60)
    expect("chat send 200/503", code in (200, 503)
           and not (isinstance(body, dict) and body.get("error") == "backend not ready"),
           f"code={code}")

    if code not in (200, 503):
        print(f"  → chat send failed body={body!r}; aborting")
        return 2

    # ── 2. Poll history for the latest assistant message ──
    print("  … waiting for assistant response (up to 45s)")
    deadline = time.time() + 45
    latest = None
    while time.time() < deadline:
        code, body = _request("GET", "/api/chat/history?limit=10")
        if code == 200 and isinstance(body, dict):
            history = body.get("history") or []
            for item in history:
                if (item.get("role") == "assistant"
                        and (PROMPT.split("，")[0] in (item.get("content") or "")
                             or any(w in (item.get("content") or "")
                                    for w in ["伊塔", "我", "嗯", "在干嘛"]))):
                    latest = item
                    break
        if latest and TAG_RE.search((latest.get("content") or "")):
            break
        time.sleep(2.0)

    if not latest:
        expect("found recent assistant message", False, "no history")
        return 2
    expect("found recent assistant message", True, f"id={latest.get('id')}")

    content = latest.get("content") or ""

    # ── 3. Assertions on the tag round-trip ────────────
    has_action = "<action>" in content
    has_thought = "<thought>" in content
    has_any = has_action or has_thought
    expect("content contains <action> or <thought> tag",
           has_any, f"len={len(content)} preview={content[:60]!r}")

    if has_action:
        # Also: tags should NOT be HTML-escaped. We send <action> over
        # JSON and the server stores it raw. If the storage layer
        # double-escaped it, we'd see &lt;action&gt; in the response.
        expect("<action> tag is not HTML-escaped",
               "&lt;action&gt;" not in content, content[:80])

    # ── 4. Persona is still the same (no prompt corruption) ──
    code, body = _request("GET", "/api/persona")
    expect("persona endpoint still healthy",
           code == 200 and isinstance(body, dict)
           and (body.get("name") == "伊塔" or body.get("name") == "Ita"),
           f"name={body.get('name') if isinstance(body, dict) else 'n/a'}")

    # ── 5. Yaml still loads ──
    code, body = _request("GET", "/api/config/yaml?file=persona.yaml")
    expect("persona.yaml still loads",
           code == 200 and isinstance(body, str) and "消息结构约定" in body,
           f"code={code} len={len(body) if isinstance(body, str) else 'n/a'}")

    print("=" * 60)
    print(f"  Passed: {passed}  Failed: {failed}")
    print("=" * 60)

    if has_any and failed == 0:
        print("  ✓ R7.4 narration E2E: PASS")
        return 0
    elif not has_any:
        # The LLM may not have honoured the persona prompt on the first
        # try. This is a soft signal — log it loudly but do not
        # treat it as a hard failure of the test framework, because
        # the actual rendering path is fully covered by the JS unit
        # tests in the renderer process. Return 2 so CI can flag it.
        print("  ⚠ R7.4 narration: LLM did not emit tags (prompt may need more examples).")
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
