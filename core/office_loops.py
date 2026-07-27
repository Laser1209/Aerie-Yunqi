"""P1-B.4 办公最小闭环：剪贴板翻译、截图问图、时间天气状态。

三个闭环都遵守统一规则：
- 仅在 OFFICE 模式下执行（CHAT 模式抛出 OfficeLoopError(mode_denied)）
- 每个操作写入审计日志（operation / request_id / timestamp / status）
- 翻译使用可注入的 TranslationProvider，默认 FakeTranslationProvider 不调真实 API
- 截图问图复用 P0 ImageWorkflow.understand_image
- 状态快照返回结构化时间/天气/网络/电池数据，且不泄漏路径
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)


# ── errors ────────────────────────────────────────────────────

class OfficeLoopError(Exception):
    """Raised when an office-loop operation is denied or invalid."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


# ── translation provider protocol ─────────────────────────────

class TranslationProvider(Protocol):
    provider_id: str
    model: str

    def translate(
        self,
        *,
        text: str,
        target_lang: str,
        source_lang: str,
        request_id: str,
        owner_id: str,
    ) -> dict[str, Any]: ...


class FakeTranslationProvider:
    """Default in-process fake that never calls external services.

    Used as a safe default until a real provider is wired in.
    """

    provider_id = "fake_translation"
    model = "fake-translate"

    def translate(
        self,
        *,
        text: str,
        target_lang: str,
        source_lang: str,
        request_id: str,
        owner_id: str,
    ) -> dict[str, Any]:
        return {
            "status": "ok",
            "provider_id": self.provider_id,
            "model": self.model,
            "original_text": text,
            "translated_text": f"[FAKE:{target_lang}] {text[:80]}",
            "source_lang": source_lang,
            "target_lang": target_lang,
        }


# ── safety ────────────────────────────────────────────────────

_SENSITIVE_PATTERNS = (
    re.compile(r"api[\s_-]?key", re.IGNORECASE),
    re.compile(r"secret[\s_-]?(token|key)?", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"凭据|密钥|密码|口令"),
)

_MAX_TRANSLATE_CHARS = 2000


def _is_sensitive_text(text: str) -> bool:
    return any(p.search(text) for p in _SENSITIVE_PATTERNS)


