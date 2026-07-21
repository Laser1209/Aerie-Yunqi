from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


def _synthetic_provider_key() -> str:
    return "".join(("s", "k", "-", "A" * 48))


def _synthetic_image_data_uri_payload() -> str:
    aws_shape = "".join(("A", "K", "I", "A", "B" * 16))
    google_shape = "".join(("A", "I", "z", "a", "C" * 30))
    payload = aws_shape + google_shape
    return payload + "D" * (256 - len(payload))


@pytest.mark.parametrize("prefix", ["Kimi-K3", "ASCII9", "\u4e2d\u6587"])
def test_redact_covers_adjacent_contiguous_provider_key_shapes(prefix):
    from tools import scan_provider_key_patterns as scanner

    token = _synthetic_provider_key()
    raw_candidate = token * 3

    redacted, labels = scanner._redact(prefix + raw_candidate + "\u5c3e\u90e8")

    assert labels == ["openai_like_sk"]
    assert token not in redacted
    assert raw_candidate not in redacted
    assert redacted.startswith(prefix + "<REDACTED:openai_like_sk>")


def test_workspace_skips_local_env_variants_but_scans_env_example(tmp_path, monkeypatch):
    from tools import scan_provider_key_patterns as scanner

    config = tmp_path / "config"
    config.mkdir()
    token = _synthetic_provider_key()
    (config / ".env").write_text("TOKEN=" + token, encoding="utf-8")
    (config / ".env.local").write_text("TOKEN=" + token, encoding="utf-8")
    (config / ".env.example").write_text("TOKEN=" + token, encoding="utf-8")

    monkeypatch.setattr(scanner, "ROOT", tmp_path)
    monkeypatch.setattr(scanner, "WORKSPACE_ROOTS", ("config",))

    findings, stats = scanner.scan_workspace()

    assert [finding.path for finding in findings] == ["config/.env.example"]
    assert stats == {
        "files_scanned": 1,
        "files_skipped": 2,
        "ignored_data_uri_matches": 0,
        "read_errors": 0,
    }
    assert token not in findings[0].snippet


def test_workspace_scans_root_env_example_without_scanning_root_env(tmp_path, monkeypatch):
    from tools import scan_provider_key_patterns as scanner

    token = _synthetic_provider_key()
    (tmp_path / ".env").write_text("TOKEN=" + token, encoding="utf-8")
    (tmp_path / ".env.example").write_text("TOKEN=" + token, encoding="utf-8")

    monkeypatch.setattr(scanner, "ROOT", tmp_path)
    monkeypatch.setattr(scanner, "WORKSPACE_ROOTS", ())

    findings, stats = scanner.scan_workspace()

    assert [finding.path for finding in findings] == [".env.example"]
    assert stats == {
        "files_scanned": 1,
        "files_skipped": 1,
        "ignored_data_uri_matches": 0,
        "read_errors": 0,
    }
    assert token not in findings[0].snippet


def test_workspace_read_errors_are_not_reported_as_a_clean_scan(tmp_path, monkeypatch, capsys):
    from tools import scan_provider_key_patterns as scanner

    config = tmp_path / "config"
    config.mkdir()
    unreadable = config / "unreadable.txt"
    unreadable.write_text("placeholder", encoding="utf-8")
    original_read_text = Path.read_text

    def fail_selected_path(path, *args, **kwargs):
        if path == unreadable:
            raise OSError("synthetic read failure")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(scanner, "ROOT", tmp_path)
    monkeypatch.setattr(scanner, "WORKSPACE_ROOTS", ("config",))
    monkeypatch.setattr(Path, "read_text", fail_selected_path)

    findings, stats = scanner.scan_workspace()

    assert findings == []
    assert stats["read_errors"] == 1

    monkeypatch.setattr(scanner, "scan_workspace", lambda: (findings, stats))
    rc = scanner.main(["--workspace-only"])
    output = capsys.readouterr()

    assert rc == 2
    assert "read_errors=1" in output.out + output.err
    assert "PROVIDER_KEY_SCAN_OK" not in output.out


