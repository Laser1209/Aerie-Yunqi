"""Persona 三视图（辅助生图参考）三阶段验证。

覆盖三个独立验证轮次：
1. 数据层：persona_manager 三视图读写/删除/隔离/清理
2. API 层：/api/persona/three-view 摘要 / 读取 / 上传 / 删除
3. 生图接入：图生图以 ``three_view:front`` 参考锁定角色外观
"""

from __future__ import annotations

import io
import json
import shutil
import tempfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from core.persona_hub.persona_manager import PersonaManager
from core.image_service import (
    ImageGenerationResult,
    ImageSafetyPolicy,
    ImageWorkflow,
)
import core.persona_hub.persona_manager as _pm


VALID_PERSONA = {
    "id": "test_persona",
    "name": "测试人设",
    "version": "1.0.0",
    "basic": {"name": "测试", "english_name": "Test", "age": 25, "product_name": "Test Product"},
    "personality": {"cores": [{"name": "温柔", "en": "Gentleness", "desc": "..."}], "speech_style": "温柔大方"},
    "relationship": {"user_address_default": "你", "self_reference": "我"},
    "emotion": {"baseline": {"pleasure": 0.1, "arousal": 0.2, "dominance": 0.8}, "thresholds": {}},
    "behavior": {"proactivity_level": 0.75, "default_permission_level": "VIEW_ONLY"},
}


