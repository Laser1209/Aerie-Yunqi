"""Aerie · 云栖 v9.0 — Legacy file organization tool (Block-5D R4).

Idempotent migration that consolidates scattered probes/debug logs/DBs
into a unified ``tmp/`` and ``logs/`` tree. Safe to re-run: existing
files at the destination are skipped, and the source is only removed
after a successful move.

Mapping (v1):
    scripts/probe_*.py        ->  tmp/probes/probe_*.py
    scripts/validate_env_keys.py
    scripts/verify_siliconflow_final.py
    logs/_smoke.py            ->  tmp/scripts/_smoke.py
    logs/debug_bat.bat        ->  tmp/scripts/debug_bat.bat
    logs/debug_napcat.py      ->  tmp/scripts/debug_napcat.py
    logs/diag.ps1             ->  tmp/scripts/diag.ps1
    logs/live2.ps1            ->  tmp/scripts/live2.ps1
    logs/live3.ps1            ->  tmp/scripts/live3.ps1
    logs/live4.ps1            ->  tmp/scripts/live4.ps1
    logs/live5.ps1            ->  tmp/scripts/live5.ps1
    logs/live_smoke_copy.ps1  ->  tmp/scripts/live_smoke_copy.ps1
    logs/live_with_full.ps1   ->  tmp/scripts/live_with_full.ps1
    logs/run_napcat_manually.bat
    logs/verify_bridge.ps1
    logs/yunqi_check.db       ->  tmp/db/yunqi_check.db
    network_probe.log         ->  logs/network_probe.log
    siliconflow_multi.log     ->  logs/siliconflow_multi.log
    siliconflow_probe.log     ->  logs/siliconflow_probe.log
    data/verify-batch4-backend.log
    data/verify-batch5-backend.log

Usage:
    python tools/migrate_legacy.py            # perform migration
    python tools/migrate_legacy.py --dry-run  # preview only
    python tools/migrate_legacy.py --list     # print mapping table
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── Source → destination mapping (relative to project root) ──
MIGRATION_MAP: list[tuple[str, str]] = [
    # ── Probes (scripts/ → tmp/probes/) ──
    ("scripts/probe_llm_providers.py",       "tmp/probes/probe_llm_providers.py"),
    ("scripts/probe_network.py",             "tmp/probes/probe_network.py"),
    ("scripts/probe_openai_direct.py",       "tmp/probes/probe_openai_direct.py"),
    ("scripts/probe_openai_new_key.py",      "tmp/probes/probe_openai_new_key.py"),
    ("scripts/probe_proxy_and_gemma.py",     "tmp/probes/probe_proxy_and_gemma.py"),
    ("scripts/probe_siliconflow_diag.py",    "tmp/probes/probe_siliconflow_diag.py"),
    ("scripts/probe_siliconflow_multi.py",   "tmp/probes/probe_siliconflow_multi.py"),
    ("scripts/probe_siliconflow_v2.py",      "tmp/probes/probe_siliconflow_v2.py"),
    ("scripts/validate_env_keys.py",         "tmp/probes/validate_env_keys.py"),
    ("scripts/verify_siliconflow_final.py",  "tmp/probes/verify_siliconflow_final.py"),

    # ── Debug scripts (logs/ → tmp/scripts/) ──
    ("logs/_smoke.py",                       "tmp/scripts/_smoke.py"),
    ("logs/debug_bat.bat",                   "tmp/scripts/debug_bat.bat"),
    ("logs/debug_napcat.py",                 "tmp/scripts/debug_napcat.py"),
    ("logs/diag.ps1",                        "tmp/scripts/diag.ps1"),
    ("logs/live2.ps1",                       "tmp/scripts/live2.ps1"),
    ("logs/live3.ps1",                       "tmp/scripts/live3.ps1"),
    ("logs/live4.ps1",                       "tmp/scripts/live4.ps1"),
    ("logs/live5.ps1",                       "tmp/scripts/live5.ps1"),
    ("logs/live_smoke_copy.ps1",             "tmp/scripts/live_smoke_copy.ps1"),
    ("logs/live_with_full.ps1",              "tmp/scripts/live_with_full.ps1"),
    ("logs/run_napcat_manually.bat",         "tmp/scripts/run_napcat_manually.bat"),
    ("logs/verify_bridge.ps1",               "tmp/scripts/verify_bridge.ps1"),

    # ── Test DB (logs/ → tmp/db/) ──
    ("logs/yunqi_check.db",                  "tmp/db/yunqi_check.db"),

    # ── Scattered logs (root + data/ → logs/) ──
    ("network_probe.log",                    "logs/network_probe.log"),
    ("siliconflow_multi.log",                "logs/siliconflow_multi.log"),
    ("siliconflow_probe.log",                "logs/siliconflow_probe.log"),
    ("data/verify-batch4-backend.log",       "logs/verify-batch4-backend.log"),
    ("data/verify-batch5-backend.log",       "logs/verify-batch5-backend.log"),
]


def print_table() -> None:
    print(f"{'SOURCE':<45} {'→':^2} {'DESTINATION':<45} {'STATUS':<10}")
    print("-" * 110)
    for src, dst in MIGRATION_MAP:
        s = _PROJECT_ROOT / src
        d = _PROJECT_ROOT / dst
        if d.exists() and not s.exists():
            status = "done"
        elif s.exists() and not d.exists():
            status = "pending"
        elif s.exists() and d.exists():
            status = "both"
        else:
            status = "missing"
        print(f"{src:<45} {'→':^2} {dst:<45} {status:<10}")


def migrate(dry_run: bool = False) -> dict:
    """Execute the migration. Returns a summary dict."""
    moved: list[tuple[str, str]] = []
    skipped: list[str] = []
    errors: list[tuple[str, str]] = []

    for src_rel, dst_rel in MIGRATION_MAP:
        src = _PROJECT_ROOT / src_rel
        dst = _PROJECT_ROOT / dst_rel

        if not src.exists():
            # Source missing — that's fine (idempotent).
            skipped.append(src_rel)
            continue

        if dst.exists():
            # Destination already populated — skip to avoid clobber.
            skipped.append(src_rel)
            continue

        if dry_run:
            moved.append((src_rel, dst_rel))
            continue

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved.append((src_rel, dst_rel))
        except Exception as e:
            errors.append((src_rel, str(e)))

    return {
        "moved": moved,
        "skipped": skipped,
        "errors": errors,
        "dry_run": dry_run,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Aerie legacy file organization")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, do not move")
    parser.add_argument("--list", action="store_true", help="Print mapping table")
    args = parser.parse_args()

    if args.list:
        print_table()
        return 0

    result = migrate(dry_run=args.dry_run)
    print(f"\n=== Aerie legacy migration {'(DRY-RUN) ' if args.dry_run else ''}===")
    print(f"Moved:   {len(result['moved'])}")
    for s, d in result["moved"]:
        print(f"  {s} → {d}")
    print(f"Skipped: {len(result['skipped'])} (already done or source missing)")
    print(f"Errors:  {len(result['errors'])}")
    for s, e in result["errors"]:
        print(f"  {s}: {e}")

    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
