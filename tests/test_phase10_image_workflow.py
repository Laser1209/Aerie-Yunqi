"""Phase 10 image workflow contracts.

These tests pin the separation between provider calls, safety review,
asset persistence, and delivery planning.  They intentionally avoid
real model calls; providers are injectable fakes so idempotency and
side effects stay observable.
"""

from __future__ import annotations

import io
import json
import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import core.api_server as api_server
from core.api_server import app
from core.image_service import (
    BrainImageGenerationProvider,
    IdempotencyConflict,
    ImageGenerationResult,
    ImageSafetyPolicy,
    ImageValidationError,
    ImageVisionResult,
    ImageWorkflow,
)


def _png_bytes(size: tuple[int, int] = (6, 4), color=(90, 140, 210)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    return buf.getvalue()


class FakeGenerationProvider:
    provider_id = "fake_generation"
    model = "fake-image-model"

    def __init__(self, *, mode: str = "success"):
        self.mode = mode
        self.calls: list[dict] = []

    def generate(self, *, prompt: str, request_id: str, owner_id: str, metadata: dict):
        self.calls.append(
            {
                "prompt": prompt,
                "request_id": request_id,
                "owner_id": owner_id,
                "metadata": metadata,
            }
        )
        if self.mode == "timeout":
            raise TimeoutError("fake timeout with secret prompt content")
        if self.mode == "failed":
            raise RuntimeError("fake provider failed with secret prompt content")
        return ImageGenerationResult(
            status="ok",
            image_bytes=_png_bytes(),
            mime_type="image/png",
            provider_id=self.provider_id,
            model=self.model,
            external_id="fake-ext-1",
        )


class FakeVisionProvider:
    provider_id = "fake_vision"
    model = "fake-vision-model"

    def __init__(self):
        self.calls: list[dict] = []

    def analyze(self, *, image_path: str, question: str, request_id: str, owner_id: str):
        self.calls.append(
            {
                "image_path": image_path,
                "question": question,
                "request_id": request_id,
                "owner_id": owner_id,
            }
        )
        return ImageVisionResult(
            status="ok",
            answer="safe description",
            provider_id=self.provider_id,
            model=self.model,
        )


def _workflow(tmp_path: Path, provider: FakeGenerationProvider) -> ImageWorkflow:
    return ImageWorkflow(
        upload_base=tmp_path / "uploads",
        feature_enabled=True,
        generation_provider=provider,
        safety_policy=ImageSafetyPolicy(blocked_terms=("aerie-test-reject",)),
        id_factory=lambda prefix: f"{prefix}-fixed",
    )


def test_generation_rejection_skips_provider_asset_and_delivery(tmp_path):
    provider = FakeGenerationProvider()
    service = _workflow(tmp_path, provider)

    result = service.generate_image(
        prompt="aerie-test-reject but do not leak this sensitive phrase",
        idempotency_key="reject-key",
        owner_id="master",
        delivery={"channel": "local_chat"},
    )

    assert result["status"] == "rejected"
    assert result["safety"]["status"] == "rejected"
    assert provider.calls == []
    assert result["asset"] is None
    assert result["delivery_plan"] is None
    assert result["side_effects"] == {
        "provider_called": False,
        "asset_created": False,
        "delivery_created": False,
    }
    assert "sensitive phrase" not in json.dumps(result, ensure_ascii=False)


def test_generation_provider_timeout_is_idempotent_and_never_creates_delivery(tmp_path):
    provider = FakeGenerationProvider(mode="timeout")
    service = _workflow(tmp_path, provider)

    first = service.generate_image(
        prompt="draw a quiet blue room",
        idempotency_key="timeout-key",
        owner_id="master",
    )
    second = service.generate_image(
        prompt="draw a quiet blue room",
        idempotency_key="timeout-key",
        owner_id="master",
    )

    assert first["status"] == "timeout"
    assert first["delivery_plan"] is None
    assert first["side_effects"]["delivery_created"] is False
    assert second["status"] == "timeout"
    assert second["idempotent_replay"] is True
    assert second["side_effects"] == {
        "provider_called": False,
        "asset_created": False,
        "delivery_created": False,
    }
    assert len(provider.calls) == 1
    assert "secret prompt content" not in json.dumps(first, ensure_ascii=False)


def test_generation_success_persists_asset_and_plans_delivery_once(tmp_path):
    provider = FakeGenerationProvider()
    service = _workflow(tmp_path, provider)

    first = service.generate_image(
        prompt="draw a tiny moon over a lake",
        idempotency_key="success-key",
        owner_id="master",
        delivery={"channel": "local_chat", "target": "desktop"},
    )
    second = service.generate_image(
        prompt="draw a tiny moon over a lake",
        idempotency_key="success-key",
        owner_id="master",
        delivery={"channel": "local_chat", "target": "desktop"},
    )

    assert first["status"] == "completed"
    assert first["asset"]["url"].startswith("/uploads/")
    assert first["delivery_plan"]["status"] == "planned"
    assert first["side_effects"] == {
        "provider_called": True,
        "asset_created": True,
        "delivery_created": True,
    }
    assert (tmp_path / "uploads" / first["asset"]["saved_as"]).exists()

    assert second["request_id"] == first["request_id"]
    assert second["idempotent_replay"] is True
    assert second["side_effects"] == {
        "provider_called": False,
        "asset_created": False,
        "delivery_created": False,
    }
    assert len(provider.calls) == 1


def test_brain_generation_provider_accepts_base64_image_bytes(tmp_path):
    class BrainWithImageBytes:
        def generate_image(self, prompt: str):
            return {
                "status": "ok",
                "provider": "openai_compatible_image",
                "model": "image-test-model",
                "image_bytes_b64": base64.b64encode(_png_bytes()).decode("ascii"),
                "mime_type": "image/png",
            }

    service = ImageWorkflow(
        upload_base=tmp_path / "uploads",
        feature_enabled=True,
        generation_provider=BrainImageGenerationProvider(BrainWithImageBytes()),
        id_factory=lambda prefix: f"{prefix}-fixed",
    )

    result = service.generate_image(
        prompt="draw a persisted provider image",
        idempotency_key="brain-b64-key",
        owner_id="master",
    )

    assert result["status"] == "completed"
    assert result["provider"] == {
        "id": "openai_compatible_image",
        "model": "image-test-model",
        "status": "ok",
    }
    assert result["asset"]["url"].startswith("/uploads/")
    assert (tmp_path / "uploads" / result["asset"]["saved_as"]).exists()


def test_generation_idempotency_key_conflict_prevents_history_crosswire(tmp_path):
    provider = FakeGenerationProvider()
    service = _workflow(tmp_path, provider)

    service.generate_image(
        prompt="first prompt",
        idempotency_key="same-key",
        owner_id="master",
    )

    with pytest.raises(IdempotencyConflict):
        service.generate_image(
            prompt="different prompt",
            idempotency_key="same-key",
            owner_id="master",
        )
    assert len(provider.calls) == 1


def test_feature_flag_off_does_not_call_provider_or_create_audit(tmp_path):
    provider = FakeGenerationProvider()
    service = ImageWorkflow(
        upload_base=tmp_path / "uploads",
        feature_enabled=False,
        generation_provider=provider,
    )

    result = service.generate_image(
        prompt="draw a disabled path",
        idempotency_key="flag-off-key",
        owner_id="master",
    )

    assert result["status"] == "disabled"
    assert result["feature_flag"] == "image_assets_v1"
    assert provider.calls == []
    assert not (tmp_path / "uploads" / ".image_assets" / "image_workflows.json").exists()


def test_vision_uses_safe_upload_reference_and_is_idempotent(tmp_path):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    image_path = upload_dir / "sample.png"
    image_path.write_bytes(_png_bytes())
    vision = FakeVisionProvider()
    service = ImageWorkflow(
        upload_base=upload_dir,
        feature_enabled=True,
        vision_provider=vision,
        id_factory=lambda prefix: f"{prefix}-fixed",
    )

    first = service.understand_image(
        image_ref="/uploads/sample.png",
        question="describe",
        idempotency_key="vision-key",
        owner_id="master",
    )
    second = service.understand_image(
        image_ref="/uploads/sample.png",
        question="describe",
        idempotency_key="vision-key",
        owner_id="master",
    )

    assert first["status"] == "completed"
    assert first["answer"] == "safe description"
    assert first["delivery_plan"] is None
    assert second["idempotent_replay"] is True
    assert len(vision.calls) == 1


def test_vision_rejects_path_traversal_before_provider(tmp_path):
    vision = FakeVisionProvider()
    service = ImageWorkflow(
        upload_base=tmp_path / "uploads",
        feature_enabled=True,
        vision_provider=vision,
    )

    with pytest.raises(ImageValidationError):
        service.understand_image(
            image_ref="/uploads/../secret.png",
            question="describe",
            idempotency_key="bad-path",
            owner_id="master",
        )
    assert vision.calls == []


def test_generate_endpoint_flag_off_uses_disabled_contract_without_new_workflow(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(api_server, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("AERIE_FEATURE_IMAGE_ASSETS_V1", "false")
    client = TestClient(app)

    response = client.post(
        "/api/images/generate",
        json={
            "prompt": "draw through old-disabled path",
            "idempotency_key": "api-flag-off",
            "owner_id": "master",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "disabled"
    assert not (tmp_path / "uploads" / ".image_assets" / "image_workflows.json").exists()
