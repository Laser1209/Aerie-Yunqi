"""Phase 13 world sidecar persistence, outbox, ACK, and supervisor contracts."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from core.world_port import Observation


def test_world_sidecar_store_outbox_ack_and_restart_replay(tmp_path):
    from world_service.storage.sqlite_store import WorldSidecarStore

    db_path = tmp_path / "world.db"
    store = WorldSidecarStore(db_path)
    first = store.append_event(
        topic="world.state",
        event_type="world.snapshot.updated",
        payload={"phase": "morning", "secret": "do not leak"},
        idempotency_key="tick-1",
    )
    duplicate = store.append_event(
        topic="world.state",
        event_type="world.snapshot.updated",
        payload={"phase": "morning", "secret": "changed"},
        idempotency_key="tick-1",
    )

    assert first["seq"] == 1
    assert duplicate["seq"] == first["seq"]
    assert duplicate["event_id"] == first["event_id"]
    assert "do not leak" not in json.dumps(first, ensure_ascii=False)

    pending = store.events_after(consumer_id="core", last_seq=0)
    assert [event["seq"] for event in pending] == [1]
    assert pending[0]["payload"]["payload_keys"] == ["phase", "secret"]
    assert "payload_sha256" in pending[0]["payload"]

    store.ack(consumer_id="core", seq=1)
    restarted = WorldSidecarStore(db_path)
    assert restarted.cursor("core") == 1
    assert restarted.events_after(consumer_id="core", last_seq=1) == []

    second = restarted.append_event(
        topic="world.state",
        event_type="world.snapshot.updated",
        payload={"phase": "afternoon"},
        idempotency_key="tick-2",
    )
    replay = restarted.events_after(consumer_id="core")
    assert [event["seq"] for event in replay] == [2]
    assert second["seq"] == 2


def test_world_sidecar_store_heartbeat_checkpoint_and_single_owner_tables(tmp_path):
    from world_service.storage.sqlite_store import WorldSidecarStore

    store = WorldSidecarStore(tmp_path / "world.db")
    heartbeat = store.heartbeat(status="ready", detail={"token": "secret-token"})
    checkpoint = store.checkpoint(
        checkpoint_id="cp-1",
        state={"phase": "night", "raw_text": "secret text"},
    )

    tables = store.table_names()
    assert {
        "world_state_snapshot",
        "world_outbox",
        "world_ack_cursor",
        "world_heartbeat",
        "world_checkpoint",
    }.issubset(tables)
    assert heartbeat["status"] == "ready"
    assert "secret-token" not in json.dumps(heartbeat, ensure_ascii=False)
    assert checkpoint["checkpoint_id"] == "cp-1"
    assert "secret text" not in json.dumps(checkpoint, ensure_ascii=False)


# ══════════════════════════════════════════════════════
# 保留窗口修剪（world.db 无界增长 → 有界）
# 回归背景：tick 默认 1s，每个 tick 往 world_outbox 与 world_state_snapshot
# 各插一行且从不清理，一天 8.6 万行/表，实测库到 1.07 GB 后拖死 Electron
# 启动握手（也就是「世界第二波起不来」），并把生图投递的世界闸门一起卡住。
# ══════════════════════════════════════════════════════

def test_prune_caps_snapshot_and_outbox_growth(tmp_path):
    from world_service.storage.sqlite_store import WorldSidecarStore

    store = WorldSidecarStore(tmp_path / "world.db")
    for i in range(300):
        store.append_event(
            topic="world.state",
            event_type="world.snapshot.updated",
            payload={"phase": "morning"},
            idempotency_key=f"tick-{i}",
        )

    def counts():
        import sqlite3

        conn = sqlite3.connect(str(tmp_path / "world.db"))
        try:
            snap = conn.execute("SELECT COUNT(*) FROM world_state_snapshot").fetchone()[0]
            out = conn.execute("SELECT COUNT(*) FROM world_outbox").fetchone()[0]
        finally:
            conn.close()
        return snap, out

    assert counts() == (300, 300)

    store.prune(keep_snapshots=50, keep_outbox=80)
    snap, out = counts()
    assert snap == 50, f"snapshot 未被修剪: {snap}"
    assert out == 80, f"outbox 未被修剪: {out}"

    # 再跑一轮：有界，不随 tick 数继续增长
    for i in range(300, 900):
        store.append_event(
            topic="world.state",
            event_type="world.snapshot.updated",
            payload={"phase": "morning"},
            idempotency_key=f"tick-{i}",
        )
    store.prune(keep_snapshots=50, keep_outbox=80)
    snap2, out2 = counts()
    assert (snap2, out2) == (50, 80), f"修剪后仍有界失败: {snap2}, {out2}"


def test_prune_never_drops_unacked_events(tmp_path):
    """消费者未 ACK 的事件不能被删——否则 core 会漏事件（含生图候选）。"""
    from world_service.storage.sqlite_store import WorldSidecarStore

    store = WorldSidecarStore(tmp_path / "world.db")
    for i in range(50):
        store.append_event(
            topic="world.state",
            event_type="world.snapshot.updated",
            payload={"phase": "morning"},
            idempotency_key=f"tick-{i}",
        )
    store.ack(consumer_id="core", seq=10)

    store.prune(keep_snapshots=5, keep_outbox=5)

    # core 的游标是 10：seq>10 的事件必须全都还在
    pending = store.events_after(consumer_id="core")
    assert [e["seq"] for e in pending] == list(range(11, 51))


def test_prune_without_ack_cursor_still_bounded(tmp_path):
    """没有任何消费者 ACK 时也不能无界增长（按条数保留最近一段）。"""
    from world_service.storage.sqlite_store import WorldSidecarStore

    store = WorldSidecarStore(tmp_path / "world.db")
    for i in range(200):
        store.append_event(
            topic="observations",
            event_type="world.observation.recorded",
            payload={"observation_type": "note"},
            idempotency_key=f"obs-{i}",
        )

    store.prune(keep_snapshots=10, keep_outbox=30)

    pending = store.events_after(consumer_id="core", last_seq=0)
    assert len(pending) == 30, f"无 ACK 游标时未按条数兜底: {len(pending)}"


def test_maintenance_prunes_through_service_and_http_route(tmp_path):
    """服务维护入口可用（真机就地瘦身用）。

    注意必须注入**递进时钟**：`WorldSimulation.tick()` 有秒级幂等
    （同一秒内重复 tick 返回缓存快照），而 world.state 的幂等键由秒级 ts
    参与生成。不加时钟时，紧密循环里 260 次 tick 落在同一秒，
    只会写入 1 行——那是测试不真实，不是实现有问题。
    """
    from datetime import datetime, timedelta, timezone

    from world_service.main import LocalWorldSidecarService

    base = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
    state = {"n": 0}

    def stepping_clock() -> datetime:
        state["n"] += 1
        return base + timedelta(seconds=state["n"])

    service = LocalWorldSidecarService(
        data_dir=tmp_path,
        clock=stepping_clock,
        prune_interval_seconds=9999,
    )
    for _ in range(260):
        service.tick(force=True)

    result = service.maintenance()
    assert result["snapshots_deleted"] > 0, result
    assert result["vacuumed"] is False

    result2 = service.maintenance(vacuum=True)
    assert result2["vacuumed"] is True


@pytest.mark.asyncio
async def test_remote_world_adapter_crash_degrades_without_blocking_chat(tmp_path):
    from core.world_adapters.remote import RemoteWorldAdapter
    from world_service.main import LocalWorldSidecarService

    service = LocalWorldSidecarService(data_dir=tmp_path)
    adapter = RemoteWorldAdapter(service, fallback_reason="sidecar_unavailable")

    state = await adapter.get_state()
    assert state.source == "remote"
    assert state.status == "running"

    service.crash()
    degraded = await adapter.get_state()
    await adapter.observe(
        Observation(
            observation_type="user_message",
            actor_id="actor-master",
            channel="desktop",
            payload={"text": "must not leak"},
            idempotency_key="obs-crash",
        )
    )

    assert degraded.status == "degraded"
    assert degraded.source == "remote"
    assert degraded.capabilities == ()


@pytest.mark.asyncio
async def test_remote_world_adapter_reconnect_replays_without_duplicates(tmp_path):
    from core.world_adapters.remote import RemoteWorldAdapter
    from world_service.main import LocalWorldSidecarService

    service = LocalWorldSidecarService(data_dir=tmp_path)
    adapter = RemoteWorldAdapter(service, consumer_id="core")
    await adapter.observe(
        Observation(
            observation_type="user_message",
            actor_id="actor-master",
            channel="desktop",
            payload={"text": "hello"},
            idempotency_key="obs-1",
        )
    )
    first = await adapter.replay_events()
    await adapter.ack(first[-1].sequence)

    restarted = LocalWorldSidecarService(data_dir=tmp_path)
    restarted_adapter = RemoteWorldAdapter(restarted, consumer_id="core")
    replay_after_ack = await restarted_adapter.replay_events()
    await restarted_adapter.observe(
        Observation(
            observation_type="user_message",
            actor_id="actor-master",
            channel="desktop",
            payload={"text": "hello"},
            idempotency_key="obs-1",
        )
    )
    replay_duplicate = await restarted_adapter.replay_events()

    assert [event.sequence for event in first] == [1]
    assert replay_after_ack == []
    assert replay_duplicate == []


def test_electron_plugin_supervisor_heartbeat_and_crash_loop_redacted():
    script = r"""
