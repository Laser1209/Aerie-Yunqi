from __future__ import annotations

from core.ids import generate_id
from core.identity.models import ChannelIdentity


class IdentityRepository:
    def __init__(self, db) -> None:
        self.db = db

    def resolve(self, channel: str, channel_account_id: str) -> ChannelIdentity:
        normalized_channel = channel.strip().lower()
        normalized_account_id = str(channel_account_id).strip()
        row = self.db.query_one(
            "SELECT actor_id FROM channel_accounts WHERE channel = ? AND channel_account_id = ?",
            (normalized_channel, normalized_account_id),
        )
        if row is None:
            actor_id = generate_id("actor")
            self.db.insert("actors", {"actor_id": actor_id})
            self.bind(actor_id, normalized_channel, normalized_account_id)
        else:
            actor_id = row["actor_id"]
        return ChannelIdentity(actor_id, normalized_channel, normalized_account_id)

    def bind(self, actor_id: str, channel: str, channel_account_id: str) -> None:
        normalized_channel = channel.strip().lower()
        normalized_account_id = str(channel_account_id).strip()
        self.db.execute(
            """INSERT INTO channel_accounts (channel, channel_account_id, actor_id)
               VALUES (?, ?, ?)
               ON CONFLICT(channel, channel_account_id) DO UPDATE SET actor_id = excluded.actor_id""",
            (normalized_channel, normalized_account_id, actor_id),
        )
