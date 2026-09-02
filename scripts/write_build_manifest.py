"""Write reproducible, non-sensitive metadata for an Electron build."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def git_commit() -> str:
    try:
        value = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).decode("ascii", errors="ignore").strip()
        return value or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def sha256_tree(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    for file_path in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(file_path.relative_to(path).as_posix().encode("utf-8"))
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "build-manifest.json")
    args = parser.parse_args()
    package = json.loads((ROOT / "electron" / "package.json").read_text(encoding="utf-8"))
    runtime = ROOT / "electron" / "runtime-build-vfix"
    value = {
        "schema": 1,
        "app": "Aerie",
        "version": str(package.get("version") or "unknown"),
        "git_commit": git_commit(),
        "runtime_sha256": sha256_tree(runtime),
        "built_at": datetime.now(timezone.utc).isoformat(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[manifest] wrote {args.out} (runtime_sha256={value['runtime_sha256'] or 'missing'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
