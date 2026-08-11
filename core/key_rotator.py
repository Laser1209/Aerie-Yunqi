"""Aerie · 云栖 — KeyRotator: thread-safe round-robin multi-key pool.

同一 base_url（如阿里云百炼业务空间专属域名）下配置多个 API Key，
用 round-robin 轮流挑选，分摊并发、防止单 Key 额度/并发被占满。
并发安全：用锁保证同时只会取到互不相同的 key。
"""
from __future__ import annotations

import itertools
import logging
import os
import threading
from typing import Iterable, Iterator, Optional

logger = logging.getLogger(__name__)


class KeyRotator:
    """Thread-safe round-robin key pool for one base_url."""

    def __init__(self, keys: Iterable[str]) -> None:
        self._keys: list[str] = [k.strip() for k in keys if k and k.strip()]
        self._lock = threading.Lock()
        self._cycle: Iterator[str] = itertools.cycle(self._keys) if self._keys else iter(())
        self._count = len(self._keys)

    @classmethod
    def from_env(
        cls,
        keys_env: str,
        single_env: str | None = None,
        *,
        base_url_env: str | None = None,
    ) -> "KeyRotator":
        """从环境变量构造：优先逗号分隔的 keys_env；否则退回单 key 环境变量。"""
        raw = os.getenv(keys_env, "").strip()
        if raw:
            keys = [k.strip() for k in raw.split(",") if k.strip()]
        else:
            single = (os.getenv(single_env, "") if single_env else "").strip()
            keys = [single] if single else []
        return cls(keys)

    @property
    def keys(self) -> list[str]:
        return list(self._keys)

    @property
    def size(self) -> int:
        return self._count

    def next(self) -> Optional[str]:
        """返回下一个 key；池为空返回 None。"""
        if not self._keys:
            return None
        with self._lock:
            try:
                return next(self._cycle)
            except StopIteration:
                return None