const { createPluginSupervisor } = require("./electron/src/plugin-supervisor");
const supervisor = createPluginSupervisor({ maxCrashes: 2, now: (() => {
  let t = 1000;
  return () => t += 100;
})() });
supervisor.register("aerie.world", { command: "python", token: "secret-token-value" });
supervisor.recordHeartbeat("aerie.world", { status: "ready", token: "secret-token-value" });
supervisor.recordCrash("aerie.world", { code: 1, token: "secret-token-value" });
supervisor.recordCrash("aerie.world", { code: 1 });
const status = supervisor.status("aerie.world");
if (status.state !== "fused") throw new Error("expected fused state: " + status.state);
const audit = JSON.stringify(status);
if (audit.includes("secret-token-value")) throw new Error("secret leaked");
if (status.crashCount !== 2) throw new Error("unexpected crash count");
"""
    subprocess.run(
        ["node", "-e", script],
        cwd=str(Path(__file__).resolve().parents[1]),
        check=True,
        capture_output=True,
        text=True,
    )


def test_world_sidecar_image_candidate_keeps_prompt_modules(tmp_path):
    """Sidecar 载荷必须保留 user_raw / reference_assets。

    它们是提示词模块化的输入，且与进程内 redact_image_candidate 契约逐字段对齐
    （两种 world_port 模式下消费端看到同样的候选）。丢掉 user_raw 会让分部位/
    景别解析拿不到指令，丢掉 reference_assets 会让参考视角永远退回 front。
    """
    from world_service.storage.sqlite_store import WorldSidecarStore

    store = WorldSidecarStore(tmp_path / "world.db")
    store.append_image_candidate(
        {
            "candidate_id": "cand-modules",
            "idempotency_key": "world-cand-modules",
            "prompt_key": "role_selfie",
            "user_raw": "看看腿",
            "reference_assets": ["three_view:back", "three_view:front"],
            "prompt": "raw prompt must not leak",
        }
    )

    events = store.events_after(consumer_id="core", last_seq=0)
    payload = events[0]["payload"]

    assert payload["user_raw"] == "看看腿"
    assert payload["reference_assets"] == ["three_view:back", "three_view:front"]
    assert "raw prompt must not leak" not in json.dumps(payload, ensure_ascii=False)


def test_core_event_stream_publishes_world_event_once():
    from core import event_stream

    event_stream._reset_for_tests()
    first = event_stream.publish_world_event_once(
        {
            "event_id": "world_evt_1",
            "topic": "world.state",
            "event_type": "world.snapshot.updated",
            "seq": 9,
            "payload": {"payload_keys": ["phase"]},
        }
    )
    second = event_stream.publish_world_event_once(
        {
            "event_id": "world_evt_1",
            "topic": "world.state",
            "event_type": "world.snapshot.updated",
            "seq": 9,
            "payload": {"payload_keys": ["phase"]},
        }
    )
    replay = event_stream._events_after("missing")

    assert first is True
    assert second is False
    assert len(replay) == 1
    assert replay[0]["type"] == "world_event"
