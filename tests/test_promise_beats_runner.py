"""Unit tests: PromiseBeatsRunner (promise_beats_runner).

重点覆盖：
- sanitize_fallback_text 的确定性规整（句号/破折号/条数/截断）
- fire 三条路径：出图成功 fired；出图失败 → 解释文段 fired；都失败 → attempts/failed
- 世界动作/出图异常不阻断后续分流
- tick 受 flag 控制 + 通过 reload 看到其他实例写入的新 beat
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

from core.promise_beats_runner import PromiseBeatsRunner, sanitize_fallback_text
from core.scheduled_beats import BeatStore

T0 = 1_756_000_000.0
HOUR = 3600.0


# ── sanitize_fallback_text ─────────────────────────────

def test_sanitize_empty() -> None:
    assert sanitize_fallback_text("") == ""
    assert sanitize_fallback_text("   \n ") == ""
    assert sanitize_fallback_text(None) == ""


def test_sanitize_compliant_text_passes() -> None:
    assert sanitize_fallback_text("路上不太方便") == "路上不太方便"


def test_sanitize_periods_become_lines() -> None:
    assert sanitize_fallback_text("先忙会儿。一会儿找你") == "先忙会儿\n一会儿找你"


def test_sanitize_trailing_punctuation_stripped() -> None:
    assert sanitize_fallback_text("先忙会儿！") == "先忙会儿"


def test_sanitize_dash_removed() -> None:
    assert sanitize_fallback_text("先——处理点事") == "先处理点事"
    assert sanitize_fallback_text("路上—不太方便") == "路上不太方便"


def test_sanitize_max_two_lines() -> None:
    result = sanitize_fallback_text("第一句。第二句。第三句。第四句")
    assert result == "第一句\n第二句"


def test_sanitize_line_truncated_to_20_chars() -> None:
    result = sanitize_fallback_text("字" * 30)
    assert result == "字" * 20


# ── runner fakes ───────────────────────────────────────

class FakeFlags:
    def __init__(self, *, enabled: bool = True) -> None:
        self._enabled = enabled

    def is_enabled(self, name: str) -> bool:
        return self._enabled


class FakeBrain:
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list[tuple[list, dict]] = []

    async def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return types.SimpleNamespace(text=self._text)


class Harness:
    def __init__(
        self,
        tmp_path: Path,
        *,
        image_result: dict,
        brain_text: str = "先忙会儿。一会儿找你",
        max_attempts: int = 3,
        flag_enabled: bool = True,
        world_raises: bool = False,
        publish_raises: bool = False,
        deliver_result: bool = True,
    ) -> None:
        self.store = BeatStore(tmp_path / "beats.json", clock=lambda: T0)
        self.world_actions: list[str] = []
        self.snapshot = {"phase": "afternoon", "activity": "散步",
                         "outdoor_place": "江边步道", "outdoor": True}
        self.delivery = {"master_id": "42", "channel": "qq",
                         "persona_id": "yita"}
        self.payloads: list[dict] = []
        self.delivered: list[str] = []
        self.brain = FakeBrain(brain_text)

        def world_action(place: str) -> None:
            if world_raises:
                raise RuntimeError("world boom")
            self.world_actions.append(place)

        async def image_publisher(payload: dict) -> dict:
            if publish_raises:
                raise RuntimeError("publish boom")
            self.payloads.append(payload)
            return image_result

        async def text_deliverer(text: str) -> bool:
            self.delivered.append(text)
            return deliver_result

        self.runner = PromiseBeatsRunner(
            brain=self.brain,
            feature_flags=FakeFlags(enabled=flag_enabled),
            settings={"promise_beats": {"poll_sec": 60, "max_pending": 2}},
            world_action=world_action,
            world_snapshot=lambda: dict(self.snapshot),
            delivery_context=lambda: dict(self.delivery),
            image_publisher=image_publisher,
            text_deliverer=text_deliverer,
            store=self.store,
            max_attempts=max_attempts,
        )

    def schedule_beat(self) -> str:
        beat = self.store.schedule(
            kind="go_out", topic="想出去走走",
            source_text="好几天闷家里了 想出去走走",
            delay_sec=HOUR, place_hint="江边步道", now=T0 - HOUR,
        )
        assert beat is not None
        return beat.id


# publish 返回的终态由 consumed 明细决定（2026-09-27 起 status 不再是 "published"）：
# 有 completed 才算交付成功，否则为 failed —— 这两条 fixture 与真实契约保持一致。
_COMPLETED = {"status": "completed",
              "consumed": [{"status": "completed", "image_path": "/tmp/x.png"}]}
_FAILED = {"status": "failed",
           "consumed": [{"status": "failed", "reason": "workflow_error"}]}


# ── fire: success path ─────────────────────────────────

@pytest.mark.asyncio
async def test_fire_success_world_then_image(tmp_path: Path) -> None:
    harness = Harness(tmp_path, image_result=_COMPLETED)
    beat_id = harness.schedule_beat()

    await harness.runner.tick()

    assert harness.world_actions == ["江边步道"]
    assert len(harness.payloads) == 1
    payload = harness.payloads[0]
    assert payload["scene"] == "promise_beat"
    assert payload["prompt_key"] == "role_in_scene"
    assert payload["channel"] == "qq"
    assert payload["target"] == "42"
    assert payload["persona_id"] == "yita"
    assert payload["candidate_id"] == f"promise-beat-{beat_id}"
    assert harness.brain.calls == []
    assert harness.delivered == []
    beat = harness.store.get(beat_id)
    assert beat.status == "fired"


@pytest.mark.asyncio
async def test_fired_beat_not_fired_again(tmp_path: Path) -> None:
    harness = Harness(tmp_path, image_result=_COMPLETED)
    harness.schedule_beat()

    await harness.runner.tick()
    await harness.runner.tick()

    assert len(harness.payloads) == 1  # 恰好一次


# ── fire: image failed → fallback text ────────────────

@pytest.mark.asyncio
async def test_fire_image_failed_delivers_fallback(tmp_path: Path) -> None:
    harness = Harness(tmp_path, image_result=_FAILED)
    beat_id = harness.schedule_beat()

    await harness.runner.tick()

    assert len(harness.brain.calls) == 1
    assert harness.delivered == ["先忙会儿\n一会儿找你"]
    assert harness.store.get(beat_id).status == "fired"


@pytest.mark.asyncio
async def test_fire_world_action_exception_still_publishes(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path, image_result=_COMPLETED, world_raises=True)
    harness.schedule_beat()

    await harness.runner.tick()

    assert len(harness.payloads) == 1
    assert harness.store.all()[0].status == "fired"


@pytest.mark.asyncio
async def test_fire_publish_exception_goes_fallback(tmp_path: Path) -> None:
    harness = Harness(tmp_path, image_result={}, publish_raises=True)
    harness.schedule_beat()

    await harness.runner.tick()

    assert harness.delivered == ["先忙会儿\n一会儿找你"]
    assert harness.store.all()[0].status == "fired"


# ── fire: everything failed → attempts / failed ───────

@pytest.mark.asyncio
async def test_fire_all_fail_records_attempts_then_failed(
    tmp_path: Path,
) -> None:
    harness = Harness(
        tmp_path, image_result=_FAILED, brain_text="", max_attempts=2,
    )
    beat_id = harness.schedule_beat()

    await harness.runner.tick()
    beat = harness.store.get(beat_id)
    assert beat.status == "pending"
    assert beat.attempts == 1

    await harness.runner.tick()
    beat = harness.store.get(beat_id)
    assert beat.status == "failed"
    assert beat.attempts == 2
    assert harness.delivered == []


@pytest.mark.asyncio
async def test_fire_fallback_delivery_failure_retries(
    tmp_path: Path,
) -> None:
    harness = Harness(
        tmp_path, image_result=_FAILED, deliver_result=False,
    )
    beat_id = harness.schedule_beat()

    await harness.runner.tick()

    assert harness.store.get(beat_id).attempts == 1
    assert harness.delivered == ["先忙会儿\n一会儿找你"]


# ── tick ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tick_flag_off_does_nothing(tmp_path: Path) -> None:
    harness = Harness(tmp_path, image_result=_COMPLETED, flag_enabled=False)
    harness.schedule_beat()

    await harness.runner.tick()

    assert harness.payloads == []
    assert harness.world_actions == []


@pytest.mark.asyncio
async def test_tick_sees_external_schedule_via_reload(
    tmp_path: Path,
) -> None:
    """pipeline 用自己的 BeatStore 实例写盘 → runner tick 靠 reload 看到新 beat。"""
    harness = Harness(tmp_path, image_result=_COMPLETED)
    external = BeatStore(tmp_path / "beats.json", clock=lambda: T0)
    beat = external.schedule(
        kind="go_out", topic="想出去走走",
        source_text="好几天闷家里了 想出去走走",
        delay_sec=HOUR, now=T0 - HOUR,
    )
    assert beat is not None

    await harness.runner.tick()

    assert len(harness.payloads) == 1
    assert harness.store.get(beat.id).status == "fired"
