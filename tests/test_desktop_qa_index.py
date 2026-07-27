from __future__ import annotations

from tools.generate_desktop_qa_index import generate


def test_generate_desktop_qa_index_hashes_files_and_passes_redaction(tmp_path):
    (tmp_path / "result.json").write_text('{"status":"passed"}', encoding="utf-8")

    result = generate(tmp_path)

    assert result["file_count"] == 1
    assert result["redaction_status"] == "passed"
    assert (tmp_path / "index.json").exists()
    assert "result.json" in (tmp_path / "sha256sum.txt").read_text(encoding="utf-8")


def test_generate_desktop_qa_index_fails_closed_on_secret_or_user_path(tmp_path):
    (tmp_path / "console.log").write_text(
        "TOKEN=super-secret-value\nC:\\Users\\Private\\document.txt",
        encoding="utf-8",
    )

    result = generate(tmp_path)

    assert result["redaction_status"] == "failed"
    assert result["violations"][0]["path"] == "console.log"
