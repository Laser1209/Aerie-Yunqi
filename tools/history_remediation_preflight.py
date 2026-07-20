"""Read-only preflight for the credential-history release blocker.

This helper intentionally does not rewrite git history, delete files, rotate
keys, push, or force push.  It only gathers current git state plus redacted
provider-key scan summaries so the user can decide whether to authorize the
destructive remediation plan documented in AI_Vibe_Coding/95.

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
    paths = sorted({finding.path for finding in findings})
    patterns = sorted({finding.pattern for finding in findings})
    commits = sorted({finding.commit[:12] for finding in findings if finding.commit})
    samples = [
        {
            "scope": finding.scope,
            "pattern": finding.pattern,
            "path": finding.path,
            "commit": finding.commit[:12] if finding.commit else None,
            "line": finding.line,
            "snippet": finding.snippet,
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
    else:
        history_findings, history_stats = [], {"skipped": 1}
    history = _scan_summary(history_findings, history_stats)

    can_close = git["clean"] and workspace["finding_count"] == 0 and history["finding_count"] == 0
    required_user_actions = []
    if history["finding_count"]:
        required_user_actions.extend(
            [
                "Rotate or revoke any provider keys that may match the historical findings.",
                "Explicitly authorize Git history rewrite rehearsal and cleanup before execution.",
            ]
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
    if history["finding_count"]:
        return "provider-key shaped values remain in git history"
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
        f"history_findings={report['history'].get('finding_count', 0)}"
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
