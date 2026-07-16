"""Aerie · 云栖 v9.0 — Theme tokenization patcher (Block-5D R5.1).

Three CSS files (emotion-history / cognition-panel / daily-brief[-detail])
contain hard-coded brand color hex values that should resolve through
theme CSS variables. This script rewrites those literals into
``var(--color-..., #fallback)`` so the default theme keeps the look
while each theme can opt into its own palette.

Idempotent: re-running the script on already-patched files is a no-op.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STYLES_DIR = PROJECT_ROOT / "electron" / "src" / "renderer" / "styles"

# Files to patch
TARGETS = [
    STYLES_DIR / "emotion-history.css",
    STYLES_DIR / "cognition-panel.css",
    STYLES_DIR / "daily-brief.css",
    STYLES_DIR / "daily-brief-detail.css",
]

# Mapping of hex literal -> (token, fallback).
# Token is the canonical name we will introduce to each theme.
SUBSTITUTIONS: dict[str, tuple[str, str]] = {
    # PAD channels
    "#ff5b9c": ("--color-pad-pleasure",  "#ff5b9c"),
    "#7e6bff": ("--color-pad-arousal",   "#7e6bff"),
    "#3acfd5": ("--color-pad-dominance", "#3acfd5"),
    # Threshold chart lines (alias of PAD for now; themes can override)
    "#ffb74d": ("--color-threshold-anxiety",   "#ffb74d"),
    # Cognition stage colors
    "#b39ddb": ("--color-stage-cognition",  "#b39ddb"),
    "#80cbc4": ("--color-stage-committed",  "#80cbc4"),
    "#ff8a65": ("--color-stage-decision",   "#ff8a65"),
    # Card / accent pinks (伊塔粉)
    "#ff7eb6": ("--color-accent-pink",     "#ff7eb6"),
    # Brief primary action accent
    "#ff9500": ("--color-accent-warm",     "#ff9500"),
}

# Pairs we keep as a literal gradient because tokenizing a gradient is
# out of scope for this pass (would require per-theme gradient overrides).
GRADIENT_LINE = re.compile(r"linear-gradient\([^)]*#[0-9a-fA-F]{3,6}[^)]*\)")


PLACEHOLDER_PREFIX = "__AERIE_TOK_PH_"


def _patch_text(text: str) -> tuple[str, int]:
    """Apply the substitution table. Returns (new_text, hits).

    Strategy: 3 phases to keep things idempotent on re-runs.
      1. Replace each bare hex literal with a unique placeholder
         ``__AERIE_TOK_PH_<token>__`` (no var() involved yet).
      2. Flatten any pre-existing nested var() chains so re-runs
         collapse to a single var(--token, <hex>).
      3. Expand each placeholder back to ``var(--token, <hex>)``.
    """
    hits = 0

    # Phase 1: bare hex → placeholder
    for literal, (token, _fallback) in SUBSTITUTIONS.items():
        ph = f"{PLACEHOLDER_PREFIX}{token}__"
        # Bare: not preceded by alphanumeric / open paren, not already a placeholder
        pattern = re.compile(
            r"(?<![\w\(])" + re.escape(literal) + r"(?!__)",
            re.IGNORECASE,
        )
        new_text, n = pattern.subn(ph, text)
        if n:
            hits += n
            text = new_text

    # Phase 2: flatten any nested var() chains.
    # A chain "var(--t, var(--t, ... PH ...))"  →  just the inner PH (one level up).
    for _token, _fb in SUBSTITUTIONS.values():
        ph = f"{PLACEHOLDER_PREFIX}{_token}__"
        flat_re = re.compile(
            r"var\(\s*" + re.escape(_token) + r",\s*"
            r"(?:var\(\s*" + re.escape(_token) + r",\s*)*"  # any inner wraps
            + re.escape(ph) + r"\s*\)+\s*"  # closing parens
        )
        prev = None
        while prev != text:
            prev = text
            text = flat_re.sub(ph, text)  # strip the wrapping var(...)

    # Phase 3: placeholder → final var() form
    for _literal, (token, fallback) in SUBSTITUTIONS.items():
        ph = f"{PLACEHOLDER_PREFIX}{token}__"
        text = text.replace(ph, f"var({token}, {fallback})")

    return text, hits


def _is_already_tokenized(text: str) -> bool:
    """Return True if every target literal is already wrapped in var() once.

    We test the absence of:
      - bare hex literals (preceded by a non-word, non-paren char)
      - placeholder strings (would mean a previous run was interrupted)
    """
    for literal, (token, _fallback) in SUBSTITUTIONS.items():
        bare_pattern = re.compile(
            r"(?<![\w\(])" + re.escape(literal),
            re.IGNORECASE,
        )
        if bare_pattern.search(text):
            return False
        # Also reject if any placeholder string is present (incomplete run).
        if f"{PLACEHOLDER_PREFIX}{token}__" in text:
            return False
    return True


def patch_file(path: Path) -> tuple[bool, int]:
    original = path.read_text(encoding="utf-8")
    # Skip if already tokenized: presence of all token names.
    if all(f"var({tok}," in original for tok, _ in SUBSTITUTIONS.values()):
        return False, 0
    # Don't touch gradient lines (keep the literal gradient intact).
    # We approximate by skipping lines containing "linear-gradient".
    out_lines: list[str] = []
    hits = 0
    for line in original.splitlines(keepends=True):
        if "linear-gradient" in line:
            out_lines.append(line)
            continue
        new_line, n = _patch_text(line)
        if n:
            hits += n
        out_lines.append(new_line)
    new_text = "".join(out_lines)
    if new_text == original:
        return False, 0
    path.write_text(new_text, encoding="utf-8")
    return True, hits


def main() -> int:
    total_files = total_hits = 0
    for p in TARGETS:
        if not p.exists():
            print(f"[skip] {p.name} (missing)")
            continue
        changed, hits = patch_file(p)
        flag = "patched" if changed else "no-op"
        print(f"[{flag:>7}] {p.name}  hits={hits}")
        if changed:
            total_files += 1
        total_hits += hits
    print(f"\nTotal: {total_files} files patched, {total_hits} literals tokenized.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
