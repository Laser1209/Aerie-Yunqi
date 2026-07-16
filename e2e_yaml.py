"""Aerie · 云栖 v9.0 — Phase 9 Batch 3 verification.

Self-doubt review + end-to-end test of the 4 new yaml endpoints:
  GET  /api/config/yaml/list
  GET  /api/config/yaml?file=settings.yaml
  PUT  /api/config/yaml?file=settings.yaml
  POST /api/config/yaml/backup?file=settings.yaml

Acceptance criteria (from B3 plan):
  - 双模式可用
  - YAML 编辑强校验
  - 写回前自动备份
  - 解析失败回滚

Usage:
  python e2e_yaml.py
"""

from __future__ import annotations
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE = "http://127.0.0.1:7890"
CONFIG_DIR = Path("config")
BACKUP_DIR = Path("data/backups/config")


def _request(method: str, path: str, body: bytes | None = None,
             headers: dict | None = None) -> tuple[int, bytes, dict]:
    url = BASE + path
    req = urllib.request.Request(url, data=body, method=method,
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {})


def _print_section(name: str) -> None:
    print("\n" + "═" * 60)
    print(f"  {name}")
    print("═" * 60)


def _assert(cond: bool, msg: str) -> bool:
    print(("  ✓ " if cond else "  ✗ ") + msg)
    return cond