def test_workspace_scans_git_listed_file_outside_legacy_roots(tmp_path, monkeypatch):
    from tools import scan_provider_key_patterns as scanner

    token = _synthetic_provider_key()
    tracked = tmp_path / "root-level.txt"
    tracked.write_text("TOKEN=" + token, encoding="utf-8")
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(scanner, "ROOT", tmp_path)
    monkeypatch.setattr(scanner, "WORKSPACE_ROOTS", ("config",))
    monkeypatch.setattr(
        scanner,
        "_git",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="root-level.txt\0",
            stderr="",
        ),
    )

    findings, stats = scanner.scan_workspace()

    assert [finding.path for finding in findings] == ["root-level.txt"]
    assert stats == {
        "files_scanned": 1,
        "files_skipped": 0,
        "ignored_data_uri_matches": 0,
        "read_errors": 0,
    }
    assert token not in findings[0].snippet


def test_workspace_ignores_only_verified_image_data_uri_payload(tmp_path, monkeypatch):
    from tools import scan_provider_key_patterns as scanner

    payload = _synthetic_image_data_uri_payload()
    logo = tmp_path / "logo.svg"
    logo.write_text(
        '<image href="data:image/png;base64,' + payload + '"/>',
        encoding="utf-8",
    )
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(scanner, "ROOT", tmp_path)
    monkeypatch.setattr(
        scanner,
        "_git",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="logo.svg\0", stderr=""),
    )

    findings, stats = scanner.scan_workspace()

    assert findings == []
    assert stats["ignored_data_uri_matches"] == 2
    assert stats["read_errors"] == 0


def test_invalid_image_data_uri_suffix_remains_actionable():
    from tools import scan_provider_key_patterns as scanner

    payload = _synthetic_image_data_uri_payload()
    line = 'data:image/png;base64,' + payload + '!'

    _, labels, ignored_labels = scanner._redact_with_ignored(line)

    assert labels == ["aws_access_key", "google_api_key"]
    assert ignored_labels == []


@pytest.mark.parametrize("prefix", ["not", "meta", "x-", "_"])
def test_embedded_data_uri_like_text_remains_actionable(prefix):
    from tools import scan_provider_key_patterns as scanner

    payload = _synthetic_image_data_uri_payload()
    line = prefix + 'data:image/png;base64,' + payload

    _, labels, ignored_labels = scanner._redact_with_ignored(line)

    assert labels == ["aws_access_key", "google_api_key"]
    assert ignored_labels == []


def test_history_attributes_git_quoted_non_ascii_diff_path(monkeypatch):
    from tools import scan_provider_key_patterns as scanner

    token = _synthetic_provider_key()
    path = "documents/\u4e8c\u671f\u5347\u7ea7/\u8ba1\u5212.md"
    quoted_path = "".join(
        chr(byte) if 32 <= byte < 127 and byte not in (34, 92) else f"\\{byte:03o}"
        for byte in path.encode("utf-8")
    )
    patch = "\n".join(
        (
            f'diff --git "a/{quoted_path}" "b/{quoted_path}"',
            f'--- "a/{quoted_path}"',
            f'+++ "b/{quoted_path}"',
            "@@ -0,0 +1 @@",
            "+prefix" + token,
        )
    )
    monkeypatch.setattr(scanner, "_history_candidate_commits", lambda: ["a" * 40])
    monkeypatch.setattr(
        scanner,
        "_git",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=patch, stderr=""),
    )

    findings, stats = scanner.scan_history()

    assert stats == {
        "commits_scanned": 1,
        "ignored_data_uri_commits": 0,
        "ignored_data_uri_matches": 0,
        "unconfirmed_git_pickaxe_commits": 0,
    }
    assert len(findings) == 1
    assert findings[0].path == path
    assert token not in findings[0].snippet


