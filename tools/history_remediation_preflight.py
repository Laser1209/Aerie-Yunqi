"""Read-only preflight for the credential-history release blocker.

This helper intentionally does not rewrite git history, delete files, rotate
keys, push, or force push.  It only gathers current git state plus redacted
provider-key and high-risk runtime-path summaries so the user can decide
whether to authorize the destructive remediation plan documented in
AI_Vibe_Coding/95.

Exit codes:
  0  preflight is clean enough to close the credential-history gate
  1  release gate remains blocked or the worktree is not ready
  2  preflight runtime error
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import scan_provider_key_patterns as scanner


_HIGH_RISK_HISTORY_PREFIXES = (
    "logs/",
    "uploads/",
    "data/backups/",
    "data/audit/",
    "data/world_sidecar/",
    "napcat/napcat.shell/config/",
    "napcat/napcat.shell/cache/",
)
_HIGH_RISK_DATABASE_SUFFIXES = (
    ".db",
    ".db-journal",
    ".db-shm",
    ".db-wal",
    ".sqlite",
    ".sqlite-journal",
    ".sqlite-shm",
    ".sqlite-wal",
    ".sqlite3",
    ".sqlite3-journal",
    ".sqlite3-shm",
    ".sqlite3-wal",
)


def _git_lines(*args: str, timeout: int = 30) -> list[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout,
    )
    if proc.returncode not in (0, 1):
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return [line.rstrip("\n") for line in proc.stdout.splitlines()]


def _is_high_risk_history_path(path: str) -> bool:
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    lowered = normalized.casefold()
    if not lowered:
        return False
    filename = lowered.rsplit("/", 1)[-1]
    if lowered.startswith(_HIGH_RISK_HISTORY_PREFIXES):
        return True
    if filename == ".env" or (filename.startswith(".env.") and not filename.endswith(".example")):
        return True
    if lowered.endswith(_HIGH_RISK_DATABASE_SUFFIXES):
        return True
    if lowered == "electron/dist" or lowered.startswith("electron/dist/"):
        return True
    if lowered.startswith("electron/dist-") or lowered.startswith("electron/dist_"):
        return True
    return lowered.startswith("spotlight/public/") and lowered.endswith((".exe", ".blockmap"))


def _history_high_risk_paths() -> list[str]:
    historical_paths = _git_lines(
        "-c",
        "core.quotepath=false",
        "log",
        "--all",
        "--format=",
        "--name-only",
        "--",
        timeout=120,
    )
    return sorted({path for path in historical_paths if _is_high_risk_history_path(path)})


def _git_state() -> dict[str, Any]:
    head = _first(_git_lines("rev-parse", "HEAD"), "")
    branch = _first(_git_lines("rev-parse", "--abbrev-ref", "HEAD"), "")
    staged = [
        f"staged:{line}"
        for line in _git_lines("diff", "--cached", "--name-status", "--")
        if line.strip()
    ]
    unstaged = [
        f"unstaged:{line}"
        for line in _git_lines("diff", "--name-status", "--")
        if line.strip()
    ]
    untracked = [
        f"untracked:{line}"
        for line in _git_lines("ls-files", "--others", "--exclude-standard")
        if line.strip()
    ]
    dirty_entries = [*staged, *unstaged, *untracked]
    remotes = _git_lines("remote", "-v")
    remote_names = sorted({line.split()[0] for line in remotes if line.split()})
    return {
        "head": head,
        "head_short": head[:7] if head else "",
        "branch": branch,
        "clean": not dirty_entries,
        "dirty_entries": dirty_entries,
        "remote_names": remote_names,
        "has_remote": bool(remote_names),
    }


def _scan_summary(findings: list[scanner.Finding], stats: dict[str, int]) -> dict[str, Any]:
    paths = sorted({scanner.redact_text(finding.path) for finding in findings})
    patterns = sorted({finding.pattern for finding in findings})
    commits = sorted({finding.commit[:12] for finding in findings if finding.commit})
    samples = [
        {
            "scope": finding.scope,
            "pattern": finding.pattern,
            "path": scanner.redact_text(finding.path),
            "commit": finding.commit[:12] if finding.commit else None,
            "line": finding.line,
            "snippet": scanner.redact_text(finding.snippet) if finding.snippet else None,
        }
        for finding in findings[:10]
    ]
    return {
        "finding_count": len(findings),
        "patterns": patterns,
        "paths": paths,
        "commits": commits,
        "stats": stats,
        "redacted_samples": samples,
    }


def build_report(*, include_history: bool = True) -> dict[str, Any]:
    git = _git_state()
    workspace_findings, workspace_stats = scanner.scan_workspace()
    workspace = _scan_summary(workspace_findings, workspace_stats)

    if include_history:
        history_findings, history_stats = scanner.scan_history()
        high_risk_paths = _history_high_risk_paths()
    else:
        history_findings, history_stats = [], {"skipped": 1}
        high_risk_paths = []
    history = _scan_summary(history_findings, history_stats)
    history["high_risk_path_count"] = len(high_risk_paths)
    history["high_risk_paths"] = high_risk_paths
    workspace_read_errors = workspace_stats.get("read_errors", 0)
    unconfirmed_pickaxe_commits = history_stats.get("unconfirmed_git_pickaxe_commits", 0)
    history_scan_skipped = bool(history_stats.get("skipped", 0))

    can_close = (
        git["clean"]
        and workspace["finding_count"] == 0
        and workspace_read_errors == 0
        and not history_scan_skipped
        and history["finding_count"] == 0
        and unconfirmed_pickaxe_commits == 0
        and history["high_risk_path_count"] == 0
    )
    required_user_actions = []
    if workspace_read_errors:
        required_user_actions.append(
            "Resolve all unreadable workspace files and rerun the provider-key scan."
        )
    if history["finding_count"]:
        required_user_actions.append(
            "Rotate or revoke any provider keys that may match the historical findings."
        )
    if history["high_risk_path_count"]:
        required_user_actions.append(
            "Remove high-risk runtime paths from every reachable Git ref before publication."
        )
    if unconfirmed_pickaxe_commits:
        required_user_actions.append(
            "Investigate all unconfirmed Git pickaxe candidates before closing the credential-history gate."
        )
    if history_scan_skipped:
        required_user_actions.append(
            "Run the full history scan before closing the credential-history gate."
        )
    if (
        history["finding_count"]
        or unconfirmed_pickaxe_commits
        or history["high_risk_path_count"]
    ):
        required_user_actions.append(
            "Explicitly authorize Git history rewrite rehearsal and cleanup before execution."
        )
    if not git["has_remote"]:
        required_user_actions.append("Configure a Git remote before uploading cleanup results, or confirm local-only closure.")
    if not git["clean"]:
        required_user_actions.append("Commit, stash, or revert working tree changes before rewrite rehearsal.")

    return {
        "mode": "read_only_preflight",
        "git": git,
        "workspace": workspace,
        "history": history,
        "authorization": {
            "history_rewrite_allowed": False,
            "force_push_allowed": False,
            "key_rotation_performed": False,
        },
        "release_gate": {
            "can_close_credential_history_gate": can_close,
            "reason": _gate_reason(git, workspace, history),
        },
        "pre_authorization_commands": [
            "python tools\\scan_provider_key_patterns.py",
            "python tools\\scan_provider_key_patterns.py --history",
            "git status --short --branch",
            "git rev-parse HEAD",
            "git bundle create aerie-before-history-clean.bundle --all",
        ],
        "required_user_actions": required_user_actions,
    }


def _gate_reason(
    git: dict[str, Any], workspace: dict[str, Any], history: dict[str, Any]
) -> str:
    if not git["clean"]:
        return "working tree is not clean"
    if workspace["finding_count"]:
        return "provider-key shaped values remain in the current workspace"
    if workspace.get("stats", {}).get("read_errors", 0):
        return "workspace scan has unreadable files"
    if history.get("stats", {}).get("skipped", 0):
        return "git history scan was skipped"
    if history["finding_count"]:
        return "provider-key shaped values remain in git history"
    if history.get("stats", {}).get("unconfirmed_git_pickaxe_commits", 0):
        return "unconfirmed git pickaxe candidates remain in git history"
    if history.get("high_risk_path_count", 0):
        return "high-risk runtime paths remain in git history"
    return "credential history gate can close"


def _first(values: list[str], default: str) -> str:
    return values[0].strip() if values else default


def _print_text(report: dict[str, Any]) -> None:
    print("HISTORY_REMEDIATION_PREFLIGHT read_only=true")
    print(
        "GIT "
        f"branch={report['git'].get('branch', '')} "
        f"head={report['git'].get('head_short', '')} "
        f"clean={str(report['git'].get('clean', False)).lower()} "
        f"has_remote={str(report['git'].get('has_remote', False)).lower()}"
    )
    print(
        "SCAN "
        f"workspace_findings={report['workspace'].get('finding_count', 0)} "
        "workspace_read_errors="
        f"{report['workspace'].get('stats', {}).get('read_errors', 0)} "
        f"history_findings={report['history'].get('finding_count', 0)} "
        "history_scan_skipped="
        f"{report['history'].get('stats', {}).get('skipped', 0)} "
        "history_unconfirmed_pickaxe_commits="
        f"{report['history'].get('stats', {}).get('unconfirmed_git_pickaxe_commits', 0)} "
        f"history_high_risk_paths={report['history'].get('high_risk_path_count', 0)}"
    )
    print(
        "RELEASE_GATE "
        f"can_close={str(report['release_gate'].get('can_close_credential_history_gate', False)).lower()} "
        f"reason={report['release_gate'].get('reason', '')}"
    )
    for action in report.get("required_user_actions", []):
        print(f"USER_ACTION_REQUIRED {action}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="skip the slower git history scan; useful for fast workspace preflight",
    )
    args = parser.parse_args(argv)

    try:
        report = build_report(include_history=not args.no_history)
    except Exception as exc:
        print(f"HISTORY_REMEDIATION_PREFLIGHT_ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_text(report)

    return 0 if report["release_gate"]["can_close_credential_history_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
