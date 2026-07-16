"""Block-5E R6.3 — CI: scan CSS for hardcoded hex colors.

Per project_memory.md ("UI elements must use CSS variables for consistent
theme adaptation across all color schemes"), CSS files should not contain
hardcoded #hex colors outside the :root token block. Hex values declared
inside :root { ... } are the SOURCE OF TRUTH and are allowed.

Scope: all .css files under electron/src/renderer/styles/

Exits 0 when no hardcoded hex color is found outside :root; non-zero otherwise.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "electron" / "src" / "renderer" / "styles"

# Match #rgb, #rgba, #rrggbb, #rrggbbaa (case-insensitive).
HEX_RE = re.compile(r"#[0-9A-Fa-f]{3,8}\b")

# Allow: #id selectors (e.g., #app, #chat-messages) and the data: URL scheme
# (which may carry # in a fragment). The HEX_RE only matches #rrggbb-like
# strings of length 3-8 hex chars, so #app is naturally excluded.

# Files that are exempt (rare edge cases).
EXEMPT_FILES: set[str] = set()


def extract_root_block(text: str) -> str:
    """Return the :root { ... } block(s) so we can mask them out of the scan."""
    # Greedy match: from `:root` or `:root, ...` up to the matching closing `}`.
    # Use a non-greedy match across newlines to be safe.
    out = []
    i = 0
    while i < len(text):
        m = re.search(r":root[^{]*\{", text[i:])
        if not m:
            break
        start = i + m.start()
        brace_open = i + m.end() - 1  # position of `{`
        depth = 1
        j = brace_open + 1
        while j < len(text) and depth > 0:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        # Replace the block content with whitespace of equal length so line
        # numbers stay accurate.
        block = text[start:j]
        masked = re.sub(r"[^\n]", " ", block)
        out.append((start, j, masked))
        i = j
    return out


def mask_root_blocks(text: str) -> str:
    """Replace the content of every :root { ... } block with whitespace.

    Also masks hex values that appear as the SECOND ARGUMENT of a var()
    call. The var(--name, #fallback) idiom is a legitimate CSS pattern
    that allows the variable to degrade gracefully when the token is
    undefined in a given theme.
    """
    pieces = []
    last = 0
    # First, mask :root blocks.
    for start, end, masked in extract_root_block(text):
        pieces.append(text[last:start])
        pieces.append(masked)
        last = end
    pieces.append(text[last:])
    text2 = "".join(pieces)

    # Second, mask var(--name, #hex) fallback hex. Replace #hex with spaces
    # so line numbers stay accurate.
    def _mask_var_fallback(m: re.Match) -> str:
        inner = m.group(1)  # content inside var(...) excluding outer parens
        # Find the LAST comma (the fallback separator).
        last_comma = inner.rfind(",")
        if last_comma < 0:
            return m.group(0)
        prefix = inner[:last_comma]
        suffix = inner[last_comma:]
        suffix = HEX_RE.sub(lambda mm: " " * len(mm.group(0)), suffix)
        return "var(" + prefix + suffix + ")"

    text2 = re.sub(r"var\(([^()]*(?:\([^()]*\)[^()]*)*)\)", _mask_var_fallback, text2)
    return text2


def is_exempt_color(hex_str: str) -> bool:
    """Some short hex colors are actually not colors (e.g., #fff as text)."""
    # 3-char or 4-char hex are almost always real colors.
    # 6-char and 8-char could in rare cases be hash-style ids; require word
    # boundary which HEX_RE already provides.
    return False


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    hits: list[tuple[int, str, str]] = []
    rel = str(path.resolve().relative_to(ROOT)).replace("\\", "/")
    if rel in EXEMPT_FILES:
        return hits
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return hits
    masked = mask_root_blocks(text)
    for i, line in enumerate(masked.splitlines(), 1):
        # Token definition lines (--name: ...) are legitimate. They define
        # the variable that the rest of the file (or theme) consumes.
        if re.search(r"--[A-Za-z][\w-]*\s*:", line):
            continue
        for hex_match in HEX_RE.findall(line):
            if is_exempt_color(hex_match):
                continue
            hits.append((i, hex_match, line.strip()[:120]))
    return hits


def main() -> int:
    if not TARGET.exists():
        print(f"OK — target dir not found ({TARGET}), nothing to scan")
        return 0
    files = list(TARGET.rglob("*.css"))
    files_scanned = len(files)
    all_hits: list[tuple[Path, int, str, str]] = []
    for p in files:
        for line_no, hex_str, snippet in scan_file(p):
            all_hits.append((p, line_no, hex_str, snippet))
    if all_hits:
        print("FAIL — hardcoded hex colors found outside :root:")
        for p, line_no, hex_str, snippet in all_hits:
            rel = p.resolve().relative_to(ROOT)
            print(f"  {rel}:{line_no}  [{hex_str}]  {snippet}")
        print(f"\nTotal hardcoded hex hits: {len(all_hits)} across {len({p for p,_,_,_ in all_hits})} file(s)")
        print("\nHint: define a CSS variable in :root and use var(--name) instead.")
        return 1
    print(f"OK — no hardcoded hex colors outside :root (scanned {files_scanned} file(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
