"""Phase 10 image understanding / generation workflow.

The service deliberately keeps four responsibilities separate:

1. safety review
2. provider call
3. asset persistence
4. delivery planning

It does not send images to any external channel.  A successful generation
only creates an auditable delivery *plan*; callers that later execute plans
must perform their own idempotent outbox handling.
"""

from __future__ import annotations

import copy
import base64
import hashlib
import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from core.image_production_log import record_image_stage

logger = logging.getLogger(__name__)

_SAFE_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
_NO_SIDE_EFFECTS = {
    "provider_called": False,
    "asset_created": False,
    "delivery_created": False,
}


class ImageWorkflowError(Exception):
    """Base class for public, redacted workflow errors."""

    code = "image_workflow_error"
    status_code = 500
    public_message = "image workflow failed"


class ImageValidationError(ImageWorkflowError):
    code = "invalid_image_workflow_request"
    status_code = 400
    public_message = "invalid image workflow request"


class IdempotencyConflict(ImageWorkflowError):
    code = "idempotency_conflict"
    status_code = 409
    public_message = "idempotency key was already used for a different payload"


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    reason_code: str = "allowed"
    categories: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        return "allowed" if self.allowed else "rejected"

    def public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason_code": self.reason_code,
            "categories": list(self.categories),
        }


@dataclass
class ImageGenerationResult:
    status: str
    image_bytes: bytes | None = None
    image_path: str | None = None
    mime_type: str = "image/png"
    provider_id: str = "unknown"
    model: str = "unknown"
    external_id: str = ""
    error_code: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageVisionResult:
    status: str
    answer: str = ""
    provider_id: str = "unknown"
    model: str = "unknown"
    error_code: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    observation: dict[str, Any] = field(default_factory=dict)


