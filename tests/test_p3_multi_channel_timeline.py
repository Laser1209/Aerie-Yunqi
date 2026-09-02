"""P3 多端存在 + 跨端时间线测试（附录 A.3.1-A.3.3 / §5 验收 2 前置）。

覆盖：010 migration、PersonaTimelineRepository 幂等写入与查询、
ContextAssembler 多端存在提示 + 视图 B 跨端回忆注入、flag 默认关闭。
"""

import sqlite3

from core.conversation_continuity import (
    ContextAssembler,
    ConversationSummaryRepository,
    PersonaTimelineRepository,
)
from core.conversation_repository import ConversationRepository


def _connection():
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
    runner = MigrationRunner(conn)
    runner.run(phase3_conversation_migrations())
    conn.execute("ALTER TABLE messages ADD COLUMN channel_account_id TEXT")
    runner.run(desktop_chat_continuity_migrations())
    runner.run(summary_buckets_migrations())
    runner.run(persona_timeline_migrations())
    return conn


def test_timeline_migration_creates_table_and_is_idempotent():
    from core.migrations import MigrationRunner, persona_timeline_migrations

    conn = _connection()
    assert MigrationRunner(conn).run(persona_timeline_migrations()) == []
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='persona_timeline'"
    ).fetchone()
    assert row is not None
    idx = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND tbl_name='persona_timeline' AND name='idx_timeline_lookup'"
    ).fetchone()
    assert idx is not None


def test_timeline_upsert_is_idempotent_by_turn():
    conn = _connection()
    repo = PersonaTimelineRepository(conn)
    assert repo.upsert_event(
        actor_id="actor_ita",
        user_id=7,
        channel="qq",
        turn_id="conv_x:b1",
        event_summary="用户问我猜今天干了什么",
        occurred_at="2026-08-12T22:10:00Z",
    )
    assert repo.upsert_event(
        actor_id="actor_ita",
        user_id=7,
        channel="qq",
        turn_id="conv_x:b1",
        event_summary="重复写入",
        occurred_at="2026-08-12T22:11:00Z",
    )
    rows = conn.execute("SELECT * FROM persona_timeline").fetchall()
    assert len(rows) == 1
    assert rows[0]["event_summary"] == "用户问我猜今天干了什么"


def test_timeline_recent_events_order_and_exclude_channel():
    conn = _connection()
    repo = PersonaTimelineRepository(conn)
    repo.upsert_event(
        actor_id="actor_ita", user_id=7, channel="qq",
        turn_id="a", event_summary="QQ 事件一", occurred_at="2026-08-12T22:00:00Z",
    )
    repo.upsert_event(
        actor_id="actor_ita", user_id=7, channel="desktop",
        turn_id="b", event_summary="桌面事件二", occurred_at="2026-08-12T22:30:00Z",
    )
    repo.upsert_event(
        actor_id="actor_ita", user_id=7, channel="qq",
        turn_id="c", event_summary="QQ 事件三", occurred_at="2026-08-12T23:00:00Z",
    )
    all_events = repo.recent_events(actor_id="actor_ita", user_id=7, limit=3)
    assert [e["turn_id"] for e in all_events] == ["c", "b", "a"]
    cross = repo.recent_events(
        actor_id="actor_ita",
        user_id=7,
        limit=3,
        exclude_channel="qq",
    )
    assert [e["channel"] for e in cross] == ["desktop"]


def _assembler():
    conn = _connection()
    repo = ConversationRepository(database=conn, enabled=True)
    summaries = ConversationSummaryRepository(conn)
    return ContextAssembler(repo, summaries, max_total_chars=4000)


def test_assembler_injects_multi_channel_identity_and_view_b():
    asm = _assembler()
    result = asm.assemble(
        system_prompt="SYSTEM",
        current_user_content="继续",
        actor_id="actor",
        channel="desktop",
        channel_account_id="local",
        user_id=7,
        conversation_id="conv_multi",
        multi_channel_identity=True,
        timeline_events=[
            {
                "channel": "qq",
                "occurred_at": "2026-08-12T22:10:00Z",
                "event_summary": "你让我猜今天干了什么",
            },
            {
                "channel": "desktop",
                "occurred_at": "2026-08-12T00:30:00Z",
                "event_summary": "我们讨论了照片的话题",
            },
        ],
    )
    system = result.messages[0]["content"]
    assert "【多端存在】" in system
    assert "【当前通道】你正在通过「云栖桌面 App」与用户聊天。" in system
    assert "[跨端回忆]" in system
    assert "08-12 22:10 [QQ] 你让我猜今天干了什么" in system
    assert result.audit["multi_channel_identity"] is True
    assert result.audit["timeline_events"] == 2
    assert result.audit["bounded"] is True


