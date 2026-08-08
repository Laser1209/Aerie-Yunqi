"""Task P1-D.3 — 克隆音色高敏感评审.

基于 core/voice_service.py 的 VoiceProfile 结构，实现克隆音色的高敏感数据
全流程管理。**刻意不调用任何真实模型/API**，全部为本地桩。

覆盖流程:
- upload    上传克隆音色（仅登记元数据 + 生物特征引用）
- authorize 签发带过期时间的授权令牌
- preview   试听（需有效且未过期的令牌）
- revoke    撤销令牌
- delete    删除音色（抹除生物特征引用、撤销全部令牌）
- audit     全程审计记录

安全审查边界:
1. 生物特征数据（biometric_ref 指向的样本）**绝不写入长期记忆**，
   仅把脱敏元数据通过 memory 桩持久化。
2. 暴露给 Renderer 的载荷（to_renderer_payload）**不含任何生物特征或令牌**，
   仅含展示所需字段。

本模块不向外部通道发送任何语音，也不会调用真实克隆模型。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Protocol

from core.voice_service import VoiceProfile

logger = logging.getLogger(__name__)


class CloneVoiceStatus(str, Enum):
    """克隆音色的生命周期状态。"""

    PENDING = "pending"
    AUTHORIZED = "authorized"
    REVOKED = "revoked"
    DELETED = "deleted"


# ── 长期记忆桩接口 ────────────────────────────────
class LongTermMemory(Protocol):
    """长期记忆写入接口。服务只通过该接口持久化脱敏元数据。"""

    def remember(self, *, key: str, data: dict) -> None: ...


class _NoopMemory:
    """默认空实现，不持久化任何内容。"""

    def remember(self, *, key: str, data: dict) -> None:
        del key, data


# ── 数据模型 ───────────────────────────────────────
@dataclass
class CloneVoiceRecord:
    """克隆音色记录。biometric_ref 为易失的敏感引用，删除时被抹除。"""

    voice_id: str
    owner_id: str
    name: str
    status: CloneVoiceStatus
    created_at: str
    profile: VoiceProfile | None = None
    biometric_ref: str = ""


@dataclass
class CloneVoiceToken:
    """授权令牌，携带过期时间，可被撤销。"""

    token_id: str
    voice_id: str
    owner_id: str
    issued_at: datetime
    expires_at: datetime
    revoked: bool = False


@dataclass
class CloneVoiceAuditEntry:
    """审计记录。"""

    operation: str
    voice_id: str
    owner_id: str
    status: str
    created_at: str
    detail: dict[str, Any] = field(default_factory=dict)


# ── 服务门面 ───────────────────────────────────────
class CloneVoiceService:
    """克隆音色高敏感数据管理门面（本地桩，不调用真实模型）。"""

    feature_flag = "clone_voice_v1"

    def __init__(
        self,
        *,
        memory: LongTermMemory | None = None,
        id_factory: Callable[[str], str] | None = None,
        clock: Callable[[], datetime] | None = None,
        default_token_ttl_sec: int = 3600,
    ) -> None:
        self.memory = memory or _NoopMemory()
        self.id_factory = id_factory or (
            lambda prefix: f"{prefix}_{uuid.uuid4().hex}"
        )
        self.clock = clock or self._now
        self.default_token_ttl_sec = int(default_token_ttl_sec)

        self._records: dict[str, CloneVoiceRecord] = {}
        self._tokens: dict[str, CloneVoiceToken] = {}
        self._audit: list[CloneVoiceAuditEntry] = []

    # ── 上传 ───────────────────────────────────────
    def upload(
        self,
        *,
        owner_id: str,
        name: str,
        biometric_ref: str,
        profile: VoiceProfile | None = None,
    ) -> CloneVoiceRecord:
        voice_id = self.id_factory("clone")
        created_at = self.clock().isoformat()
        record = CloneVoiceRecord(
            voice_id=voice_id,
            owner_id=owner_id,
            name=name,
            status=CloneVoiceStatus.PENDING,
            created_at=created_at,
            profile=profile,
            biometric_ref=biometric_ref,
        )
        self._records[voice_id] = record

        # 安全边界: 仅将脱敏元数据写入长期记忆，绝不包含生物特征。
        self.memory.remember(
            key=f"clone_voice:{voice_id}",
            data={
                "voice_id": voice_id,
                "owner_id": owner_id,
                "name": name,
                "status": record.status.value,
                "created_at": created_at,
            },
        )
        self._record("clone_upload", voice_id, owner_id, "ok")
        return record

    # ── 授权 ───────────────────────────────────────
    def authorize(
        self,
        *,
        voice_id: str,
        owner_id: str,
        ttl_sec: int | None = None,
    ) -> CloneVoiceToken:
        ttl = int(ttl_sec) if ttl_sec is not None else self.default_token_ttl_sec
        now = self.clock()
        token = CloneVoiceToken(
            token_id=self.id_factory("tok"),
            voice_id=voice_id,
            owner_id=owner_id,
            issued_at=now,
            expires_at=now + timedelta(seconds=ttl),
        )
        self._tokens[token.token_id] = token
        record = self._records.get(voice_id)
        if record is not None and record.status == CloneVoiceStatus.PENDING:
            record.status = CloneVoiceStatus.AUTHORIZED
        self._record("clone_authorize", voice_id, owner_id, "ok")
        return token

    # ── 试听 ───────────────────────────────────────
    def preview(self, *, voice_id: str, token_id: str) -> dict[str, Any]:
        record = self._records.get(voice_id)
        token = self._tokens.get(token_id)
        if record is None or token is None:
            self._record(
                "clone_preview",
                voice_id,
                token.owner_id if token else "",
                "rejected",
                error_code="not_found",
            )
            return {"status": "rejected", "error_code": "not_found"}

        if not self._token_valid(token, voice_id):
            self._record(
                "clone_preview",
                voice_id,
                token.owner_id,
                "rejected",
                error_code="unauthorized",
            )
            return {"status": "rejected", "error_code": "unauthorized"}

        if record.status != CloneVoiceStatus.AUTHORIZED:
            self._record(
                "clone_preview",
                voice_id,
                token.owner_id,
                "rejected",
                error_code="not_available",
            )
            return {"status": "rejected", "error_code": "not_available"}

        # 本地桩: 返回确定性合成试听引用，绝不回传生物特征原文。
        result = {
            "status": "ok",
            "voice_id": voice_id,
            "audio_ref": f"preview:{voice_id}.wav",
        }
        self._record("clone_preview", voice_id, token.owner_id, "ok")
        return result

    # ── 撤销 ───────────────────────────────────────
    def revoke(self, *, token_id: str) -> bool:
        token = self._tokens.get(token_id)
        if token is None or token.revoked:
            return False
        token.revoked = True
        self._record("clone_revoke", token.voice_id, token.owner_id, "ok")
        return True

    # ── 删除 ───────────────────────────────────────
    def delete(self, *, voice_id: str, owner_id: str) -> bool:
        record = self._records.get(voice_id)
        if record is None:
            return False
        # 安全边界: 抹除生物特征引用。
        record.biometric_ref = ""
        record.status = CloneVoiceStatus.DELETED
        # 撤销该音色的全部令牌。
        for token in self._tokens.values():
            if token.voice_id == voice_id:
                token.revoked = True
        self._record("clone_delete", voice_id, owner_id, "ok")
        return True

    # ── 查询 ───────────────────────────────────────
    def get(self, *, voice_id: str) -> CloneVoiceRecord | None:
        return self._records.get(voice_id)

    def to_renderer_payload(self, *, voice_id: str) -> dict[str, Any]:
        """暴露给 Renderer 的脱敏载荷: 仅展示字段，不含生物特征/令牌。"""
        record = self._records.get(voice_id)
        if record is None:
            return {"error": "not_found"}
        return {
            "voice_id": record.voice_id,
            "name": record.name,
            "status": record.status.value,
            "created_at": record.created_at,
            "owner_id": record.owner_id,
            "display": "clone_voice",
        }

    def audit_entries(self) -> list[CloneVoiceAuditEntry]:
        return list(self._audit)

    # ── 内部辅助 ───────────────────────────────────
    def _token_valid(self, token: CloneVoiceToken, voice_id: str) -> bool:
        return (
            token.token_id in self._tokens
            and not token.revoked
            and token.voice_id == voice_id
            and self.clock() <= token.expires_at
        )

    def _record(
        self,
        operation: str,
        voice_id: str,
        owner_id: str,
        status: str,
        *,
        error_code: str = "",
    ) -> None:
        self._audit.append(
            CloneVoiceAuditEntry(
                operation=operation,
                voice_id=voice_id,
                owner_id=owner_id,
                status=status,
                created_at=self.clock().isoformat(),
                detail={"error_code": error_code},
            )
        )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)
