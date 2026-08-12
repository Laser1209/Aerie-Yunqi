from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Sequence

from core._hist_utils import hist_label as _hist_label
from core.conversation_repository import ConversationRepository


class SummaryConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class ContextAssembly:
    messages: list[dict[str, str]]
    audit: dict[str, Any]


class ConversationSummaryRepository:
    """Optimistically-versioned rolling summaries for completed messages."""

    def __init__(self, database: Any) -> None:
        self.database = database

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        if isinstance(self.database, sqlite3.Connection):
            yield self.database
            return
        with self.database.connection() as conn:
            yield conn

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            if not self._table_exists(conn, "conversation_summaries"):
                return None
            row = conn.execute(
                "SELECT * FROM conversation_summaries WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def upsert(
        self,
        *,
        conversation_id: str,
        summary: str,
        through_message_rowid: int,
        source_message_count: int,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        cleaned = str(summary or "").strip()
        if not cleaned:
            raise ValueError("summary must not be empty")
        if len(cleaned) > 12_000:
            raise ValueError("summary exceeds 12000 characters")
        if through_message_rowid < 0 or source_message_count < 0:
            raise ValueError("summary counters must be non-negative")

        with self._connection() as conn:
            conn.execute("SAVEPOINT upsert_conversation_summary")
            try:
                current = conn.execute(
                    "SELECT revision FROM conversation_summaries "
                    "WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()
                if current is None:
                    if expected_revision not in {None, 0}:
                        raise SummaryConflict("summary revision conflict")
                    conn.execute(
                        """INSERT INTO conversation_summaries
                           (conversation_id, summary, through_message_rowid,
                            source_message_count, revision)
                           VALUES (?, ?, ?, ?, 1)""",
                        (
                            conversation_id,
                            cleaned,
                            int(through_message_rowid),
                            int(source_message_count),
                        ),
                    )
                else:
                    current_revision = int(current["revision"])
                    if (
                        expected_revision is not None
                        and expected_revision != current_revision
                    ):
                        raise SummaryConflict("summary revision conflict")
                    updated = conn.execute(
                        """UPDATE conversation_summaries
                           SET summary = ?, through_message_rowid = ?,
                               source_message_count = ?,
                               revision = revision + 1,
                               updated_at = strftime(
                                   '%Y-%m-%dT%H:%M:%fZ', 'now'
                               )
                           WHERE conversation_id = ? AND revision = ?""",
                        (
                            cleaned,
                            int(through_message_rowid),
                            int(source_message_count),
                            conversation_id,
                            current_revision,
                        ),
                    ).rowcount
                    if updated != 1:
                        raise SummaryConflict("summary revision conflict")
            except Exception:
                conn.execute("ROLLBACK TO SAVEPOINT upsert_conversation_summary")
                conn.execute("RELEASE SAVEPOINT upsert_conversation_summary")
                raise
            conn.execute("RELEASE SAVEPOINT upsert_conversation_summary")
            row = conn.execute(
                "SELECT * FROM conversation_summaries WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return dict(row)

    def completed_messages_after(
        self,
        *,
        conversation_id: str,
        after_rowid: int = 0,
        limit: int = 400,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        with self._connection() as conn:
            if not self._table_exists(conn, "messages"):
                return []
            rows = conn.execute(
                """SELECT m.rowid AS history_rowid, m.message_id,
                          m.turn_id, m.role, m.content, m.created_at
                   FROM messages m
                   JOIN turns t ON t.turn_id = m.turn_id
                   WHERE m.conversation_id = ?
                     AND m.rowid > ?
                     AND t.status = 'completed'
                   ORDER BY m.rowid ASC
                   LIMIT ?""",
                (conversation_id, int(after_rowid), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def refresh_due(
        self,
        *,
        conversation_id: str,
        turn_interval: int = 20,
        char_threshold: int = 12_000,
    ) -> bool:
        current = self.get(conversation_id)
        after = int(current["through_message_rowid"]) if current else 0
        with self._connection() as conn:
            if not self._table_exists(conn, "messages"):
                return False
            row = conn.execute(
                """SELECT COUNT(DISTINCT m.turn_id) AS turn_count,
                          COALESCE(SUM(length(m.content)), 0) AS char_count
                   FROM messages m
                   JOIN turns t ON t.turn_id = m.turn_id
                   WHERE m.conversation_id = ?
                     AND m.rowid > ?
                     AND t.status = 'completed'""",
                (conversation_id, after),
            ).fetchone()
        return (
            int(row["turn_count"] or 0) >= max(1, int(turn_interval))
            or int(row["char_count"] or 0) >= max(1, int(char_threshold))
        )

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone() is not None


class SummaryRefreshPlanner:
    """Build bounded summary jobs; callers schedule them off the send path."""

    def __init__(
        self,
        repository: ConversationSummaryRepository,
        *,
        max_input_chars: int = 24_000,
    ) -> None:
        self.repository = repository
        self.max_input_chars = max(1000, int(max_input_chars))

    def prepare(self, conversation_id: str) -> dict[str, Any] | None:
        if not self.repository.refresh_due(conversation_id=conversation_id):
            return None
        current = self.repository.get(conversation_id)
        after = int(current["through_message_rowid"]) if current else 0
        rows = self.repository.completed_messages_after(
            conversation_id=conversation_id,
            after_rowid=after,
        )
        if not rows:
            return None
        selected: list[dict[str, Any]] = []
        used = 0
        for row in rows:
            content = str(row.get("content") or "")
            remaining = self.max_input_chars - used
            if remaining <= 0:
                break
            clipped = content[:remaining]
            selected.append({"role": row.get("role", "user"), "content": clipped})
            used += len(clipped)
        last_rowid = int(rows[len(selected) - 1]["history_rowid"])
        return {
            "conversation_id": conversation_id,
            "previous_summary": (current or {}).get("summary", ""),
            "expected_revision": int((current or {}).get("revision", 0)),
            "through_message_rowid": last_rowid,
            "source_message_count": int(
                (current or {}).get("source_message_count", 0)
            ) + len(selected),
            "messages": selected,
        }

    def complete(
        self,
        job: dict[str, Any],
        summarizer: Callable[[str, Sequence[dict[str, str]]], str],
    ) -> dict[str, Any]:
        summary = summarizer(
            str(job.get("previous_summary") or ""),
            job["messages"],
        )
        return self.repository.upsert(
            conversation_id=job["conversation_id"],
            summary=summary,
            through_message_rowid=int(job["through_message_rowid"]),
            source_message_count=int(job["source_message_count"]),
            expected_revision=int(job["expected_revision"]),
        )


class ContextAssembler:
    """Combine recent history, summary and retrieved snippets within a hard cap."""

    def __init__(
        self,
        conversations: ConversationRepository,
        summaries: ConversationSummaryRepository,
        *,
        max_total_chars: int = 16_000,
        recent_message_limit: int = 24,
        max_summary_chars: int = 3_500,
        max_memory_chars: int = 2_000,
        max_attachment_chars: int = 4_000,
    ) -> None:
        self.conversations = conversations
        self.summaries = summaries
        self.max_total_chars = max(2000, int(max_total_chars))
        self.recent_message_limit = max(2, min(int(recent_message_limit), 200))
        self.max_summary_chars = max(0, int(max_summary_chars))
        self.max_memory_chars = max(0, int(max_memory_chars))
        self.max_attachment_chars = max(0, int(max_attachment_chars))

    def assemble(
        self,
        *,
        system_prompt: str,
        current_user_content: str,
        actor_id: str | None,
        channel: str | None,
        channel_account_id: str | None,
        user_id: int,
        conversation_id: str | None = None,
        memories: Sequence[str] = (),
        attachment_snippets: Sequence[str] = (),
    ) -> ContextAssembly:
        resolved_id = conversation_id
        if resolved_id is None:
            from core.conversation_repository import resolve_conversation_id

            resolved_id = resolve_conversation_id(
                actor_id=actor_id,
                channel=channel,
                channel_account_id=channel_account_id,
                user_id=user_id,
            )
        page = self.conversations.history_page(
            actor_id=actor_id,
            channel=channel,
            channel_account_id=channel_account_id,
            user_id=user_id,
            conversation_id=resolved_id,
            limit=self.recent_message_limit,
        )
        summary = self.summaries.get(resolved_id)

        supplemental_sections: list[str] = []
        if summary and summary.get("summary"):
            supplemental_sections.append(
                "[滚动对话摘要]\n"
                + self._clip(summary["summary"], self.max_summary_chars)
            )
        memory_text = self._bounded_join(memories, self.max_memory_chars)
        if memory_text:
            supplemental_sections.append("[相关长期记忆]\n" + memory_text)
        attachment_text = self._bounded_join(
            attachment_snippets,
            self.max_attachment_chars,
        )
        if attachment_text:
            supplemental_sections.append("[相关附件片段]\n" + attachment_text)

        current = self._clip(
            str(current_user_content or ""),
            min(6000, self.max_total_chars // 3),
        )
        history_reserve = min(
            6000,
            max(512, self.max_total_chars // 4),
        )
        system_budget = max(
            self.max_total_chars - len(current) - history_reserve,
            0,
        )
        supplemental_chars = sum(len(section) + 2 for section in supplemental_sections)
        if supplemental_chars and system_budget:
            supplemental_reserve = min(
                supplemental_chars,
                max(512, system_budget // 3),
            )
        else:
            supplemental_reserve = 0
        base_budget = min(
            len(str(system_prompt or "")),
            max(system_budget - supplemental_reserve, 0),
        )
        base = self._clip(system_prompt, base_budget)
        system_parts = [base] if base else []
        remaining_system = max(system_budget - len(base), 0)
        for section in supplemental_sections:
            separator = 2 if system_parts else 0
            if remaining_system <= separator:
                break
            clipped = self._clip(section, remaining_system - separator)
            if clipped:
                system_parts.append(clipped)
                remaining_system -= separator + len(clipped)
        system = "\n\n".join(system_parts)
        budget = max(self.max_total_chars - len(system) - len(current), 0)

        history: list[dict[str, str]] = []
        used = 0
        for item in reversed(page["items"]):
            role = item.get("role")
            if role not in {"user", "assistant"}:
                continue
            content = str(item.get("content") or "")
            if not content:
                continue
            label = _hist_label(item)
            entry_len = len(label) + len(content)
            if used + entry_len > budget:
                continue
            history.append({"role": role, "content": label + content})
            used += entry_len
        history.reverse()
        messages = [{"role": "system", "content": system}]
        messages.extend(history)
        messages.append({"role": "user", "content": current})
        total_chars = sum(len(item["content"]) for item in messages)
        return ContextAssembly(
            messages=messages,
            audit={
                "conversation_id": resolved_id,
                "total_chars": total_chars,
                "max_total_chars": self.max_total_chars,
                "history_messages": len(history),
                "summary_revision": int(summary["revision"]) if summary else 0,
                "memory_chars": len(memory_text),
                "attachment_chars": len(attachment_text),
                "bounded": total_chars <= self.max_total_chars,
            },
        )

    @staticmethod
    def _clip(value: Any, limit: int) -> str:
        text = str(value or "")
        if limit <= 0:
            return ""
        if len(text) <= limit:
            return text
        if limit == 1:
            return "…"
        return text[: limit - 1] + "…"

    def _bounded_join(self, values: Sequence[str], limit: int) -> str:
        if limit <= 0:
            return ""
        result: list[str] = []
        used = 0
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            separator = 1 if result else 0
            remaining = limit - used - separator
            if remaining <= 0:
                break
            clipped = self._clip(text, remaining)
            result.append(clipped)
            used += separator + len(clipped)
        return "\n".join(result)
