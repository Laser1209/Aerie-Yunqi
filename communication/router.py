"""Aerie · 云栖 v13.9.8 — Three-tier message routing."""

from __future__ import annotations
from enum import Enum


class RouteMode(str, Enum):
    FULL = "FULL"           # master account — full AI pipeline
    AUTO_REPLY = "AUTO"     # friends — chat only
    BASIC = "BASIC"         # strangers — skip (or basic template)


class Router:
    def __init__(self, self_qq: int, friends_qq: list[int]) -> None:
        self.master = self_qq
        self.friends: set[int] = set(friends_qq)

    def route(self, user_id: int) -> str:
        """Return RouteMode for the given user_id."""
        if user_id == self.master:
            return RouteMode.FULL
        if user_id in self.friends:
            return RouteMode.AUTO_REPLY
        return RouteMode.BASIC

    def is_master(self, user_id: int) -> bool:
        return user_id == self.master

    def is_friend(self, user_id: int) -> bool:
        return user_id in self.friends
