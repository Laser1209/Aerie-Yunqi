"""Local-only account administration for the Aerie mobile gateway."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.mobile_identity import MobileIdentityStore


def _store() -> MobileIdentityStore:
    load_dotenv(ROOT / ".env", override=False)
    pepper = os.getenv("AERIE_MOBILE_TOKEN_PEPPER", "")
    if not pepper:
        raise SystemExit("AERIE_MOBILE_TOKEN_PEPPER is required")
    path = Path(os.getenv("AERIE_MOBILE_AUTH_DB", "data/mobile_gateway.db"))
    return MobileIdentityStore(path, pepper=pepper)


def _password(prompt: str) -> str:
    value = getpass.getpass(prompt)
    confirmation = getpass.getpass("Confirm password: ")
    if value != confirmation:
        raise SystemExit("passwords do not match")
    return value


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _bind_actor(
    account_id: str,
    actor_id: str,
    user_id: int,
    role: str,
) -> None:
    db_path = Path(os.getenv("AERIE_DB_PATH", "data/aerie.db"))
    if not db_path.exists():
        raise RuntimeError(f"Aerie database does not exist: {db_path}")
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR IGNORE INTO actors(actor_id) VALUES (?)",
            (actor_id,),
        )
        bindings = [("mobile", account_id)]
        if role == "owner":
            bindings.extend((("desktop", "local"), ("qq", str(user_id))))
        for channel, channel_account_id in bindings:
            conn.execute(
                """INSERT INTO channel_accounts
                   (channel, channel_account_id, actor_id)
                   VALUES (?, ?, ?)
                   ON CONFLICT(channel, channel_account_id)
                   DO UPDATE SET actor_id = excluded.actor_id""",
                (channel, channel_account_id, actor_id),
            )
        for table in ("chat_log", "long_term_memory", "emotion_state_snapshot"):
            conn.execute(
                f"""UPDATE {table} SET actor_id = ?
                    WHERE user_id = ? AND actor_id IS NULL""",
                (actor_id, user_id),
            )
        conn.execute(
            """UPDATE messages SET actor_id = ?
               WHERE actor_id IS NULL AND legacy_chat_log_id IN (
                   SELECT id FROM chat_log WHERE user_id = ?
               )""",
            (actor_id, user_id),
        )
        conn.execute(
            """UPDATE conversations SET actor_id = ?
               WHERE actor_id IS NULL AND conversation_id IN (
                   SELECT DISTINCT conversation_id FROM messages
                   WHERE actor_id = ?
               )""",
            (actor_id, actor_id),
        )
        conn.execute(
            """UPDATE requests SET actor_id = ?, user_id = COALESCE(user_id, ?)
               WHERE actor_id IS NULL AND conversation_id IN (
                   SELECT conversation_id FROM conversations WHERE actor_id = ?
               )""",
            (actor_id, user_id, actor_id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _add_account_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("username")
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--user-id", required=True, type=int)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    _add_account_arguments(commands.add_parser("create-owner"))
    _add_account_arguments(commands.add_parser("create-guest"))

    reset = commands.add_parser("reset-password")
    reset.add_argument("username")

    pairing = commands.add_parser("pairing-code")
    pairing.add_argument("username")

    commands.add_parser("list-accounts")

    devices = commands.add_parser("list-devices")
    devices.add_argument("username")

    revoke = commands.add_parser("revoke-device")
    revoke.add_argument("username")
    revoke.add_argument("device_id")

    disable = commands.add_parser("disable-account")
    disable.add_argument("username")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = _store()

    if args.command in {"create-owner", "create-guest"}:
        role = args.command.removeprefix("create-")
        account = store.create_account(
            username=args.username,
            password=_password("Password: "),
            role=role,
            actor_id=args.actor_id,
            user_id=args.user_id,
        )
        try:
            _bind_actor(
                account.account_id,
                account.actor_id,
                account.user_id,
                account.role,
            )
        except Exception:
            store.delete_unpaired_account(account.username)
            raise
        _print(account.__dict__)
    elif args.command == "reset-password":
        store.reset_password(args.username, _password("New password: "))
        _print({"status": "ok"})
    elif args.command == "pairing-code":
        _print({"pairingCode": store.create_pairing_code(args.username)})
    elif args.command == "list-accounts":
        _print(store.list_accounts())
    elif args.command == "list-devices":
        _print(store.list_account_devices(args.username))
    elif args.command == "revoke-device":
        store.revoke_account_device(args.username, args.device_id)
        _print({"status": "ok"})
    elif args.command == "disable-account":
        store.set_account_enabled(args.username, False)
        _print({"status": "ok"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
