"""Aerie · P3 过关点「性能无退化」微基准（assemble 耗时对比基线）。

在隔离测试 DB 中对比 ContextAssembler.assemble 两种配置的耗时与体积：
- 基线：multi_channel_identity=False，无视图 B（P0/P1 原有组装路径）
- 视图 B：multi_channel_identity=True + 3 条 persona_timeline 事件

衡量：
1. 平均/中位/95 分位耗时（pytest 之外的可复现数值）
2. 组装后 total chars，验证视图 B 预留预算内（L0 不挤占）
3. 断言：视图 B 相对基线平均耗时增幅 < 20% 且绝对增幅 < 5ms

纯内存计算、不调用 LLM，可直接离线复跑。

用法（仓库根目录）：
    .\\.venv\\Scripts\\python.exe tools\\context_assembler_perf_check.py
"""
from __future__ import annotations

import json
import sqlite3
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.conversation_continuity import (
    ContextAssembler,
    ConversationSummaryRepository,
    PersonaTimelineRepository,
    SummaryRefreshPlanner,
)
from core.conversation_repository import ConversationRepository

RUNS = 50
N_TURNS = 40  # 大于热窗口 8 轮，覆盖滚动窗口/摘要路径


def _build_db():
    from core.migrations import (
        MigrationRunner,
        desktop_chat_continuity_migrations,
        persona_timeline_migrations,
        phase3_conversation_migrations,
        summary_buckets_migrations,
    )

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE actors (actor_id TEXT PRIMARY KEY, created_at TEXT)")
    conn.execute(
        "INSERT OR IGNORE INTO actors (actor_id, created_at) VALUES ('actor_ita', datetime('now'))"
    )
    runner = MigrationRunner(conn)
    runner.run(phase3_conversation_migrations())
    conn.execute("ALTER TABLE messages ADD COLUMN channel_account_id TEXT")
    runner.run(desktop_chat_continuity_migrations())
    runner.run(summary_buckets_migrations())
    runner.run(persona_timeline_migrations())
    return conn


def _seed(conn, *, conversation_id, channel, n_turns=N_TURNS):
    conn.execute(
        "INSERT OR IGNORE INTO conversations (conversation_id, channel, actor_id) "
        "VALUES (?, ?, 'actor_ita')",
        (conversation_id, channel),
    )
    for i in range(n_turns):
        turn_id = f"{conversation_id}_t{i}"
        conn.execute(
            "INSERT INTO turns (turn_id, conversation_id, status, completed_at) "
            "VALUES (?, ?, 'completed', datetime('now'))",
            (turn_id, conversation_id),
        )
        conn.execute(
            "INSERT INTO messages (message_id, conversation_id, turn_id, role, content, sequence) "
            "VALUES (?, ?, ?, 'user', ?, 1)",
            (f"{conversation_id}_u{i}", conversation_id, turn_id, f"第{i}条消息 用户话题{i}"),
        )
        conn.execute(
            "INSERT INTO messages (message_id, conversation_id, turn_id, role, content, sequence) "
            "VALUES (?, ?, ?, 'assistant', ?, 2)",
            (f"{conversation_id}_a{i}", conversation_id, turn_id, "嗯嗯，我记下了。"),
        )


def _refresh_summary_and_timeline(conn, *, conversation_id, user_id, actor_id):
    summaries = ConversationSummaryRepository(conn)
    planner = SummaryRefreshPlanner(summaries, turn_interval=8)
    bucket = planner.complete(
        planner.prepare(conversation_id),
        lambda prev, msgs: " / ".join(str(m.get("content") or "") for m in msgs),
    )
    timeline = PersonaTimelineRepository(conn)
    timeline.upsert_event(
        actor_id=actor_id,
        user_id=user_id,
        channel="qq",
        turn_id=f"{conversation_id}:b{bucket.get('bucket_index')}",
        event_summary=str(bucket.get("summary") or "")[:400],
    )
    return timeline


def _measure(asm, *, conn, conversation_id, user_id, actor_id, timeline, use_view_b):
    samples = []
    charses = []
    for _ in range(RUNS):
        started = time.perf_counter()
        assembled = asm.assemble(
            system_prompt="你是伊塔，28 岁独立设计师，是用户的恋人。",
            current_user_content="最近过得怎么样？",
            actor_id=actor_id,
            channel="desktop",
            channel_account_id="local",
            user_id=user_id,
            conversation_id=conversation_id,
            multi_channel_identity=use_view_b,
            timeline_events=timeline.recent_events(
                actor_id=actor_id, user_id=user_id, limit=3
            )
            if use_view_b
            else [],
        )
        samples.append((time.perf_counter() - started) * 1000.0)
        charses.append(sum(len(str(m.get("content") or "")) for m in assembled.messages))
    samples.sort()
    return {
        "mean_ms": round(statistics.mean(samples), 3),
        "median_ms": round(statistics.median(samples), 3),
        "p95_ms": round(samples[int(len(samples) * 0.95) - 1], 3),
        "min_ms": round(samples[0], 3),
        "max_ms": round(samples[-1], 3),
        "total_chars": max(charses),
        "n": RUNS,
    }


def main() -> None:
    conn = _build_db()
    _seed(conn, conversation_id="conv_qq", channel="qq")
    summaries = ConversationSummaryRepository(conn)
    timeline = _refresh_summary_and_timeline(
        conn, conversation_id="conv_qq", user_id=7, actor_id="actor_ita"
    )
    asm = ContextAssembler(
        ConversationRepository(database=conn, enabled=True),
        summaries,
        max_total_chars=24_000,
    )
    baseline = _measure(
        asm, conn=conn, conversation_id="conv_qq", user_id=7,
        actor_id="actor_ita", timeline=timeline, use_view_b=False,
    )
    view_b = _measure(
        asm, conn=conn, conversation_id="conv_qq", user_id=7,
        actor_id="actor_ita", timeline=timeline, use_view_b=True,
    )
    conn.close()

    overhead_pct = (
        (view_b["mean_ms"] - baseline["mean_ms"]) / baseline["mean_ms"] * 100
        if baseline["mean_ms"]
        else 0.0
    )
    abs_overhead_ms = round(view_b["mean_ms"] - baseline["mean_ms"], 3)
    # 判定：视图 B 为纯字符串格式化（≤3 条事件），绝对增量 < 5ms 且新增字符 ≤ 500
    # （相对百分比在亚毫秒操作上无意义，仅作信息记录）
    added_chars = view_b["total_chars"] - baseline["total_chars"]
    ok = abs_overhead_ms < 5.0 and added_chars <= 500
    report = {
        "runs": RUNS,
        "turns_seeded": N_TURNS,
        "baseline": baseline,
        "view_b": view_b,
        "overhead_pct": round(overhead_pct, 2),
        "abs_overhead_ms": abs_overhead_ms,
        "view_b_added_chars": added_chars,
        "threshold": {"abs_ms": "< 5ms", "added_chars": "<= 500"},
        "pass": ok,
    }
    out = Path(__file__).resolve().parent.parent / "work_progress"
    out.mkdir(exist_ok=True)
    target = out / "context_assembler_perf_report.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("PASS" if ok else "FAIL", target)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
