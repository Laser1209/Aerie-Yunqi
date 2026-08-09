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
    LLMCallerImageGenerationProvider,
    IdempotencyConflict,
    ImageGenerationResult,
    ImageSafetyPolicy,
    ImageValidationError,
    ImageVisionResult,
    ImageWorkflow,
    VisualIntentRouter,
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

    def __init__(self, *, answer: str = "safe description", metadata: dict | None = None):
        self.answer = answer
        self.metadata = metadata or {}
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
            answer=self.answer,
            provider_id=self.provider_id,
            model=self.model,
            metadata=dict(self.metadata),
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


def test_generation_environment_object_routes_without_reference_assets(tmp_path):
    provider = FakeGenerationProvider()
    service = ImageWorkflow(
        upload_base=tmp_path / "uploads",
        feature_enabled=True,
        generation_provider=provider,
        visual_intent_router=VisualIntentRouter(),
        id_factory=lambda prefix: f"{prefix}-fixed",
    )

    result = service.generate_image(
        prompt="拍一下桌上的西瓜",
        idempotency_key="environment-object",
        owner_id="master",
        metadata={
            "world_snapshot": {
                "instance_id": "ws_1",
                "revision": 7,
                "location": "home",
                "activity": "eating_watermelon",
            }
        },
    )

    assert result["status"] == "completed"
    visual_request = result["visual_request"]
    assert visual_request["visual_intent"] == "environment_object"
    assert visual_request["reference_assets"] == []
    assert visual_request["world_snapshot_id"] == "ws_1"
    assert visual_request["world_context"]["location"] == "home"
    assert provider.calls[0]["metadata"]["visual_request"] == visual_request


def test_generation_role_selfie_freezes_visual_identity_revision(tmp_path):
    provider = FakeGenerationProvider()
    service = ImageWorkflow(
        upload_base=tmp_path / "uploads",
        feature_enabled=True,
        generation_provider=provider,
        visual_intent_router=VisualIntentRouter(),
        id_factory=lambda prefix: f"{prefix}-fixed",
    )

    result = service.generate_image(
        prompt="发张你的自拍",
        idempotency_key="role-selfie",
        owner_id="master",
        metadata={
            "persona_config": {
                "id": "persona_5872",
                "visual_identity": {
                    "visual_identity_revision": 3,
                    "selfie_reference_asset_id": "asset_selfie",
                },
            }
        },
    )

    visual_request = result["visual_request"]
    assert visual_request["visual_intent"] == "role_selfie"
    assert visual_request["persona_id"] == "persona_5872"
    assert visual_request["identity_revision"] == 3
    assert visual_request["reference_assets"] == ["asset_selfie"]
    assert "face_identity" in visual_request["must_preserve"]


def test_generation_low_confidence_visual_intent_does_not_call_provider(tmp_path):
    provider = FakeGenerationProvider()
    service = ImageWorkflow(
        upload_base=tmp_path / "uploads",
        feature_enabled=True,
        generation_provider=provider,
        visual_intent_router=VisualIntentRouter(min_confidence=0.8),
        id_factory=lambda prefix: f"{prefix}-fixed",
    )

    result = service.generate_image(
        prompt="拍一张照片",
        idempotency_key="low-confidence-visual-intent",
        owner_id="master",
    )

    assert result["status"] == "rejected"
    assert result["error_code"] == "visual_intent_low_confidence"
    assert result["visual_request"]["status"] == "needs_clarification"
    assert result["side_effects"] == {
        "provider_called": False,
        "asset_created": False,
        "delivery_created": False,
    }
    assert provider.calls == []


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
        generation_provider=LLMCallerImageGenerationProvider(BrainWithImageBytes()),
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


def test_vision_builds_chinese_screenshot_image_observation(tmp_path):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    image_path = upload_dir / "screenshot.png"
    image_path.write_bytes(_png_bytes())
    vision = FakeVisionProvider(
        answer="截图显示待办应用，OCR 文本包含：今天 18:00 提交报告。",
        metadata={
            "scene": {"type": "screenshot", "summary": "待办应用截图"},
            "ocr_text": ["今天 18:00 提交报告"],
            "confidence": 0.86,
        },
    )
    service = ImageWorkflow(
        upload_base=upload_dir,
        feature_enabled=True,
        vision_provider=vision,
        id_factory=lambda prefix: f"{prefix}-fixed",
    )

    result = service.understand_image(
        image_ref="/uploads/screenshot.png",
        question="读一下截图",
        idempotency_key="vision-cn-screenshot",
        owner_id="master",
    )

    observation = result["observation"]
    assert observation["scene"] == {"type": "screenshot", "summary": "待办应用截图"}
    assert observation["ocr_text"] == ["今天 18:00 提交报告"]
    assert observation["objects"] == []
    assert observation["relations"] == []
    assert observation["confidence"] == 0.86
    assert observation["provider"] == {
        "id": "fake_vision",
        "model": "fake-vision-model",
        "status": "ok",
    }
    assert observation["memory_eligibility"] == {
        "eligible": False,
        "reason": "requires_explicit_confirmation",
    }


