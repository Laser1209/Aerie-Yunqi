"""配图多端口投递：图片必须跟到文本实际投递过的端口。

**背景（实测 2026-09-28 15:51~15:55）**

同一轮主动消息，文本在 **QQ 与桌面都到**（QQ 走 `_send_proactive_bubbles`，
桌面走 `chat_events.emit`），但配图**只到了桌面** —— 因为
`_maybe_attach_companion_image` 把 `channel` 写死成 `local_chat`。

本测试锁定修好后的契约：候选声明 `delivery_channels` 时，`_deliver` 逐端投递；
未声明时回落单一渠道（聊天要图等单端口路径行为不变）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from core.world_image_candidates import (
    WorldImageCandidateConsumer,
    _DELIVERY_CHANNELS,
)


class _Flags:
    def is_enabled(self, name: str) -> bool:  # noqa: ARG002
        return True


def _consumer(sender) -> WorldImageCandidateConsumer:
    return WorldImageCandidateConsumer(
        feature_flags=_Flags(),
        image_workflow=None,
        sender=sender,
    )


def _workflow_result(channel: str = "local_chat") -> dict[str, Any]:
    return {
        "status": "completed",
        "asset": {"url": "/uploads/x.png"},
        "delivery_plan": {
            "delivery_plan_id": "p1",
            "request_id": "r1",
            "channel": channel,
            "target": "3489352115",
            "asset_url": "/uploads/x.png",
        },
    }


@pytest.mark.asyncio
async def test_fans_out_to_all_declared_channels():
    """文本到了 QQ + 桌面，图片必须两边都发。"""
    seen: list[str] = []

    async def sender(plan, workflow_result):  # noqa: ARG001
        seen.append(str(plan.get("channel")))
        return True

    consumer = _consumer(sender)
    candidate = {
        "candidate_id": "c1",
        "channel": "qq",
        "delivery_channels": ["qq", "local_chat"],
        "prompt_key": "role_in_scene",
    }

    delivered = await consumer._deliver(_workflow_result(), candidate)

    assert delivered is True
    assert seen == ["qq", "local_chat"]


@pytest.mark.asyncio
async def test_single_channel_fallback_unchanged():
    """未声明 delivery_channels（聊天要图路径）：沿用 plan 里的单一渠道。"""
    seen: list[str] = []

    async def sender(plan, workflow_result):  # noqa: ARG001
        seen.append(str(plan.get("channel")))
        return True

    consumer = _consumer(sender)
    delivered = await consumer._deliver(
        _workflow_result("ilink"), {"candidate_id": "c2"},
    )

    assert delivered is True
    assert seen == ["ilink"]


@pytest.mark.asyncio
async def test_one_channel_failure_does_not_block_others():
    """单端失败不得让整张图丢掉（另一个端仍要收到）。"""
    seen: list[str] = []

    async def sender(plan, workflow_result):  # noqa: ARG001
        channel = str(plan.get("channel"))
        seen.append(channel)
        if channel == "qq":
            raise RuntimeError("QQ 掉线")
        return True

    consumer = _consumer(sender)
    delivered = await consumer._deliver(
        _workflow_result(), {"candidate_id": "c3", "delivery_channels": ["qq", "local_chat"]},
    )

    assert delivered is True          # 桌面成功，整体算投递成功
    assert seen == ["qq", "local_chat"]


@pytest.mark.asyncio
async def test_invalid_channels_are_filtered():
    seen: list[str] = []

    async def sender(plan, workflow_result):  # noqa: ARG001
        seen.append(str(plan.get("channel")))
        return True

    consumer = _consumer(sender)
    delivered = await consumer._deliver(
        _workflow_result(),
        {"candidate_id": "c4", "delivery_channels": ["qq", "telegram", ""]},
    )

    assert delivered is True
    assert seen == ["qq"]


@pytest.mark.asyncio
async def test_all_invalid_channels_skips_delivery():
    called = {"n": 0}

    async def sender(plan, workflow_result):  # noqa: ARG001
        called["n"] += 1
        return True

    consumer = _consumer(sender)
    delivered = await consumer._deliver(
        _workflow_result("local_chat"),
        {"candidate_id": "c5", "delivery_channels": ["telegram"]},
    )

    assert delivered is False
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_each_channel_gets_its_own_plan_copy():
    """两端不能共用同一个 dict：后一端会读到被改写的 channel。"""
    plans: list[dict] = []

    async def sender(plan, workflow_result):  # noqa: ARG001
        plans.append(plan)
        return True

    consumer = _consumer(sender)
    await consumer._deliver(
        _workflow_result(), {"candidate_id": "c6", "delivery_channels": ["qq", "local_chat"]},
    )

    assert plans[0] is not plans[1]
    assert plans[0]["channel"] == "qq"
    assert plans[1]["channel"] == "local_chat"
    # 其余元信息两端共享
    assert plans[0]["delivery_plan_id"] == plans[1]["delivery_plan_id"] == "p1"


def test_delivery_channels_whitelist_is_the_three_ports():
    assert _DELIVERY_CHANNELS == frozenset({"qq", "ilink", "local_chat"})


# ── 候选重建白名单必须保留 delivery_channels ─────────────────────────────


def _event_with_payload(payload: dict) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(
        event_type="world.image_candidate.published",
        topic="",
        payload=payload,
        event_id="e1",
        occurred_at="2026-09-28T07:55:51+00:00",
    )


def test_candidate_reconstruction_preserves_delivery_channels():
    """候选是按显式白名单重建的：漏字段就会被静默丢弃，配图又只剩桌面端。"""
    consumer = _consumer(None)
    event = _event_with_payload({
        "candidate_id": "c7",
        "idempotency_key": "k7",
        "prompt_key": "role_in_scene",
        "channel": "qq",
        "delivery_channels": ["QQ", "local_chat"],
    })

    candidate = consumer._candidate_from_event(event)

    assert candidate is not None
    # 归一为小写，便于后续比对
    assert candidate["delivery_channels"] == ["qq", "local_chat"]


def test_candidate_reconstruction_defaults_to_empty_channels():
    consumer = _consumer(None)
    event = _event_with_payload({
        "candidate_id": "c8",
        "idempotency_key": "k8",
        "prompt_key": "role_selfie",
        "channel": "qq",
    })

    candidate = consumer._candidate_from_event(event)

    assert candidate is not None
    # 空列表 → _deliver 回落到 plan 的单一渠道，行为与改动前一致
    assert candidate["delivery_channels"] == []
