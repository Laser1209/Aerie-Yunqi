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
import base64
import binascii
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
    ".codex-deploy-aerie-spotlight",
    ".codex-temp",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "android-client",
    "node_modules",
    "dist",
    "dist-final",
    "build",
    "out",
    "Spotlight",
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
    "openai_like_sk": re.compile(r"sk-[A-Za-z0-9_-]{20,}", re.IGNORECASE),
    "github_pat": re.compile(r"github_pat_[A-Za-z0-9_]{20,}", re.IGNORECASE),
    "github_ghp": re.compile(r"ghp_[A-Za-z0-9]{20,}", re.IGNORECASE),
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}", re.IGNORECASE),
    "google_api_key": re.compile(r"AIza[0-9A-Za-z_-]{30,}", re.IGNORECASE),
    "slack_token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}", re.IGNORECASE),
}

_DATA_IMAGE_BASE64_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_+.-])data:image/[A-Za-z0-9.+-]+"
    r"(?:;[A-Za-z0-9.+-]+=[^;,\s\"']+)*"
    r";base64,(?P<payload>[A-Za-z0-9+/]*={0,2})(?=$|[\s\"'()<>])",
    re.IGNORECASE,
)
_MIN_VERIFIED_DATA_URI_PAYLOAD = 256

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


def _redact_patterns(text: str) -> tuple[str, list[str]]:
    labels: list[str] = []
    redacted = text
    for name, pattern in PATTERNS.items():
        if pattern.search(redacted):
            labels.append(name)
            redacted = pattern.sub(f"<REDACTED:{name}>", redacted)
    return redacted, labels


def _mask_verified_image_data_uris(text: str) -> tuple[str, list[str]]:
    ignored_labels: list[str] = []

    def replace(match: re.Match[str]) -> str:
        payload = match.group("payload")
        if (
            len(payload) < _MIN_VERIFIED_DATA_URI_PAYLOAD
            or len(payload) % 4 != 0
        ):
            return match.group(0)
        try:
            base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError):
            return match.group(0)
        _, labels = _redact_patterns(payload)
        ignored_labels.extend(labels)
        prefix_length = match.start("payload") - match.start()
        return match.group(0)[:prefix_length] + "<IGNORED:verified_image_data_uri>"

    return _DATA_IMAGE_BASE64_PATTERN.sub(replace, text), ignored_labels


def _redact_with_ignored(line: str) -> tuple[str, list[str], list[str]]:
    masked, ignored_labels = _mask_verified_image_data_uris(line)
    redacted, labels = _redact_patterns(masked)
    return redacted, labels, ignored_labels


def _redact(line: str) -> tuple[str, list[str]]:
    redacted, labels, _ = _redact_with_ignored(line)
    return redacted, labels


def redact_text(text: str) -> str:
    """Return provider-key-shaped text with all known patterns removed."""
    return _redact(text)[0]


def _clip(text: str, limit: int = 180) -> str:
    text = " ".join(text.strip().split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _iter_workspace_files() -> tuple[list[Path], int]:
    candidates: list[Path] = []
    if (ROOT / ".git").exists():
        proc = _git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "git ls-files failed")
        for rel in proc.stdout.split("\0"):
            if not rel:
                continue
            rel_path = Path(rel)
            if rel_path.is_absolute() or ".." in rel_path.parts:
                raise RuntimeError("git ls-files returned a path outside the workspace")
            candidates.append(ROOT / rel_path)
    else:
        candidates.extend(path for path in ROOT.glob(".env*") if path.is_file())
        for rel_root in WORKSPACE_ROOTS:
            base = ROOT / rel_root
            if not base.exists():
                continue
            candidates.extend(path for path in base.rglob("*") if path.is_file())

    files: list[Path] = []
    skipped = 0
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if not path.is_file():
            skipped += 1
            continue
        rel_parts = set(path.relative_to(ROOT).parts)
        if rel_parts & EXCLUDED_PARTS:
            skipped += 1
            continue
        filename = path.name.casefold()
        if filename == ".env" or (
            filename.startswith(".env.") and filename != ".env.example"
        ):
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
    files_scanned = 0
    ignored_data_uri_matches = 0
    read_errors = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            read_errors += 1
            continue
        files_scanned += 1
        rel = path.relative_to(ROOT).as_posix()
        for line_no, line in enumerate(text.splitlines(), 1):
            redacted, labels, ignored_labels = _redact_with_ignored(line)
            ignored_data_uri_matches += len(ignored_labels)
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
    return findings, {
        "files_scanned": files_scanned,
        "files_skipped": skipped,
        "ignored_data_uri_matches": ignored_data_uri_matches,
        "read_errors": read_errors,
    }


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


