from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChannelIdentity:
    actor_id: str
    channel: str
    channel_account_id: str
