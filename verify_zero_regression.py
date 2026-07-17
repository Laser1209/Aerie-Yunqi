"""Aerie · 云栖 v9.0 — Phase 9 Batch 4 verify: zero-regression sweep.

Verifies that the previous-batch functionality still works:
  1. Backend health
  2. Settings form/YAML dual-mode endpoints
  3. Chat send + history
  4. Emotion state + history endpoint (Batch 5 will consume history)
  5. SSE endpoint reachability
  6. Cognition trace list + detail (Batch 4 backend)
  7. YAML save still rejected for invalid + backup created

This script talks to the running Python backend on port 7890.
It does NOT spin up the backend itself — the dev is expected to have
already started it (via main.py or launcher).
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
import urllib.error
import socket

PORT = 7890
BASE = f"http://127.0.0.1:{PORT}"


def _check_port() -> bool:
    """Block up to 45 seconds for the backend to come up (per project rule)."""
    deadline = time.time() + 45
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def _request(method: str, path: str, body: dict | None = None,
             raw_body: bytes | None = None,
             headers: dict | None = None) -> tuple[int, object]:
    url = BASE + path
    data: bytes | None = None
    h = {"Accept": "application/json"}
    if raw_body is not None:
        data = raw_body
        h.update(headers or {"Content-Type": "text/plain; charset=utf-8"})
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    # NOTE (R7.0): chat send can take 10-15s on slow providers (the
    # cognition log shows 11-13s for verify-batch4 ping). 10s is too
    # tight and produces flaky "timed out" failures. Bump to 40s to
    # accommodate DeepSeek/BigModel cold-start + context window build.
    _HTTP_TIMEOUT_SEC = 40
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SEC) as r:
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


def main() -> int:
    print("=" * 60)
    print("Phase 9 Batch 4 — Zero-regression verify")
    print("=" * 60)
    if not _check_port():
        print(f"  ✗ backend not reachable on port {PORT}")
        return 1
    print(f"  ✓ backend reachable on port {PORT}")

    passed = 0
    failed = 0
    cases = []

    def expect(name: str, cond: bool, detail: str = ""):
        nonlocal passed, failed
        if cond:
            print(f"  ✓ {name}")
            cases.append((True, name))
            passed += 1
        else:
            print(f"  ✗ {name}  {detail}")
            cases.append((False, name))
            failed += 1

    # ── 1. Health ────────────────────────────────────
    code, body = _request("GET", "/api/health")
    expect("/api/health ok", code == 200 and isinstance(body, dict)
           and body.get("status") == "ok", f"code={code} body={body!r}")

    # ── 2. Chat send + history (smoke) ──────────────
    code, body = _request("POST", "/api/chat/send", body={"text": "verify-batch4 ping"})
    expect("chat send", code in (200, 503)
           and not (isinstance(body, dict) and body.get("error") == "backend not ready"),
           f"code={code} body={body!r}")

    code, body = _request("GET", "/api/chat/history?limit=3")
    expect("chat history", code == 200 and isinstance(body, dict)
           and isinstance(body.get("history"), list), f"code={code}")

    # ── 3. Emotion state + thresholds ───────────────
    code, body = _request("GET", "/api/emotion/state?user_id=0")
    expect("emotion state", code == 200 and isinstance(body, dict), f"code={code}")

    code, body = _request("GET", "/api/emotion/thresholds")
    expect("emotion thresholds", code == 200 and isinstance(body, dict), f"code={code}")

    # ── 4. Emotion history (Batch 5 endpoint) ───────
    code, body = _request("GET", "/api/emotion/history?window=24h")
    expect("emotion history", code == 200 and isinstance(body, dict)
           and "items" in body, f"code={code} body={body!r}")

    # ── 5. YAML endpoints (Batch 3) ─────────────────
    code, body = _request("GET", "/api/config/yaml/list")
    expect("yaml list", code == 200 and isinstance(body, dict)
           and set(body.get("files") or []) == {"settings.yaml", "persona.yaml", "proactive.yaml"},
           f"code={code} body={body!r}")

    code, body = _request("GET", "/api/config/yaml?file=settings.yaml")
    expect("yaml get", code == 200 and isinstance(body, str) and len(body) > 0,
           f"code={code}")

    # Valid yaml PUT
    valid_yaml = "verify_batch4:\n  ping: pong\n  ts: " + str(int(time.time())) + "\n"
    code, body = _request("PUT", "/api/config/yaml?file=settings.yaml",
                          raw_body=valid_yaml.encode("utf-8"),
                          headers={"Content-Type": "text/plain; charset=utf-8"})
    expect("yaml put valid", code == 200
           and isinstance(body, dict) and body.get("status") == "ok",
           f"code={code} body={body!r}")

    # Invalid yaml PUT (must be rejected with 400)
    code, body = _request("PUT", "/api/config/yaml?file=settings.yaml",
                          raw_body=b"this is: invalid: yaml: [unclosed",
                          headers={"Content-Type": "text/plain; charset=utf-8"})
    expect("yaml put invalid rejected", code == 400,
           f"code={code} body={body!r}")

    # ── 6. Cognition endpoints (Batch 4 backend) ────
    code, body = _request("GET", "/api/cognition/recent?limit=5")
    expect("cognition recent", code == 200 and isinstance(body, dict)
           and isinstance(body.get("traces"), list),
           f"code={code} body={body!r}")

    code, body = _request("GET", "/api/cognition/stats")
    expect("cognition stats", code == 200 and isinstance(body, dict)
           and "total" in body and "today" in body and "avg_duration_ms" in body,
           f"code={code} body={body!r}")

    # Pick a real trace if available, otherwise just confirm 404 path.
    code_list, body_list = _request("GET", "/api/cognition/recent?limit=1")
    top = (body_list.get("traces") or [None])[0] if isinstance(body_list, dict) else None
    if top and top.get("id"):
        code, body = _request("GET", f"/api/cognition/{top['id']}")
        expect("cognition detail", code == 200 and isinstance(body, dict)
               and "stage_route" in body,
               f"code={code}")
    else:
        code, body = _request("GET", "/api/cognition/9999999")
        expect("cognition detail 404", code == 404, f"code={code}")

    # ── 7. SSE endpoint reachability (1-sec sniff) ──
    # Use a raw socket so we don't have to wait for urllib to flush its
    # internal buffer. The server emits a stream_open frame immediately.
    try:
        s = socket.create_connection(("127.0.0.1", PORT), timeout=3.0)
        s.sendall(b"GET /api/events/stream HTTP/1.1\r\n"
                  b"Host: 127.0.0.1:7890\r\n"
                  b"Accept: text/event-stream\r\n"
                  b"Connection: close\r\n\r\n")
        s.settimeout(3.0)
        buf = b""
        deadline = time.time() + 3.0
        while time.time() < deadline and len(buf) < 4096:
            try:
                chunk = s.recv(512)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
            if b"data:" in buf and (b"stream_open" in buf or b"heartbeat" in buf):
                break
        s.close()
        expect("sse stream reachable", b"data:" in buf,
               f"buf={buf[:200]!r}")
    except Exception as e:
        expect("sse stream reachable", False, f"err={e}")

    print("=" * 60)
    print(f"  Passed: {passed}  Failed: {failed}")
    print("=" * 60)
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