def main() -> int:
    failed = 0

    _print_section("B3.4 self-doubt review: 4 yaml endpoints")

    # ── Pre-flight: ensure backend up ──
    try:
        code, body, _ = _request("GET", "/api/health")
        if code != 200:
            print(f"  ! backend not healthy (code={code}); start python main.py first")
            return 2
        health = json.loads(body)
        print(f"  ✓ backend OK: {health.get('app')} v{health.get('version')}")
    except Exception as e:
        print(f"  ! cannot reach backend: {e}")
        return 2

    # ── Review 1: backup path is correct ──
    _print_section("Review 1: backup path is correct")
    target = CONFIG_DIR / "settings.yaml"
    if not target.exists():
        print(f"  ✗ settings.yaml missing at {target}")
        return 2
    initial_size = target.stat().st_size
    initial_text = target.read_text(encoding="utf-8")
    print(f"  baseline settings.yaml = {initial_size} bytes")

    # ── Test 1: list endpoint ──
    _print_section("Test 1: GET /api/config/yaml/list")
    code, body, _ = _request("GET", "/api/config/yaml/list")
    if not _assert(code == 200, f"status=200 (got {code})"):
        failed += 1
    try:
        j = json.loads(body)
        files = set(j.get("files", []))
        if not _assert(files == {"settings.yaml", "persona.yaml", "proactive.yaml"},
                       f"whitelist exact match (got {files})"):
            failed += 1
    except Exception as e:
        print(f"  ✗ JSON parse: {e}")
        failed += 1

    # ── Test 2: get endpoint ──
    _print_section("Test 2: GET /api/config/yaml?file=settings.yaml")
    code, body, headers = _request("GET", "/api/config/yaml?file=settings.yaml")
    if not _assert(code == 200, f"status=200 (got {code})"):
        failed += 1
    ct = headers.get("content-type", "").lower()
    if not _assert("text/plain" in ct, f"content-type=text/plain (got {ct})"):
        failed += 1
    if not _assert(body.decode("utf-8") == initial_text, "body matches file on disk"):
        failed += 1

    # ── Test 3: get endpoint with non-whitelisted file ──
    _print_section("Test 3: GET non-whitelisted file (rejected)")
    code, body, _ = _request("GET", "/api/config/yaml?file=evil.yaml")
    if not _assert(code == 400, f"status=400 (got {code})"):
        failed += 1

    # ── Test 4: put endpoint with valid yaml ──
    _print_section("Test 4: PUT valid yaml")
    new_text = initial_text + "\n# self-doubt review test marker\n"
    code, body, _ = _request(
        "PUT", "/api/config/yaml?file=settings.yaml",
        body=new_text.encode("utf-8"),
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    if not _assert(code == 200, f"status=200 (got {code})"):
        failed += 1
    try:
        j = json.loads(body)
        if not _assert(j.get("status") == "ok", "response status=ok"):
            failed += 1
        if not _assert(j.get("backup_path"), f"backup_path returned: {j.get('backup_path')}"):
            failed += 1
        if not _assert(target.read_text(encoding="utf-8") == new_text,
                       "file on disk matches new text"):
            failed += 1
    except Exception as e:
        print(f"  ✗ JSON parse: {e}")
        failed += 1

    # ── Test 5: get endpoint after write (self-consistency) ──
    _print_section("Test 5: re-GET after write (self-consistency)")
    code, body, _ = _request("GET", "/api/config/yaml?file=settings.yaml")
    if not _assert(code == 200, f"status=200 (got {code})"):
        failed += 1
    if not _assert(body.decode("utf-8") == new_text, "GET returns new text"):
        failed += 1

    # ── Test 6: put endpoint with invalid yaml (should 400 + rollback) ──
    _print_section("Test 6: PUT invalid yaml (parse error → 400 + rollback)")
    invalid = "this is: invalid: yaml: with: colons: everywhere:\n  - [unclosed"
    code, body, _ = _request(
        "PUT", "/api/config/yaml?file=settings.yaml",
        body=invalid.encode("utf-8"),
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    if not _assert(code == 400, f"status=400 (got {code})"):
        failed += 1
    # file should still be the previous (valid) content
    if not _assert(target.read_text(encoding="utf-8") == new_text,
                   "file unchanged after rejected write"):
        failed += 1

    # ── Test 7: backup endpoint ──
    _print_section("Test 7: POST /api/config/yaml/backup")
    code, body, _ = _request("POST", "/api/config/yaml/backup?file=settings.yaml")
    if not _assert(code == 200, f"status=200 (got {code})"):
        failed += 1
    try:
        j = json.loads(body)
        if not _assert(j.get("status") == "ok", "response status=ok"):
            failed += 1
        if not _assert(Path(j.get("backup_path", "")).exists(),
                       f"backup file exists: {j.get('backup_path')}"):
            failed += 1
    except Exception as e:
        print(f"  ✗ JSON parse: {e}")
        failed += 1

    # ── Test 8: verify all 3 files are accessible ──
    _print_section("Test 8: 3 whitelisted files all readable")
    for f in ("settings.yaml", "persona.yaml", "proactive.yaml"):
        code, body, _ = _request("GET", f"/api/config/yaml?file={f}")
        if not _assert(code == 200, f"GET {f} → 200"):
            failed += 1
        else:
            print(f"    body length = {len(body)} bytes")

    # ── Test 9: backup directory exists ──
    _print_section("Review 2: backup directory has files")
    if BACKUP_DIR.exists():
        files = sorted(BACKUP_DIR.glob("settings.yaml.*.yaml"))
        if not _assert(len(files) >= 2, f"at least 2 backup files (got {len(files)})"):
            failed += 1
        for f in files:
            print(f"    {f.name} ({f.stat().st_size} bytes)")
    else:
        print("  ✗ backup directory missing")
        failed += 1

    # ── Cleanup: restore original settings.yaml ──
    _print_section("Cleanup: restore original settings.yaml")
    code, body, _ = _request(
        "PUT", "/api/config/yaml?file=settings.yaml",
        body=initial_text.encode("utf-8"),
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    if _assert(code == 200, "restore ok"):
        print("    settings.yaml restored to original")
    else:
        failed += 1
        print(f"    ✗ restore failed code={code}")

    # ── Summary ──
    _print_section("Summary")
    if failed == 0:
        print("  ✓ all checks passed")
        return 0
    else:
        print(f"  ✗ {failed} check(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