def _decode_git_quoted_path(value: str) -> str:
    if len(value) < 2 or not (value.startswith('"') and value.endswith('"')):
        return value

    value = value[1:-1]
    decoded: list[str] = []
    octets = bytearray()

    def flush_octets() -> None:
        if octets:
            decoded.append(octets.decode("utf-8", errors="replace"))
            octets.clear()

    escapes = {
        "a": "\a",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
        "\\": "\\",
        '"': '"',
    }
    index = 0
    while index < len(value):
        if value[index] != "\\":
            flush_octets()
            decoded.append(value[index])
            index += 1
            continue
        if index + 3 < len(value) and all(
            char in "01234567" for char in value[index + 1 : index + 4]
        ):
            octets.append(int(value[index + 1 : index + 4], 8))
            index += 4
            continue
        flush_octets()
        if index + 1 < len(value):
            decoded.append(escapes.get(value[index + 1], value[index + 1]))
            index += 2
        else:
            decoded.append("\\")
            index += 1
    flush_octets()
    return "".join(decoded)


def _diff_marker_path(line: str) -> str | None:
    if not line.startswith(("+++ ", "--- ")):
        return None
    path = _decode_git_quoted_path(line[4:].strip())
    if path == "/dev/null":
        return None
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path or None


def scan_history() -> tuple[list[Finding], dict[str, int]]:
    commits = _history_candidate_commits()
    findings: list[Finding] = []
    commits_with_text_hit: set[str] = set()
    commits_with_ignored_data_uri_hit: set[str] = set()
    ignored_data_uri_matches = 0

    for commit in commits:
        proc = _git(
            "-c",
            "core.quotepath=false",
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
        in_hunk = False
        for line in proc.stdout.splitlines():
            if line.startswith(("diff --git ", "diff --cc ", "diff --combined ")):
                current_file = ""
                in_hunk = False
                continue
            if line.startswith("@@"):
                in_hunk = True
                continue
            if not in_hunk:
                marker_path = _diff_marker_path(line)
                if marker_path is not None:
                    current_file = marker_path
                continue
            if not line.startswith(("+", "-")):
                continue
            redacted, labels, ignored_labels = _redact_with_ignored(line)
            if ignored_labels:
                commits_with_ignored_data_uri_hit.add(commit)
                ignored_data_uri_matches += len(ignored_labels)
            if not labels:
                continue
            commits_with_text_hit.add(commit)
            for label in labels:
                findings.append(
                    Finding(
                        scope="history",
                        pattern=label,
                        path=redact_text(current_file or "<unknown>"),
                        commit=commit,
                        snippet=_clip(redacted),
                    )
                )

    confirmed_commits = commits_with_text_hit | commits_with_ignored_data_uri_hit
    unconfirmed = len([commit for commit in commits if commit not in confirmed_commits])
    return findings, {
        "commits_scanned": len(commits),
        "ignored_data_uri_commits": len(commits_with_ignored_data_uri_hit),
        "ignored_data_uri_matches": ignored_data_uri_matches,
        "unconfirmed_git_pickaxe_commits": unconfirmed,
    }


def _print_findings(findings: list[Finding]) -> None:
    by_scope: dict[str, int] = {}
    for finding in findings:
        by_scope[finding.scope] = by_scope.get(finding.scope, 0) + 1
    print("PROVIDER_KEY_SCAN_FINDINGS " + " ".join(f"{k}={v}" for k, v in sorted(by_scope.items())))
    for finding in findings:
        loc = redact_text(finding.path)
        if finding.line is not None:
            loc += f":{finding.line}"
        prefix = f"{finding.scope} pattern={finding.pattern} path={loc}"
        if finding.commit:
            prefix += f" commit={finding.commit[:12]}"
        print(prefix)
        if finding.snippet:
            print(f"  snippet={_clip(redact_text(finding.snippet))}")


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
    unconfirmed_pickaxe_commits = 0
    workspace_read_errors = 0
    try:
        workspace_findings, workspace_stats = scan_workspace()
        findings.extend(workspace_findings)
        workspace_read_errors = workspace_stats.get("read_errors", 0)
        print(
            "WORKSPACE_SCAN "
            + " ".join(f"{key}={value}" for key, value in sorted(workspace_stats.items()))
        )

        if args.history and not args.workspace_only:
            history_findings, history_stats = scan_history()
            findings.extend(history_findings)
            unconfirmed_pickaxe_commits = history_stats.get(
                "unconfirmed_git_pickaxe_commits", 0
            )
            print(
                "HISTORY_SCAN "
                + " ".join(f"{key}={value}" for key, value in sorted(history_stats.items()))
            )
    except Exception as exc:
        print(f"PROVIDER_KEY_SCAN_ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if findings:
        _print_findings(findings)
    if workspace_read_errors:
        print(
            "PROVIDER_KEY_SCAN_INCONCLUSIVE "
            f"workspace_read_errors={workspace_read_errors}",
            file=sys.stderr,
        )
        return 2
    if findings:
        return 1
    if unconfirmed_pickaxe_commits:
        print(
            "PROVIDER_KEY_SCAN_INCONCLUSIVE "
            f"unconfirmed_git_pickaxe_commits={unconfirmed_pickaxe_commits}"
        )
        return 1
    print("PROVIDER_KEY_SCAN_OK no provider-key shaped matches in selected scope")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
