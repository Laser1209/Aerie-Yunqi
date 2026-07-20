"""Aerie · 云栖 v0.1.0-beta.1 — Phase 5/9 Upload tests."""

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import core.api_server as api_server
from core.api_server import app


def _png_bytes(size: tuple[int, int] = (8, 6), color=(20, 80, 140)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    return buf.getvalue()


class _FixedIdFactory:
    def __init__(self):
        self.counts = {}

    def __call__(self, prefix):
        current = self.counts.get(prefix, 0) + 1
        self.counts[prefix] = current
        return f"{prefix}_upload_gc_{current}"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def isolated_upload_dir(monkeypatch, tmp_path):
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(api_server, "UPLOAD_DIR", str(upload_dir))
    return upload_dir


class TestUploadAPI:
    def test_upload_types(self, client):
        r = client.get("/api/upload/types")
        assert r.status_code == 200
        data = r.json()
        assert "allowed_types" in data
        assert "max_size_bytes" in data
        assert data["max_size_bytes"] == 20 * 1024 * 1024

    def test_upload_image_legacy_flag_off_keeps_raw_bytes(
        self, client, isolated_upload_dir, monkeypatch
    ):
        monkeypatch.setenv("AERIE_FEATURE_IMAGE_ASSETS_V1", "false")
        # Legacy rollback path must not decode/rewrite image bytes.
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
        assert "sha256" not in data
        assert (isolated_upload_dir / data["saved_as"]).read_bytes() == png_bytes

    def test_upload_image_assets_flag_on_returns_metadata(
        self, client, isolated_upload_dir, monkeypatch
    ):
        monkeypatch.setenv("AERIE_FEATURE_IMAGE_ASSETS_V1", "true")
        png_bytes = _png_bytes(size=(7, 5))
        r = client.post(
            "/api/upload",
            files={"file": ("real.png", png_bytes, "image/png")},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["filename"] == "real.png"
        assert data["saved_as"].endswith(".png")
        assert data["url"].startswith("/uploads/")
        assert data["width"] == 7
        assert data["height"] == 5
        assert data["mime_type"] == "image/png"
        assert len(data["sha256"]) == 64
        assert data["is_image"] is True
        assert data["deduplicated"] is False
        assert data["thumbnail_url"].startswith("/uploads/.image_assets/thumbs/")
        assert (isolated_upload_dir / data["saved_as"]).exists()

        thumb = client.get(data["thumbnail_url"])
        assert thumb.status_code == 200
        assert thumb.headers["content-type"].startswith("image/png")

    def test_upload_image_assets_rejects_invalid_magic(
        self, client, isolated_upload_dir, monkeypatch
    ):
        monkeypatch.setenv("AERIE_FEATURE_IMAGE_ASSETS_V1", "true")
        r = client.post(
            "/api/upload",
            files={"file": ("fake.png", b"not really an image", "image/png")},
        )
        assert r.status_code == 400
        assert "image" in r.json()["error"].lower()

    def test_upload_image_assets_rejects_pixel_bomb_limit(
        self, client, isolated_upload_dir, monkeypatch
    ):
        monkeypatch.setenv("AERIE_FEATURE_IMAGE_ASSETS_V1", "true")
        import core.attachment_handler as attachment_handler

        monkeypatch.setattr(attachment_handler, "_MAX_IMAGE_PIXELS", 10)
        r = client.post(
            "/api/upload",
            files={"file": ("too-many-pixels.png", _png_bytes(size=(4, 4)), "image/png")},
        )
        assert r.status_code == 400
        assert "large" in r.json()["error"].lower()

    def test_upload_image_assets_deduplicates(
        self, client, isolated_upload_dir, monkeypatch
    ):
        monkeypatch.setenv("AERIE_FEATURE_IMAGE_ASSETS_V1", "true")
        png_bytes = _png_bytes(size=(3, 4), color=(200, 20, 60))

        first = client.post(
            "/api/upload",
            files={"file": ("first.png", png_bytes, "image/png")},
        )
        second = client.post(
            "/api/upload",
            files={"file": ("second.png", png_bytes, "image/png")},
        )

        assert first.status_code == 200
        assert second.status_code == 200
        first_data = first.json()
        second_data = second.json()
        assert second_data["deduplicated"] is True
        assert second_data["saved_as"] == first_data["saved_as"]
        assert second_data["duplicate_of"] == first_data["saved_as"]
        assert second_data["sha256"] == first_data["sha256"]

    def test_image_asset_gc_preserves_referenced_and_deletes_orphan(
        self,
        client,
        isolated_upload_dir,
        phase4_db,
        monkeypatch,
    ):
        monkeypatch.setenv("AERIE_FEATURE_IMAGE_ASSETS_V1", "true")

        kept = client.post(
            "/api/upload",
            files={"file": ("kept.png", _png_bytes(size=(4, 4)), "image/png")},
        ).json()
        orphan = client.post(
            "/api/upload",
            files={"file": ("orphan.png", _png_bytes(size=(5, 5), color=(220, 30, 90)), "image/png")},
        ).json()

        from core.chat_request_repository import ChatRequestRepository
        from core.chat_request_service import ChatRequestService
        from core.identity import IdentityRepository

        repository = ChatRequestRepository(phase4_db)
        identity_repository = IdentityRepository(phase4_db)
        service = ChatRequestService(
            repository=repository,
            identity_repository=identity_repository,
            master_user_id_provider=lambda: 7001,
            id_factory=_FixedIdFactory(),
        )
        service.submit(
            text="",
            attachments=[
                {
                    "name": "kept.png",
                    "url": kept["url"].lstrip("/"),
                    "state": "ready",
                    "size": kept["size"],
                    "type": "image",
                    "content_type": kept["mime_type"],
                    "saved_as": kept["saved_as"],
                    "thumbnail_url": kept["thumbnail_url"].lstrip("/"),
                    "sha256": kept["sha256"],
                    "width": kept["width"],
                    "height": kept["height"],
                    "deduplicated": False,
                    "duplicate_of": "",
                    "is_image": True,
                }
            ],
            reply_to_id=0,
            user_id=None,
        )

        monkeypatch.setattr(api_server, "_db", phase4_db)

        dry_run = client.post(
            "/api/upload/gc",
            json={"dry_run": True, "min_age_hours": 0},
        )
        assert dry_run.status_code == 200
        dry_run_data = dry_run.json()
        assert dry_run_data["orphan_count"] == 1
        assert (isolated_upload_dir / kept["saved_as"]).exists()
        assert (isolated_upload_dir / orphan["saved_as"]).exists()

        result = client.post(
            "/api/upload/gc",
            json={"dry_run": False, "min_age_hours": 0},
        )
        assert result.status_code == 200
        result_data = result.json()
        assert result_data["deleted_count"] == 1
        assert (isolated_upload_dir / kept["saved_as"]).exists()
        assert not (isolated_upload_dir / orphan["saved_as"]).exists()

    def test_upload_text(self, client, isolated_upload_dir):
        r = client.post(
            "/api/upload",
            files={"file": ("note.txt", b"hello world", "text/plain")},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert (isolated_upload_dir / data["saved_as"]).read_bytes() == b"hello world"

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
        Path(api_server.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        assert Path(api_server.UPLOAD_DIR).exists()
