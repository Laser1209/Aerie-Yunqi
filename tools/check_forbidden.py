"""Block-5E R6.3 — CI: scan user-facing files for forbidden terms.

Per project_memory.md, the user dislikes being called "主人" (master) and
all direct user-facing references must use "你" (you) since v8.0. The
product concept name "主人哲学" is allowed.

Scope: markdown (docs/user-facing), html (renderer), yaml (config),
       python (prompts/strings).

Exits 0 when no forbidden term is found; non-zero otherwise.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Files to scan (relative to ROOT).
# Excluded by design:
#   - .trae/documents/* (planning/historical docs discuss the rule itself)
#   - tools/* (developer-facing scripts, not user-facing)
#   - e2e_*.py / verify_*.py (test scripts are not user-facing)
#   - tmp/*, .trae/* (workspace scratch)
SCAN_DIRS = [
    ROOT / "electron" / "src" / "renderer",
    ROOT / "config",
    ROOT / "core",
    ROOT / "communication",
]

# File extensions to include
EXTS = {".md", ".html", ".yaml", ".yml", ".py", ".js"}

# Forbidden terms (case-insensitive substring match)
# "主人" is the master prefix; "主人哲学" is the product concept name
# and is allowed in dedicated design docs only (whitelisted below).
FORBIDDEN_TERMS = ["主人", "陛下", "大王", "在下不才", "臣妾", "本王", "孤家", "寡人"]

# Files that are allowed to contain these terms (product concept name
# "主人哲学" appears in design docs and is part of the brand).
WHITELIST_FILES = {
    # Add relative paths here, e.g. ".trae/documents/ita-aerie-companion-spec-plan.md"
}

# Per-file/per-line whitelist (more granular than whole-file).
# Format: { "path/relative": [line_numbers_allowed_to_contain_term] }
# Lines that DECLARE the rule itself are exempt — they are not user-facing.
WHITELIST_LINES: dict[str, list[int]] = {
    "config/persona.yaml": [4, 91, 105, 127],  # rule declarations (forbidden_user_terms / taboo_phrases lists)
}


def iter_files() -> list[Path]:
    out: list[Path] = []
    for target in SCAN_DIRS:
        if not target.exists():
            continue
        if target.is_file():
            if target.suffix in EXTS:
                out.append(target)
            continue
        for p in target.rglob("*"):
            if p.is_file() and p.suffix in EXTS:
                out.append(p)
    return out


def is_whitelisted(rel: str, line_no: int) -> bool:
    if rel in WHITELIST_FILES:
        return True
    allowed_lines = WHITELIST_LINES.get(rel, [])
    return line_no in allowed_lines


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return list of (line_no, term, snippet) hits."""
    hits: list[tuple[int, str, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return hits
    rel = str(path.resolve().relative_to(ROOT)).replace("\\", "/")
    for i, line in enumerate(text.splitlines(), 1):
        if is_whitelisted(rel, i):
            continue
        for term in FORBIDDEN_TERMS:
            if term in line:
                # Skip the phrase "主人哲学" as a product concept name.
                if "主人哲学" in line and term == "主人":
                    # Only allow when the line is dominated by the concept name.
                    if line.count("主人哲学") >= 1 and line.count("主人") == line.count("主人哲学") * 3:
                        continue
                hits.append((i, term, line.strip()[:120]))
    return hits


def main() -> int:
    all_hits: list[tuple[Path, int, str, str]] = []
    files_scanned = 0
    for p in iter_files():
        files_scanned += 1
        for line_no, term, snippet in scan_file(p):
            all_hits.append((p, line_no, term, snippet))
    if all_hits:
        print("FAIL — forbidden user-address terms found:")
        for p, line_no, term, snippet in all_hits:
            rel = p.resolve().relative_to(ROOT)
            print(f"  {rel}:{line_no}  [{term}]  {snippet}")
        print(f"\nTotal forbidden hits: {len(all_hits)} across {len({p for p,_,_,_ in all_hits})} file(s)")
        print("\nHint: use '你' (you) for direct address. '主人哲学' is allowed only as product concept name.")
        return 1
    print(f"OK — no forbidden user-address terms (scanned {files_scanned} file(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
