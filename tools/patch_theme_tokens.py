"""Aerie · 云栖 v0.1.0-beta.1 — Theme tokenization patcher (Block-5D R5.1).

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
# Block-5E R6.1: added floating-ball.css (shell + badge literals) and
# main.css (threshold warning/danger bar end-stops).
TARGETS = [
    STYLES_DIR / "emotion-history.css",
    STYLES_DIR / "cognition-panel.css",
    STYLES_DIR / "daily-brief.css",
    STYLES_DIR / "daily-brief-detail.css",
    STYLES_DIR / "floating-ball.css",
    STYLES_DIR / "main.css",
]

# Mapping of hex literal -> (token, fallback).
# Token is the canonical name we will introduce to each theme.
# Block-5E R6.1: extended to cover the literal values that lived inside
# linear-gradient() / radial-gradient() lines (cognition-bar, eruption
# banner, threshold warning/danger ends, floating-ball shell).
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
    # Block-5E R6.1: gradient stop / shell / badge literal values
    "#9c27b0": ("--color-eruption-grad-2",        "#9c27b0"),
    "#ff6d00": ("--color-accent-warning-strong",  "#ff6d00"),
    "#d50000": ("--color-accent-danger-strong",   "#d50000"),
    "#66abff": ("--color-floating-ball-grad-1",   "#66abff"),
    "#007aff": ("--color-floating-ball-grad-2",   "#007aff"),
    "#ff3b30": ("--color-ball-badge",             "#ff3b30"),
}

# Pairs we keep as a literal gradient because tokenizing a gradient is
# out of scope for this pass (would require per-theme gradient overrides).
GRADIENT_LINE = re.compile(r"linear-gradient\([^)]*#[0-9a-fA-F]{3,6}[^)]*\)")


PLACEHOLDER_PREFIX = "__AERIE_TOK_PH_"


def _patch_text(text: str) -> tuple[str, int]:
    """Apply the substitution table. Returns (new_text, hits).

    Strategy: 5 phases to keep things idempotent on re-runs and to
    avoid corrupting the design-token definition block.
      0a. Mask every existing var(...) body so substitution can never
          reach inside an already-tokenised fallback (prevents
          ``var(--t, var(--t, #hex))`` nesting on re-runs).
      0b. Mask every top-level ``:root { ... }`` block so the design
          token definitions are not rewritten (prevents
          ``--color-x: var(--color-x, #hex)`` self-reference loops).
      1. Replace each remaining bare hex literal with a unique
         placeholder ``__AERIE_TOK_PH_<token>__``.
      2. Restore the masked var(...) bodies (their internals are
         already either tokenised or fallbacks).
      3. Restore the masked :root blocks.
      4. Expand each placeholder back to ``var(--token, <hex>)``.
    """
    hits = 0
    var_mask: dict[str, str] = {}
    root_mask: dict[str, str] = {}

    def _mask_var(match: re.Match) -> str:
        sentinel = f"__AERIE_TOK_VAR_{len(var_mask)}__"
        var_mask[sentinel] = match.group(0)
        return sentinel

    def _mask_root(match: re.Match) -> str:
        sentinel = f"__AERIE_TOK_ROOT_{len(root_mask)}__"
        root_mask[sentinel] = match.group(0)
        return sentinel

    masked = text
    # Phase 0b FIRST: mask every top-level :root { ... } block (so
    # design-token definitions are never rewritten). After this, the
    # masked text contains __AERIE_TOK_ROOT_*__ sentinels.
    def _root_scan(s: str) -> str:
        out = []
        i = 0
        while i < len(s):
            m = re.search(r":root\s*\{", s[i:])
            if not m:
                out.append(s[i:])
                break
            start = i + m.start()
            out.append(s[i:start])
            # Find the matching closing brace.
            j = i + m.end()
            depth = 1
            while j < len(s) and depth > 0:
                if s[j] == "{":
                    depth += 1
                elif s[j] == "}":
                    depth -= 1
                j += 1
            block = s[start:j]
            sentinel = f"__AERIE_TOK_ROOT_{len(root_mask)}__"
            root_mask[sentinel] = block
            out.append(sentinel)
            i = j
        return "".join(out)

    masked = _root_scan(masked)

    # Phase 0a SECOND: mask every existing var(...) body outside the
    # already-masked :root blocks. This protects already-tokenised
    # fallbacks from being re-wrapped.
    masked = re.sub(r"var\([^()]*(?:\([^()]*\)[^()]*)*\)", _mask_var, masked)

    # Phase 1: bare hex → placeholder (in masked text).
    for literal, (token, _fallback) in SUBSTITUTIONS.items():
        ph = f"{PLACEHOLDER_PREFIX}{token}__"
        pattern = re.compile(
            r"(?<![\w\(])" + re.escape(literal) + r"(?!__)",
            re.IGNORECASE,
        )
        new_text, n = pattern.subn(ph, masked)
        if n:
            hits += n
            masked = new_text

    # Phase 2: restore masked var(...) bodies.
    for sentinel, original in var_mask.items():
        masked = masked.replace(sentinel, original)

    # Phase 3: restore masked :root blocks.
    for sentinel, original in root_mask.items():
        masked = masked.replace(sentinel, original)

    # Phase 4: placeholder → final var() form
    for _literal, (token, fallback) in SUBSTITUTIONS.items():
        ph = f"{PLACEHOLDER_PREFIX}{token}__"
        masked = masked.replace(ph, f"var({token}, {fallback})")

    return masked, hits


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
    # Block-5E R6.1: process the WHOLE file in one call so :root { ... }
    # blocks (which may span many lines) are masked as a single unit.
    # Idempotency is decided by _patch_text itself: if it returns hits=0
    # (no bare literals left to convert) the file is already in a clean
    # state and we skip writing.
    new_text, hits = _patch_text(original)
    if hits == 0 or new_text == original:
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