class VisualIntentRouter:
    """Route visual generation requests before any provider receives reference assets.

    Determines visual intent from prompt + metadata, freezes identity revision
    for role images, and ensures environment_object never mounts reference assets.
    Does not call real models; uses deterministic keyword matching.
    """

    _INTENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("role_selfie", ("自拍", "发张你的", "发张你的照片", "你的照片", "照片给我", "要照片", "发照片", "拍照", "拍个照", "拍张照", "拍张照片", "给我拍", "selfie")),
        ("role_in_scene", ("你拍", "你窗边", "拍一张", "拍一张你", "拍你现在", "你现在的样子", "在家拍", "现在拍一张")),
        ("couple_photo", ("合照", "我们的照片", "合影", "couple")),
        ("environment_object", ("拍一下", "桌上的", "西瓜", "小狗", "窗户", "environment")),
        ("document_snapshot", ("截图", "文档", "document")),
        ("meme_sticker", ("表情包", "贴纸", "meme", "sticker")),
    )

    _ROLE_INTENTS = frozenset({"role_selfie", "role_in_scene"})
    _ENVIRONMENT_INTENTS = frozenset({"environment_object"})

    def __init__(self, *, min_confidence: float = 0.5) -> None:
        self.min_confidence = float(min_confidence)

    def route(
        self,
        *,
        prompt: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prompt_text = str(prompt or "")
        metadata = dict(metadata or {})

        scores: dict[str, float] = {}
        for intent, keywords in self._INTENT_KEYWORDS:
            score = 0.0
            for kw in keywords:
                if kw in prompt_text:
                    score += 0.5
            if score > 0:
                scores[intent] = min(score, 1.0)

        if not scores:
            return {
                "status": "needs_clarification",
                "visual_intent": "unknown",
                "confidence": 0.0,
                "reason": "no_intent_keywords_matched",
                "reference_assets": [],
            }

        best_intent = max(scores, key=scores.get)
        confidence = scores[best_intent]
        if confidence < self.min_confidence:
            return {
                "status": "needs_clarification",
                "visual_intent": best_intent,
                "confidence": confidence,
                "reason": "low_confidence",
                "reference_assets": [],
            }

        return self._build_visual_request(best_intent, confidence, metadata)

    def _build_visual_request(
        self,
        intent: str,
        confidence: float,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        reference_assets: list[str] = []
        persona_id = ""
        identity_revision = 0
        world_snapshot_id = ""
        world_context: dict[str, Any] = {}
        must_preserve: list[str] = []

        if intent in self._ROLE_INTENTS:
            persona_config = metadata.get("persona_config") or {}
            visual_identity = persona_config.get("visual_identity") or {}
            persona_id = str(persona_config.get("id", ""))
            identity_revision = int(visual_identity.get("visual_identity_revision", 0))
            selfie_asset = visual_identity.get("selfie_reference_asset_id", "")
            if selfie_asset:
                reference_assets.append(str(selfie_asset))
            must_preserve = ["face_identity", "age_impression", "hair_style", "character_vibe"]
        elif intent == "couple_photo":
            persona_config = metadata.get("persona_config") or {}
            visual_identity = persona_config.get("visual_identity") or {}
            persona_id = str(persona_config.get("id", ""))
            identity_revision = int(visual_identity.get("visual_identity_revision", 0))
            selfie_asset = visual_identity.get("selfie_reference_asset_id", "")
            if selfie_asset:
                reference_assets.append(str(selfie_asset))
            couple_asset = visual_identity.get("couple_reference_asset_id", "")
            if couple_asset:
                reference_assets.append(str(couple_asset))
            must_preserve = ["face_identity", "relationship_facts"]
        elif intent in self._ENVIRONMENT_INTENTS:
            reference_assets = []
            world_snapshot = metadata.get("world_snapshot") or {}
            world_snapshot_id = str(world_snapshot.get("instance_id", ""))
            world_context = {
                k: v for k, v in world_snapshot.items()
                if k != "instance_id"
            }

        return {
            "status": "ok",
            "visual_intent": intent,
            "confidence": confidence,
            "persona_id": persona_id,
            "identity_revision": identity_revision,
            "reference_assets": reference_assets,
            "world_snapshot_id": world_snapshot_id,
            "world_context": world_context,
            "must_preserve": must_preserve,
        }


class ImageGenerationProvider(Protocol):
    provider_id: str
    model: str

    def generate(
        self,
        *,
        prompt: str,
        request_id: str,
        owner_id: str,
        metadata: dict[str, Any],
    ) -> ImageGenerationResult:
        ...


class ImageVisionProvider(Protocol):
    provider_id: str
    model: str

    def analyze(
        self,
        *,
        image_path: str,
        question: str,
        request_id: str,
        owner_id: str,
    ) -> ImageVisionResult:
        ...


class ImageSafetyPolicy:
    """Small deterministic safety gate for Phase 10 contracts.

    This is not meant to be a full policy classifier.  It gives the Core
    workflow a stable, testable place where richer moderation can later be
    plugged in without moving provider or delivery side effects.
    """

    def __init__(self, blocked_terms: tuple[str, ...] | None = None) -> None:
        default_terms = (
            "aerie-test-reject",
            "api key",
            "password",
            "secret token",
            "credential",
            "凭据",
            "密钥",
        )
        self.blocked_terms = tuple(t.lower() for t in (blocked_terms or default_terms))

    def review_generation_prompt(self, prompt: str) -> SafetyDecision:
        normalized = (prompt or "").strip().lower()
        if not normalized:
            return SafetyDecision(False, "empty_prompt", ("validation",))
        if len(normalized) > 4000:
            return SafetyDecision(False, "prompt_too_long", ("validation",))
        for term in self.blocked_terms:
            if term and term in normalized:
                return SafetyDecision(False, "policy_rejected", ("sensitive_content",))
        return SafetyDecision(True)

    def review_vision_question(self, question: str) -> SafetyDecision:
        normalized = (question or "").strip().lower()
        if not normalized:
            return SafetyDecision(False, "empty_question", ("validation",))
        if len(normalized) > 1000:
            return SafetyDecision(False, "question_too_long", ("validation",))
        for term in self.blocked_terms:
            if term and term in normalized:
                return SafetyDecision(False, "policy_rejected", ("sensitive_content",))
        return SafetyDecision(True)


class LLMCallerImageGenerationProvider:
    """Adapter around the legacy ``LLMCaller.generate_image`` surface."""

    provider_id = "image_sdxl"
    model = "sdxl"

    def __init__(self, brain: object | None) -> None:
        self.brain = brain

    def generate(
        self,
        *,
        prompt: str,
        request_id: str,
        owner_id: str,
        metadata: dict[str, Any],
    ) -> ImageGenerationResult:
        trace_id = str(metadata.get("idempotency_key") or metadata.get("candidate_id") or request_id)
        if self.brain is None or not hasattr(self.brain, "generate_image"):
            record_image_stage(trace_id, "provider.completed", status="unavailable", operation="generate", error_code="brain_unavailable")
            return ImageGenerationResult(
                status="unavailable",
                provider_id=self.provider_id,
                model=self.model,
                error_code="brain_unavailable",
            )
        started = time.perf_counter()
        record_image_stage(trace_id, "provider.requested", status="started", operation="generate", provider=self.provider_id, model=self.model, prompt_chars=len(prompt))
        raw = self.brain.generate_image(prompt, metadata=metadata)
        duration_ms = int((time.perf_counter() - started) * 1000)
        if not isinstance(raw, dict):
            record_image_stage(trace_id, "provider.completed", status="failed", operation="generate", duration_ms=duration_ms, error_code="invalid_provider_response")
            return ImageGenerationResult(
                status="failed",
                provider_id=self.provider_id,
                model=self.model,
                error_code="invalid_provider_response",
            )
        provider_id = str(raw.get("provider") or self.provider_id)
        model = str(raw.get("model") or self.model)
        record_image_stage(trace_id, "provider.completed", status=str(raw.get("status") or "unknown"), operation="generate", duration_ms=duration_ms, provider=provider_id, model=model)
        output_path = raw.get("output_path") or raw.get("path")
        if output_path:
            path = Path(str(output_path))
            if path.exists() and path.is_file():
                return ImageGenerationResult(
                    status="ok",
                    image_path=str(path),
                    mime_type=str(raw.get("mime_type") or "image/png"),
                    provider_id=provider_id,
                    model=model,
                    external_id=str(raw.get("external_id") or ""),
                )
        image_bytes_b64 = raw.get("image_bytes_b64")
        if image_bytes_b64:
            try:
                image_bytes = base64.b64decode(str(image_bytes_b64), validate=True)
            except Exception:
                return ImageGenerationResult(
                    status="failed",
                    provider_id=provider_id,
                    model=model,
                    error_code="invalid_provider_image_bytes",
                )
            return ImageGenerationResult(
                status="ok",
                image_bytes=image_bytes,
                mime_type=str(raw.get("mime_type") or "image/png"),
                provider_id=provider_id,
                model=model,
                external_id=str(raw.get("external_id") or ""),
            )
        return ImageGenerationResult(
            status="unavailable",
            provider_id=provider_id,
            model=model,
            error_code=str(raw.get("status") or "provider_unavailable"),
        )

    def generate_edit(
        self,
        *,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/png",
        request_id: str,
        owner_id: str,
        metadata: dict[str, Any],
    ) -> ImageGenerationResult:
        """Image-to-image edit via the legacy ``LLMCaller.generate_image_edit`` surface.
        Best-effort: if the LLMCaller lacks an edit path or the provider cannot
        serve edits, we return ``unavailable`` (never raise).
        """
        trace_id = str(metadata.get("idempotency_key") or metadata.get("candidate_id") or request_id)
        if self.brain is None or not hasattr(self.brain, "generate_image_edit"):
            record_image_stage(trace_id, "provider.completed", status="unavailable", operation="edit", error_code="image_edit_unsupported")
            return ImageGenerationResult(
                status="unavailable",
                provider_id=self.provider_id,
                model=self.model,
                error_code="image_edit_unsupported",
            )
        try:
            started = time.perf_counter()
            record_image_stage(trace_id, "provider.requested", status="started", operation="edit", provider=self.provider_id, model=self.model, prompt_chars=len(prompt), reference_bytes=len(image_bytes))
            raw = self.brain.generate_image_edit(
                prompt,
                image_bytes,
                mime_type=mime_type,
                metadata=metadata,
            )
        except Exception:
            record_image_stage(trace_id, "provider.completed", status="failed", operation="edit", duration_ms=int((time.perf_counter() - started) * 1000), error_code="image_edit_unsupported")
            return ImageGenerationResult(
                status="unavailable",
                provider_id=self.provider_id,
                model=self.model,
                error_code="image_edit_unsupported",
            )
        if not isinstance(raw, dict):
            return ImageGenerationResult(
                status="unavailable",
                provider_id=self.provider_id,
                model=self.model,
                error_code="image_edit_unsupported",
            )
        provider_id = str(raw.get("provider") or self.provider_id)
        model = str(raw.get("model") or self.model)
        record_image_stage(trace_id, "provider.completed", status=str(raw.get("status") or "unknown"), operation="edit", duration_ms=int((time.perf_counter() - started) * 1000), provider=provider_id, model=model)
        image_bytes_b64 = raw.get("image_bytes_b64")
        if image_bytes_b64:
            try:
                decoded = base64.b64decode(str(image_bytes_b64), validate=True)
            except Exception:
                return ImageGenerationResult(
                    status="failed",
                    provider_id=provider_id,
                    model=model,
                    error_code="invalid_provider_image_bytes",
                )
            return ImageGenerationResult(
                status="ok",
                image_bytes=decoded,
                mime_type=str(raw.get("mime_type") or "image/png"),
                provider_id=provider_id,
                model=model,
                external_id=str(raw.get("external_id") or ""),
            )
        return ImageGenerationResult(
            status=str(raw.get("status") or "unavailable"),
            provider_id=provider_id,
            model=model,
            error_code=str(raw.get("error_code") or raw.get("status") or "image_edit_unsupported"),
        )



class LLMCallerImageVisionProvider:
    """Adapter around the legacy ``LLMCaller.see_image`` surface."""

    provider_id = "vision_llava"
    model = "llava"

    def __init__(self, brain: object | None) -> None:
        self.brain = brain

    def analyze(
        self,
        *,
        image_path: str,
        question: str,
        request_id: str,
        owner_id: str,
    ) -> ImageVisionResult:
        if self.brain is None or not hasattr(self.brain, "see_image"):
            return ImageVisionResult(
                status="unavailable",
                provider_id=self.provider_id,
                model=self.model,
                error_code="brain_unavailable",
            )
        raw = self.brain.see_image(image_path, question)
        if not isinstance(raw, dict):
            return ImageVisionResult(
                status="failed",
                provider_id=self.provider_id,
                model=self.model,
                error_code="invalid_provider_response",
            )
        answer = str(raw.get("answer") or "")
        provider_id = str(raw.get("provider") or self.provider_id)
        model = str(raw.get("model") or self.model)
        if answer:
            return ImageVisionResult(
                status="ok",
                answer=answer,
                provider_id=provider_id,
                model=model,
            )
        return ImageVisionResult(
            status="unavailable",
            provider_id=provider_id,
            model=model,
            error_code=str(raw.get("status") or "provider_unavailable"),
        )


class JsonImageWorkflowStore:
    """Tiny JSON store for Phase 10 audit/idempotency without a DB migration."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def get_by_key(self, operation: str, idempotency_key: str) -> dict[str, Any] | None:
        data = self._load()
        key = self._store_key(operation, idempotency_key)
        record = (data.get("records_by_key") or {}).get(key)
        return copy.deepcopy(record) if isinstance(record, dict) else None

    def put(self, record: dict[str, Any]) -> None:
        with self._lock:
            data = self._load()
            records = data.setdefault("records_by_key", {})
            records[self._store_key(record["operation"], record["idempotency_key"])] = record
            by_id = data.setdefault("records_by_id", {})
            by_id[record["request_id"]] = record
            self._save(data)

    def _load(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                return {"version": 1, "records_by_key": {}, "records_by_id": {}}
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("image workflow store corrupt: %s", self.path, exc_info=True)
                return {"version": 1, "records_by_key": {}, "records_by_id": {}}
            if not isinstance(data, dict):
                return {"version": 1, "records_by_key": {}, "records_by_id": {}}
            data.setdefault("version", 1)
            data.setdefault("records_by_key", {})
            data.setdefault("records_by_id", {})
            return data

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    @staticmethod
    def _store_key(operation: str, idempotency_key: str) -> str:
        return f"{operation}:{idempotency_key}"


class ImageWorkflow:
    """Auditable image workflow facade used by API and tests."""

    feature_flag = "image_assets_v1"

    def __init__(
        self,
        *,
        upload_base: str | Path = "uploads",
        feature_enabled: bool = False,
        generation_provider: ImageGenerationProvider | None = None,
        vision_provider: ImageVisionProvider | None = None,
        safety_policy: ImageSafetyPolicy | None = None,
        store: JsonImageWorkflowStore | None = None,
        id_factory: Any | None = None,
        clock: Any | None = None,
        visual_intent_router: VisualIntentRouter | None = None,
    ) -> None:
        self.upload_base = Path(upload_base)
        if not self.upload_base.is_absolute():
            self.upload_base = (Path.cwd() / self.upload_base).resolve()
        else:
            self.upload_base = self.upload_base.resolve()
        self.feature_enabled = bool(feature_enabled)
        self.generation_provider = generation_provider or LLMCallerImageGenerationProvider(None)
        self.visual_intent_router = visual_intent_router
        self.vision_provider = vision_provider or LLMCallerImageVisionProvider(None)
        self.safety_policy = safety_policy or ImageSafetyPolicy()
        self.store = store or JsonImageWorkflowStore(
            self.upload_base / ".image_assets" / "image_workflows.json"
        )
        self.id_factory = id_factory or (lambda prefix: f"{prefix}_{uuid.uuid4().hex}")
        self.clock = clock or self._now

    def generate_image(
        self,
        *,
        prompt: str,
        idempotency_key: str,
        owner_id: str = "master",
        delivery: dict[str, Any] | None = None,
        conversation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        operation = "image_generation"
        if not self.feature_enabled:
            return self._disabled_result(operation)

        prompt_text = str(prompt or "")
        owner = self._normalize_owner(owner_id)
        idem = self._normalize_idempotency_key(idempotency_key)
        prompt_sha = _sha256_text(prompt_text)
        delivery_payload = self._normalize_delivery(delivery)
        fingerprint = _json_sha256(
            {
                "operation": operation,
                "prompt_sha256": prompt_sha,
                "owner_id": owner,
                "delivery": delivery_payload,
                "conversation_id": conversation_id or "",
            }
        )
        replay = self._replay_if_existing(operation, idem, fingerprint)
        if replay is not None:
            return replay

        request_id = self.id_factory("imggen")
        safety = self.safety_policy.review_generation_prompt(prompt_text)
        record_image_stage(
            str(idem),
            "safety.reviewed",
            status=safety.status,
            operation=operation,
            reason_code=safety.reason_code,
            categories=list(safety.categories),
        )
        if not safety.allowed:
            result = self._base_result(
                operation=operation,
                request_id=request_id,
                idempotency_key=idem,
                status="rejected",
                safety=safety,
                owner_id=owner,
                audit={"prompt_sha256": prompt_sha},
                provider_attempted=False,
            )
            self._record_result(result, operation, idem, fingerprint, owner)
            return result

        visual_request: dict[str, Any] | None = None
        if self.visual_intent_router is not None:
            visual_request = self.visual_intent_router.route(
                prompt=prompt_text,
                metadata=metadata or {},
            )
            if visual_request.get("status") == "needs_clarification":
                result = self._base_result(
                    operation=operation,
                    request_id=request_id,
                    idempotency_key=idem,
                    status="rejected",
                    safety=safety,
                    owner_id=owner,
                    audit={"prompt_sha256": prompt_sha},
                    provider_attempted=False,
                    error_code="visual_intent_low_confidence",
                )
                result["visual_request"] = visual_request
                self._record_result(result, operation, idem, fingerprint, owner)
                return result

        provider = self.generation_provider
        provider_id = str(getattr(provider, "provider_id", "unknown"))
        model = str(getattr(provider, "model", "unknown"))
        metadata_payload = {
            "conversation_id": conversation_id or "",
            "idempotency_key": idem,
            "prompt_sha256": prompt_sha,
            **(metadata or {}),
        }
        if visual_request is not None:
            metadata_payload["visual_request"] = visual_request

        try:
            generated = provider.generate(
                prompt=prompt_text,
                request_id=request_id,
                owner_id=owner,
                metadata=metadata_payload,
            )
        except TimeoutError:
            result = self._base_result(
                operation=operation,
                request_id=request_id,
                idempotency_key=idem,
                status="timeout",
                safety=safety,
                owner_id=owner,
                audit={"prompt_sha256": prompt_sha},
                provider_attempted=True,
                provider={"id": provider_id, "model": model, "status": "timeout"},
                error_code="provider_timeout",
            )
            self._record_result(result, operation, idem, fingerprint, owner)
            return result
        except Exception:
            logger.warning("image generation provider failed", exc_info=True)
            result = self._base_result(
                operation=operation,
                request_id=request_id,
                idempotency_key=idem,
                status="failed",
                safety=safety,
                owner_id=owner,
                audit={"prompt_sha256": prompt_sha},
                provider_attempted=True,
                provider={"id": provider_id, "model": model, "status": "failed"},
                error_code="provider_failed",
            )
            self._record_result(result, operation, idem, fingerprint, owner)
            return result

        provider_public = {
            "id": str(generated.provider_id or provider_id),
            "model": str(generated.model or model),
            "status": str(generated.status or "unknown"),
        }
        image_bytes = self._read_generation_bytes(generated)
        if generated.status != "ok" or not image_bytes:
            result = self._base_result(
                operation=operation,
                request_id=request_id,
                idempotency_key=idem,
                status="failed",
                safety=safety,
                owner_id=owner,
                audit={"prompt_sha256": prompt_sha},
                provider_attempted=True,
                provider=provider_public,
                error_code=str(generated.error_code or generated.status or "provider_failed"),
            )
            self._record_result(result, operation, idem, fingerprint, owner)
            return result

        try:
            asset = self._persist_generated_asset(
                request_id=request_id,
                image_bytes=image_bytes,
                mime_type=generated.mime_type or "image/png",
            )
            record_image_stage(
                str(metadata_payload.get("idempotency_key") or metadata_payload.get("candidate_id") or request_id),
                "asset.persisted",
                status="completed",
                request_id=request_id,
                asset_id=asset.get("asset_id"),
                url=asset.get("url"),
                sha256=asset.get("sha256"),
                size_bytes=asset.get("size_bytes"),
            )
        except Exception:
            logger.warning("generated image asset persistence failed", exc_info=True)
            result = self._base_result(
                operation=operation,
                request_id=request_id,
                idempotency_key=idem,
                status="failed",
                safety=safety,
                owner_id=owner,
                audit={"prompt_sha256": prompt_sha},
                provider_attempted=True,
                provider=provider_public,
                error_code="asset_persistence_failed",
            )
            self._record_result(result, operation, idem, fingerprint, owner)
            return result

        delivery_plan = self._create_delivery_plan(
            request_id=request_id,
            asset=asset,
            delivery=delivery_payload,
        )
        result = self._base_result(
            operation=operation,
            request_id=request_id,
            idempotency_key=idem,
            status="completed",
            safety=safety,
            owner_id=owner,
            audit={"prompt_sha256": prompt_sha},
            provider_attempted=True,
            provider=provider_public,
            asset=asset,
            delivery_plan=delivery_plan,
            side_effects={
                "provider_called": True,
                "asset_created": True,
                "delivery_created": True,
            },
        )
        if visual_request is not None:
            result["visual_request"] = visual_request
        self._record_result(result, operation, idem, fingerprint, owner)
        return result

    def generate_image_edit(
        self,
        *,
        prompt: str,
        reference_assets: list[str],
        idempotency_key: str,
        owner_id: str = "master",
        delivery: dict[str, Any] | None = None,
        conversation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Image-to-image workflow (best-effort).

        Mirrors :meth:`generate_image` but feeds a reference image to the
        provider's edit path. If the provider cannot serve edits, it returns
        ``unavailable`` without raising, so the surrounding loop never breaks.
        """
        operation = "image_edit"
        if not self.feature_enabled:
            return self._disabled_result(operation)

        prompt_text = str(prompt or "")
        owner = self._normalize_owner(owner_id)
        idem = self._normalize_idempotency_key(idempotency_key)
        reference_bytes, mime = self._resolve_reference_assets(reference_assets)
        if reference_bytes is None:
            result = self._base_result(
                operation=operation,
                request_id=self.id_factory("imgedit"),
                idempotency_key=idem,
                status="rejected",
                safety=self.safety_policy.review_generation_prompt(prompt_text),
                owner_id=owner,
                audit={"prompt_sha256": _sha256_text(prompt_text)},
                provider_attempted=False,
                error_code="missing_reference_asset",
            )
            self._record_result(result, operation, idem, "", owner)
            return result

        safety = self.safety_policy.review_generation_prompt(prompt_text)
        record_image_stage(
            str(idem),
            "safety.reviewed",
            status=safety.status,
            operation=operation,
            reason_code=safety.reason_code,
            categories=list(safety.categories),
        )
        if not safety.allowed:
            result = self._base_result(
                operation=operation,
                request_id=self.id_factory("imgedit"),
                idempotency_key=idem,
                status="rejected",
                safety=safety,
                owner_id=owner,
                audit={"prompt_sha256": _sha256_text(prompt_text)},
                provider_attempted=False,
            )
            self._record_result(result, operation, idem, "", owner)
            return result

        provider = self.generation_provider
        provider_id = str(getattr(provider, "provider_id", "unknown"))
        model = str(getattr(provider, "model", "unknown"))
        if not hasattr(provider, "generate_edit"):
            result = self._base_result(
                operation=operation,
                request_id=self.id_factory("imgedit"),
                idempotency_key=idem,
                status="failed",
                safety=safety,
                owner_id=owner,
                audit={"prompt_sha256": _sha256_text(prompt_text)},
                provider_attempted=False,
                provider={"id": provider_id, "model": model, "status": "not_called"},
                error_code="image_edit_unsupported",
            )
            self._record_result(result, operation, idem, "", owner)
            return result

        request_id = self.id_factory("imgedit")
        metadata_payload = {
            "conversation_id": conversation_id or "",
            "idempotency_key": idem,
            "prompt_sha256": _sha256_text(prompt_text),
            "reference_assets": list(reference_assets),
            **(metadata or {}),
        }
        try:
            generated = provider.generate_edit(
                prompt=prompt_text,
                image_bytes=reference_bytes,
                mime_type=mime,
                request_id=request_id,
                owner_id=owner,
                metadata=metadata_payload,
            )
        except Exception:
            logger.warning("image edit provider failed", exc_info=True)
            generated = ImageGenerationResult(
                status="failed",
                provider_id=provider_id,
                model=model,
                error_code="provider_failed",
            )

        provider_public = {
            "id": str(generated.provider_id or provider_id),
            "model": str(generated.model or model),
            "status": str(generated.status or "unknown"),
        }
        if generated.status != "ok":
            result = self._base_result(
                operation=operation,
                request_id=request_id,
                idempotency_key=idem,
                status="failed",
                safety=safety,
                owner_id=owner,
                audit={"prompt_sha256": _sha256_text(prompt_text)},
                provider_attempted=True,
                provider=provider_public,
                error_code=str(generated.error_code or generated.status or "provider_failed"),
            )
            self._record_result(result, operation, idem, "", owner)
            return result

        image_bytes = self._read_generation_bytes(generated)
        if not image_bytes:
            result = self._base_result(
                operation=operation,
                request_id=request_id,
                idempotency_key=idem,
                status="failed",
                safety=safety,
                owner_id=owner,
                audit={"prompt_sha256": _sha256_text(prompt_text)},
                provider_attempted=True,
                provider=provider_public,
                error_code="provider_failed",
            )
            self._record_result(result, operation, idem, "", owner)
            return result

        asset = self._persist_generated_asset(
            request_id=request_id,
            image_bytes=image_bytes,
            mime_type=generated.mime_type or "image/png",
        )
        delivery_plan = self._create_delivery_plan(
            request_id=request_id,
            asset=asset,
            delivery=self._normalize_delivery(delivery),
        )
        result = self._base_result(
            operation=operation,
            request_id=request_id,
            idempotency_key=idem,
            status="completed",
            safety=safety,
            owner_id=owner,
            audit={"prompt_sha256": _sha256_text(prompt_text)},
            provider_attempted=True,
            provider=provider_public,
            asset=asset,
            delivery_plan=delivery_plan,
            side_effects={
                "provider_called": True,
                "asset_created": True,
                "delivery_created": True,
            },
        )
        self._record_result(result, operation, idem, "", owner)
        return result

    def _resolve_reference_assets(
        self,
        reference_assets: list[str],
    ) -> tuple[bytes | None, str]:
        """Resolve the first usable reference image to ``(bytes, mime)``.

        Supports two reference forms:
        - a normal upload path (as before),
        - a ``three_view:<view>`` token (front/side/back) that resolves to the
          active persona's stored three-view reference, so图生图 can lock the
          character's appearance without the caller re-uploading the image.
        """
        for ref in reference_assets or []:
            try:
                ref_str = str(ref)
                if ref_str.startswith("three_view:"):
                    resolved = self._resolve_three_view_reference(ref_str)
                else:
                    resolved = self._resolve_upload_reference(ref_str)
                mime = _guess_mime(resolved.name)
                return resolved.read_bytes(), mime
            except Exception:
                logger.debug("image edit reference asset unusable: %s", ref, exc_info=True)
                continue
        return None, "image/png"

    def _resolve_three_view_reference(self, ref: str) -> Path:
        """Resolve ``three_view:<view>`` to the active persona's stored file."""
        view = str(ref).split(":", 1)[1] if ":" in str(ref) else ""
        from core.persona_hub import get_persona_manager

        mgr = get_persona_manager()
        pair = mgr.load_three_view(mgr.get_active_id(), view)
        if pair is None:
            raise ImageValidationError()
        # Persist to a temp file under upload_base so the read path stays
        # consistent and _url_for_upload_path (if ever needed) keeps working.
        ext = "png" if pair[1] == "image/png" else "jpg"
        tmp = self.upload_base / ".three_view" / f"{view}.{ext}"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(pair[0])
        return tmp

    def understand_image(
        self,
        *,
        image_ref: str,
        question: str,
        idempotency_key: str,
        owner_id: str = "master",
    ) -> dict[str, Any]:
        operation = "image_vision"
        if not self.feature_enabled:
            return self._disabled_result(operation)

        owner = self._normalize_owner(owner_id)
        idem = self._normalize_idempotency_key(idempotency_key)
        resolved = self._resolve_upload_reference(image_ref)
        question_text = str(question or "")
        question_sha = _sha256_text(question_text)
        image_sha = _sha256_bytes(resolved.read_bytes())
        fingerprint = _json_sha256(
            {
                "operation": operation,
                "image_sha256": image_sha,
                "question_sha256": question_sha,
                "owner_id": owner,
            }
        )
        replay = self._replay_if_existing(operation, idem, fingerprint)
        if replay is not None:
            return replay

        request_id = self.id_factory("imgvision")
        safety = self.safety_policy.review_vision_question(question_text)
        if not safety.allowed:
            result = self._base_result(
                operation=operation,
                request_id=request_id,
                idempotency_key=idem,
                status="rejected",
                safety=safety,
                owner_id=owner,
                audit={"image_sha256": image_sha, "question_sha256": question_sha},
                provider_attempted=False,
            )
            result["answer"] = ""
            self._record_result(result, operation, idem, fingerprint, owner)
            return result

        provider = self.vision_provider
        provider_id = str(getattr(provider, "provider_id", "unknown"))
        model = str(getattr(provider, "model", "unknown"))
        try:
            analyzed = provider.analyze(
                image_path=str(resolved),
                question=question_text,
                request_id=request_id,
                owner_id=owner,
            )
        except TimeoutError:
            result = self._base_result(
                operation=operation,
                request_id=request_id,
                idempotency_key=idem,
                status="timeout",
                safety=safety,
                owner_id=owner,
                audit={"image_sha256": image_sha, "question_sha256": question_sha},
                provider_attempted=True,
                provider={"id": provider_id, "model": model, "status": "timeout"},
                error_code="provider_timeout",
            )
            result["answer"] = ""
            self._record_result(result, operation, idem, fingerprint, owner)
            return result
        except Exception:
            logger.warning("image vision provider failed", exc_info=True)
            result = self._base_result(
                operation=operation,
                request_id=request_id,
                idempotency_key=idem,
                status="failed",
                safety=safety,
                owner_id=owner,
                audit={"image_sha256": image_sha, "question_sha256": question_sha},
                provider_attempted=True,
                provider={"id": provider_id, "model": model, "status": "failed"},
                error_code="provider_failed",
            )
            result["answer"] = ""
            self._record_result(result, operation, idem, fingerprint, owner)
            return result

        provider_public = {
            "id": str(analyzed.provider_id or provider_id),
            "model": str(analyzed.model or model),
            "status": str(analyzed.status or "unknown"),
        }
        if analyzed.status != "ok":
            result = self._base_result(
                operation=operation,
                request_id=request_id,
                idempotency_key=idem,
                status="failed",
                safety=safety,
                owner_id=owner,
                audit={"image_sha256": image_sha, "question_sha256": question_sha},
                provider_attempted=True,
                provider=provider_public,
                error_code=str(analyzed.error_code or analyzed.status or "provider_failed"),
            )
            result["answer"] = ""
            self._record_result(result, operation, idem, fingerprint, owner)
            return result

        result = self._base_result(
            operation=operation,
            request_id=request_id,
            idempotency_key=idem,
            status="completed",
            safety=safety,
            owner_id=owner,
            audit={"image_sha256": image_sha, "question_sha256": question_sha},
            provider_attempted=True,
            provider=provider_public,
            side_effects={
                "provider_called": True,
                "asset_created": False,
                "delivery_created": False,
            },
        )
        result["answer"] = analyzed.answer
        result["image"] = {"url": self._url_for_upload_path(resolved)}
        result["observation"] = self._build_image_observation(
            analyzed=analyzed,
            provider=provider_public,
            answer=analyzed.answer,
            image_url=result["image"]["url"],
            audit={"image_sha256": image_sha, "question_sha256": question_sha},
        )
        self._record_result(result, operation, idem, fingerprint, owner)
        return result

    def _disabled_result(self, operation: str) -> dict[str, Any]:
        return {
            "status": "disabled",
            "workflow": operation,
            "feature_flag": self.feature_flag,
            "idempotent_replay": False,
            "side_effects": dict(_NO_SIDE_EFFECTS),
            "asset": None,
            "delivery_plan": None,
        }

    def _base_result(
        self,
        *,
        operation: str,
        request_id: str,
        idempotency_key: str,
        status: str,
        safety: SafetyDecision,
        owner_id: str,
        audit: dict[str, Any],
        provider_attempted: bool,
        provider: dict[str, Any] | None = None,
        asset: dict[str, Any] | None = None,
        delivery_plan: dict[str, Any] | None = None,
        side_effects: dict[str, bool] | None = None,
        error_code: str = "",
    ) -> dict[str, Any]:
        now = self.clock()
        public_provider = provider or {
            "id": "",
            "model": "",
            "status": "not_called" if not provider_attempted else "unknown",
        }
        return {
            "status": status,
            "workflow": operation,
            "request_id": request_id,
            "idempotency_key": idempotency_key,
            "created_at": now,
            "updated_at": now,
            "feature_flag": self.feature_flag,
            "ownership": {"owner_id": owner_id},
            "safety": safety.public_dict(),
            "provider": public_provider,
            "asset": asset,
            "delivery_plan": delivery_plan,
            "side_effects": side_effects or {
                "provider_called": provider_attempted,
                "asset_created": False,
                "delivery_created": False,
            },
            "idempotent_replay": False,
            "audit": audit,
            "error_code": error_code,
        }

    def _record_result(
        self,
        result: dict[str, Any],
        operation: str,
        idempotency_key: str,
        fingerprint: str,
        owner_id: str,
    ) -> None:
        self.store.put(
            {
                "request_id": result["request_id"],
                "operation": operation,
                "idempotency_key": idempotency_key,
                "fingerprint": fingerprint,
                "owner_id": owner_id,
                "status": result["status"],
                "created_at": result["created_at"],
                "updated_at": result["updated_at"],
                "result": result,
            }
        )
        metadata = result.get("delivery_plan") or {}
        trace_id = str(idempotency_key or result.get("request_id") or "unknown")
        if trace_id.startswith("world-image:"):
            trace_id = trace_id[len("world-image:"):]
        record_image_stage(
            trace_id,
            "workflow.completed",
            status=str(result.get("status") or "unknown"),
            operation=operation,
            request_id=result.get("request_id"),
            idempotency_key=idempotency_key,
            provider=result.get("provider") or {},
            safety=result.get("safety") or {},
            asset=result.get("asset") or {},
            delivery_plan=result.get("delivery_plan") or {},
            side_effects=result.get("side_effects") or {},
            error_code=result.get("error_code") or "",
        )

    def _build_image_observation(
        self,
        *,
        analyzed: ImageVisionResult,
        provider: dict[str, Any],
        answer: str,
        image_url: str,
        audit: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = dict(analyzed.metadata or {})
        observation = dict(analyzed.observation or metadata.get("observation") or {})
        scene = observation.get("scene") or metadata.get("scene") or {}
        if not isinstance(scene, dict):
            scene = {"summary": str(scene)}
        scene = {"summary": str(answer or scene.get("summary") or ""), **scene}
        objects = observation.get("objects", metadata.get("objects", []))
        relations = observation.get("relations", metadata.get("relations", []))
        ocr_text = observation.get("ocr_text", metadata.get("ocr_text", []))
        uncertainties = observation.get(
            "uncertainties",
            metadata.get("uncertainties") or metadata.get("uncertainty") or [],
        )
        if isinstance(ocr_text, str):
            ocr_text = [ocr_text]
        if isinstance(uncertainties, str):
            uncertainties = [uncertainties]
        if not isinstance(uncertainties, list):
            uncertainties = []
        confidence = observation.get("confidence", metadata.get("confidence", 0.5))
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 0.5
            uncertainties.append("invalid_provider_confidence")
        memory_eligibility = observation.get("memory_eligibility") or metadata.get(
            "memory_eligibility"
        ) or {
            "eligible": False,
            "reason": "requires_explicit_confirmation",
        }
        return {
            "scene": scene,
            "objects": list(objects) if isinstance(objects, list) else [],
            "ocr_text": list(ocr_text) if isinstance(ocr_text, list) else [],
            "relations": list(relations) if isinstance(relations, list) else [],
            "confidence": confidence_value,
            "uncertainties": list(uncertainties),
            "provider": dict(provider),
            "memory_eligibility": dict(memory_eligibility),
            "source": {"image_url": image_url},
            "audit_refs": dict(audit),
        }

    def _replay_if_existing(
        self,
        operation: str,
        idempotency_key: str,
        fingerprint: str,
    ) -> dict[str, Any] | None:
        existing = self.store.get_by_key(operation, idempotency_key)
        if not existing:
            return None
        if existing.get("fingerprint") != fingerprint:
            raise IdempotencyConflict()
        result = copy.deepcopy(existing.get("result") or {})
        result["idempotent_replay"] = True
        result["side_effects"] = dict(_NO_SIDE_EFFECTS)
        return result

    def _persist_generated_asset(
        self,
        *,
        request_id: str,
        image_bytes: bytes,
        mime_type: str,
    ) -> dict[str, Any]:
        from core.attachment_handler import process_image_upload

        asset = process_image_upload(
            filename=f"{request_id}.png",
            content=image_bytes,
            content_type=mime_type,
            upload_base=self.upload_base,
        )
        return {
            "saved_as": asset.get("saved_as", ""),
            "url": asset.get("url", ""),
            "thumbnail_url": asset.get("thumbnail_url", ""),
            "mime_type": asset.get("mime_type", mime_type),
            "width": int(asset.get("width") or 0),
            "height": int(asset.get("height") or 0),
            "sha256": asset.get("sha256", ""),
            "deduplicated": bool(asset.get("deduplicated", False)),
            "is_image": True,
        }

    def _create_delivery_plan(
        self,
        *,
        request_id: str,
        asset: dict[str, Any],
        delivery: dict[str, Any],
    ) -> dict[str, Any]:
        channel = delivery.get("channel") or "local_chat"
        target = delivery.get("target") or ""
        return {
            "delivery_plan_id": self.id_factory("imgdelivery"),
            "request_id": request_id,
            "status": "planned",
            "channel": channel,
            "target": target,
            "asset_url": asset.get("url", ""),
            "sequence": 1,
            "external_sent": False,
        }

    def _read_generation_bytes(self, generated: ImageGenerationResult) -> bytes | None:
        if generated.image_bytes:
            return generated.image_bytes
        if generated.image_path:
            path = Path(generated.image_path)
            if path.exists() and path.is_file():
                return path.read_bytes()
        return None

    def _resolve_upload_reference(self, image_ref: str) -> Path:
        raw = str(image_ref or "").strip()
        if not raw or "\x00" in raw or "\\" in raw:
            raise ImageValidationError()
        if "://" in raw:
            raise ImageValidationError()
        normalized = raw.lstrip("/")
        if normalized.startswith("uploads/"):
            normalized = normalized[len("uploads/") :]
        if not normalized or normalized.startswith("../") or "/../" in normalized:
            raise ImageValidationError()
        try:
            target = (self.upload_base / normalized).resolve()
            target.relative_to(self.upload_base)
        except (OSError, ValueError):
            raise ImageValidationError() from None
        if not target.exists() or not target.is_file():
            raise ImageValidationError()
        return target

    def _url_for_upload_path(self, path: Path) -> str:
        try:
            rel = path.resolve().relative_to(self.upload_base).as_posix()
        except ValueError:
            raise ImageValidationError() from None
        return f"/uploads/{rel}"

    def _normalize_delivery(self, delivery: dict[str, Any] | None) -> dict[str, Any]:
        payload = delivery if isinstance(delivery, dict) else {}
        channel = str(payload.get("channel") or "local_chat")[:80]
        target = str(payload.get("target") or "")[:200]
        return {"channel": channel, "target": target}

    def _normalize_owner(self, owner_id: str) -> str:
        owner = str(owner_id or "master").strip()
        if not owner or len(owner) > 200:
            raise ImageValidationError()
        return owner

    def _normalize_idempotency_key(self, idempotency_key: str) -> str:
        idem = str(idempotency_key or "").strip()
        if not _SAFE_IDEMPOTENCY_KEY.match(idem):
            raise ImageValidationError()
        return idem

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _guess_mime(filename: str) -> str:
    """Guess a mime type from a filename suffix (defaults to PNG)."""
    suffix = Path(str(filename)).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }.get(suffix, "image/png")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_sha256(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_text(raw)
