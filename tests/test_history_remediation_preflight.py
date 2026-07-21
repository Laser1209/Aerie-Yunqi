from __future__ import annotations

from types import SimpleNamespace


def test_history_preflight_collects_read_only_release_blocker(monkeypatch):
    from tools import history_remediation_preflight as preflight
    from tools.scan_provider_key_patterns import Finding

    monkeypatch.setattr(
        preflight,
        "_git_lines",
        lambda *args, **kwargs: {
            ("rev-parse", "HEAD"): ["abcdef1234567890"],
            ("rev-parse", "--abbrev-ref", "HEAD"): ["Aerie-Model-X"],
            ("diff", "--cached", "--name-status", "--"): [],
            ("diff", "--name-status", "--"): [],
            ("ls-files", "--others", "--exclude-standard"): [],
            ("remote", "-v"): [],
        }.get(args, []),
    )
    monkeypatch.setattr(preflight.scanner, "scan_workspace", lambda: ([], {"files_scanned": 7}))
    monkeypatch.setattr(
        preflight.scanner,
        "scan_history",
        lambda: (
            [
                Finding(
                    scope="history",
                    pattern="openai_like_sk",
                    path="old/.env.example",
                    commit="abc123def456",
                    snippet="TOKEN=<REDACTED:openai_like_sk>",
                )
            ],
            {"commits_scanned": 1, "unconfirmed_git_pickaxe_commits": 0},
        ),
    )

    report = preflight.build_report(include_history=True)

    assert report["mode"] == "read_only_preflight"
    assert report["git"]["clean"] is True
    assert report["git"]["has_remote"] is False
    assert report["history"]["finding_count"] == 1
    assert report["authorization"]["history_rewrite_allowed"] is False
    assert report["release_gate"]["can_close_credential_history_gate"] is False
    assert any("Rotate" in item for item in report["required_user_actions"])
    assert all("force push" not in item.lower() for item in report["pre_authorization_commands"])


def test_history_preflight_blocks_high_risk_runtime_paths(monkeypatch):
    from tools import history_remediation_preflight as preflight

    monkeypatch.setattr(
        preflight,
        "_git_state",
        lambda: {
            "head": "abcdef1234567890",
            "head_short": "abcdef1",
            "branch": "Aerie-Model-X",
            "clean": True,
            "dirty_entries": [],
            "remote_names": ["origin"],
            "has_remote": True,
        },
    )
    monkeypatch.setattr(preflight.scanner, "scan_workspace", lambda: ([], {"files_scanned": 7}))
    monkeypatch.setattr(preflight.scanner, "scan_history", lambda: ([], {"commits_scanned": 3}))
    monkeypatch.setattr(preflight, "_history_high_risk_paths", lambda: ["logs/verify_bridge.ps1"])

    report = preflight.build_report(include_history=True)

    assert report["history"]["finding_count"] == 0
    assert report["history"]["high_risk_path_count"] == 1
    assert report["release_gate"]["can_close_credential_history_gate"] is False
    assert report["release_gate"]["reason"] == "high-risk runtime paths remain in git history"
    assert any("runtime paths" in item for item in report["required_user_actions"])


def test_high_risk_history_path_classifier():
    from tools import history_remediation_preflight as preflight

    blocked = [
        "logs/chat_resp.json",
        "uploads/private.png",
        "data/aerie.db-wal",
        "data/world.sqlite3-shm",
        "data/backups/snapshot.json",
        "NapCat/NapCat.Shell/config/napcat.json",
        "electron/dist-win-unpacked/Aerie.exe",
        "Spotlight/public/Aerie Setup.exe",
        ".env",
        "config/.env.local",
    ]
    allowed = [
        ".env.example",
        "documents/logging.md",
        "electron/src/distribution.js",
        "tests/test_database.py",
    ]

    assert all(preflight._is_high_risk_history_path(path) for path in blocked)
    assert not any(preflight._is_high_risk_history_path(path) for path in allowed)


def test_git_state_ignores_status_stat_cache_false_positive(monkeypatch):
    from tools import history_remediation_preflight as preflight

    monkeypatch.setattr(
        preflight,
        "_git_lines",
        lambda *args, **kwargs: {
            ("rev-parse", "HEAD"): ["abcdef1234567890"],
            ("rev-parse", "--abbrev-ref", "HEAD"): ["Aerie-Model-X"],
            ("status", "--porcelain"): [" M core/companion.py"],
            ("diff", "--cached", "--name-status", "--"): [],
            ("diff", "--name-status", "--"): [],
            ("ls-files", "--others", "--exclude-standard"): [],
            ("remote", "-v"): [],
        }.get(args, []),
    )

    state = preflight._git_state()

    assert state["clean"] is True
    assert state["dirty_entries"] == []


