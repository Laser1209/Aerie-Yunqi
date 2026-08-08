"""TDD tests for Task P1-D.3: 克隆音色高敏感评审.

覆盖:
  - 克隆音色上传/试听/授权/撤销/删除/审计全流程 (本地桩, 不调用真实模型/API)
  - 授权令牌与过期机制
  - 安全审查边界:
      * 生物特征数据不写入长期记忆 (仅写入脱敏元数据)
      * 生物特征数据不暴露到 Renderer (脱敏展示载荷)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.clone_voice_service import (
    CloneVoiceService,
    CloneVoiceStatus,
)
from core.voice_service import VoiceProfile


# ── 测试辅助 ───────────────────────────────────────
class FakeClock:
    """可控时钟, 便于验证令牌过期。"""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now += timedelta(seconds=seconds)


class RecordingMemory:
    """长期记忆桩: 记录所有被写入的键值。"""

    def __init__(self) -> None:
        self.items: list[dict] = []

    def remember(self, *, key: str, data: dict) -> None:
        self.items.append({"key": key, "data": data})


START = datetime(2026, 7, 20, 0, 0, 0, tzinfo=timezone.utc)


def _service(**kw) -> CloneVoiceService:
    kw.setdefault("clock", FakeClock(START))
    return CloneVoiceService(**kw)


# ── 1. 上传 ───────────────────────────────────────
def test_upload_creates_record_without_real_model():
    svc = _service()
    rec = svc.upload(
        owner_id="master",
        name="Yita clone",
        biometric_ref="uploads/samples/yita.wav",
    )
    assert rec.voice_id
    assert rec.owner_id == "master"
    assert rec.name == "Yita clone"
    assert rec.status == CloneVoiceStatus.PENDING
    assert rec.biometric_ref == "uploads/samples/yita.wav"


def test_upload_records_audit():
    svc = _service()
    rec = svc.upload(owner_id="master", name="Yita", biometric_ref="x.wav")
    ops = [e.operation for e in svc.audit_entries()]
    assert "clone_upload" in ops
    assert any(e.voice_id == rec.voice_id for e in svc.audit_entries())


# ── 2. 安全边界: 生物特征不写入长期记忆 ─────────────
def test_upload_persists_only_sanitized_metadata_to_long_term_memory():
    mem = RecordingMemory()
    svc = _service(memory=mem)
    svc.upload(
        owner_id="master",
        name="Yita",
        biometric_ref="secret/voice.bin",
    )
    assert mem.items  # 有元数据写入长期记忆
    raw = str(mem.items)
    assert "secret/voice.bin" not in raw
    assert "biometric" not in raw.lower()
    assert "Yita" in raw  # 非敏感元数据可写入


def test_biometric_never_persisted_across_full_lifecycle():
    mem = RecordingMemory()
    svc = _service(memory=mem)
    rec = svc.upload(
        owner_id="master",
        name="Yita",
        biometric_ref="secret/voice.bin",
    )
    token = svc.authorize(voice_id=rec.voice_id, owner_id="master")
    svc.preview(voice_id=rec.voice_id, token_id=token.token_id)
    svc.delete(voice_id=rec.voice_id, owner_id="master")

    raw = str(mem.items)
    assert "secret/voice.bin" not in raw
    assert "biometric" not in raw.lower()


# ── 3. 授权令牌与过期 ──────────────────────────────
def test_authorize_issues_expiring_token():
    svc = _service()
    rec = svc.upload(owner_id="master", name="Yita", biometric_ref="x.wav")
    token = svc.authorize(voice_id=rec.voice_id, owner_id="master", ttl_sec=3600)
    assert token.token_id
    assert token.voice_id == rec.voice_id
    assert token.expires_at > token.issued_at


def test_preview_requires_valid_token_and_authorized_status():
    svc = _service()
    rec = svc.upload(owner_id="master", name="Yita", biometric_ref="x.wav")
    token = svc.authorize(voice_id=rec.voice_id, owner_id="master")
    result = svc.preview(voice_id=rec.voice_id, token_id=token.token_id)
    assert result["status"] == "ok"
    assert result["voice_id"] == rec.voice_id
    assert result["audio_ref"]


def test_preview_rejects_expired_token():
    clock = FakeClock(START)
    svc = _service(clock=clock)
    rec = svc.upload(owner_id="master", name="Yita", biometric_ref="x.wav")
    token = svc.authorize(
        voice_id=rec.voice_id, owner_id="master", ttl_sec=60
    )
    clock.advance(61)
    result = svc.preview(voice_id=rec.voice_id, token_id=token.token_id)
    assert result["status"] == "rejected"
    assert result["error_code"] == "unauthorized"


def test_preview_rejects_revoked_token():
    svc = _service()
    rec = svc.upload(owner_id="master", name="Yita", biometric_ref="x.wav")
    token = svc.authorize(voice_id=rec.voice_id, owner_id="master")
    assert svc.revoke(token_id=token.token_id) is True
    result = svc.preview(voice_id=rec.voice_id, token_id=token.token_id)
    assert result["status"] == "rejected"
    assert result["error_code"] == "unauthorized"


def test_preview_rejects_unknown_token():
    svc = _service()
    rec = svc.upload(owner_id="master", name="Yita", biometric_ref="x.wav")
    result = svc.preview(voice_id=rec.voice_id, token_id="nope")
    assert result["status"] == "rejected"


# ── 4. 撤销 ───────────────────────────────────────
def test_revoke_invalidates_token():
    svc = _service()
    rec = svc.upload(owner_id="master", name="Yita", biometric_ref="x.wav")
    token = svc.authorize(voice_id=rec.voice_id, owner_id="master")
    assert token.revoked is False
    assert svc.revoke(token_id=token.token_id) is True
    assert token.revoked is True


# ── 5. 删除 ───────────────────────────────────────
def test_delete_wipes_biometric_and_revokes_tokens():
    svc = _service()
    rec = svc.upload(
        owner_id="master",
        name="Yita",
        biometric_ref="secret/voice.bin",
    )
    t1 = svc.authorize(voice_id=rec.voice_id, owner_id="master")
    t2 = svc.authorize(voice_id=rec.voice_id, owner_id="master")

    assert svc.delete(voice_id=rec.voice_id, owner_id="master") is True
    deleted = svc.get(voice_id=rec.voice_id)
    assert deleted is not None
    assert deleted.status == CloneVoiceStatus.DELETED
    assert deleted.biometric_ref == ""  # 生物特征被抹除
    assert t1.revoked is True
    assert t2.revoked is True


# ── 6. 安全边界: 不暴露到 Renderer ─────────────────
def test_renderer_payload_does_not_expose_biometric():
    svc = _service()
    rec = svc.upload(
        owner_id="master",
        name="Yita",
        biometric_ref="secret/voice.bin",
    )
    svc.authorize(voice_id=rec.voice_id, owner_id="master")
    payload = svc.to_renderer_payload(voice_id=rec.voice_id)
    assert "biometric" not in str(payload).lower()
    assert "secret/voice.bin" not in str(payload)


def test_renderer_payload_exposes_only_display_fields():
    svc = _service()
    rec = svc.upload(owner_id="master", name="Yita", biometric_ref="x.wav")
    payload = svc.to_renderer_payload(voice_id=rec.voice_id)
    assert payload["voice_id"] == rec.voice_id
    assert payload["name"] == "Yita"
    assert payload["status"] == CloneVoiceStatus.PENDING.value
    # 不暴露令牌/生物特征等敏感字段
    assert "token" not in payload
    assert "biometric" not in payload
    assert "owner_id" in payload


def test_authorize_updates_record_to_authorized():
    svc = _service()
    rec = svc.upload(owner_id="master", name="Yita", biometric_ref="x.wav")
    svc.authorize(voice_id=rec.voice_id, owner_id="master")
    assert rec.status == CloneVoiceStatus.AUTHORIZED


# ── 7. 审计 ───────────────────────────────────────
def test_all_operations_are_audited():
    svc = _service()
    rec = svc.upload(owner_id="master", name="Yita", biometric_ref="x.wav")
    token = svc.authorize(voice_id=rec.voice_id, owner_id="master")
    svc.preview(voice_id=rec.voice_id, token_id=token.token_id)
    svc.revoke(token_id=token.token_id)
    svc.delete(voice_id=rec.voice_id, owner_id="master")

    ops = [e.operation for e in svc.audit_entries()]
    for expected in (
        "clone_upload",
        "clone_authorize",
        "clone_preview",
        "clone_revoke",
        "clone_delete",
    ):
        assert expected in ops, f"缺少审计记录: {expected}"


def test_profile_is_reused_from_voice_service():
    svc = _service()
    profile = VoiceProfile(voice_id="yita-female-warm", name="Yita")
    rec = svc.upload(
        owner_id="master",
        name="Yita",
        biometric_ref="x.wav",
        profile=profile,
    )
    assert rec.profile is profile
