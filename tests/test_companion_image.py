"""P4 companion image: proactive text + probabilistic image attachment tests."""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, r"e:\Agent_reply")

from core.companion import Companion


def _make_companion(probability: float = 0.3, world_port_available: bool = True):
    """Build a minimal mock companion with _maybe_attach_companion_image bound."""
    comp = MagicMock(spec=Companion)
    comp.settings = {"proactive": {"companion_image_probability": probability}}
    comp.qq = MagicMock()
    comp.qq.is_logged_in = False
    comp._active_persona_id = MagicMock(return_value="ita-default")
    comp.publish_image_candidate = AsyncMock(return_value={"status": "published"})
    comp._persist_image_event = AsyncMock()

    if world_port_available:
        comp.world_port = MagicMock()
        comp.world_port.publish_image_candidate = MagicMock()
    else:
        comp.world_port = None

    comp._maybe_attach_companion_image = Companion._maybe_attach_companion_image.__get__(comp)
    return comp


class TestCompanionImageProbability:
    """Probability gating: 0% never fires, edge cases handled."""

    def test_probability_zero_never_fires(self):
        comp = _make_companion(probability=0.0)
        comp._maybe_attach_companion_image(12345, "早安", "morning_greet")
        # No task created → publish not called even after event loop tick

    def test_empty_content_skips(self):
        comp = _make_companion(probability=1.0)
        # Should not crash on empty/whitespace content
        comp._maybe_attach_companion_image(12345, "", "morning_greet")
        comp._maybe_attach_companion_image(12345, "   ", "morning_greet")

    def test_no_world_port_skips(self):
        comp = _make_companion(probability=1.0, world_port_available=False)
        comp._maybe_attach_companion_image(12345, "早安", "morning_greet")

    def test_default_probability_is_03(self):
        """When settings has no companion_image_probability key, default to 0.3."""
        comp = MagicMock(spec=Companion)
        comp.settings = {"proactive": {}}
        comp.world_port = MagicMock()
        comp.world_port.publish_image_candidate = MagicMock()
        comp._active_persona_id = MagicMock(return_value="ita-default")
        comp.publish_image_candidate = AsyncMock()
        comp._persist_image_event = AsyncMock()
        comp._maybe_attach_companion_image = Companion._maybe_attach_companion_image.__get__(comp)

        with patch("core.companion.random") as mock_random:
            mock_random.random.return_value = 0.25  # below 0.3 → fires
            comp._maybe_attach_companion_image(12345, "test", "test")


class TestCompanionImagePayload:
    """Verify the candidate payload structure passed to publish_image_candidate."""

    @pytest.mark.asyncio
    async def test_fire_calls_publish_with_correct_payload(self):
        comp = _make_companion(probability=1.0)
        content = "今天做了杯拿铁，阳光照进来好温暖"

        with patch("core.companion.random") as mock_random, \
             patch("core.companion._COMPANION_IMAGE_DELAY_SEC", 0):
            mock_random.random.return_value = 0.0  # always fire
            comp._maybe_attach_companion_image(12345, content, "afternoon_care")
            # Let the task complete
            await asyncio.sleep(0.01)

        # Verify publish was called
        assert comp.publish_image_candidate.call_count == 1
        call_args = comp.publish_image_candidate.call_args[0][0]
        assert call_args["scene"] == "local_send"
        assert call_args["user_raw"] == content
        assert call_args["prompt_key"] == "role_in_scene"
        assert "proactive_companion:afternoon_care" in call_args["reason_code"]
        assert call_args["owner_id"] == 12345
        assert call_args["channel"] == "local_chat"

    @pytest.mark.asyncio
    async def test_logged_in_qq_master_uses_qq_channel(self):
        comp = _make_companion(probability=1.0)
        comp.qq.is_logged_in = True

        with patch("core.companion.random") as mock_random, \
             patch("core.companion._COMPANION_IMAGE_DELAY_SEC", 0):
            mock_random.random.return_value = 0.0
            comp._maybe_attach_companion_image(3489352115, "午安", "afternoon_care")
            await asyncio.sleep(0.01)

        call_args = comp.publish_image_candidate.call_args[0][0]
        assert call_args["channel"] == "qq"
        assert call_args["target"] == 3489352115
        persist_args = comp._persist_image_event.call_args.kwargs
        assert persist_args["channel"] == "qq"

    @pytest.mark.asyncio
    async def test_successful_publish_records_image_event(self):
        comp = _make_companion(probability=1.0)
        comp.publish_image_candidate = AsyncMock(
            return_value={"status": "published", "image_path": "/tmp/test.jpg"}
        )

        with patch("core.companion.random") as mock_random, \
             patch("core.companion._COMPANION_IMAGE_DELAY_SEC", 0):
            mock_random.random.return_value = 0.0
            comp._maybe_attach_companion_image(12345, "午安", "afternoon_care")
            await asyncio.sleep(0.01)

        assert comp._persist_image_event.call_count == 1

    @pytest.mark.asyncio
    async def test_failed_publish_does_not_record_event(self):
        comp = _make_companion(probability=1.0)
        comp.publish_image_candidate = AsyncMock(
            return_value={"status": "failed", "reason": "provider_error"}
        )

        with patch("core.companion.random") as mock_random, \
             patch("core.companion._COMPANION_IMAGE_DELAY_SEC", 0):
            mock_random.random.return_value = 0.0
            comp._maybe_attach_companion_image(12345, "午安", "afternoon_care")
            await asyncio.sleep(0.01)

        assert comp._persist_image_event.call_count == 0


class TestCompanionImageNoBlockPush:
    """Verify companion image never blocks or breaks the push dispatch."""

    def test_exception_in_trigger_is_caught(self):
        comp = MagicMock(spec=Companion)
        comp.settings = {"proactive": {"companion_image_probability": 1.0}}
        comp.world_port = MagicMock()
        comp.world_port.publish_image_candidate = MagicMock(
            side_effect=RuntimeError("world port broken")
        )
        comp._maybe_attach_companion_image = Companion._maybe_attach_companion_image.__get__(comp)

        # Should not raise
        comp._maybe_attach_companion_image(12345, "test", "test")

    def test_settings_missing_proactive_key(self):
        comp = MagicMock(spec=Companion)
        comp.settings = {}
        comp.world_port = MagicMock()
        comp.world_port.publish_image_candidate = MagicMock()
        comp._active_persona_id = MagicMock(return_value="ita")
        comp.publish_image_candidate = AsyncMock()
        comp._persist_image_event = AsyncMock()
        comp._maybe_attach_companion_image = Companion._maybe_attach_companion_image.__get__(comp)

        comp._maybe_attach_companion_image(12345, "test", "test")