def test_git_state_reports_content_and_untracked_changes(monkeypatch):
    from tools import history_remediation_preflight as preflight

    monkeypatch.setattr(
        preflight,
        "_git_lines",
        lambda *args, **kwargs: {
            ("rev-parse", "HEAD"): ["abcdef1234567890"],
            ("rev-parse", "--abbrev-ref", "HEAD"): ["Aerie-Model-X"],
            ("diff", "--cached", "--name-status", "--"): ["M\tstaged.py"],
            ("diff", "--name-status", "--"): ["M\tworking.py"],
            ("ls-files", "--others", "--exclude-standard"): ["new.txt"],
            ("remote", "-v"): ["origin https://example.invalid/repo.git (fetch)"],
        }.get(args, []),
    )

    state = preflight._git_state()

    assert state["clean"] is False
    assert state["dirty_entries"] == [
        "staged:M\tstaged.py",
        "unstaged:M\tworking.py",
        "untracked:new.txt",
    ]


def test_history_preflight_exit_code_blocks_when_history_findings(monkeypatch, capsys):
    from tools import history_remediation_preflight as preflight

    monkeypatch.setattr(
        preflight,
        "build_report",
        lambda *, include_history: {
            "git": {"clean": True},
            "history": {"finding_count": 2 if include_history else 0},
            "workspace": {"finding_count": 0},
            "release_gate": {"can_close_credential_history_gate": False},
        },
    )

    rc = preflight.main(["--json"])

    assert rc == 1
    out = capsys.readouterr().out
    assert '"can_close_credential_history_gate": false' in out


def test_history_preflight_fails_closed_for_unconfirmed_pickaxe_candidates(monkeypatch):
    from tools import history_remediation_preflight as preflight

    monkeypatch.setattr(
        preflight,
        "_git_state",
        lambda: {
            "head": "abcdef1234567890",
            "head_short": "abcdef1",
            "branch": "Aerie-Model-X",
            "clean": True,
            "dirty_entries": [],
            "remote_names": ["origin"],
            "has_remote": True,
        },
    )
    monkeypatch.setattr(preflight.scanner, "scan_workspace", lambda: ([], {"files_scanned": 7}))
    monkeypatch.setattr(
        preflight.scanner,
        "scan_history",
        lambda: (
            [],
            {"commits_scanned": 1, "unconfirmed_git_pickaxe_commits": 1},
        ),
    )
    monkeypatch.setattr(preflight, "_history_high_risk_paths", lambda: [])

    report = preflight.build_report(include_history=True)

    assert report["history"]["finding_count"] == 0
    assert report["history"]["stats"]["unconfirmed_git_pickaxe_commits"] == 1
    assert report["release_gate"]["can_close_credential_history_gate"] is False
    assert "unconfirmed" in report["release_gate"]["reason"]
    assert any("unconfirmed" in item.lower() for item in report["required_user_actions"])


def test_history_preflight_cannot_close_when_history_scan_is_skipped(monkeypatch):
    from tools import history_remediation_preflight as preflight

    monkeypatch.setattr(
        preflight,
        "_git_state",
        lambda: {
            "head": "abcdef1234567890",
            "head_short": "abcdef1",
            "branch": "Aerie-Model-X",
            "clean": True,
            "dirty_entries": [],
            "remote_names": ["origin"],
            "has_remote": True,
        },
    )
    monkeypatch.setattr(preflight.scanner, "scan_workspace", lambda: ([], {"files_scanned": 7}))

    report = preflight.build_report(include_history=False)

    assert report["history"]["stats"]["skipped"] == 1
    assert report["release_gate"]["can_close_credential_history_gate"] is False
    assert "skipped" in report["release_gate"]["reason"]
    assert any("history scan" in item.lower() for item in report["required_user_actions"])


def test_history_preflight_cannot_close_when_workspace_files_are_unreadable(monkeypatch):
    from tools import history_remediation_preflight as preflight

    monkeypatch.setattr(
        preflight,
        "_git_state",
        lambda: {
            "head": "abcdef1234567890",
            "head_short": "abcdef1",
            "branch": "Aerie-Model-X",
            "clean": True,
            "dirty_entries": [],
            "remote_names": ["origin"],
            "has_remote": True,
        },
    )
    monkeypatch.setattr(
        preflight.scanner,
        "scan_workspace",
        lambda: ([], {"files_scanned": 6, "files_skipped": 1, "read_errors": 1}),
    )
    monkeypatch.setattr(
        preflight.scanner,
        "scan_history",
        lambda: ([], {"commits_scanned": 0, "unconfirmed_git_pickaxe_commits": 0}),
    )
    monkeypatch.setattr(preflight, "_history_high_risk_paths", lambda: [])

    report = preflight.build_report(include_history=True)

    assert report["release_gate"]["can_close_credential_history_gate"] is False
    assert "unreadable" in report["release_gate"]["reason"]
    assert any("unreadable" in item.lower() for item in report["required_user_actions"])
