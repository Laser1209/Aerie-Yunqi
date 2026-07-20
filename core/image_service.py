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
import hashlib
import json
import logging
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

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


class BrainImageGenerationProvider:
    """Adapter around the legacy ``Brain.generate_image`` surface."""

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
        if self.brain is None or not hasattr(self.brain, "generate_image"):
            return ImageGenerationResult(
                status="unavailable",
                provider_id=self.provider_id,
                model=self.model,
                error_code="brain_unavailable",
            )
        raw = self.brain.generate_image(prompt)
        if not isinstance(raw, dict):
            return ImageGenerationResult(
                status="failed",
                provider_id=self.provider_id,
                model=self.model,
                error_code="invalid_provider_response",
            )
        provider_id = str(raw.get("provider") or self.provider_id)
        model = str(raw.get("model") or self.model)
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
        return ImageGenerationResult(
            status="unavailable",
            provider_id=provider_id,
            model=model,
            error_code=str(raw.get("status") or "provider_unavailable"),
        )


class BrainImageVisionProvider:
    """Adapter around the legacy ``Brain.see_image`` surface."""

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
    ) -> None:
        self.upload_base = Path(upload_base)
        if not self.upload_base.is_absolute():
            self.upload_base = (Path.cwd() / self.upload_base).resolve()
        else:
            self.upload_base = self.upload_base.resolve()
        self.feature_enabled = bool(feature_enabled)
        self.generation_provider = generation_provider or BrainImageGenerationProvider(None)
        self.vision_provider = vision_provider or BrainImageVisionProvider(None)
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

        provider = self.generation_provider
        provider_id = str(getattr(provider, "provider_id", "unknown"))
        model = str(getattr(provider, "model", "unknown"))
        metadata_payload = {
            "conversation_id": conversation_id or "",
            "idempotency_key": idem,
            "prompt_sha256": prompt_sha,
            **(metadata or {}),
        }

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
        self._record_result(result, operation, idem, fingerprint, owner)
        return result

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


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_sha256(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_text(raw)