def _redact_path_leak(value: Any) -> Any:
    """Recursively strip path-like strings from snapshot payloads."""
    if isinstance(value, str):
        # drop common absolute path prefixes / home dirs / office dir
        cleaned = value
        for pat in (
            r"[A-Za-z]:\\[^\s\"']*",
            r"/home/[^\s\"']*",
            r"/Users/[^\s\"']*",
            r"~[\\/][^\s\"']*",
            r"AerieOffice",
        ):
            cleaned = re.sub(pat, "<redacted>", cleaned)
        return cleaned
    if isinstance(value, dict):
        return {k: _redact_path_leak(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_path_leak(v) for v in value]
    return value


# ── office loops ──────────────────────────────────────────────

class OfficeLoops:
    """最小办公闭环 facade。"""

    def __init__(
        self,
        *,
        mode_manager: Any,
        action_registry: Any,
        image_workflow: Any,
        translation_provider: TranslationProvider | None = None,
        weather_provider: Callable[[], dict[str, Any]] | None = None,
        system_probe: Callable[[], dict[str, Any]] | None = None,
        clock: Callable[[], datetime] | None = None,
        audit_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._mode_manager = mode_manager
        self._action_registry = action_registry
        self._image_workflow = image_workflow
        self._translator = translation_provider or FakeTranslationProvider()
        self._weather_provider = weather_provider or (lambda: {
            "city": "上海",
            "temp": "—",
            "desc": "—",
            "humidity": "",
            "wind": "",
        })
        self._system_probe = system_probe or (lambda: {
            "network": "unknown",
            "battery_percent": None,
            "power_plugged": None,
        })
        self._clock = clock or datetime.now
        self._audit_sink = audit_sink
        self.audit_log: list[dict[str, Any]] = []

    # ── mode guard ────────────────────────────────────────────

    def _require_office(self) -> None:
        ctx = self._mode_manager.get_context()
        if not ctx.is_office_mode():
            raise OfficeLoopError("mode_denied", "office loops only available in OFFICE mode")

    def _audit(self, operation: str, status: str, **extra: Any) -> None:
        entry = {
            "operation": operation,
            "request_id": extra.get("request_id") or f"audit_{uuid.uuid4().hex[:12]}",
            "timestamp": self._clock().isoformat(timespec="seconds"),
            "status": status,
            **{k: v for k, v in extra.items() if k != "request_id"},
        }
        self.audit_log.append(entry)
        if self._audit_sink is not None:
            try:
                self._audit_sink(entry)
            except Exception:  # noqa: BLE001 - audit never breaks primary flow
                logger.warning("audit sink failed", exc_info=True)

    # ── 1. clipboard translation ─────────────────────────────

    def translate_clipboard(
        self,
        *,
        clipboard_candidate: str,
        target_lang: str = "zh",
        source_lang: str = "auto",
        idempotency_key: str = "",
        owner_id: str = "master",
    ) -> dict[str, Any]:
        self._require_office()

        request_id = f"translate_{uuid.uuid4().hex[:12]}"
        text = (clipboard_candidate or "").strip()

        if not text:
            self._audit(
                "clipboard_translate",
                "skipped",
                request_id=request_id,
                reason="empty_clipboard",
            )
            return {
                "status": "skipped",
                "reason": "empty_clipboard",
                "request_id": request_id,
            }

        if len(text) > _MAX_TRANSLATE_CHARS:
            self._audit(
                "clipboard_translate",
                "rejected",
                request_id=request_id,
                reason="text_too_long",
                length=len(text),
            )
            return {
                "status": "rejected",
                "reason": "text_too_long",
                "request_id": request_id,
            }

        if _is_sensitive_text(text):
            self._audit(
                "clipboard_translate",
                "rejected",
                request_id=request_id,
                reason="sensitive_content",
            )
            return {
                "status": "rejected",
                "reason": "sensitive_content",
                "request_id": request_id,
            }

        try:
            result = self._translator.translate(
                text=text,
                target_lang=target_lang,
                source_lang=source_lang,
                request_id=request_id,
                owner_id=owner_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("clipboard translate failed", exc_info=True)
            self._audit(
                "clipboard_translate",
                "failed",
                request_id=request_id,
                error=str(exc)[:200],
            )
            return {
                "status": "failed",
                "reason": "provider_error",
                "request_id": request_id,
            }

        payload = {
            "status": "ok",
            "request_id": request_id,
            "original_text": text,
            "translated_text": result.get("translated_text", ""),
            "source_lang": result.get("source_lang", source_lang),
            "target_lang": result.get("target_lang", target_lang),
            "provider_id": result.get("provider_id", getattr(self._translator, "provider_id", "unknown")),
            "model": result.get("model", getattr(self._translator, "model", "unknown")),
        }
        self._audit("clipboard_translate", "ok", request_id=request_id)
        return payload

    # ── 2. screenshot inquire ────────────────────────────────

    def inquire_screenshot(
        self,
        *,
        screenshot_path: str,
        question: str = "请描述这张截图的内容",
        idempotency_key: str = "",
        owner_id: str = "master",
    ) -> dict[str, Any]:
        self._require_office()

        request_id = f"shot_{uuid.uuid4().hex[:12]}"
        raw_path = (screenshot_path or "").strip()

        if not raw_path:
            self._audit(
                "screenshot_inquire",
                "rejected",
                request_id=request_id,
                reason="missing_path",
            )
            return {
                "status": "rejected",
                "reason": "missing_path",
                "request_id": request_id,
            }

        # path-traversal guard: only accept absolute existing files under upload_base
        try:
            p = Path(raw_path)
            if not p.is_absolute() or not p.exists() or not p.is_file():
                self._audit(
                    "screenshot_inquire",
                    "rejected",
                    request_id=request_id,
                    reason="invalid_path",
                )
                return {"status": "rejected", "reason": "invalid_path", "request_id": request_id}
            upload_base = self._image_workflow.upload_base.resolve()
            resolved = p.resolve()
            resolved.relative_to(upload_base)
        except (ValueError, OSError):
            self._audit(
                "screenshot_inquire",
                "rejected",
                request_id=request_id,
                reason="path_traversal",
            )
            return {"status": "rejected", "reason": "path_traversal", "request_id": request_id}

        idem = idempotency_key or f"shot_{uuid.uuid4().hex[:16]}"
        try:
            rel = resolved.relative_to(upload_base).as_posix()
        except ValueError:
            rel = resolved.name

        result = self._image_workflow.understand_image(
            image_ref=rel,
            question=question,
            idempotency_key=idem[:200],
            owner_id=owner_id,
        )

        status = str(result.get("status", "failed"))
        self._audit(
            "screenshot_inquire",
            status,
            request_id=result.get("request_id", request_id),
        )
        return result

    # ── 3. status snapshot ───────────────────────────────────

    def get_status_snapshot(self) -> dict[str, Any]:
        self._require_office()

        request_id = f"status_{uuid.uuid4().hex[:12]}"
        now = self._clock()

        try:
            weather = self._weather_provider()
        except Exception as exc:  # noqa: BLE001
            logger.warning("weather provider failed", exc_info=True)
            weather = {"city": "—", "temp": "—", "desc": "获取失败", "humidity": "", "wind": "", "error": str(exc)[:80]}

        try:
            system = self._system_probe()
        except Exception as exc:  # noqa: BLE001
            logger.warning("system probe failed", exc_info=True)
            system = {"network": "unknown", "battery_percent": None, "power_plugged": None, "error": str(exc)[:80]}

        snapshot = {
            "status": "ok",
            "request_id": request_id,
            "time": {
                "iso": now.isoformat(timespec="seconds"),
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M:%S"),
                "weekday": now.strftime("%A"),
                "timezone": "local",
            },
            "weather": {
                "city": str(weather.get("city", "—")),
                "temp": str(weather.get("temp", "—")),
                "desc": str(weather.get("desc", "—")),
                "humidity": str(weather.get("humidity", "")),
                "wind": str(weather.get("wind", "")),
            },
            "network": {
                "state": str(system.get("network", "unknown")),
            },
            "battery": {
                "percent": system.get("battery_percent"),
                "power_plugged": system.get("power_plugged"),
            },
        }

        cleaned = _redact_path_leak(snapshot)
        self._audit("status_snapshot", "ok", request_id=request_id)
        return cleaned
