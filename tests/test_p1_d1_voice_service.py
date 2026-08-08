"""TDD tests for Task P1-D.1: Voice ASR/TTS 三服务边界.

覆盖:
  - 三类服务接口: VoiceProfile / SpeechMarkup / VoiceDeliveryPolicy
  - 本地 ASR/TTS 桩适配层 (不调用真实模型/API)
  - 语音开关 (VoiceSwitch) 与审计记录
  - VoiceService 门面: 开关/通道策略/审计, 全程无真实服务调用
"""

from __future__ import annotations

import pytest

from core.voice_service import (
    DefaultVoiceDeliveryPolicy,
    LocalAsrProvider,
    LocalTtsProvider,
    SpeechMarkup,
    VoiceAuditStore,
    VoiceGender,
    VoiceProfile,
    VoiceService,
    VoiceSwitch,
)


# ── 1. 服务接口: VoiceProfile ──────────────────────
def test_voice_profile_defines_identity_and_prosody():
    profile = VoiceProfile(
        voice_id="yita-female-warm",
        name="Yita",
        gender=VoiceGender.FEMALE,
        style="warm",
        pitch=1.05,
        speed=0.9,
        volume=0.8,
        locale="zh-CN",
    )
    assert profile.voice_id == "yita-female-warm"
    assert profile.gender == VoiceGender.FEMALE
    assert profile.speed == 0.9
    assert profile.locale == "zh-CN"


def test_voice_profile_has_sane_defaults():
    profile = VoiceProfile(voice_id="default")
    assert profile.gender == VoiceGender.NEUTRAL
    assert profile.style == "warm"
    assert profile.pitch == 1.0
    assert profile.speed == 1.0
    assert profile.volume == 0.8


# ── 2. 服务接口: SpeechMarkup ──────────────────────
def test_speech_markup_carries_text_and_emphasis_hints():
    markup = SpeechMarkup(
        text="晚安，好好休息",
        style="night",
        emphasis=("晚安",),
        pause_before_ms=120,
        pause_after_ms=200,
    )
    assert markup.text == "晚安，好好休息"
    assert "晚安" in markup.emphasis
    assert markup.pause_after_ms == 200


# ── 3. 服务接口: VoiceDeliveryPolicy ───────────────
def test_default_delivery_policy_allows_only_voice_channels_when_enabled():
    policy = DefaultVoiceDeliveryPolicy(enabled=True)
    assert policy.allows(channel="voice_chat") is True
    assert policy.allows(channel="voice_note") is True
    assert policy.allows(channel="text_chat") is False


def test_default_delivery_policy_blocks_everything_when_disabled():
    policy = DefaultVoiceDeliveryPolicy(enabled=False)
    assert policy.allows(channel="voice_chat") is False
    assert policy.should_deliver(text="hello") is False


def test_default_delivery_policy_caps_text_length():
    policy = DefaultVoiceDeliveryPolicy(max_text_len=10)
    assert policy.should_deliver(text="短文本") is True
    assert policy.should_deliver(text="这是一段超过十个字符上限的长文本内容") is False


# ── 4. 本地 ASR/TTS 桩适配层 (无真实调用) ──────────
def test_local_asr_transcribes_without_real_service():
    provider = LocalAsrProvider(transcript="今天过得怎么样")
    result = provider.transcribe(
        audio_ref="uploads/voice/1.wav",
        request_id="asr-1",
        owner_id="master",
        metadata={},
    )
    assert result.status == "ok"
    assert result.text == "今天过得怎么样"
    assert provider.provider_id == "local_asr_stub"
    assert result.model == "stub-v1"


def test_local_tts_synthesizes_without_real_service():
    provider = LocalTtsProvider()
    result = provider.synthesize(
        markup=SpeechMarkup(text="晚安", style="night"),
        request_id="tts-1",
        owner_id="master",
        metadata={},
    )
    assert result.status == "ok"
    assert result.text == "晚安"
    assert provider.provider_id == "local_tts_stub"
    assert result.audio_name


# ── 5. 语音开关与审计 ──────────────────────────────
def test_voice_switch_toggles_and_records_audit():
    switch = VoiceSwitch(enabled=False)
    assert switch.enabled is False

    switch.set_enabled(True, reason="user_request", actor="user")
    assert switch.enabled is True

    toggles = switch.toggle_audit()
    assert len(toggles) == 1
    assert toggles[0]["operation"] == "voice_switch"
    assert toggles[0]["enabled"] is True
    assert toggles[0]["reason"] == "user_request"


def test_voice_switch_ignores_noop_and_records_nothing():
    switch = VoiceSwitch(enabled=True)
    switch.set_enabled(True, reason="duplicate", actor="system")
    assert switch.toggle_audit() == []


# ── 6. VoiceService 门面 ───────────────────────────
def test_voice_service_disabled_returns_disabled_result():
    service = VoiceService(feature_enabled=False)
    result = service.transcribe_audio(audio_ref="uploads/voice/1.wav")
    assert result["status"] == "disabled"
    assert result["feature_flag"] == "voice_service_v1"
    assert result["side_effects"]["provider_called"] is False


def test_voice_service_transcribe_records_audit_with_no_side_effects():
    service = VoiceService(feature_enabled=True)
    result = service.transcribe_audio(audio_ref="uploads/voice/1.wav")

    assert result["status"] == "completed"
    assert result["transcript"]["text"]  # 桩返回文本
    assert result["side_effects"]["provider_called"] is True
    # 审计记录应存在
    entries = service.audit_entries()
    assert any(e.operation == "voice_asr" for e in entries)


def test_voice_service_synthesize_respects_channel_policy():
    service = VoiceService(
        feature_enabled=True,
        delivery_policy=DefaultVoiceDeliveryPolicy(enabled=True),
    )
    result = service.synthesize_speech(
        markup=SpeechMarkup(text="晚安"),
        channel="text_chat",  # 非语音通道
    )
    assert result["status"] == "rejected"
    assert result["error_code"] == "delivery_policy_rejected"
    assert result["side_effects"]["provider_called"] is False


def test_voice_service_switch_gates_delivery():
    service = VoiceService(feature_enabled=True)
    service.set_voice_enabled(False, reason="privacy", actor="user")

    result = service.synthesize_speech(markup=SpeechMarkup(text="晚安"))
    assert result["status"] == "rejected"
    assert result["side_effects"]["provider_called"] is False
    assert service.is_voice_enabled() is False


def test_voice_service_uses_audit_store_injection():
    store = VoiceAuditStore()
    service = VoiceService(feature_enabled=True, audit_store=store)
    service.transcribe_audio(audio_ref="uploads/voice/2.wav")
    assert any(e.operation == "voice_asr" for e in store.recent())