def test_history_does_not_treat_hunk_content_as_a_diff_marker(monkeypatch, capsys):
    from tools import scan_provider_key_patterns as scanner

    token = _synthetic_provider_key()
    patch = "\n".join(
        (
            "diff --git a/safe.md b/safe.md",
            "--- a/safe.md",
            "+++ b/safe.md",
            "@@ -0,0 +1,2 @@",
            "+++ " + token,
            "+value=" + token,
        )
    )
    monkeypatch.setattr(scanner, "_history_candidate_commits", lambda: ["a" * 40])
    monkeypatch.setattr(
        scanner,
        "_git",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=patch, stderr=""),
    )

    findings, stats = scanner.scan_history()
    scanner._print_findings(findings)
    output = capsys.readouterr().out

    assert stats == {
        "commits_scanned": 1,
        "ignored_data_uri_commits": 0,
        "ignored_data_uri_matches": 0,
        "unconfirmed_git_pickaxe_commits": 0,
    }
    assert len(findings) == 2
    assert all(finding.path == "safe.md" for finding in findings)
    assert token not in output


def test_history_classifies_verified_image_data_uri_matches_as_ignored(monkeypatch):
    from tools import scan_provider_key_patterns as scanner

    payload = _synthetic_image_data_uri_payload()
    patch = "\n".join(
        (
            "diff --git a/logo.svg b/logo.svg",
            "--- a/logo.svg",
            "+++ b/logo.svg",
            "@@ -0,0 +1 @@",
            '+<image href="data:image/png;base64,' + payload + '"/>',
        )
    )
    monkeypatch.setattr(scanner, "_history_candidate_commits", lambda: ["a" * 40])
    monkeypatch.setattr(
        scanner,
        "_git",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=patch, stderr=""),
    )

    findings, stats = scanner.scan_history()

    assert findings == []
    assert stats == {
        "commits_scanned": 1,
        "ignored_data_uri_commits": 1,
        "ignored_data_uri_matches": 2,
        "unconfirmed_git_pickaxe_commits": 0,
    }


def test_history_resets_path_for_combined_diff_files(monkeypatch):
    from tools import scan_provider_key_patterns as scanner

    token = _synthetic_provider_key()
    patch = "\n".join(
        (
            "diff --cc first.md",
            "--- a/first.md",
            "+++ b/first.md",
            "@@@ -0,0 -0,0 +1 @@@",
            "+value=" + token,
            "diff --combined second.md",
            "--- a/second.md",
            "+++ b/second.md",
            "@@@ -0,0 -0,0 +1 @@@",
            "+value=" + token,
        )
    )
    monkeypatch.setattr(scanner, "_history_candidate_commits", lambda: ["a" * 40])
    monkeypatch.setattr(
        scanner,
        "_git",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=patch, stderr=""),
    )

    findings, stats = scanner.scan_history()

    assert [finding.path for finding in findings] == ["first.md", "second.md"]
    assert stats["unconfirmed_git_pickaxe_commits"] == 0


def test_print_findings_defensively_redacts_path_and_snippet(capsys):
    from tools import scan_provider_key_patterns as scanner

    token = _synthetic_provider_key()
    scanner._print_findings(
        [
            scanner.Finding(
                scope="history",
                pattern="openai_like_sk",
                path="prefix-" + token,
                commit="a" * 40,
                snippet="value=" + token,
            )
        ]
    )

    output = capsys.readouterr().out

    assert token not in output
    assert "<REDACTED:openai_like_sk>" in output


def test_cli_blocks_on_unconfirmed_git_pickaxe_candidates(monkeypatch, capsys):
    from tools import scan_provider_key_patterns as scanner

    monkeypatch.setattr(scanner, "scan_workspace", lambda: ([], {"files_scanned": 1}))
    monkeypatch.setattr(
        scanner,
        "scan_history",
        lambda: (
            [],
            {"commits_scanned": 1, "unconfirmed_git_pickaxe_commits": 1},
        ),
    )

    rc = scanner.main(["--history"])

    assert rc == 1
    output = capsys.readouterr().out
    assert "unconfirmed_git_pickaxe_commits=1" in output
    assert "PROVIDER_KEY_SCAN_OK" not in output
