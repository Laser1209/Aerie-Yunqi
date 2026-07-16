"""Block-5E R6.2 — CI: check renderer source for emoji (excludes typographic arrows/dots).

Scans .html/.js/.css under electron/src/renderer and reports any character in
the Unicode emoji blocks. Arrows (U+2190..21FF, U+2794..27BF) and middle-dot
(U+00B7, U+2027, U+30FB, U+FF65) and similar typographic glyphs are explicitly
allowed because they appear in UI text like "展开完整日报 ↗".

Exits 0 when no real emoji is found; non-zero otherwise.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "electron" / "src" / "renderer"

# Same ranges as scan_emojis.py (comprehensive emoji blocks).
EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001F02F"
    "\U0001F0A0-\U0001F0FF"
    "\U0001F100-\U0001F1FF"
    "\U0001F200-\U0001F2FF"
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\u2600-\u26FF"
    "\u2700-\u27BF"
    "\u2300-\u23FF"
    "\u2B00-\u2BFF"
    "\u25A0-\u25FF"
    "]"
)

# Allowed typographic glyphs (commonly appear in UI text).
ALLOWED = set("\u2192\u2190\u2191\u2193\u2196\u2197\u2198\u2199")  # basic arrows

def is_allowed(ch: str) -> bool:
    """Return True if the character is a typographic glyph, not an emoji."""
    if ch in ALLOWED:
        return True
    # Arrows in U+2794..27BF and similar decorative arrows.
    if 0x2794 <= ord(ch) <= 0x27BF and ch not in {"\u2728"}:  # ✨
        return True
    # Middle dot, half-width katakana middle dot.
    if ch in {"\u00B7", "\u2027", "\u30FB", "\uFF65"}:
        return True
    # Geometric placeholder glyphs (□ ● ◦ etc. are not really "emoji").
    if ch in {"\u25A1", "\u25CF", "\u25E6", "\u2022"}:
        return True
    return False

def main() -> int:
    total = 0
    files_scanned = 0
    hits = []
    for p in TARGET.rglob("*"):
        if p.is_file() and p.suffix in {".html", ".js", ".css"}:
            files_scanned += 1
            try:
                text = p.read_text(encoding="utf-8")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                matches = [m for m in EMOJI_RE.findall(line) if not is_allowed(m)]
                if matches:
                    joined = "|".join(matches)
                    snippet = line.strip()[:120]
                    rel = p.relative_to(ROOT)
                    hits.append(f"{rel}:{i}  {joined}  {snippet}")
                    total += len(matches)
    if hits:
        print("FAIL — emoji found in renderer (must be replaced with <svg><use>):")
        for h in hits:
            print(f"  {h}")
        print(f"\nTotal forbidden emoji: {total} across {len({h.rsplit(':',1)[0] for h in hits})} file(s)")
        return 1
    print(f"OK — no forbidden emoji found (scanned {files_scanned} file(s))")
    return 0

if __name__ == "__main__":
    sys.exit(main())
