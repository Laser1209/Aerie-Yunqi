"""Aerie · P3 §5 验收 2 跨通道连续性离线验收（真实 LLM 判定）。

在隔离测试 DB 中构造「QQ 对话 → 桌面端继续」场景：
1. QQ conversation 写入带主题词的轮次，模拟摘要刷新写入 persona_timeline 事件
2. 桌面端以显式回忆句式（命中 _RECALL_KEYWORDS）触发视图 B 注入
3. 用真实主模型回复，再用轻量 LLM 判定「回复是否延续 QQ 端主题」
4. 对照组：multi_channel_identity 关闭时同样回复，验证视图 B 是连续性来源

输出连续率（应与 §5 验收 2 的 ≥80% 对齐）。真实链路（QQ/桌面）复测仍待运行时。

用法（仓库根目录）：
    .\\.venv\\Scripts\\python.exe tools\\cross_channel_continuity_acceptance.py
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

from core._hist_utils import channel_short
from core.conversation_continuity import (
    ContextAssembler,
    ConversationSummaryRepository,
    PersonaTimelineRepository,
    SummaryRefreshPlanner,
)
from core.conversation_repository import ConversationRepository
from core.llm_caller import LLMCaller

# 场景：(qq_topic, desktop 追问) —— §5 验收 2 规格 ≥10 组，覆盖多元话题主体
SCENARIOS: list[tuple[str, str]] = [
    ("我最近在学做重庆小面，还专门买了石磨。", "还记得我之前跟你提过重庆小面的事吗？"),
    ("这周末想去洪崖洞看夜景。", "你记得我说过这周末要去哪里吗？"),
    ("我养了只三花猫叫糯米。", "还记得我跟你说的猫叫什么名字吗？"),
    ("我下个月要搬到上海工作了。", "我之前跟你提过搬家的事，你记得吗？"),
    ("最近在减肥，晚上都只吃沙拉。", "你记得我说最近在做什么吗？"),
    ("下周我妈生日，想给她订个蛋糕。", "我之前跟你说过我妈妈生日的事，你还记得吗？"),
    ("最近在学吉他，手指都磨出茧了。", "还记得我说过在学什么乐器吗？"),
    ("周末想去爬歌乐山看日出。", "你记得我说周末有什么打算吗？"),
    ("最近在考虑买一辆公路自行车。", "我跟你提过想买自行车的事，你还记得吗？"),
    ("昨天熬夜把《三体》第二部看完了。", "记得我昨天在看什么书吗？"),
]


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


def _seed_conversation(conn, *, conversation_id, channel, topic, n_turns=3):
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
        user_content = f"第{i}条消息 {topic}" if i == 0 else f"第{i}条消息"
        conn.execute(
            "INSERT INTO messages (message_id, conversation_id, turn_id, role, content, sequence) "
            "VALUES (?, ?, ?, 'user', ?, 1)",
            (f"{conversation_id}_u{i}", conversation_id, turn_id, user_content),
        )
        conn.execute(
            "INSERT INTO messages (message_id, conversation_id, turn_id, role, content, sequence) "
            "VALUES (?, ?, ?, 'assistant', ?, 2)",
            (f"{conversation_id}_a{i}", conversation_id, turn_id, "嗯嗯，我记下了。"),
        )


async def _judge(llm: LLMCaller, reply: str, topic: str) -> bool:
    """轻量 LLM 判定回复是否延续了 QQ 端主题。"""
    prompt = (
        "你是一个连续性判定器。判断下面这条回复是否延续/回应了给定的主题。\n"
        f"主题：{topic}\n"
        f"回复：{reply}\n"
        "只输出一个 JSON 对象，不要其他文字：{\"related\": true 或 false}"
    )
    try:
        resp = await asyncio.wait_for(
            llm.chat(
                [
                    {"role": "system", "content": "你是严格的布尔判定器。"},
                    {"role": "user", "content": prompt},
                ],
                preferred_provider="siliconflow-light",
                temperature=0.0,
            ),
            timeout=12,
        )
        text = (getattr(resp, "text") or "").strip()
        if '"related": true' in text.lower():
            return True
        if '"related": false' in text.lower():
            return False
        # 降级：主题关键词是否出现在回复
        keyword = topic.split("，")[0].split("。")[0].split("，")[0]
        return keyword in reply
    except Exception:
        keyword = topic.split("，")[0].split("。")[0]
        return keyword in reply


async def _run_case(
    *,
    llm: LLMCaller,
    conn,
    topic: str,
    followup: str,
    multi_channel_identity: bool,
    index: int,
) -> dict:
    conv_qq = f"conv_qq_{index}"
    conv_desktop = f"conv_desktop_{index}"
    _seed_conversation(conn, conversation_id=conv_qq, channel="qq", topic=topic)
    _seed_conversation(conn, conversation_id=conv_desktop, channel="desktop", topic="")

    # 模拟摘要刷新 → persona_timeline 事件
    summaries = ConversationSummaryRepository(conn)
    planner = SummaryRefreshPlanner(summaries, turn_interval=3)
    job = planner.prepare(conv_qq)
    if job is not None:
        bucket = planner.complete(job, lambda prev, msgs: " / ".join(
            str(m.get("content") or "") for m in msgs
        ))
        timeline = PersonaTimelineRepository(conn)
        timeline.upsert_event(
            actor_id="actor_ita",
            user_id=7,
            channel="qq",
            turn_id=f"{conv_qq}:b{bucket.get('bucket_index')}",
            event_summary=str(bucket.get("summary") or "")[:400],
        )

    repo = ConversationRepository(database=conn, enabled=True)
    asm = ContextAssembler(repo, summaries, max_total_chars=24_000)
    timeline = PersonaTimelineRepository(conn)
    events = timeline.recent_events(actor_id="actor_ita", user_id=7, limit=3)

    assembled = asm.assemble(
        system_prompt=(
            "你是伊塔，一位28岁的独立设计师，是用户的恋人。说话直接、带着偏爱。"
            "回答要口语化，像真实的人在聊天。"
        ),
        current_user_content=followup,
        actor_id="actor_ita",
        channel="desktop",
        channel_account_id="local",
        user_id=7,
        conversation_id=conv_desktop,
        multi_channel_identity=multi_channel_identity,
        timeline_events=events if multi_channel_identity else [],
    )
    messages = assembled.messages
    resp = await llm.chat(messages, temperature=0.7)
    reply = (getattr(resp, "text") or "").strip()
    related = await _judge(llm, reply, topic)
    return {
        "index": index,
        "topic": topic,
        "followup": followup,
        "reply": reply[:120],
        "related": related,
        "viewB_injected": (
            "[跨端回忆]" in str(assembled.messages[0].get("content") or "")
        ),
    }


async def main() -> None:
    llm = LLMCaller()
    rows: list[dict] = []
    started = time.perf_counter()
    for i, (topic, followup) in enumerate(SCENARIOS):
        conn = _build_db()
        # 对照组：flag 关闭
        control = await _run_case(
            llm=llm, conn=conn, topic=topic, followup=followup,
            multi_channel_identity=False, index=i,
        )
        conn.close()

        conn = _build_db()
        # 实验组：flag 开启 → 视图 B 注入
        treated = await _run_case(
            llm=llm, conn=conn, topic=topic, followup=followup,
            multi_channel_identity=True, index=i,
        )
        conn.close()
        rows.append({"control": control, "treated": treated})

    n = len(SCENARIOS)
    treated_related = sum(1 for r in rows if r["treated"]["related"])
    control_related = sum(1 for r in rows if r["control"]["related"])
    view_b_injected = sum(1 for r in rows if r["treated"]["viewB_injected"])
    report = {
        "case_count": n,
        "treated_continuity_rate": round(treated_related / n, 3),
        "control_continuity_rate": round(control_related / n, 3),
        "viewB_injected_rate": round(view_b_injected / n, 3),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "cases": rows,
    }
    print("=== CROSS_CHANNEL_CONTINUITY_ACCEPTANCE ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # 落盘证据（work_progress 由脚本直接写文件，工具层怪癖不影响）
    out = Path(__file__).resolve().parent.parent / "work_progress" / "cross_channel_continuity_acceptance_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] report written to {out}")


if __name__ == "__main__":
    asyncio.run(main())