def test_assembler_skips_view_b_when_flag_off_or_events_empty():
    asm = _assembler()
    result_off = asm.assemble(
        system_prompt="SYSTEM",
        current_user_content="继续",
        actor_id="actor",
        channel="desktop",
        channel_account_id="local",
        user_id=7,
        conversation_id="conv_off",
        multi_channel_identity=False,
        timeline_events=[
            {"channel": "qq", "occurred_at": "2026-08-12T22:10:00Z", "event_summary": "x"}
        ],
    )
    assert "【多端存在】" not in result_off.messages[0]["content"]
    assert "[跨端回忆]" not in result_off.messages[0]["content"]

    result_empty = asm.assemble(
        system_prompt="SYSTEM",
        current_user_content="继续",
        actor_id="actor",
        channel="desktop",
        channel_account_id="local",
        user_id=7,
        conversation_id="conv_empty",
        multi_channel_identity=True,
        timeline_events=[],
    )
    assert "【多端存在】" in result_empty.messages[0]["content"]
    assert "[跨端回忆]" not in result_empty.messages[0]["content"]
    assert result_empty.audit["timeline_events"] == 0


def test_timeline_line_truncates_to_80_chars():
    from core.conversation_continuity import ContextAssembler

    lines = ContextAssembler._format_timeline_events(
        [
            {
                "channel": "qq",
                "occurred_at": "2026-08-12T22:10:00Z",
                "event_summary": "x" * 200,
            }
        ]
    )
    assert len(lines) == 1
    assert len(lines[0]) <= 80 + len("- 08-12 22:10 [QQ] ")


def test_multi_channel_flag_default_on():
    from core.feature_flags import FeatureFlags

    assert FeatureFlags().is_enabled("multi_channel_identity_v1") is True


def test_view_b_budget_within_500_chars():
    """附录 A.3.3：视图 B（多端存在提示 + 跨端回忆 3 条）预算 ≤ 500 字符。"""
    asm = _assembler()
    result = asm.assemble(
        system_prompt="SYSTEM",
        current_user_content="继续",
        actor_id="actor",
        channel="desktop",
        channel_account_id="local",
        user_id=7,
        conversation_id="conv_budget",
        multi_channel_identity=True,
        timeline_events=[
            {
                "channel": ch,
                "occurred_at": "2026-08-12T22:10:00Z",
                "event_summary": "事件摘要" * 20,
            }
            for ch in ("qq", "qq", "mobile")
        ],
    )
    system = result.messages[0]["content"]
    # 视图 B 段落（多端存在提示 + [跨端回忆]）整体不超过 500 字符
    multi_start = system.find("【多端存在】")
    recall_start = system.find("[跨端回忆]")
    if multi_start != -1 and recall_start != -1:
        view_b = system[multi_start: recall_start + 500]
        assert len(view_b) <= 500
    # 3 条事件行均被 80 字符截断（行 = 前缀 + 80 字符摘要，前缀 ≤ 30）
    for line in system.splitlines():
        if line.startswith("- "):
            assert len(line) <= 80 + 30
            assert len(line.split("] ", 1)[-1]) <= 80


def test_write_isolation_red_line_l0_never_injects_other_channels():
    """附录 A.2 写入隔离红线：跨端时间线只进视图 B 摘要，不进 L0 历史。"""
    asm = _assembler()
    result = asm.assemble(
        system_prompt="SYSTEM",
        current_user_content="继续",
        actor_id="actor",
        channel="desktop",
        channel_account_id="local",
        user_id=7,
        conversation_id="conv_isolation",
        multi_channel_identity=True,
        timeline_events=[
            {
                "channel": "qq",
                "occurred_at": "2026-08-12T22:10:00Z",
                "event_summary": "QQ端完整对话内容泄漏标记XYZ",
            }
        ],
    )
    messages = result.messages
    system = messages[0]["content"]
    # 跨端内容以 [跨端回忆] 摘要形式存在于 system（视图 B）
    assert "[跨端回忆]" in system
    assert "泄漏标记XYZ" in system
    # 但 L0 历史消息（system 之后、user 之前）不含任何跨端消息正文
    history = messages[1:-1]
    for h in history:
        assert "泄漏标记XYZ" not in h["content"]
        assert h["role"] in {"user", "assistant"}
    assert messages[-1]["role"] == "user"
