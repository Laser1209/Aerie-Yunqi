"""Phase 14 world ImageCandidate approval, idempotency, and ACK contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core.world_port import WorldEvent


class FlagStub:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def is_enabled(self, name: str) -> bool:
        return name == "world_image_candidates_v1" and self.enabled


class WorkflowStub:
    def __init__(self, status: str = "completed") -> None:
        self.status = status
        self.calls: list[dict] = []

    def generate_image(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        if self.status == "disabled":
            return {
                "status": "disabled",
                "side_effects": {
                    "provider_called": False,
                    "asset_created": False,
                    "delivery_created": False,
                },
                "delivery_plan": None,
            }
        if self.status == "failed":
            return {
                "status": "failed",
                "request_id": "img-failed",
                "side_effects": {
                    "provider_called": True,
                    "asset_created": False,
                    "delivery_created": False,
                },
                "delivery_plan": None,
            }
        return {
            "status": "completed",
            "request_id": "img-ok",
            "side_effects": {
                "provider_called": True,
                "asset_created": True,
                "delivery_created": True,
            },
            "delivery_plan": {
                "delivery_plan_id": "delivery-1",
                "status": "planned",
            },
        }


class WorldPortStub:
    def __init__(self, events: list[WorldEvent] | None = None) -> None:
        self.events = events or []
        self.acks: list[int] = []

    async def replay_events(self, *, last_seq=None):
        return self.events

    async def ack(self, seq: int):
        self.acks.append(seq)
        return {"consumer_id": "core", "last_seq": seq}


class PolicyStub:
    def __init__(
        self,
        allowed: bool = True,
        reason: str = "ok",
        mute_until: datetime | None = None,
    ) -> None:
        self.allowed = allowed
        self.reason = reason
        self.mute_until = mute_until
        self.recorded: list[str] = []

    def can_push(self, scene: str):
        return self.allowed, self.reason

    def record(self, scene: str) -> None:
        self.recorded.append(scene)


class JudgeStub:
    def __init__(self, suppress_reason: str = "") -> None:
        self.suppress_reason = suppress_reason
        self.calls: list[str] = []

    def evaluate(self, scene: str, context_override=None):
        self.calls.append(scene)
        return SimpleNamespace(
            scene=scene,
            score=81,
            tone="casual_warm",
            suppress_reason=self.suppress_reason,
            to_dict=lambda: {
                "scene": scene,
                "score": 81,
                "tone": "casual_warm",
                "suppress_reason": self.suppress_reason,
            },
        )


def _clock() -> datetime:
    return datetime(2026, 7, 20, 20, 0, tzinfo=timezone.utc)


def _candidate_payload(**overrides) -> dict:
    payload = {
        "candidate_id": "cand-1",
        "scene": "idle_care",
        "owner_id": "master",
        "channel": "local_chat",
        "target": "desktop",
        "prompt_key": "evening_home",
        "reason_code": "evening_private_scene",
        "source": "generated",
        "score": 0.91,
        "expires_at": "2026-07-20T20:10:00+00:00",
        "idempotency_key": "world-cand-1",
    }
    payload.update(overrides)
    return payload


def _candidate_event(**payload_overrides) -> WorldEvent:
    return WorldEvent(
        event_id="world_evt_candidate_1",
        topic="image_candidates",
        event_type="world.image_candidate.published",
        sequence=7,
        occurred_at="2026-07-20T20:00:00+00:00",
        payload=_candidate_payload(**payload_overrides),
    )


@pytest.mark.asyncio
async def test_flag_off_closes_consumer_without_ack_or_side_effects(tmp_path):
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    workflow = WorkflowStub()
    port = WorldPortStub()
    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(False),
        image_workflow=workflow,
        world_port=port,
        store=JsonWorldImageCandidateStore(tmp_path / "candidates.json"),
        clock=_clock,
    )

    result = await consumer.process_event(_candidate_event())

    assert result["status"] == "disabled"
    assert result["acked"] is False
    assert workflow.calls == []
    assert port.acks == []
    assert result["side_effects"]["delivery_created"] is False


@pytest.mark.asyncio
async def test_approved_candidate_calls_image_workflow_acks_and_survives_replay(tmp_path):
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    store = JsonWorldImageCandidateStore(tmp_path / "candidates.json")
    workflow = WorkflowStub()
    port = WorldPortStub()
    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=workflow,
        world_port=port,
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=store,
        clock=_clock,
    )

    first = await consumer.process_event(_candidate_event())
    restarted = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=workflow,
        world_port=port,
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=JsonWorldImageCandidateStore(tmp_path / "candidates.json"),
        clock=_clock,
    )
    replay = await restarted.process_event(_candidate_event())

    assert first["status"] == "completed"
    assert first["acked"] is True
    assert port.acks == [7, 7]
    assert len(workflow.calls) == 1
    assert workflow.calls[0]["idempotency_key"] == "world-image:world-cand-1"
    assert workflow.calls[0]["prompt"] == "world_prompt:evening_home"
    assert replay["status"] == "duplicate"
    assert replay["side_effects"]["provider_called"] is False


@pytest.mark.asyncio
async def test_muted_expired_and_judge_no_suppress_ack_without_workflow(tmp_path):
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    # 全局静音（mute_until 在未来）：主动图片被抑制，不调用 workflow。
    muted_port = WorldPortStub()
    muted_workflow = WorkflowStub()
    muted = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=muted_workflow,
        world_port=muted_port,
        push_policy=PolicyStub(mute_until=datetime(2099, 1, 1, tzinfo=timezone.utc)),
        store=JsonWorldImageCandidateStore(tmp_path / "muted.json"),
        clock=_clock,
    )
    muted_result = await muted.process_event(_candidate_event())

    expired_port = WorldPortStub()
    expired = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=WorkflowStub(),
        world_port=expired_port,
        store=JsonWorldImageCandidateStore(tmp_path / "expired.json"),
        clock=_clock,
    )
    expired_result = await expired.process_event(
        _candidate_event(
            candidate_id="cand-expired",
            idempotency_key="world-cand-expired",
            expires_at="2026-07-20T19:59:00+00:00",
        )
    )

    # 主动发图不限制调用：proactive_judge 的抑制被清空（Agent 决策即执行），
    # 即使打分低于阈值也会继续生图，只保留分数/语气供审计。
    judge_port = WorldPortStub()
    judge_workflow = WorkflowStub()
    judge_ok = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=judge_workflow,
        world_port=judge_port,
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub("score_below_threshold(20<45)"),
        store=JsonWorldImageCandidateStore(tmp_path / "judge.json"),
        clock=_clock,
    )
    judge_result = await judge_ok.process_event(
        _candidate_event(candidate_id="cand-judge", idempotency_key="world-cand-judge")
    )

    assert muted_result["status"] == "suppressed"
    assert muted_result["reason"] == "muted"
    assert muted_port.acks == [7]
    assert muted_workflow.calls == []
    assert expired_result["status"] == "expired"
    assert expired_port.acks == [7]
    assert judge_result["status"] == "completed"
    assert judge_port.acks == [7]
    assert len(judge_workflow.calls) == 1
    assert judge_result["recorded"] is True


@pytest.mark.asyncio
async def test_offline_candidate_is_not_acked_and_has_no_side_effects(tmp_path):
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    workflow = WorkflowStub()
    port = WorldPortStub()
    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=workflow,
        world_port=port,
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=JsonWorldImageCandidateStore(tmp_path / "offline.json"),
        clock=_clock,
        delivery_online=lambda: False,
    )

    result = await consumer.process_event(_candidate_event())

    assert result["status"] == "offline"
    assert result["acked"] is False
    assert workflow.calls == []
    assert port.acks == []
    assert result["side_effects"]["provider_called"] is False


@pytest.mark.asyncio
async def test_image_workflow_disabled_does_not_ack_or_record_candidate(tmp_path):
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    store = JsonWorldImageCandidateStore(tmp_path / "workflow-disabled.json")
    workflow = WorkflowStub(status="disabled")
    port = WorldPortStub()
    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=workflow,
        world_port=port,
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=store,
        clock=_clock,
    )

    result = await consumer.process_event(_candidate_event())

    assert result["status"] == "workflow_disabled"
    assert result["acked"] is False
    assert port.acks == []
    assert store.get("world-cand-1") is None
    assert result["side_effects"]["provider_called"] is False


@pytest.mark.asyncio
async def test_sidecar_publishes_redacted_image_candidate_for_core_replay(tmp_path):
    from core.world_adapters.remote import RemoteWorldAdapter
    from world_service.main import LocalWorldSidecarService

    service = LocalWorldSidecarService(data_dir=tmp_path)
    service.publish_image_candidate(
        {
            **_candidate_payload(),
            "prompt": "raw intimate prompt must not leak",
            "message_text": "private chat text must not leak",
        }
    )
    adapter = RemoteWorldAdapter(service, consumer_id="core")

    events = await adapter.replay_events(last_seq=0)
    raw = str(events[0].to_public_dict())

    assert events[0].event_type == "world.image_candidate.published"
    assert events[0].payload["candidate_id"] == "cand-1"
    assert events[0].payload["prompt_key"] == "evening_home"
    assert "raw intimate prompt" not in raw
    assert "private chat text" not in raw


@pytest.mark.asyncio
async def test_companion_exposes_one_shot_candidate_consumer(tmp_path):
    from core.companion import Companion
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    event = _candidate_event()
    workflow = WorkflowStub()
    port = WorldPortStub([event])
    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=workflow,
        world_port=port,
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=JsonWorldImageCandidateStore(tmp_path / "companion.json"),
        clock=_clock,
    )
    companion = Companion.__new__(Companion)
    companion.world_image_candidate_consumer = consumer

    results = await companion.process_world_image_candidates_once(last_seq=0)

    assert [result["status"] for result in results] == ["completed"]
    assert workflow.calls
    assert port.acks == [7]


class BudgetStub:
    """Minimal stand-in mirroring ImageBudget.can_record/record."""

    def __init__(self, allowed: bool = True, reason: str = "ok") -> None:
        self.allowed = allowed
        self.reason = reason
        self.recorded: list[str] = []

    def can_record(self, kind: str):
        return self.allowed, self.reason

    def record(self, kind: str) -> None:
        self.recorded.append(kind)


@pytest.mark.asyncio
async def test_daily_image_limit_rejects_and_acks_without_workflow(tmp_path):
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    workflow = WorkflowStub()
    port = WorldPortStub()
    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=workflow,
        world_port=port,
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        image_budget=BudgetStub(False, "daily_image_limit"),
        store=JsonWorldImageCandidateStore(tmp_path / "budget-reject.json"),
        clock=_clock,
    )

    result = await consumer.process_event(_candidate_event())

    assert result["status"] == "suppressed"
    assert result["reason"] == "daily_image_limit"
    assert result["acked"] is True
    assert workflow.calls == []
    assert port.acks == [7]


@pytest.mark.asyncio
async def test_completed_proactive_image_records_budget(tmp_path):
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    workflow = WorkflowStub()
    port = WorldPortStub()
    budget = BudgetStub(True, "ok")
    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=workflow,
        world_port=port,
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        image_budget=budget,
        store=JsonWorldImageCandidateStore(tmp_path / "budget-record.json"),
        clock=_clock,
    )

    result = await consumer.process_event(_candidate_event())

    assert result["status"] == "completed"
    assert budget.recorded == ["proactive"]
    assert workflow.calls


@pytest.mark.asyncio
async def test_local_send_photo_bypasses_vision_same_scene_dedup(tmp_path):
    """scene=local_send（用户主动要求）必须豁免视觉场景判重。

    复现线上 bug：用户连续要"自拍"，每张画面高度相似，被视觉判重（与 4h 内
    最近一张已生成图判为 same scene）当成重复 dedup_skipped，导致主 Agent
    已同意拍照但图迟迟不出。修复后：local_send 直接放行生图，不走视觉判重。
    """
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    store = JsonWorldImageCandidateStore(tmp_path / "candidates.json")
    workflow = WorkflowStub()
    port = WorldPortStub()

    # 预置一条"4 小时内已完成的同意图图"，使 _recent_completed_asset 有参考图，
    # 否则视觉判重因无参考图而天然短路，测不出豁免效果。
    store.put({
        "idempotency_key": "world-cand-prior",
        "candidate_id": "cand-prior",
        "scene": "idle_care",
        "status": "completed",
        "updated_at": 1753026000.0,  # 2026-07-20 同小时，在 4h 窗口内
        "workflow": {"asset_url": "/uploads/prior.png"},
    })

    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=workflow,
        world_port=port,
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=store,
        clock=_clock,
    )

    # local_send（用户主动命令）
    result = await consumer.process_event(
        _candidate_event(scene="local_send", prompt_key="role_selfie",
                         idempotency_key="world-cand-user", candidate_id="cand-user")
    )

    # 必须真正调用了生图 workflow，而不是被视觉判重 dedup_skipped。
    assert result["status"] == "completed"
    assert workflow.calls, "local_send 应绕过视觉判重并调用 workflow"
    assert workflow.calls[0]["prompt"] == "world_prompt:role_selfie"


@pytest.mark.asyncio
async def test_user_requested_photo_bypasses_proactive_budget(tmp_path):
    """scene=local_send（用户主动要求）不占用主动发图每日额度，也不被额度拒绝。"""
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    workflow = WorkflowStub()
    port = WorldPortStub()
    budget = BudgetStub(False, "daily_image_limit")
    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=workflow,
        world_port=port,
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        image_budget=budget,
        store=JsonWorldImageCandidateStore(tmp_path / "local-send-budget.json"),
        clock=_clock,
    )

    result = await consumer.process_event(
        _candidate_event(
            candidate_id="cand-user-1",
            scene="local_send",
            source="manual",
            idempotency_key="chat-photo:3489352115:turn_abc",
        )
    )

    assert result["status"] == "completed"
    assert budget.recorded == []
    assert workflow.calls
    assert port.acks == [7]


@pytest.mark.asyncio
async def test_has_recent_completed_tracks_successful_same_topic_across_restart(tmp_path):
    """持久化同主题去重：completed 记录在窗口内可被新 consumer（模拟重启）识别。"""
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    store_path = tmp_path / "dedup.json"
    workflow = WorkflowStub()
    port = WorldPortStub()
    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=workflow,
        world_port=port,
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=JsonWorldImageCandidateStore(store_path),
        clock=_clock,
    )

    result = await consumer.process_event(_candidate_event())

    assert result["status"] == "completed"

    # 模拟后端重启：全新 consumer 读同一持久化存储。
    restarted = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=WorkflowStub(),
        world_port=WorldPortStub(),
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=JsonWorldImageCandidateStore(store_path),
        clock=_clock,
    )

    assert restarted.has_recent_completed("evening_private_scene", window_sec=1800) is True
    # 不同主题/不同 reason_code 不应被误伤。
    assert restarted.has_recent_completed("world_visual:other_topic", window_sec=1800) is False
    assert restarted.has_recent_completed("", window_sec=1800) is False


@pytest.mark.asyncio
async def test_has_recent_completed_ignores_failed_and_expired_window(tmp_path):
    """failed 记录不计入去重；超出窗口的 completed 记录不再拦截。"""
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    def _advance_clock(minutes: int):
        return lambda: datetime(2026, 7, 20, 20, minutes, tzinfo=timezone.utc)

    store_path = tmp_path / "dedup-window.json"
    workflow = WorkflowStub()
    port = WorldPortStub()
    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=workflow,
        world_port=port,
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=JsonWorldImageCandidateStore(store_path),
        clock=_clock,
    )
    await consumer.process_event(_candidate_event())

    # 窗口外：completed 记录在 1800s 之前 → 不再拦截。
    outside = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=WorkflowStub(),
        world_port=WorldPortStub(),
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=JsonWorldImageCandidateStore(store_path),
        clock=_advance_clock(35),
    )
    assert outside.has_recent_completed("evening_private_scene", window_sec=1800) is False

    # failed 记录（provider 调了但资产没落地）不参与去重。
    store_path2 = tmp_path / "dedup-failed.json"
    failed = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=WorkflowStub(status="failed"),
        world_port=WorldPortStub(),
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=JsonWorldImageCandidateStore(store_path2),
        clock=_clock,
    )
    await failed.process_event(_candidate_event())

    fresh = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=WorkflowStub(),
        world_port=WorldPortStub(),
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=JsonWorldImageCandidateStore(store_path2),
        clock=_clock,
    )
    assert fresh.has_recent_completed("evening_private_scene", window_sec=1800) is False


# ── 世界数据异常兜底（修复 empty_prompt 根因后的健壮性契约） ──────────────
# 历史问题：prompt resolver（_image_prompt_for）在世界数据接力（world snapshot /
# fine_time_descriptor / moon_phase / light relay）抛异常时，异常被 _resolve_prompt
# 的 except 分支静默吞掉并返回空串 ""，导致 generate_image 以 empty_prompt 拒绝、
# provider_called=False。修复后两层兜底保证任何异常都退回非空提示词。


def _booming_resolver(prompt_key: str, candidate: dict[str, Any]) -> str:
    """模拟世界数据接力抛异常：resolver 内部崩溃。"""
    raise RuntimeError("world data relay crashed")


async def _empty_resolver(prompt_key: str, candidate: dict[str, Any]) -> str:
    """模拟 resolver 返回空串（修复前等于放弃生图）。"""
    return ""


@pytest.mark.asyncio
async def test_resolver_exception_returns_non_empty_placeholder(tmp_path):
    """resolver 抛异常 → _resolve_prompt 兜底返回非空占位，绝不返回空串。"""
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=WorkflowStub(),
        world_port=WorldPortStub(),
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=JsonWorldImageCandidateStore(tmp_path / "resolver-exc.json"),
        clock=_clock,
        prompt_resolver=_booming_resolver,
    )

    prompt = await consumer._resolve_prompt(_candidate_payload())

    assert prompt.strip() != ""
    assert prompt == "world_prompt:evening_home"


@pytest.mark.asyncio
async def test_resolver_empty_result_returns_non_empty_placeholder(tmp_path):
    """resolver 返回空串 → _resolve_prompt 兜底返回非空占位。"""
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=WorkflowStub(),
        world_port=WorldPortStub(),
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=JsonWorldImageCandidateStore(tmp_path / "resolver-empty.json"),
        clock=_clock,
        prompt_resolver=_empty_resolver,
    )

    prompt = await consumer._resolve_prompt(_candidate_payload())

    assert prompt.strip() != ""
    assert prompt == "world_prompt:evening_home"


@pytest.mark.asyncio
async def test_workflow_survives_world_data_exception(tmp_path):
    """完整链路：世界数据异常被吞后，生图仍 completed、provider 被调用。"""
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    workflow = WorkflowStub()
    port = WorldPortStub()
    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=workflow,
        world_port=port,
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=JsonWorldImageCandidateStore(tmp_path / "workflow-exc.json"),
        clock=_clock,
        prompt_resolver=_booming_resolver,
    )

    result = await consumer.process_event(_candidate_event())

    assert result["status"] == "completed"
    assert result["acked"] is True
    assert workflow.calls
    assert workflow.calls[0]["prompt"].strip() != ""
    assert workflow.calls[0]["prompt"] == "world_prompt:evening_home"
    assert result["side_effects"]["provider_called"] is True


@pytest.mark.asyncio
async def test_image_prompt_for_world_context_exception_returns_base(tmp_path):
    """_image_world_context 抛异常 → _image_prompt_for 退回基础提示词（恒非空）。

    这正是 16:03 空提示词的根因层：修复前 world 接力无 try 兜底，异常冒泡到
    _resolve_prompt 被吞成空串；修复后任何世界数据异常都退回 base 基础提示词。
    """
    from core.companion import Companion

    companion = Companion.__new__(Companion)
    companion._compose_base_image_prompt = (
        lambda key, cand, spec=None: "一张写实生活照，人物是一位28岁的中国女性独立设计师（伊塔/Ita）。"
    )

    def _boom_context(candidate):
        raise RuntimeError("world snapshot / fine_time / moon_phase relay crashed")

    companion._image_world_context = _boom_context
    companion._light_relay_refine_prompt = None  # 不应被调用（_image_world_context 先抛）
    companion._inject_world_context_fallback = None

    prompt = await companion._image_prompt_for(
        "role_selfie", {"prompt_key": "role_selfie"}
    )

    assert prompt.strip() != ""
    assert "一张写实生活照" in prompt


@pytest.mark.asyncio
async def test_image_prompt_for_world_context_empty_returns_base(tmp_path):
    """_image_world_context 返回空 context → 直接退回基础提示词。"""
    from core.companion import Companion

    companion = Companion.__new__(Companion)
    companion._compose_base_image_prompt = (
        lambda key, cand, spec=None: "一张写实生活照，人物是一位28岁的中国女性独立设计师（伊塔/Ita）。"
    )
    companion._image_world_context = lambda cand: {}
    companion._light_relay_refine_prompt = None
    companion._inject_world_context_fallback = None

    prompt = await companion._image_prompt_for(
        "role_selfie", {"prompt_key": "role_selfie"}
    )

    assert prompt.strip() != ""
    assert "一张写实生活照" in prompt


# ── 可观测性兜底（Task 5）：被消费但未落盘的分支有迹可循 ──────────────────
# 背景：主动发图发布了候选，但 store 无落盘、也无任何生成/交付/失败日志。
# 根因是 process_event 里 disabled/ignored/offline/workflow_disabled 分支既不
# 打日志也不落盘。以下用例钉住这些分支的语义（返回明确 status、不抛异常、
# 不向 store 写记录），并保证 consume_replay 单条失败不中断整批。


@pytest.mark.asyncio
async def test_disabled_and_offline_do_not_write_store_or_raise(tmp_path):
    """disabled / offline 返回明确 status、不抛异常，且不向 store 写记录。"""
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    # disabled：feature flag 关闭 → status=disabled，不落盘、不 ACK。
    disabled_store = JsonWorldImageCandidateStore(tmp_path / "disabled-norecord.json")
    disabled = WorldImageCandidateConsumer(
        feature_flags=FlagStub(False),
        image_workflow=WorkflowStub(),
        world_port=WorldPortStub(),
        store=disabled_store,
        clock=_clock,
    )
    disabled_result = await disabled.process_event(_candidate_event())
    assert disabled_result["status"] == "disabled"
    assert disabled_result["reason"] == "feature_flag_off"
    assert disabled_result["acked"] is False
    assert disabled_store.get("world-cand-1") is None

    # offline：推送离线（非 manual）→ status=offline，不落盘、不 ACK。
    offline_store = JsonWorldImageCandidateStore(tmp_path / "offline-norecord.json")
    offline = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=WorkflowStub(),
        world_port=WorldPortStub(),
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=offline_store,
        clock=_clock,
        delivery_online=lambda: False,
    )
    offline_result = await offline.process_event(_candidate_event())
    assert offline_result["status"] == "offline"
    assert offline_result["reason"] == "delivery_offline"
    assert offline_result["acked"] is False
    assert offline_store.get("world-cand-1") is None


@pytest.mark.asyncio
async def test_consume_replay_survives_process_event_exception(tmp_path):
    """process_event 抛异常时，consume_replay 不中断整批，正常事件仍被处理。"""
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    def _evt(seq: int, key: str) -> WorldEvent:
        return WorldEvent(
            event_id=f"evt_{seq}",
            topic="image_candidates",
            event_type="world.image_candidate.published",
            sequence=seq,
            occurred_at="2026-07-20T20:00:00+00:00",
            payload=_candidate_payload(
                candidate_id=f"cand-{seq}",
                idempotency_key=key,
            ),
        )

    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=WorkflowStub(),
        world_port=WorldPortStub(),
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=JsonWorldImageCandidateStore(tmp_path / "replay-exc.json"),
        clock=_clock,
    )

    async def _flaky_process(event):
        if int(getattr(event, "sequence", 0)) == 1:
            raise RuntimeError("boom on first event")
        return {"status": "ok", "sequence": int(getattr(event, "sequence", 0))}

    consumer.process_event = _flaky_process  # type: ignore[method-assign]
    consumer._world_port_provider = lambda: WorldPortStub(
        [_evt(1, "key-a"), _evt(2, "key-b")]
    )

    results = await consumer.consume_replay(last_seq=0)

    # 第一条抛异常被跳过并记 warning，第二条正常处理 → 批不中断。
    assert len(results) == 1
    assert results[0]["sequence"] == 2


# ── 方向3：人物类走图生图（image_edit_v1 flag 门控 + 优雅降级） ──────────
class EditFlagStub:
    def __init__(self, edit_enabled: bool = True) -> None:
        self.edit_enabled = edit_enabled

    def is_enabled(self, name: str) -> bool:
        if name == "world_image_candidates_v1":
            return True
        if name == "image_edit_v1":
            return self.edit_enabled
        return False


class EditWorkflowStub:
    """同时具备 generate_image 与 generate_image_edit 的工作流桩。"""

    def __init__(self, edit_status: str = "completed") -> None:
        self.edit_status = edit_status
        self.generate_calls: list[dict] = []
        self.edit_calls: list[dict] = []

    def generate_image(self, **kwargs) -> dict:
        self.generate_calls.append(kwargs)
        return {
            "status": "completed",
            "request_id": "txt2img",
            "side_effects": {
                "provider_called": True,
                "asset_created": True,
                "delivery_created": True,
            },
            "delivery_plan": {"delivery_plan_id": "txt-delivery", "status": "planned"},
        }

    def generate_image_edit(self, **kwargs) -> dict:
        self.edit_calls.append(kwargs)
        if self.edit_status == "completed":
            return {
                "status": "completed",
                "request_id": "img2img",
                "side_effects": {
                    "provider_called": True,
                    "asset_created": True,
                    "delivery_created": True,
                },
                "delivery_plan": {"delivery_plan_id": "edit-delivery", "status": "planned"},
            }
        return {
            "status": "failed",
            "request_id": "img2img",
            "error_code": self.edit_status,
            "side_effects": {
                "provider_called": False,
                "asset_created": False,
                "delivery_created": False,
            },
            "delivery_plan": None,
        }


def _role_edit_consumer(tmp_path, workflow, flags):
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    return WorldImageCandidateConsumer(
        feature_flags=flags,
        image_workflow=workflow,
        world_port=WorldPortStub(),
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=JsonWorldImageCandidateStore(tmp_path / "edit.json"),
        clock=_clock,
    )


@pytest.mark.asyncio
async def test_edit_flag_off_uses_txt2img_for_role(tmp_path):
    """image_edit_v1 关闭时，角色类也走文生图（generate_image），不调用 edit。"""
    workflow = EditWorkflowStub("completed")
    consumer = _role_edit_consumer(tmp_path, workflow, FlagStub(True))
    result = await consumer.process_event(
        _candidate_event(prompt_key="role_selfie", reason_code="user_requested")
    )
    assert result["status"] == "completed"
    assert workflow.generate_calls
    assert workflow.edit_calls == []


@pytest.mark.asyncio
async def test_edit_flag_on_role_uses_img2img_with_reference(tmp_path):
    """image_edit_v1 开启 + 角色类 → 走 generate_image_edit，并带 three_view:front 参考资产。"""
    workflow = EditWorkflowStub("completed")
    consumer = _role_edit_consumer(tmp_path, workflow, EditFlagStub(True))
    result = await consumer.process_event(
        _candidate_event(prompt_key="role_selfie", reason_code="user_requested")
    )
    assert result["status"] == "completed"
    assert workflow.edit_calls
    assert workflow.edit_calls[0]["reference_assets"] == ["three_view:front"]
    assert workflow.generate_calls == []


@pytest.mark.asyncio
async def test_edit_failure_falls_back_to_txt2img(tmp_path):
    """edit 未产出 completed（缺参考资产/不支持）→ 优雅降级回文生图，用户要图不落空。"""
    workflow = EditWorkflowStub("missing_reference_asset")
    consumer = _role_edit_consumer(tmp_path, workflow, EditFlagStub(True))
    result = await consumer.process_event(
        _candidate_event(prompt_key="role_selfie", reason_code="user_requested")
    )
    assert result["status"] == "completed"
    assert workflow.edit_calls
    assert workflow.generate_calls  # 已降级
    assert workflow.edit_calls[0]["reference_assets"] == ["three_view:front"]


# ── 方向4：时间光线 + 房间物件恒注入（room 键） ─────────────────
def _fallback_injector():
    from core.companion import Companion

    return Companion.__new__(Companion)._inject_world_context_fallback


def test_room_inject_in_role_selfie_with_objects():
    """role_selfie：光线恒注入 + 房间物件翻译后注入。"""
    out = _fallback_injector()(
        "base。",
        {
            "prompt_key": "role_selfie",
            "time_of_day_light": "深夜，室内一盏暖黄灯",
            "nearby_objects": ["gray_sofa", "bookshelf", "pendant"],
        },
        {"prompt_key": "role_selfie"},
    )
    assert "深夜，室内一盏暖黄灯" in out
    assert "灰模块沙发" in out
    assert "满墙书柜" in out
    assert "你送的挂件" in out
    assert "房间里有" in out


def test_room_inject_skips_when_no_objects():
    """role_selfie 无房间物件 → 只注入光线，不出现"房间里有"，且不返空。"""
    out = _fallback_injector()(
        "base。",
        {"prompt_key": "role_selfie", "time_of_day_light": "深夜暖灯", "nearby_objects": []},
        {"prompt_key": "role_selfie"},
    )
    assert "深夜暖灯" in out
    assert "房间里有" not in out


def test_room_not_injected_for_environment_object():
    """environment_object 兜底规则不含 room → 即使有物件也不重复注入（物件即主体）。"""
    out = _fallback_injector()(
        "base。",
        {
            "prompt_key": "environment_object",
            "time_of_day_light": "白天，窗外阴天",
            "weather_desc": "重庆多云",
            "nearby_objects": ["gray_sofa", "bookshelf"],
        },
        {"prompt_key": "environment_object"},
    )
    assert "重庆多云" in out
    assert "房间里有" not in out


def test_room_fallback_empty_returns_base():
    """全部缺省 → 原样返回 base，绝不返空串。"""
    out = _fallback_injector()("base。", {"prompt_key": "role_selfie"}, {"prompt_key": "role_selfie"})
    assert out == "base。"


# ── P3：consumer 派发时把候选语义字段注入 delivery plan（发图自我认知） ──
class _PlanCaptureSender:
    """记录 sender 收到的 plan，用于断言注入的语义字段。"""

    def __init__(self) -> None:
        self.plan: dict | None = None

    async def __call__(self, plan: dict, workflow_result: dict) -> bool:
        self.plan = dict(plan)
        return True


@pytest.mark.asyncio
async def test_deliver_injects_candidate_fields_to_plan(tmp_path):
    """_deliver 把 candidate 的 reason_code/prompt_key/scene 注入 delivery plan，
    供 sender 生成图片事件描述（P3：发图后知道图里是什么）。"""
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    sender = _PlanCaptureSender()
    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=WorkflowStub(),
        world_port=WorldPortStub(),
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=JsonWorldImageCandidateStore(tmp_path / "deliver-inject.json"),
        clock=_clock,
        sender=sender,
    )
    workflow_result = {
        "delivery_plan": {
            "channel": "qq",
            "target": "3489352115",
            "delivery_plan_id": "delivery-p3",
        },
    }
    ok = await consumer._deliver(
        workflow_result,
        {
            "reason_code": "world_visual:reading_time",
            "prompt_key": "role_in_scene",
            "scene": "life_share",
        },
    )
    assert ok is True
    assert sender.plan is not None
    assert sender.plan["reason_code"] == "world_visual:reading_time"
    assert sender.plan["prompt_key"] == "role_in_scene"
    assert sender.plan["scene"] == "life_share"


@pytest.mark.asyncio
async def test_deliver_without_candidate_keeps_plan_unchanged(tmp_path):
    """无 candidate 时 plan 不被注入额外字段（幂等兼容旧调用方）。"""
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    sender = _PlanCaptureSender()
    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=WorkflowStub(),
        world_port=WorldPortStub(),
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=JsonWorldImageCandidateStore(tmp_path / "deliver-no-cand.json"),
        clock=_clock,
        sender=sender,
    )
    plan = {"channel": "qq", "target": "123", "delivery_plan_id": "d0"}
    ok = await consumer._deliver({"delivery_plan": plan})
    assert ok is True
    assert sender.plan == plan


@pytest.mark.asyncio
async def test_world_port_provider_tracks_runtime_replacement(tmp_path):
    """Scheme-3 回归：consumer 每次消费都取当前 world_port，运行中被替换
    （如 /api/world/runtime/bind 把 InProcess 换成 sidecar 适配器）后立即读到
    新适配器的事件，杜绝 publish 与 consume 端口分离导致的生图断链。
    """
    from core.world_image_candidates import (
        JsonWorldImageCandidateStore,
        WorldImageCandidateConsumer,
    )

    holder = {"port": WorldPortStub()}
    consumer = WorldImageCandidateConsumer(
        feature_flags=FlagStub(True),
        image_workflow=WorkflowStub(),
        world_port=lambda: holder["port"],
        push_policy=PolicyStub(),
        proactive_judge=JudgeStub(),
        store=JsonWorldImageCandidateStore(tmp_path / "scheme3-track.json"),
        clock=_clock,
    )

    # 端口 A：无事件 → 空消费（修复前 consumer 持有的旧场景）。
    res_a = await consumer.consume_replay(last_seq=0)
    assert res_a == []

    # 运行时替换端口（模拟 runtime/bind 注入的适配器），事件落进新端口。
    port_b = WorldPortStub(events=[_candidate_event()])
    holder["port"] = port_b

    # 同一 consumer 必须立即读到新端口的事件并 ACK —— 修复前它持有旧端口拿不到。
    res_b = await consumer.consume_replay(last_seq=0)
    assert len(res_b) == 1
    assert res_b[0]["status"] == "completed"
    assert port_b.acks == [7]

