"""Generate a redacted manifest and SHA-256 inventory for desktop QA evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


TEXT_SUFFIXES = {".csv", ".json", ".jsonl", ".log", ".md", ".txt"}
FORBIDDEN_PATTERNS = (
    re.compile(r"\b(?:sk|gho|ghp|github_pat)_[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{12,}\b", re.IGNORECASE),
    re.compile(r"\b(?:API_KEY|TOKEN|SECRET)\s*[:=]\s*[^\s\"']{8,}", re.IGNORECASE),
    re.compile(r"C:\\Users\\[^\\\s]+\\", re.IGNORECASE),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scan_text(path: Path) -> list[str]:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ["unreadable"]
    return [pattern.pattern for pattern in FORBIDDEN_PATTERNS if pattern.search(text)]


def generate(root: Path) -> dict:
    files = []
    violations = []
    excluded = {"index.json", "sha256sum.txt"}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        hits = scan_text(path)
        if hits:
            violations.append({"path": relative, "patterns": hits})
        files.append({
            "path": relative,
            "size": path.stat().st_size,
            "sha256": sha256(path),
        })
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "file_count": len(files),
        "redaction_status": "failed" if violations else "passed",
        "violations": violations,
        "files": files,
    }
    (root / "index.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "sha256sum.txt").write_text(
        "".join(f"{item['sha256']}  {item['path']}\n" for item in files),
        encoding="utf-8",
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        parser.error(f"evidence root does not exist: {root}")
    payload = generate(root)
    print(json.dumps({
        "file_count": payload["file_count"],
        "redaction_status": payload["redaction_status"],
    }))
    return 1 if payload["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
