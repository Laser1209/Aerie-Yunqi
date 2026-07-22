"""Account, device, and opaque-token boundary for the mobile gateway."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError


Clock = Callable[[], datetime]
USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,32}$")


class MobileAuthError(Exception):
    def __init__(self, code: str, *, status_code: int = 401) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class MobileAccount:
    account_id: str
    username: str
    role: str
    actor_id: str
    user_id: int


@dataclass(frozen=True)
class MobilePrincipal(MobileAccount):
    device_id: str


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    access_expires_in: int
    refresh_expires_in: int
    principal: MobilePrincipal


class MobileIdentityStore:
    ACCESS_TTL = timedelta(minutes=15)
    REFRESH_TTL = timedelta(days=30)
    PAIRING_TTL = timedelta(minutes=10)
    FAILURE_WINDOW = timedelta(minutes=15)
    FAILURE_LIMIT = 5

    def __init__(
        self,
        db_path: str | Path,
        *,
        pepper: str,
        clock: Clock | None = None,
        password_hasher: PasswordHasher | None = None,
    ) -> None:
        if len(pepper.encode("utf-8")) < 32:
            raise ValueError("mobile token pepper must be at least 32 bytes")
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._pepper = pepper.encode("utf-8")
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.password_hasher = password_hasher or PasswordHasher(
            time_cost=3,
            memory_cost=65536,
            parallelism=2,
        )
        self._dummy_password_hash = self.password_hasher.hash(
            secrets.token_urlsafe(24)
        )
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_schema(self) -> None:
        statements = (
            """CREATE TABLE IF NOT EXISTS mobile_accounts (
                account_id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL CHECK(role IN ('owner', 'guest')),
                password_hash TEXT NOT NULL,
                actor_id TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )""",
            """CREATE UNIQUE INDEX IF NOT EXISTS one_enabled_mobile_owner
                ON mobile_accounts(role) WHERE role = 'owner' AND enabled = 1""",
            """CREATE TABLE IF NOT EXISTS mobile_devices (
                device_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL REFERENCES mobile_accounts(account_id),
                device_name TEXT NOT NULL,
                public_key TEXT,
                created_at TEXT NOT NULL,
                last_used_at TEXT NOT NULL,
                revoked_at TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS mobile_access_tokens (
                token_hash TEXT PRIMARY KEY,
                account_id TEXT NOT NULL REFERENCES mobile_accounts(account_id),
                device_id TEXT NOT NULL REFERENCES mobile_devices(device_id),
                expires_at TEXT NOT NULL,
                revoked_at TEXT,
                created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS mobile_refresh_tokens (
                token_id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                account_id TEXT NOT NULL REFERENCES mobile_accounts(account_id),
                device_id TEXT NOT NULL REFERENCES mobile_devices(device_id),
                expires_at TEXT NOT NULL,
                revoked_at TEXT,
                replaced_by TEXT,
                created_at TEXT NOT NULL
            )""",
            """CREATE INDEX IF NOT EXISTS mobile_refresh_family
                ON mobile_refresh_tokens(family_id)""",
            """CREATE TABLE IF NOT EXISTS mobile_pairing_sessions (
                pairing_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL REFERENCES mobile_accounts(account_id),
                code_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                failure_count INTEGER NOT NULL DEFAULT 0,
                used_at TEXT,
                created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS mobile_login_failures (
                failure_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""",
            """CREATE INDEX IF NOT EXISTS mobile_login_failure_lookup
                ON mobile_login_failures(username, ip_address, created_at)""",
            """CREATE TABLE IF NOT EXISTS mobile_audit (
                audit_id TEXT PRIMARY KEY,
                account_id TEXT,
                device_id TEXT,
                event_type TEXT NOT NULL,
                outcome TEXT NOT NULL,
                ip_address TEXT,
                created_at TEXT NOT NULL
            )""",
        )
        with self._lock, self._connect() as conn:
            for statement in statements:
                conn.execute(statement)

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _timestamp(self, value: datetime | None = None) -> str:
        return (value or self._now()).isoformat()

    @staticmethod
    def _normalize_username(username: str) -> str:
        normalized = username.strip().lower()
        if not USERNAME_RE.fullmatch(normalized):
            raise ValueError("username must be 3-32 safe characters")
        return normalized

    def _digest(self, purpose: str, value: str) -> str:
        return hmac.new(
            self._pepper,
            f"{purpose}:{value}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{secrets.token_hex(16)}"

    @staticmethod
    def _opaque_token() -> str:
        return secrets.token_urlsafe(32)

    def _audit(
        self,
        conn: sqlite3.Connection,
        event_type: str,
        outcome: str,
        *,
        account_id: str | None = None,
        device_id: str | None = None,
        ip_address: str | None = None,
    ) -> None:
        conn.execute(
            """INSERT INTO mobile_audit
               (audit_id, account_id, device_id, event_type, outcome,
                ip_address, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                self._id("audit"),
                account_id,
                device_id,
                event_type,
                outcome,
                ip_address,
                self._timestamp(),
            ),
        )

    def create_account(
        self,
        *,
        username: str,
        password: str,
        role: str,
        actor_id: str,
        user_id: int,
    ) -> MobileAccount:
        normalized = self._normalize_username(username)
        if len(password) < 12:
            raise ValueError("password must be at least 12 characters")
        if role not in {"owner", "guest"}:
            raise ValueError("role must be owner or guest")
        if not actor_id.strip():
            raise ValueError("actor_id is required")
        account = MobileAccount(
            account_id=self._id("acct"),
            username=normalized,
            role=role,
            actor_id=actor_id.strip(),
            user_id=int(user_id),
        )
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    """INSERT INTO mobile_accounts
                       (account_id, username, role, password_hash, actor_id,
                        user_id, enabled, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
                    (
                        account.account_id,
                        account.username,
                        account.role,
                        self.password_hasher.hash(password),
                        account.actor_id,
                        account.user_id,
                        self._timestamp(),
                    ),
                )
                self._audit(
                    conn,
                    "account.created",
                    "success",
                    account_id=account.account_id,
                )
        except sqlite3.IntegrityError as exc:
            if role == "owner":
                raise ValueError("only one enabled owner is allowed") from exc
            raise ValueError("mobile identity already exists") from exc
        return account

    def _fetch_account(self, username: str) -> sqlite3.Row | None:
        try:
            normalized = self._normalize_username(username)
        except ValueError:
            return None
        with self._lock, self._connect() as conn:
            return conn.execute(
                "SELECT * FROM mobile_accounts WHERE username = ?",
                (normalized,),
            ).fetchone()

    def create_pairing_code(self, username: str) -> str:
        account = self._fetch_account(username)
        if account is None or not account["enabled"]:
            raise ValueError("account is not available")
        code = f"{secrets.randbelow(100_000_000):08d}"
        now = self._now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """UPDATE mobile_pairing_sessions SET used_at = ?
                   WHERE account_id = ? AND used_at IS NULL""",
                (self._timestamp(now), account["account_id"]),
            )
            conn.execute(
                """INSERT INTO mobile_pairing_sessions
                   (pairing_id, account_id, code_hash, expires_at,
                    failure_count, used_at, created_at)
                   VALUES (?, ?, ?, ?, 0, NULL, ?)""",
                (
                    self._id("pair"),
                    account["account_id"],
                    self._digest("pairing", code),
                    self._timestamp(now + self.PAIRING_TTL),
                    self._timestamp(now),
                ),
            )
        return code

    def _is_rate_limited(
        self,
        conn: sqlite3.Connection,
        username: str,
        ip_address: str,
    ) -> bool:
        cutoff = self._timestamp(self._now() - self.FAILURE_WINDOW)
        account_count = conn.execute(
            """SELECT COUNT(*) FROM mobile_login_failures
               WHERE username = ? AND created_at >= ?""",
            (username, cutoff),
        ).fetchone()[0]
        ip_count = conn.execute(
            """SELECT COUNT(*) FROM mobile_login_failures
               WHERE ip_address = ? AND created_at >= ?""",
            (ip_address, cutoff),
        ).fetchone()[0]
        return account_count >= self.FAILURE_LIMIT or ip_count >= self.FAILURE_LIMIT

    def _record_login_failure(
        self,
        conn: sqlite3.Connection,
        username: str,
        ip_address: str,
        account_id: str | None,
    ) -> None:
        conn.execute(
            """INSERT INTO mobile_login_failures
               (username, ip_address, created_at) VALUES (?, ?, ?)""",
            (username, ip_address, self._timestamp()),
        )
        if account_id:
            conn.execute(
                """UPDATE mobile_pairing_sessions
                   SET failure_count = failure_count + 1
                   WHERE account_id = ? AND used_at IS NULL""",
                (account_id,),
            )
        self._audit(
            conn,
            "auth.login",
            "failure",
            account_id=account_id,
            ip_address=ip_address,
        )

    @staticmethod
    def _account_from_row(row: sqlite3.Row) -> MobileAccount:
        return MobileAccount(
            account_id=row["account_id"],
            username=row["username"],
            role=row["role"],
            actor_id=row["actor_id"],
            user_id=int(row["user_id"]),
        )

    def _issue_tokens(
        self,
        conn: sqlite3.Connection,
        account: sqlite3.Row,
        device_id: str,
        *,
        family_id: str | None = None,
    ) -> TokenPair:
        now = self._now()
        access_token = self._opaque_token()
        refresh_token = self._opaque_token()
        token_id = self._id("rt")
        family = family_id or self._id("family")
        conn.execute(
            """INSERT INTO mobile_access_tokens
               (token_hash, account_id, device_id, expires_at, revoked_at,
                created_at) VALUES (?, ?, ?, ?, NULL, ?)""",
            (
                self._digest("access", access_token),
                account["account_id"],
                device_id,
                self._timestamp(now + self.ACCESS_TTL),
                self._timestamp(now),
            ),
        )
        conn.execute(
            """INSERT INTO mobile_refresh_tokens
               (token_id, family_id, token_hash, account_id, device_id,
                expires_at, revoked_at, replaced_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?)""",
            (
                token_id,
                family,
                self._digest("refresh", refresh_token),
                account["account_id"],
                device_id,
                self._timestamp(now + self.REFRESH_TTL),
                self._timestamp(now),
            ),
        )
        base = self._account_from_row(account)
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_in=int(self.ACCESS_TTL.total_seconds()),
            refresh_expires_in=int(self.REFRESH_TTL.total_seconds()),
            principal=MobilePrincipal(**base.__dict__, device_id=device_id),
        )

    def login(
        self,
        *,
        username: str,
        password: str,
        device_name: str,
        pairing_code: str,
        ip_address: str,
        public_key: str | None = None,
    ) -> TokenPair:
        normalized = username.strip().lower()
        now_text = self._timestamp()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if self._is_rate_limited(conn, normalized, ip_address):
                conn.execute("ROLLBACK")
                raise MobileAuthError("rate_limited", status_code=429)
            account = conn.execute(
                "SELECT * FROM mobile_accounts WHERE username = ?",
                (normalized,),
            ).fetchone()
            password_hash = (
                account["password_hash"]
                if account is not None and account["enabled"]
                else self._dummy_password_hash
            )
            try:
                valid_password = self.password_hasher.verify(
                    password_hash, password
                )
            except VerifyMismatchError:
                valid_password = False
            valid_password = valid_password and account is not None and bool(
                account["enabled"]
            )
            pairing = None
            if account is not None and len(pairing_code) == 8:
                pairing = conn.execute(
                    """SELECT * FROM mobile_pairing_sessions
                       WHERE account_id = ? AND code_hash = ?
                         AND used_at IS NULL AND expires_at > ?
                         AND failure_count < ?
                       ORDER BY created_at DESC LIMIT 1""",
                    (
                        account["account_id"],
                        self._digest("pairing", pairing_code),
                        now_text,
                        self.FAILURE_LIMIT,
                    ),
                ).fetchone()
            if not valid_password or pairing is None or not device_name.strip():
                self._record_login_failure(
                    conn,
                    normalized,
                    ip_address,
                    account["account_id"] if account is not None else None,
                )
                conn.execute("COMMIT")
                raise MobileAuthError("invalid_credentials")
            device_id = self._id("device")
            conn.execute(
                "UPDATE mobile_pairing_sessions SET used_at = ? WHERE pairing_id = ?",
                (now_text, pairing["pairing_id"]),
            )
            conn.execute(
                """INSERT INTO mobile_devices
                   (device_id, account_id, device_name, public_key, created_at,
                    last_used_at, revoked_at)
                   VALUES (?, ?, ?, ?, ?, ?, NULL)""",
                (
                    device_id,
                    account["account_id"],
                    device_name.strip()[:100],
                    public_key,
                    now_text,
                    now_text,
                ),
            )
            tokens = self._issue_tokens(conn, account, device_id)
            self._audit(
                conn,
                "auth.login",
                "success",
                account_id=account["account_id"],
                device_id=device_id,
                ip_address=ip_address,
            )
            conn.execute("COMMIT")
            return tokens

    def refresh(self, refresh_token: str) -> TokenPair:
        token_hash = self._digest("refresh", refresh_token)
        now_text = self._timestamp()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM mobile_refresh_tokens WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                raise MobileAuthError("invalid_token")
            if row["revoked_at"] is not None:
                if row["replaced_by"] is not None:
                    conn.execute(
                        """UPDATE mobile_refresh_tokens SET revoked_at = ?
                           WHERE family_id = ? AND revoked_at IS NULL""",
                        (now_text, row["family_id"]),
                    )
                conn.execute("COMMIT")
                raise MobileAuthError("invalid_token")
            account = conn.execute(
                "SELECT * FROM mobile_accounts WHERE account_id = ? AND enabled = 1",
                (row["account_id"],),
            ).fetchone()
            device = conn.execute(
                """SELECT * FROM mobile_devices
                   WHERE device_id = ? AND revoked_at IS NULL""",
                (row["device_id"],),
            ).fetchone()
            if account is None or device is None or row["expires_at"] <= now_text:
                conn.execute(
                    "UPDATE mobile_refresh_tokens SET revoked_at = ? WHERE token_id = ?",
                    (now_text, row["token_id"]),
                )
                conn.execute("COMMIT")
                raise MobileAuthError("invalid_token")
            tokens = self._issue_tokens(
                conn,
                account,
                row["device_id"],
                family_id=row["family_id"],
            )
            replacement_hash = self._digest("refresh", tokens.refresh_token)
            replacement = conn.execute(
                "SELECT token_id FROM mobile_refresh_tokens WHERE token_hash = ?",
                (replacement_hash,),
            ).fetchone()
            conn.execute(
                """UPDATE mobile_refresh_tokens
                   SET revoked_at = ?, replaced_by = ? WHERE token_id = ?""",
                (now_text, replacement["token_id"], row["token_id"]),
            )
            conn.execute(
                "UPDATE mobile_devices SET last_used_at = ? WHERE device_id = ?",
                (now_text, row["device_id"]),
            )
            conn.execute("COMMIT")
            return tokens

    def authenticate_access(self, access_token: str) -> MobilePrincipal:
        now_text = self._timestamp()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """SELECT a.*, d.device_id
                   FROM mobile_access_tokens t
                   JOIN mobile_accounts a ON a.account_id = t.account_id
                   JOIN mobile_devices d ON d.device_id = t.device_id
                   WHERE t.token_hash = ? AND t.revoked_at IS NULL
                     AND t.expires_at > ? AND a.enabled = 1
                     AND d.revoked_at IS NULL""",
                (self._digest("access", access_token), now_text),
            ).fetchone()
            if row is None:
                raise MobileAuthError("invalid_token")
            base = self._account_from_row(row)
            return MobilePrincipal(**base.__dict__, device_id=row["device_id"])

    def logout(self, principal: MobilePrincipal) -> None:
        self._revoke_device_sessions(principal.device_id, revoke_device=False)

    def _revoke_device_sessions(self, device_id: str, *, revoke_device: bool) -> None:
        now_text = self._timestamp()
        with self._lock, self._connect() as conn:
            conn.execute(
                """UPDATE mobile_access_tokens SET revoked_at = ?
                   WHERE device_id = ? AND revoked_at IS NULL""",
                (now_text, device_id),
            )
            conn.execute(
                """UPDATE mobile_refresh_tokens SET revoked_at = ?
                   WHERE device_id = ? AND revoked_at IS NULL""",
                (now_text, device_id),
            )
            if revoke_device:
                conn.execute(
                    """UPDATE mobile_devices SET revoked_at = ?
                       WHERE device_id = ? AND revoked_at IS NULL""",
                    (now_text, device_id),
                )

    def list_devices(self, principal: MobilePrincipal) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            if principal.role == "owner":
                rows = conn.execute(
                    """SELECT device_id, account_id, device_name, created_at,
                              last_used_at, revoked_at
                       FROM mobile_devices ORDER BY created_at DESC"""
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT device_id, account_id, device_name, created_at,
                              last_used_at, revoked_at
                       FROM mobile_devices WHERE account_id = ?
                       ORDER BY created_at DESC""",
                    (principal.account_id,),
                ).fetchall()
        return [dict(row) for row in rows]

    def revoke_device(self, principal: MobilePrincipal, device_id: str) -> None:
        with self._lock, self._connect() as conn:
            device = conn.execute(
                "SELECT account_id FROM mobile_devices WHERE device_id = ?",
                (device_id,),
            ).fetchone()
        if device is None:
            raise MobileAuthError("not_found", status_code=404)
        if principal.role != "owner" and device_id != principal.device_id:
            raise MobileAuthError("forbidden", status_code=403)
        self._revoke_device_sessions(device_id, revoke_device=True)

    def reset_password(self, username: str, password: str) -> None:
        if len(password) < 12:
            raise ValueError("password must be at least 12 characters")
        account = self._fetch_account(username)
        if account is None:
            raise ValueError("account is not available")
        now_text = self._timestamp()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE mobile_accounts SET password_hash = ? WHERE account_id = ?",
                (self.password_hasher.hash(password), account["account_id"]),
            )
            conn.execute(
                """UPDATE mobile_access_tokens SET revoked_at = ?
                   WHERE account_id = ? AND revoked_at IS NULL""",
                (now_text, account["account_id"]),
            )
            conn.execute(
                """UPDATE mobile_refresh_tokens SET revoked_at = ?
                   WHERE account_id = ? AND revoked_at IS NULL""",
                (now_text, account["account_id"]),
            )

    def set_account_enabled(self, username: str, enabled: bool) -> None:
        account = self._fetch_account(username)
        if account is None:
            raise ValueError("account is not available")
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE mobile_accounts SET enabled = ? WHERE account_id = ?",
                (int(enabled), account["account_id"]),
            )
        if not enabled:
            now_text = self._timestamp()
            with self._lock, self._connect() as conn:
                conn.execute(
                    """UPDATE mobile_devices SET revoked_at = ?
                       WHERE account_id = ? AND revoked_at IS NULL""",
                    (now_text, account["account_id"]),
                )
                conn.execute(
                    """UPDATE mobile_access_tokens SET revoked_at = ?
                       WHERE account_id = ? AND revoked_at IS NULL""",
                    (now_text, account["account_id"]),
                )
                conn.execute(
                    """UPDATE mobile_refresh_tokens SET revoked_at = ?
                       WHERE account_id = ? AND revoked_at IS NULL""",
                    (now_text, account["account_id"]),
                )

    def list_accounts(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT account_id, username, role, actor_id, user_id,
                          enabled, created_at
                   FROM mobile_accounts ORDER BY created_at"""
            ).fetchall()
        return [dict(row) for row in rows]

    def list_account_devices(self, username: str) -> list[dict[str, Any]]:
        account = self._fetch_account(username)
        if account is None:
            raise ValueError("account is not available")
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT device_id, device_name, created_at, last_used_at,
                          revoked_at
                   FROM mobile_devices WHERE account_id = ?
                   ORDER BY created_at""",
                (account["account_id"],),
            ).fetchall()
        return [dict(row) for row in rows]

    def revoke_account_device(self, username: str, device_id: str) -> None:
        account = self._fetch_account(username)
        if account is None:
            raise ValueError("account is not available")
        with self._lock, self._connect() as conn:
            device = conn.execute(
                """SELECT 1 FROM mobile_devices
                   WHERE device_id = ? AND account_id = ?""",
                (device_id, account["account_id"]),
            ).fetchone()
        if device is None:
            raise ValueError("device is not available for this account")
        self._revoke_device_sessions(device_id, revoke_device=True)

    def delete_unpaired_account(self, username: str) -> None:
        account = self._fetch_account(username)
        if account is None:
            return
        with self._lock, self._connect() as conn:
            device_count = conn.execute(
                "SELECT COUNT(*) FROM mobile_devices WHERE account_id = ?",
                (account["account_id"],),
            ).fetchone()[0]
            if device_count:
                raise ValueError("account already has devices")
            conn.execute(
                "DELETE FROM mobile_pairing_sessions WHERE account_id = ?",
                (account["account_id"],),
            )
            conn.execute(
                "DELETE FROM mobile_accounts WHERE account_id = ?",
                (account["account_id"],),
            )