def test_vision_builds_object_relation_image_observation(tmp_path):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    image_path = upload_dir / "object.png"
    image_path.write_bytes(_png_bytes())
    vision = FakeVisionProvider(
        answer="桌面上有一只白色杯子，杯子在笔记本电脑旁边。",
        metadata={
            "objects": [
                {"label": "白色杯子", "confidence": 0.91},
                {"label": "笔记本电脑", "confidence": 0.88},
            ],
            "relations": [
                {"subject": "白色杯子", "relation": "next_to", "object": "笔记本电脑"}
            ],
        },
    )
    service = ImageWorkflow(
        upload_base=upload_dir,
        feature_enabled=True,
        vision_provider=vision,
        id_factory=lambda prefix: f"{prefix}-fixed",
    )

    result = service.understand_image(
        image_ref="/uploads/object.png",
        question="这是什么",
        idempotency_key="vision-object",
        owner_id="master",
    )

    observation = result["observation"]
    assert observation["scene"]["summary"] == "桌面上有一只白色杯子，杯子在笔记本电脑旁边。"
    assert observation["objects"] == [
        {"label": "白色杯子", "confidence": 0.91},
        {"label": "笔记本电脑", "confidence": 0.88},
    ]
    assert observation["relations"] == [
        {"subject": "白色杯子", "relation": "next_to", "object": "笔记本电脑"}
    ]
    assert observation["memory_eligibility"]["eligible"] is False


def test_vision_low_confidence_observation_records_uncertainty(tmp_path):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    image_path = upload_dir / "uncertain.png"
    image_path.write_bytes(_png_bytes())
    vision = FakeVisionProvider(
        answer="可能是表格截图，但文字不清晰。",
        metadata={
            "confidence": 0.22,
            "uncertainties": ["ocr_unavailable", "low_resolution"],
        },
    )
    service = ImageWorkflow(
        upload_base=upload_dir,
        feature_enabled=True,
        vision_provider=vision,
        id_factory=lambda prefix: f"{prefix}-fixed",
    )

    result = service.understand_image(
        image_ref="/uploads/uncertain.png",
        question="识别表格",
        idempotency_key="vision-low-confidence",
        owner_id="master",
    )

    observation = result["observation"]
    assert observation["confidence"] == 0.22
    assert observation["uncertainties"] == ["ocr_unavailable", "low_resolution"]
    assert observation["memory_eligibility"] == {
        "eligible": False,
        "reason": "requires_explicit_confirmation",
    }


def test_vision_observation_handles_invalid_provider_confidence(tmp_path):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    image_path = upload_dir / "bad-confidence.png"
    image_path.write_bytes(_png_bytes())
    vision = FakeVisionProvider(
        answer="provider confidence is malformed",
        metadata={"confidence": "not-a-number"},
    )
    service = ImageWorkflow(
        upload_base=upload_dir,
        feature_enabled=True,
        vision_provider=vision,
        id_factory=lambda prefix: f"{prefix}-fixed",
    )

    result = service.understand_image(
        image_ref="/uploads/bad-confidence.png",
        question="describe",
        idempotency_key="vision-bad-confidence",
        owner_id="master",
    )

    assert result["status"] == "completed"
    assert result["observation"]["confidence"] == 0.5
    assert "invalid_provider_confidence" in result["observation"]["uncertainties"]


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


def test_image_edit_degrades_when_provider_lacks_edit_support(tmp_path):
    # FakeGenerationProvider only exposes generate() (no generate_edit).
    provider = FakeGenerationProvider()
    service = _workflow(tmp_path, provider)

    # First write a reference asset into the uploads dir.
    uploads = tmp_path / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    ref = uploads / "ref.png"
    ref.write_bytes(_png_bytes())

    result = service.generate_image_edit(
        prompt="turn it into a night scene",
        reference_assets=["uploads/ref.png"],
        idempotency_key="edit-nosupport",
        owner_id="master",
        delivery={"channel": "local_chat"},
    )

    assert result["status"] == "failed"
    assert result["error_code"] == "image_edit_unsupported"
    assert result["side_effects"]["provider_called"] is False
    assert result["asset"] is None


def test_image_edit_rejects_missing_reference_asset(tmp_path):
    provider = FakeGenerationProvider()
    service = _workflow(tmp_path, provider)

    result = service.generate_image_edit(
        prompt="edit something",
        reference_assets=["uploads/does-not-exist.png"],
        idempotency_key="edit-missing",
        owner_id="master",
    )

    assert result["status"] == "rejected"
    assert result["error_code"] == "missing_reference_asset"
    assert result["side_effects"]["provider_called"] is False


class FakeEditProvider:
    """Provider exposing both generate() and generate_edit()."""

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


def test_image_edit_success_persists_asset_and_delivery_plan(tmp_path):
    provider = FakeEditProvider()
    service = _workflow(tmp_path, provider)

    uploads = tmp_path / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / "ref.png").write_bytes(_png_bytes())

    result = service.generate_image_edit(
        prompt="make it sunset",
        reference_assets=["uploads/ref.png"],
        idempotency_key="edit-ok",
        owner_id="master",
        delivery={"channel": "local_chat", "target": "desktop"},
    )

    assert result["status"] == "completed"
    assert provider.edits and provider.edits[0]["image_bytes"] == _png_bytes()
    assert result["asset"]["is_image"] is True
    assert result["delivery_plan"]["status"] == "planned"
    assert result["delivery_plan"]["channel"] == "local_chat"
    assert result["side_effects"]["asset_created"] is True

