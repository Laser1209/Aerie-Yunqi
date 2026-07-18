"""Aerie · 云栖 v13.9.8 — Phase 5 Upload tests."""
import pytest
from fastapi.testclient import TestClient
from core.api_server import app, UPLOAD_DIR


@pytest.fixture
def client():
    return TestClient(app)


class TestUploadAPI:
    def test_upload_types(self, client):
        r = client.get("/api/upload/types")
        assert r.status_code == 200
        data = r.json()
        assert "allowed_types" in data
        assert "max_size_bytes" in data
        assert data["max_size_bytes"] == 20 * 1024 * 1024

    def test_upload_image(self, client, tmp_path):
        # Create fake PNG bytes
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        r = client.post(
            "/api/upload",
            files={"file": ("test.png", png_bytes, "image/png")},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["filename"] == "test.png"
        assert data["size"] == len(png_bytes)
        assert data["url"].startswith("/uploads/")
        # Cleanup
        import os
        path = UPLOAD_DIR + "/" + data["saved_as"]
        if os.path.exists(path):
            os.unlink(path)

    def test_upload_text(self, client):
        r = client.post(
            "/api/upload",
            files={"file": ("note.txt", b"hello world", "text/plain")},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        import os
        path = UPLOAD_DIR + "/" + data["saved_as"]
        if os.path.exists(path):
            os.unlink(path)

    def test_upload_unsupported_type(self, client):
        r = client.post(
            "/api/upload",
            files={"file": ("malware.exe", b"MZ\x00\x00", "application/x-msdownload")},
        )
        assert r.status_code == 415
        assert "unsupported type" in r.json()["error"]

    def test_upload_oversize(self, client):
        big = b"x" * (21 * 1024 * 1024)   # 21MB > 20MB cap
        r = client.post(
            "/api/upload",
            files={"file": ("huge.txt", big, "text/plain")},
        )
        assert r.status_code == 413
        assert "too large" in r.json()["error"]

    def test_serve_upload_path_traversal_blocked(self, client):
        r = client.get("/uploads/..%2F..%2Fetc%2Fpasswd")
        assert r.status_code in (400, 404)

    def test_serve_upload_not_found(self, client):
        r = client.get("/uploads/nonexistent.png")
        assert r.status_code == 404


class TestUploadDirectory:
    def test_upload_dir_exists_or_creatable(self):
        from pathlib import Path
        Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        assert Path(UPLOAD_DIR).exists()
