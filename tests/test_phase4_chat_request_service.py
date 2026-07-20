def test_ready_attachment_fixture_contains_only_server_metadata(
    ready_attachment,
):
    assert ready_attachment["state"] == "ready"
    assert ready_attachment["url"].startswith(
        "/uploads/"
    )
    assert ready_attachment["name"]
    assert ready_attachment["size"] > 0
    assert ready_attachment["type"]
    assert "path" not in ready_attachment
    assert "content" not in ready_attachment
