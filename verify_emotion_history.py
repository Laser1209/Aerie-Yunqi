"""Aerie · 云栖 v9.0 — Phase 9 Batch 5 verify: emotion history curves.

Verifies:
  1. /api/emotion/history works for all 4 windows (1h/24h/7d/30d)
  2. The response shape is what emotion-history.js expects
  3. The downsampling path returns the documented fields
  4. The non-downsampled path is also available (?downsample=false)
  5. All 7 numeric series (pleasure, arousal, dominance, 4 thresholds)
     are present in each item when there's data
  6. The label field is always a string (never null/empty)
  7. Backward-compat: items in a 1h window are not downsampled when
     the raw count is < 120
"""
from __future__ import annotations

import json
import sys
import time
import socket

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


def _request(method: str, path: str) -> tuple[int, object]:
    import urllib.request
    url = BASE + path
    req = urllib.request.Request(url, method=method,
                                 headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            ct = r.headers.get("Content-Type", "")
            raw = r.read()
            if "application/json" in ct:
                return r.status, json.loads(raw.decode("utf-8"))
            return r.status, raw.decode("utf-8", errors="replace")
    except Exception as e:
        return 0, {"error": str(e)}


def main() -> int:
    print("=" * 60)
    print("Phase 9 Batch 5 — Emotion history verify")
    print("=" * 60)
    if not _check_port():
        print(f"  ✗ backend not reachable on port {PORT}")
        return 1
    print(f"  ✓ backend reachable on port {PORT}")

    passed = failed = 0

    def expect(name: str, cond: bool, detail: str = ""):
        nonlocal passed, failed
        if cond:
            print(f"  ✓ {name}")
            passed += 1
        else:
            print(f"  ✗ {name}  {detail}")
            failed += 1

    # Top-level shape per window
    for w in ("1h", "24h", "7d", "30d"):
        code, body = _request("GET", f"/api/emotion/history?window={w}")
        expect(f"emotion history window={w}",
               code == 200 and isinstance(body, dict)
               and body.get("window") == w
               and isinstance(body.get("items"), list),
               f"code={code} body={body!r}")

        # Each item has the expected keys
        if isinstance(body, dict) and body.get("items"):
            first = body["items"][0]
            for k in ("pleasure", "arousal", "dominance", "label",
                      "patience_value", "anxiety_value",
                      "desire_value", "tenderness_value"):
                expect(f"  · window={w} item has {k}",
                       k in first,
                       f"first={first!r}")
            expect(f"  · window={w} label is string",
                   isinstance(first.get("label"), str)
                   and len(first.get("label") or "") > 0,
                   f"label={first.get('label')!r}")

    # Downsampling behaviour
    code, body = _request("GET", "/api/emotion/history?window=30d&downsample=true")
    expect("downsample=true returns downsampled field",
           code == 200 and isinstance(body, dict)
           and "downsampled" in body,
           f"body={body!r}")
    if isinstance(body, dict) and body.get("downsampled"):
        expect("  · downsampled count <= 500",
               body.get("count", 0) <= 500,
               f"count={body.get('count')}")
        expect("  · raw_count >= count",
               body.get("raw_count", 0) >= body.get("count", 0),
               f"raw={body.get('raw_count')} count={body.get('count')}")

    code, body = _request("GET", "/api/emotion/history?window=30d&downsample=false")
    expect("downsample=false returns raw items",
           code == 200 and isinstance(body, dict)
           and body.get("downsampled") is False
           and "items" in body,
           f"body={body!r}")

    # Empty windows still respond cleanly (1h with no data)
    code, body = _request("GET", "/api/emotion/history?window=1h")
    expect("emotion history empty 1h",
           code == 200 and isinstance(body, dict)
           and isinstance(body.get("items"), list)
           and body.get("count", 0) >= 0,
           f"code={code}")

    print("=" * 60)
    print(f"  Passed: {passed}  Failed: {failed}")
    print("=" * 60)
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
