from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from core.paths import data_dir
from core.windows_dpapi import DPAPIError, protect_data, unprotect_data


class ILinkStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ILinkBinding:
    bot_id: str
    ilink_user_id: str
    primary_user_id: int


class ILinkStateStore:
    def __init__(
        self,
        path: str | Path | None = None,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path or data_dir() / "ilink_state.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._connection = sqlite3.connect(str(self.path))
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def close(self) -> None:
        self._connection.close()

    def get_cursor(self, bot_id: str) -> str:
        row = self._connection.execute(
            "SELECT cursor FROM ilink_sessions WHERE bot_id = ?",
            (bot_id,),
        ).fetchone()
        return str(row["cursor"]) if row else ""

    def set_cursor(self, bot_id: str, cursor: str) -> None:
        self._connection.execute(
            """INSERT INTO ilink_sessions(bot_id, cursor, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(bot_id) DO UPDATE SET
                   cursor = excluded.cursor,
                   updated_at = excluded.updated_at""",
            (bot_id, cursor, self._timestamp()),
        )
        self._connection.commit()

    def get_context_token(self, bot_id: str) -> str | None:
        row = self._connection.execute(
            "SELECT context_ciphertext FROM ilink_sessions WHERE bot_id = ?",
            (bot_id,),
        ).fetchone()
        if row is None or row["context_ciphertext"] is None:
            return None
        try:
            return unprotect_data(bytes(row["context_ciphertext"])).decode("utf-8")
        except (DPAPIError, UnicodeError) as exc:
            raise ILinkStateError("Unable to decrypt iLink context token") from exc

    def set_context_token(self, bot_id: str, token: str) -> None:
        try:
            ciphertext = protect_data(token.encode("utf-8"))
        except DPAPIError as exc:
            raise ILinkStateError("Unable to encrypt iLink context token") from exc
        self._connection.execute(
            """INSERT INTO ilink_sessions(
                   bot_id, cursor, context_ciphertext, updated_at
               ) VALUES (?, '', ?, ?)
               ON CONFLICT(bot_id) DO UPDATE SET
                   context_ciphertext = excluded.context_ciphertext,
                   updated_at = excluded.updated_at""",
            (bot_id, ciphertext, self._timestamp()),
        )
        self._connection.commit()

    def is_message_processed(self, bot_id: str, dedupe_key: str) -> bool:
        row = self._connection.execute(
            """SELECT 1 FROM ilink_processed_messages
               WHERE bot_id = ? AND dedupe_key = ?""",
            (bot_id, dedupe_key),
        ).fetchone()
        return row is not None

    def mark_message_processed(self, bot_id: str, dedupe_key: str) -> bool:
        cursor = self._connection.execute(
            """INSERT OR IGNORE INTO ilink_processed_messages(
                   bot_id, dedupe_key, processed_at
               ) VALUES (?, ?, ?)""",
            (bot_id, dedupe_key, self._timestamp()),
        )
        self._connection.commit()
        return cursor.rowcount == 1

    def create_pairing_code(self, bot_id: str) -> str:
        code = f"{secrets.randbelow(100_000_000):08d}"
        salt = secrets.token_bytes(32)
        digest = self._pairing_digest(salt, code)
        expires_at = self._now() + timedelta(minutes=10)
        self._connection.execute(
            """INSERT INTO ilink_pairing(
                   bot_id, code_hash, salt, expires_at, failed_attempts
               ) VALUES (?, ?, ?, ?, 0)
               ON CONFLICT(bot_id) DO UPDATE SET
                   code_hash = excluded.code_hash,
                   salt = excluded.salt,
                   expires_at = excluded.expires_at,
                   failed_attempts = 0""",
            (bot_id, digest, salt, expires_at.isoformat()),
        )
        self._connection.commit()
        return code

    def verify_pairing(
        self,
        bot_id: str,
        ilink_user_id: str,
        message: str,
        primary_user_id: int,
    ) -> bool:
        if self.get_binding(bot_id) is not None:
            return False
        row = self._connection.execute(
            """SELECT code_hash, salt, expires_at, failed_attempts
               FROM ilink_pairing WHERE bot_id = ?""",
            (bot_id,),
        ).fetchone()
        if row is None:
            return False
        expires_at = datetime.fromisoformat(row["expires_at"])
        if self._now() >= expires_at or row["failed_attempts"] >= 5:
            self._connection.execute("DELETE FROM ilink_pairing WHERE bot_id = ?", (bot_id,))
            self._connection.commit()
            return False
        candidate = self._pairing_digest(bytes(row["salt"]), message)
        if not hmac.compare_digest(bytes(row["code_hash"]), candidate):
            failed_attempts = int(row["failed_attempts"]) + 1
            if failed_attempts >= 5:
                self._connection.execute(
                    "DELETE FROM ilink_pairing WHERE bot_id = ?",
                    (bot_id,),
                )
            else:
                self._connection.execute(
                    "UPDATE ilink_pairing SET failed_attempts = ? WHERE bot_id = ?",
                    (failed_attempts, bot_id),
                )
            self._connection.commit()
            return False
        with self._connection:
            self._connection.execute(
                """INSERT INTO ilink_bindings(
                       bot_id, ilink_user_id, primary_user_id, bound_at
                   ) VALUES (?, ?, ?, ?)""",
                (bot_id, ilink_user_id, primary_user_id, self._timestamp()),
            )
            self._connection.execute("DELETE FROM ilink_pairing WHERE bot_id = ?", (bot_id,))
        return True

    def get_binding(self, bot_id: str) -> ILinkBinding | None:
        row = self._connection.execute(
            """SELECT bot_id, ilink_user_id, primary_user_id
               FROM ilink_bindings WHERE bot_id = ?""",
            (bot_id,),
        ).fetchone()
        return ILinkBinding(**dict(row)) if row else None

    def clear(self, bot_id: str) -> None:
        with self._connection:
            self._connection.execute("DELETE FROM ilink_sessions WHERE bot_id = ?", (bot_id,))
            self._connection.execute("DELETE FROM ilink_pairing WHERE bot_id = ?", (bot_id,))
            self._connection.execute("DELETE FROM ilink_bindings WHERE bot_id = ?", (bot_id,))
            self._connection.execute(
                "DELETE FROM ilink_processed_messages WHERE bot_id = ?",
                (bot_id,),
            )

    def _initialize(self) -> None:
        self._connection.executescript(
            """CREATE TABLE IF NOT EXISTS ilink_sessions (
                   bot_id TEXT PRIMARY KEY,
                   cursor TEXT NOT NULL DEFAULT '',
                   context_ciphertext BLOB,
                   updated_at TEXT NOT NULL
               );
               CREATE TABLE IF NOT EXISTS ilink_pairing (
                   bot_id TEXT PRIMARY KEY,
                   code_hash BLOB NOT NULL,
                   salt BLOB NOT NULL,
                   expires_at TEXT NOT NULL,
                   failed_attempts INTEGER NOT NULL
               );
               CREATE TABLE IF NOT EXISTS ilink_bindings (
                   bot_id TEXT PRIMARY KEY,
                   ilink_user_id TEXT NOT NULL UNIQUE,
                   primary_user_id INTEGER NOT NULL,
                   bound_at TEXT NOT NULL
               );
               CREATE TABLE IF NOT EXISTS ilink_processed_messages (
                   bot_id TEXT NOT NULL,
                   dedupe_key TEXT NOT NULL,
                   processed_at TEXT NOT NULL,
                   PRIMARY KEY(bot_id, dedupe_key)
               );"""
        )
        self._connection.commit()

    def _timestamp(self) -> str:
        return self._now().isoformat()

    @staticmethod
    def _pairing_digest(salt: bytes, code: str) -> bytes:
        return hashlib.sha256(salt + code.encode("utf-8")).digest()
