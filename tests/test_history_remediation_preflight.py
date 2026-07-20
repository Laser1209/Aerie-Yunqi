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
            ("status", "--porcelain"): [],
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
