"""Aerie · 云栖 v9.0 — Three-level router (FULL / AUTO / BASIC)."""

from __future__ import annotations

from communication.message import IncomingMessage, RouteMode
from typing import Optional


class Router:
    """Decide how to handle an incoming message based on sender identity."""

    def __init__(
        self,
        self_qq: int,
        friends_qq: Optional[list[int]] = None,
        blacklist_qq: Optional[list[int]] = None,
    ) -> None:
        self.self_qq = int(self_qq)
        self.friends_qq = set(int(x) for x in (friends_qq or []))
        self.blacklist_qq = set(int(x) for x in (blacklist_qq or []))

    def is_master(self, user_id: int) -> bool:
        return int(user_id) == self.self_qq

    def is_friend(self, user_id: int) -> bool:
        return int(user_id) in self.friends_qq

    def is_blacklisted(self, user_id: int) -> bool:
        return int(user_id) in self.blacklist_qq

    def is_stranger(self, user_id: int) -> bool:
        return not (self.is_master(user_id) or self.is_friend(user_id))

    def route(self, user_id: int) -> RouteMode:
        """Return routing mode for the given QQ user_id."""
        if self.is_blacklisted(user_id):
            return RouteMode.BASIC
        if self.is_master(user_id):
            return RouteMode.FULL
        if self.is_friend(user_id):
            return RouteMode.AUTO_REPLY
        return RouteMode.BASIC

    def route_message(self, msg: IncomingMessage) -> RouteMode:
        return self.route(msg.user_id)

    def add_friend(self, user_id: int) -> None:
        self.friends_qq.add(int(user_id))

    def remove_friend(self, user_id: int) -> None:
        self.friends_qq.discard(int(user_id))
