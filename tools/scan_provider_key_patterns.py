"""Scan workspace and git history for provider-key shaped secrets.

This release helper is intentionally conservative and redacted:

* it never prints matched secret values;
* workspace scans skip binary/runtime/vendor directories;
* history scans report commit, path, pattern type, and redacted snippets only.

Exit codes:
  0  no provider-key shaped matches found in the selected scope
  1  matches found; review/rotate/clean before closing the release gate
  2  scanner/runtime error
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

WORKSPACE_ROOTS = (
    "documents",
    "logs",
    "tmp",
    "config",
    "core",
    "electron/src",
    "tools",
    "tests",
)

EXCLUDED_PARTS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    "dist",
    "dist-final",
    "build",
    "out",
}

BINARY_SUFFIXES = {
    ".asar",
    ".db",
    ".dll",
    ".exe",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".mp3",
    ".mp4",
    ".png",
    ".pyc",
    ".sqlite",
    ".wav",
    ".webp",
}


PATTERNS: dict[str, re.Pattern[str]] = {
    "openai_like_sk": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b", re.IGNORECASE),
    "github_pat": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b", re.IGNORECASE),
    "github_ghp": re.compile(r"\bghp_[A-Za-z0-9]{20,}\b", re.IGNORECASE),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b", re.IGNORECASE),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b", re.IGNORECASE),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b", re.IGNORECASE),
}

# Git's pickaxe regex is not Python's ``re``.  Keep it POSIX-ERE-shaped and
# use Python's stricter patterns for final confirmation/redaction.
GIT_COMBINED_PATTERN = (
    "sk-[A-Za-z0-9_-]{20,}"
    "|github_pat_[A-Za-z0-9_]{20,}"
    "|ghp_[A-Za-z0-9]{20,}"
    "|AKIA[0-9A-Z]{16}"
    "|AIza[0-9A-Za-z_-]{30,}"
    "|xox[baprs]-[A-Za-z0-9-]{20,}"
)


@dataclass(frozen=True)
class Finding:
    scope: str
    pattern: str
    path: str
    line: int | None = None
    commit: str | None = None
    snippet: str | None = None


def _redact(line: str) -> tuple[str, list[str]]:
    labels: list[str] = []
    redacted = line
    for name, pattern in PATTERNS.items():
        if pattern.search(redacted):
            labels.append(name)
            redacted = pattern.sub(f"<REDACTED:{name}>", redacted)
    return redacted, labels


def _clip(text: str, limit: int = 180) -> str:
    text = " ".join(text.strip().split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _iter_workspace_files() -> tuple[list[Path], int]:
    files: list[Path] = []
    skipped = 0
    for rel_root in WORKSPACE_ROOTS:
        base = ROOT / rel_root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel_parts = set(path.relative_to(ROOT).parts)
            if rel_parts & EXCLUDED_PARTS:
                skipped += 1
                continue
            if path.suffix.lower() in BINARY_SUFFIXES:
                skipped += 1
                continue
            files.append(path)
    return files, skipped


def scan_workspace() -> tuple[list[Finding], dict[str, int]]:
    findings: list[Finding] = []
    files, skipped = _iter_workspace_files()
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            skipped += 1
            continue
        rel = path.relative_to(ROOT).as_posix()
        for line_no, line in enumerate(text.splitlines(), 1):
            redacted, labels = _redact(line)
            for label in labels:
                findings.append(
                    Finding(
                        scope="workspace",
                        pattern=label,
                        path=rel,
                        line=line_no,
                        snippet=_clip(redacted),
                    )
                )
    return findings, {"files_scanned": len(files), "files_skipped": skipped}


def _git(*args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout,
    )


def _history_candidate_commits() -> list[str]:
    proc = _git(
        "log",
        "--all",
        "--regexp-ignore-case",
        "-G",
        GIT_COMBINED_PATTERN,
        "--format=%H",
        timeout=180,
    )
    if proc.returncode not in (0, 1):
        raise RuntimeError(proc.stderr.strip() or "git log failed")
    seen: set[str] = set()
    commits: list[str] = []
    for line in proc.stdout.splitlines():
        commit = line.strip()
        if commit and commit not in seen:
            seen.add(commit)
            commits.append(commit)
    return commits


def scan_history() -> tuple[list[Finding], dict[str, int]]:
    commits = _history_candidate_commits()
    findings: list[Finding] = []
    commits_with_text_hit: set[str] = set()

    for commit in commits:
        proc = _git(
            "show",
            "--text",
            "--format=",
            "--unified=0",
            "--no-ext-diff",
            commit,
            timeout=120,
        )
        if proc.returncode != 0:
            continue
        current_file = ""
        for line in proc.stdout.splitlines():
            if line.startswith("+++ b/") or line.startswith("--- a/"):
                current_file = line[6:]
                continue
            if not line.startswith(("+", "-")) or line.startswith(("+++", "---")):
                continue
            redacted, labels = _redact(line)
            if not labels:
                continue
            commits_with_text_hit.add(commit)
            for label in labels:
                findings.append(
                    Finding(
                        scope="history",
                        pattern=label,
                        path=current_file or "<unknown>",
                        commit=commit,
                        snippet=_clip(redacted),
                    )
                )

    unconfirmed = len([commit for commit in commits if commit not in commits_with_text_hit])
    return findings, {
        "commits_scanned": len(commits),
        "unconfirmed_git_pickaxe_commits": unconfirmed,
    }


def _print_findings(findings: list[Finding]) -> None:
    by_scope: dict[str, int] = {}
    for finding in findings:
        by_scope[finding.scope] = by_scope.get(finding.scope, 0) + 1
    print("PROVIDER_KEY_SCAN_FINDINGS " + " ".join(f"{k}={v}" for k, v in sorted(by_scope.items())))
    for finding in findings:
        loc = finding.path
        if finding.line is not None:
            loc += f":{finding.line}"
        prefix = f"{finding.scope} pattern={finding.pattern} path={loc}"
        if finding.commit:
            prefix += f" commit={finding.commit[:12]}"
        print(prefix)
        if finding.snippet:
            print(f"  snippet={finding.snippet}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--history",
        action="store_true",
        help="also scan git history diffs; can be slower and may require remediation",
    )
    parser.add_argument(
        "--workspace-only",
        action="store_true",
        help="scan only the current workspace, even if --history is present",
    )
    args = parser.parse_args(argv)

    findings: list[Finding] = []
    try:
        workspace_findings, workspace_stats = scan_workspace()
        findings.extend(workspace_findings)
        print(
            "WORKSPACE_SCAN "
            + " ".join(f"{key}={value}" for key, value in sorted(workspace_stats.items()))
        )

        if args.history and not args.workspace_only:
            history_findings, history_stats = scan_history()
            findings.extend(history_findings)
            print(
                "HISTORY_SCAN "
                + " ".join(f"{key}={value}" for key, value in sorted(history_stats.items()))
            )
    except Exception as exc:
        print(f"PROVIDER_KEY_SCAN_ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if findings:
        _print_findings(findings)
        return 1
    print("PROVIDER_KEY_SCAN_OK no provider-key shaped matches in selected scope")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
