"""Aerie · 云栖 v9.0 — Phase 9 Batch 7 E2E: persona pacing 综合节奏演示.

Verifies the 11-style persona pacing decision tree under 6 emotional /
eruption states, 5 segments each. Pure local — does not depend on
LLM, DB, or backend.

Acceptance (from B7 plan):
  * First segment is always immediate (interval = 0.0)
  * Subsequent segments are bounded by the style's [min, max] range
  * No segment exceeds 5.0s (the soft ceiling for a real human's gap)
  * The style label is one of the 11 documented styles

Usage:
  python e2e_pacing.py
"""
from __future__ import annotations

import asyncio
import sys

from core.persona_pacing import STYLES, compute_persona_interval

# ── 6 test scenarios (emotion / eruption) ──────────────────
SCENARIOS: list[tuple[str, dict, bool]] = [
    ("neutral",     {},                                                                       False),
    ("joy",         {},                                                                       False),
    ("sad",         {},                                                                       False),
    ("fear",        {},                                                                       False),
    ("anxiety",     {"anxiety":   {"active": True, "value": 100, "threshold": 80}},          True),
    ("tenderness",  {"tenderness":{"active": True, "value": 60,  "threshold": 50}},          True),
]

VALID_STYLES = set(STYLES.keys())
SOFT_CEILING_SECONDS = 5.0
N_SEGMENTS = 5


def _check(label: str, ok: bool, detail: str = "") -> None:
    sym = "✓" if ok else "✗"
    print(f"  {sym} {label}  {detail}")


async def _run_scenario(name: str, threshold: dict, is_eruption: bool) -> tuple[int, int]:
    """Run one scenario for N_SEGMENTS segments; return (passed, failed)."""
    passed = failed = 0
    print(f"\n=== {name}{'  [eruption]' if is_eruption else ''} ===")
    intervals: list[float] = []
    styles: list[str] = []
    for i in range(N_SEGMENTS):
        seg_content = f"伊塔——第{i+1}句"
        iv, style = compute_persona_interval(
            segment_index=i,
            emotion_label=name,
            threshold=threshold,
            is_eruption=is_eruption,
            segment_content=seg_content,
        )
        print(f"  seg {i}: {iv:.2f}s [{style}]")
        intervals.append(iv)
        styles.append(style)

    # ── Acceptance 1: first segment is always immediate ──
    if intervals[0] == 0.0 and styles[0] == "immediate":
        passed += 1
        _check("first segment is immediate (interval=0)", True)
    else:
        failed += 1
        _check(
            "first segment is immediate (interval=0)",
            False, f"got {intervals[0]!r} [{styles[0]}]",
        )

    # ── Acceptance 2: all intervals are within their declared style range ──
    for iv, st in zip(intervals, styles):
        rng = STYLES.get(st)
        if rng is None:
            failed += 1
            _check(f"style {st!r} is in 11-style catalogue", False)
            continue
        lo, hi = rng
        if iv < lo - 1e-6 or iv > hi + 1e-6:
            failed += 1
            _check(
                f"seg iv={iv:.2f}s within {st} [{lo:.2f}, {hi:.2f}]",
                False, f"iv={iv} outside [{lo}, {hi}]",
            )
        else:
            passed += 1
            _check(
                f"seg iv={iv:.2f}s within {st} [{lo:.2f}, {hi:.2f}]",
                True,
            )

    # ── Acceptance 3: no segment exceeds soft ceiling ──
    for i, iv in enumerate(intervals):
        if iv <= SOFT_CEILING_SECONDS:
            passed += 1
            _check(f"seg {i} iv {iv:.2f}s ≤ {SOFT_CEILING_SECONDS}s ceiling", True)
        else:
            failed += 1
            _check(
                f"seg {i} iv {iv:.2f}s ≤ {SOFT_CEILING_SECONDS}s ceiling",
                False, f"exceeded by {iv - SOFT_CEILING_SECONDS:.2f}s",
            )

    # ── Acceptance 4: every style is in the catalogue ──
    for st in styles:
        if st in VALID_STYLES:
            passed += 1
            _check(f"style {st!r} ∈ 11-style catalogue", True)
        else:
            failed += 1
            _check(f"style {st!r} ∈ 11-style catalogue", False, "unknown style")

    return passed, failed


async def main() -> int:
    print("=" * 60)
    print("Phase 9 Batch 7 E2E — persona_pacing 综合节奏演示")
    print(f"  scenarios={len(SCENARIOS)}  segments/scenario={N_SEGMENTS}")
    print("=" * 60)
    total_p = total_f = 0
    for name, threshold, is_eruption in SCENARIOS:
        p, f = await _run_scenario(name, threshold, is_eruption)
        total_p += p
        total_f += f

    print("\n" + "=" * 60)
    print(f"  Total: passed={total_p}  failed={total_f}")
    if total_f == 0:
        print("  ✓ e2e_pacing 全部通过")
    print("=" * 60)
    return 0 if total_f == 0 else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
