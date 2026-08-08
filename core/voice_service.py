"""Task P1-D.1 — Voice ASR/TTS 三服务边界.

参照 core/image_service.py 的分层风格，把语音能力拆成三个清晰的服务接口:

1. VoiceProfile           — 声音身份与韵律配置 (dataclass)
2. SpeechMarkup           — 待合成的文本及语气/停顿/重音标记 (dataclass)
3. VoiceDeliveryPolicy    — 语音投递策略 (Protocol, 提供 DefaultVoiceDeliveryPolicy)

在服务接口之上，提供:
- 本地 ASR/TTS 桩适配层 (LocalAsrProvider / LocalTtsProvider)，不调用真实模型/API
- 语音开关 (VoiceSwitch) 与审计记录 (VoiceAuditStore)
- VoiceService 门面: 受 feature flag 与投递策略约束，全程记录审计

本模块刻意不向任何外部通道发送语音，也不会调用真实 ASR/TTS 服务；
调用方后续可自行接入真实 provider 而无需改动门面流程。
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class VoiceGender(str, Enum):
    FEMALE = "female"
    MALE = "male"
    NEUTRAL = "neutral"


# ── 服务接口 1: VoiceProfile ───────────────────────
@dataclass(frozen=True)
class VoiceProfile:
    """声音身份与韵律配置。"""

    voice_id: str
    name: str = ""
    gender: VoiceGender = VoiceGender.NEUTRAL
    style: str = "warm"
    pitch: float = 1.0
    speed: float = 1.0
    volume: float = 0.8
    locale: str = "zh-CN"


# ── 服务接口 2: SpeechMarkup ───────────────────────
@dataclass(frozen=True)
class SpeechMarkup:
    """待合成的文本及语气/重音/停顿标记。"""

    text: str
    style: str = "warm"
    emphasis: tuple[str, ...] = ()
    pause_before_ms: int = 0
    pause_after_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


# ── 服务接口 3: VoiceDeliveryPolicy ────────────────
class VoiceDeliveryPolicy(Protocol):
    """语音投递策略接口。"""

    def allows(self, *, channel: str) -> bool: ...

    def should_deliver(self, *, text: str) -> bool: ...


@dataclass(frozen=True)
class DefaultVoiceDeliveryPolicy:
    """默认投递策略: 仅放行语音通道，且受开关与文本长度约束。"""

    enabled: bool = True
    allowed_channels: tuple[str, ...] = ("voice_chat", "voice_note")
    max_text_len: int = 500

    def allows(self, *, channel: str) -> bool:
        return self.enabled and channel in self.allowed_channels

    def should_deliver(self, *, text: str) -> bool:
        return self.enabled and bool(text) and len(text) <= self.max_text_len


# ── ASR 桩适配层 ───────────────────────────────────
@dataclass
class AsrTranscript:
    status: str
    text: str = ""
    language: str = "zh-CN"
    confidence: float = 0.0
    duration_sec: float = 0.0
    provider_id: str = "unknown"
    model: str = "unknown"
    error_code: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class AsrProvider(Protocol):
    provider_id: str
    model: str

    def transcribe(
        self,
        *,
        audio_ref: str,
        request_id: str,
        owner_id: str,
        metadata: dict[str, Any],
    ) -> AsrTranscript: ...


class LocalAsrProvider:
    """本地 ASR 桩: 不调用真实服务，返回确定性转写文本。"""

    provider_id = "local_asr_stub"
    model = "stub-v1"

    def __init__(self, transcript: str = "") -> None:
        self.transcript = transcript

    def transcribe(
        self,
        *,
        audio_ref: str,
        request_id: str,
        owner_id: str,
        metadata: dict[str, Any],
    ) -> AsrTranscript:
        text = self.transcript or f"local transcript for {audio_ref}"
        return AsrTranscript(
            status="ok",
            text=text,
            confidence=0.9,
            duration_sec=max(0.0, len(text) * 0.1),
            provider_id=self.provider_id,
            model=self.model,
            metadata={"request_id": request_id, "owner_id": owner_id},
        )


# ── TTS 桩适配层 ───────────────────────────────────
@dataclass
class TtsSynthesis:
    status: str
    audio_name: str = ""
    text: str = ""
    provider_id: str = "unknown"
    model: str = "unknown"
    duration_sec: float = 0.0
    error_code: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class TtsProvider(Protocol):
    provider_id: str
    model: str

    def synthesize(
        self,
        *,
        markup: SpeechMarkup,
        request_id: str,
        owner_id: str,
        metadata: dict[str, Any],
    ) -> TtsSynthesis: ...


class LocalTtsProvider:
    """本地 TTS 桩: 不调用真实服务，返回确定性合成元数据。"""

    provider_id = "local_tts_stub"
    model = "stub-v1"

    def synthesize(
        self,
        *,
        markup: SpeechMarkup,
        request_id: str,
        owner_id: str,
        metadata: dict[str, Any],
    ) -> TtsSynthesis:
        text = markup.text or ""
        return TtsSynthesis(
            status="ok",
            audio_name=f"tts_{request_id}.wav",
            text=text,
            provider_id=self.provider_id,
            model=self.model,
            duration_sec=max(0.0, len(text) * 0.1),
            metadata={
                "request_id": request_id,
                "owner_id": owner_id,
                "style": markup.style,
            },
        )


# ── 审计记录 ───────────────────────────────────────
@dataclass
class VoiceAuditEntry:
    operation: str
    request_id: str
    owner_id: str
    status: str
    created_at: str
    detail: dict[str, Any] = field(default_factory=dict)


class VoiceAuditStore:
    """内存审计存储，供测试与轻量调用方使用。"""

    def __init__(self) -> None:
        self._entries: list[VoiceAuditEntry] = []

    def add(self, entry: VoiceAuditEntry) -> None:
        self._entries.append(entry)

    def recent(self, limit: int | None = None) -> list[VoiceAuditEntry]:
        if limit is None:
            return list(self._entries)
        return list(self._entries[-limit:])


# ── 语音开关 ───────────────────────────────────────
class VoiceSwitch:
    """语音开关: 记录每次有效切换的审计信息。"""

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = bool(enabled)
        self._audit: list[dict[str, Any]] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(
        self,
        enabled: bool,
        *,
        reason: str = "",
        actor: str = "system",
    ) -> bool:
        enabled = bool(enabled)
        if enabled == self._enabled:
            return False
        self._enabled = enabled
        self._audit.append(
            {
                "operation": "voice_switch",
                "enabled": enabled,
                "reason": reason,
                "actor": actor,
            }
        )
        return True

    def toggle_audit(self) -> list[dict[str, Any]]:
        return list(self._audit)


# ── VoiceService 门面 ──────────────────────────────
class VoiceService:
    """可审计的语音门面，供 API 与测试调用。

    不直接调用真实 provider; 桩 provider 与真实 provider 均实现相同协议。
    """

    feature_flag = "voice_service_v1"

    def __init__(
        self,
        *,
        feature_enabled: bool = False,
        asr_provider: AsrProvider | None = None,
        tts_provider: TtsProvider | None = None,
        delivery_policy: VoiceDeliveryPolicy | None = None,
        switch: VoiceSwitch | None = None,
        audit_store: VoiceAuditStore | None = None,
        id_factory: Any | None = None,
        clock: Any | None = None,
    ) -> None:
        self.feature_enabled = bool(feature_enabled)
        self.asr_provider = asr_provider or LocalAsrProvider()
        self.tts_provider = tts_provider or LocalTtsProvider()
        self.delivery_policy = delivery_policy or DefaultVoiceDeliveryPolicy()
        self.switch = switch or VoiceSwitch()
        self.audit_store = audit_store or VoiceAuditStore()
        self.id_factory = id_factory or (lambda prefix: f"{prefix}_{uuid.uuid4().hex}")
        self.clock = clock or self._now

    # 语音开关
    def set_voice_enabled(
        self,
        enabled: bool,
        *,
        reason: str = "",
        actor: str = "system",
    ) -> bool:
        return self.switch.set_enabled(enabled, reason=reason, actor=actor)

    def is_voice_enabled(self) -> bool:
        return self.switch.enabled

    # 审计查询
    def audit_entries(self) -> list[VoiceAuditEntry]:
        return self.audit_store.recent()

    # ASR
    def transcribe_audio(
        self,
        *,
        audio_ref: str,
        owner_id: str = "master",
        channel: str = "voice_chat",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        operation = "voice_asr"
        if not self.feature_enabled:
            return self._disabled_result(operation)

        request_id = self.id_factory("asr")
        allowed = self._delivery_allows(channel)
        if not allowed:
            result = self._base_result(
                operation=operation,
                request_id=request_id,
                owner_id=owner_id,
                status="rejected",
                channel=channel,
                side_effects={"provider_called": False},
                error_code="delivery_policy_rejected",
            )
            self._record(operation, request_id, owner_id, result)
            return result

        transcript = self.asr_provider.transcribe(
            audio_ref=str(audio_ref or ""),
            request_id=request_id,
            owner_id=owner_id,
            metadata=dict(metadata or {}),
        )
        result = self._base_result(
            operation=operation,
            request_id=request_id,
            owner_id=owner_id,
            status="completed" if transcript.status == "ok" else "failed",
            channel=channel,
            side_effects={"provider_called": True},
            transcript={
                "text": transcript.text,
                "language": transcript.language,
                "confidence": transcript.confidence,
                "duration_sec": transcript.duration_sec,
                "provider": {
                    "id": transcript.provider_id,
                    "model": transcript.model,
                },
            },
            error_code=transcript.error_code,
        )
        self._record(operation, request_id, owner_id, result)
        return result

    # TTS
    def synthesize_speech(
        self,
        *,
        markup: SpeechMarkup,
        owner_id: str = "master",
        channel: str = "voice_chat",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        operation = "voice_tts"
        if not self.feature_enabled:
            return self._disabled_result(operation)

        request_id = self.id_factory("tts")
        if not self._delivery_allows(channel) or not self.delivery_policy.should_deliver(
            text=markup.text
        ):
            result = self._base_result(
                operation=operation,
                request_id=request_id,
                owner_id=owner_id,
                status="rejected",
                channel=channel,
                side_effects={"provider_called": False},
                error_code="delivery_policy_rejected",
            )
            self._record(operation, request_id, owner_id, result)
            return result

        synthesis = self.tts_provider.synthesize(
            markup=markup,
            request_id=request_id,
            owner_id=owner_id,
            metadata=dict(metadata or {}),
        )
        result = self._base_result(
            operation=operation,
            request_id=request_id,
            owner_id=owner_id,
            status="completed" if synthesis.status == "ok" else "failed",
            channel=channel,
            side_effects={"provider_called": True},
            synthesis={
                "audio_name": synthesis.audio_name,
                "text": synthesis.text,
                "duration_sec": synthesis.duration_sec,
                "provider": {
                    "id": synthesis.provider_id,
                    "model": synthesis.model,
                },
            },
            error_code=synthesis.error_code,
        )
        self._record(operation, request_id, owner_id, result)
        return result

    # 内部辅助
    def _delivery_allows(self, channel: str) -> bool:
        return self.switch.enabled and self.delivery_policy.allows(channel=channel)

    def _disabled_result(self, operation: str) -> dict[str, Any]:
        return {
            "status": "disabled",
            "workflow": operation,
            "feature_flag": self.feature_flag,
            "side_effects": {"provider_called": False},
        }

    def _base_result(
        self,
        *,
        operation: str,
        request_id: str,
        owner_id: str,
        status: str,
        channel: str,
        side_effects: dict[str, bool],
        transcript: dict[str, Any] | None = None,
        synthesis: dict[str, Any] | None = None,
        error_code: str = "",
    ) -> dict[str, Any]:
        now = self.clock()
        return {
            "status": status,
            "workflow": operation,
            "request_id": request_id,
            "created_at": now,
            "feature_flag": self.feature_flag,
            "ownership": {"owner_id": owner_id},
            "delivery": {"channel": channel, "allowed": self._delivery_allows(channel)},
            "transcript": transcript,
            "synthesis": synthesis,
            "side_effects": side_effects,
            "error_code": error_code,
        }

    def _record(
        self,
        operation: str,
        request_id: str,
        owner_id: str,
        result: dict[str, Any],
    ) -> None:
        self.audit_store.add(
            VoiceAuditEntry(
                operation=operation,
                request_id=request_id,
                owner_id=owner_id,
                status=result["status"],
                created_at=result["created_at"],
                detail={"workflow": operation, "error_code": result.get("error_code", "")},
            )
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