def _png_bytes(size: tuple[int, int] = (6, 4), color=(90, 140, 210)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    return buf.getvalue()


def _jpg_bytes(size: tuple[int, int] = (5, 5), color=(20, 200, 120)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture()
def persona_mgr(tmp_path):
    """一个隔离的 PersonaManager，且作为全局单例注入，供生图接入复用。"""
    mgr = PersonaManager(data_dir=str(tmp_path))
    mgr.create_persona(json.loads(json.dumps(VALID_PERSONA)))
    # 注入单例，使 image_service._resolve_three_view_reference 可访问
    _pm.PersonaManager._instance = mgr
    yield mgr
    _pm.PersonaManager._instance = None


# ── 验证轮 1：数据层 ────────────────────────────────


class TestThreeViewDataLayer:
    def test_save_and_load_png(self, persona_mgr):
        ok, suffix = persona_mgr.save_three_view("test_persona", "front", _png_bytes())
        assert ok is True
        assert suffix == "front.png"
        pair = persona_mgr.load_three_view("test_persona", "front")
        assert pair is not None
        data, mime = pair
        assert mime == "image/png"
        assert data == _png_bytes()

    def test_save_and_load_jpg(self, persona_mgr):
        ok, suffix = persona_mgr.save_three_view("test_persona", "side", _jpg_bytes())
        assert ok is True
        assert suffix == "side.jpg"
        data, mime = persona_mgr.load_three_view("test_persona", "side")
        assert mime == "image/jpeg"
        assert data == _jpg_bytes()

    def test_invalid_view_rejected(self, persona_mgr):
        ok, msg = persona_mgr.save_three_view("test_persona", "top", _png_bytes())
        assert ok is False
        assert "invalid view" in msg

    def test_unsupported_format_rejected(self, persona_mgr):
        ok, msg = persona_mgr.save_three_view(
            "test_persona", "front", b"not an image at all", ext="gif"
        )
        assert ok is False
        assert "unsupported" in msg

    def test_unrecognized_bytes_default_to_png_when_no_ext(self, persona_mgr):
        # 无法嗅探格式且未传 ext 时，按实现约定回退为 png
        ok, suffix = persona_mgr.save_three_view("test_persona", "front", b"not an image at all")
        assert ok is True
        assert suffix == "front.png"
        pair = persona_mgr.load_three_view("test_persona", "front")
        assert pair is not None
        assert pair[1] == "image/png"

    def test_load_missing_returns_none(self, persona_mgr):
        assert persona_mgr.load_three_view("test_persona", "back") is None

    def test_summary_marks_present_and_absent(self, persona_mgr):
        persona_mgr.save_three_view("test_persona", "front", _png_bytes())
        summary = persona_mgr.get_three_view_summary("test_persona")
        assert summary["front"]["present"] is True
        assert summary["front"]["dataurl"].startswith("data:image/png;base64,")
        assert summary["side"]["present"] is False
        assert summary["back"]["present"] is False

    def test_delete_single_view(self, persona_mgr):
        persona_mgr.save_three_view("test_persona", "front", _png_bytes())
        ok, _ = persona_mgr.delete_three_view("test_persona", "front")
        assert ok is True
        assert persona_mgr.load_three_view("test_persona", "front") is None

    def test_delete_all_views_with_star(self, persona_mgr):
        persona_mgr.save_three_view("test_persona", "front", _png_bytes())
        persona_mgr.save_three_view("test_persona", "side", _png_bytes())
        ok, _ = persona_mgr.delete_three_view("test_persona", "*")
        assert ok is True
        assert persona_mgr.load_three_view("test_persona", "front") is None
        assert persona_mgr.load_three_view("test_persona", "side") is None

    def test_persona_isolation(self, persona_mgr):
        persona_mgr.save_three_view("test_persona", "front", _png_bytes(color=(1, 2, 3)))
        # 另一套人设的 front 为空
        assert persona_mgr.load_three_view("yita_default", "front") is None

    def test_re_save_same_view_replaces_old(self, persona_mgr):
        persona_mgr.save_three_view("test_persona", "front", _png_bytes(color=(1, 1, 1)))
        persona_mgr.save_three_view("test_persona", "front", _png_bytes(color=(9, 9, 9)))
        data, _ = persona_mgr.load_three_view("test_persona", "front")
        assert data == _png_bytes(color=(9, 9, 9))

    def test_delete_persona_cleans_three_views(self, persona_mgr):
        persona_mgr.save_three_view("test_persona", "front", _png_bytes())
        ok, _ = persona_mgr.delete_persona("test_persona")
        assert ok is True
        # 目录应被一并清理
        d = persona_mgr._personas_dir / "three_views" / "test_persona"
        assert not d.exists()


# ── 验证轮 2：API 层 ────────────────────────────────


@pytest.fixture()
def client(persona_mgr):
    # api_server 使用模块级单例 _persona_mgr；这里把单例指向隔离实例
    import core.api_server as api_server
    api_server._persona_mgr = persona_mgr
    from core.api_server import app
    return TestClient(app)


class TestThreeViewAPI:
    def test_summary_default_active(self, client, persona_mgr):
        persona_mgr.save_three_view("test_persona", "front", _png_bytes())
        persona_mgr.switch_persona("test_persona")
        r = client.get("/api/persona/three-view")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["views"]["front"]["present"] is True
        assert body["views"]["side"]["present"] is False

    def test_summary_by_persona_id(self, client):
        r = client.get("/api/persona/three-view?persona_id=test_persona")
        assert r.status_code == 200
        assert r.json()["persona_id"] == "test_persona"

    def test_summary_unknown_persona_404(self, client):
        r = client.get("/api/persona/three-view?persona_id=nope")
        assert r.status_code == 404

    def test_upload_and_get(self, client):
        r = client.post(
            "/api/persona/three-view/test_persona/front",
            files={"file": ("front.png", _png_bytes(), "image/png")},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["file"] == "front.png"
        assert body["dataurl"].startswith("data:image/png")

        g = client.get("/api/persona/three-view/test_persona/front")
        assert g.status_code == 200
        assert g.headers["content-type"] == "image/png"
        assert g.content == _png_bytes()

    def test_upload_unknown_persona_404(self, client):
        r = client.post(
            "/api/persona/three-view/nope/front",
            files={"file": ("front.png", _png_bytes(), "image/png")},
        )
        assert r.status_code == 404

    def test_upload_empty_file_400(self, client):
        r = client.post(
            "/api/persona/three-view/test_persona/front",
            files={"file": ("front.png", b"abc", "image/png")},
        )
        assert r.status_code == 400

    def test_delete_view(self, client):
        client.post(
            "/api/persona/three-view/test_persona/front",
            files={"file": ("front.png", _png_bytes(), "image/png")},
        )
        r = client.delete("/api/persona/three-view/test_persona/front")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        g = client.get("/api/persona/three-view/test_persona/front")
        assert g.status_code == 404

    def test_delete_all(self, client):
        client.post(
            "/api/persona/three-view/test_persona/front",
            files={"file": ("front.png", _png_bytes(), "image/png")},
        )
        r = client.delete("/api/persona/three-view/test_persona/*")
        assert r.status_code == 200
        g = client.get("/api/persona/three-view/test_persona/front")
        assert g.status_code == 404

    def test_oversized_upload_is_compressed(self, client, persona_mgr, monkeypatch):
        # 上限有 64KB 下限；设一个略高于下限的阈值，用大噪点图确保超限被压缩
        monkeypatch.setenv("AERIE_THREE_VIEW_MAX_BYTES", str(128 * 1024))
        big = io.BytesIO()
        noise = Image.effect_noise((700, 700), 120).convert("RGB")
        noise.save(big, format="PNG")
        raw = big.getvalue()
        assert len(raw) > 128 * 1024

        r = client.post(
            "/api/persona/three-view/test_persona/front",
            files={"file": ("front.png", raw, "image/png")},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        # 压缩后落盘应转为 jpg 且不超过上限
        assert body["file"] == "front.jpg"
        stored, mime = persona_mgr.load_three_view("test_persona", "front")
        assert mime == "image/jpeg"
        assert len(stored) <= 128 * 1024
        assert len(stored) < len(raw)

    def test_uncompressible_falls_back_to_413(self, client, monkeypatch):
        monkeypatch.setenv("AERIE_THREE_VIEW_MAX_BYTES", "4096")
        r = client.post(
            "/api/persona/three-view/test_persona/front",
            files={"file": ("front.bin", b"x" * 70000, "application/octet-stream")},
        )
        # 非图片超过下限(64KB)触发压缩，但无法用 PIL 打开 → 413
        assert r.status_code == 413


# ── 验证轮 2.5：压缩辅助函数 ────────────────────────


class TestThreeViewCompression:
    def test_small_image_passthrough(self, persona_mgr, monkeypatch):
        import core.api_server as api_server
        data = _png_bytes()
        assert len(data) <= 8 * 1024 * 1024
        # 未超限则直接保存，不被压缩
        ok, suffix = persona_mgr.save_three_view("test_persona", "front", data)
        assert ok is True
        assert suffix == "front.png"

    def test_compress_helper_reduces_below_limit(self, monkeypatch):
        import core.api_server as api_server
        big = io.BytesIO()
        Image.new("RGB", (1600, 2000), color=(10, 20, 30)).save(big, format="PNG")
        raw = big.getvalue()
        limit = 8192
        assert len(raw) > limit
        out, ext = api_server._compress_three_view_image(raw, limit)
        assert ext == "jpg"
        assert len(out) <= limit
        assert len(out) < len(raw)


# ── 验证轮 3：生图接入 ──────────────────────────────


class FakeEditProvider:
    provider_id = "fake_edit"
    model = "fake-edit-model"

    def __init__(self) -> None:
        self.edits: list[dict] = []

    def generate(self, *, prompt, request_id, owner_id, metadata):
        raise AssertionError("generate should not be called")

    def generate_edit(self, *, prompt, image_bytes, mime_type, request_id, owner_id, metadata):
        self.edits.append({"prompt": prompt, "image_bytes": image_bytes})
        return ImageGenerationResult(
            status="ok",
            image_bytes=_png_bytes((8, 8), color=(200, 60, 60)),
            mime_type="image/png",
            provider_id=self.provider_id,
            model=self.model,
            external_id="edit-ext-1",
        )


def _workflow(tmp_path, provider) -> ImageWorkflow:
    return ImageWorkflow(
        upload_base=tmp_path / "uploads",
        feature_enabled=True,
        generation_provider=provider,
        safety_policy=ImageSafetyPolicy(blocked_terms=("aerie-test-reject",)),
        id_factory=lambda prefix: f"{prefix}-fixed",
    )


class TestThreeViewImageGeneration:
    def test_edit_with_three_view_front_reference(self, tmp_path, persona_mgr):
        persona_mgr.save_three_view("test_persona", "front", _png_bytes(color=(7, 8, 9)))
        persona_mgr.switch_persona("test_persona")

        provider = FakeEditProvider()
        service = _workflow(tmp_path, provider)

        result = service.generate_image_edit(
            prompt="keep the face, change the outfit",
            reference_assets=["three_view:front"],
            idempotency_key="edit-tv-front",
            owner_id="master",
            delivery={"channel": "local_chat"},
        )

        assert result["status"] == "completed"
        assert provider.edits, "provider should have received a reference image"
        # 参考图应为该人设存储的 front 三视图字节
        assert provider.edits[0]["image_bytes"] == _png_bytes(color=(7, 8, 9))
        assert result["asset"]["is_image"] is True

    def test_edit_rejects_when_no_three_view(self, tmp_path, persona_mgr):
        # test_persona 未上传任何三视图 → 参考不可解析 → rejected
        provider = FakeEditProvider()
        service = _workflow(tmp_path, provider)
        result = service.generate_image_edit(
            prompt="edit it",
            reference_assets=["three_view:front"],
            idempotency_key="edit-tv-missing",
            owner_id="master",
        )
        assert result["status"] == "rejected"
        assert result["error_code"] == "missing_reference_asset"
        assert result["side_effects"]["provider_called"] is False
        assert provider.edits == []

    def test_resolve_uses_active_persona(self, tmp_path, persona_mgr):
        # 未切换时 active 仍为 yita_default，无 front → 解析失败
        persona_mgr.save_three_view("test_persona", "front", _png_bytes())
        provider = FakeEditProvider()
        service = _workflow(tmp_path, provider)
        result = service.generate_image_edit(
            prompt="edit it",
            reference_assets=["three_view:front"],
            idempotency_key="edit-tv-active",
            owner_id="master",
        )
        assert result["status"] == "rejected"
        assert provider.edits == []
