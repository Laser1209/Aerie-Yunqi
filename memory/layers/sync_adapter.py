"""Aerie · 云栖 v0.1.0-beta.1 — LayeredMemory 同步兼容适配器 (P1-D.5.3).

将异步四层记忆调度器 ``LayeredMemory`` 桥接到生产代码依赖的旧同步
``LongTermMemory`` 接口（store / retrieve / decay），使 context_builder /
pipeline 无需改动即可切换到新的向量语义检索记忆。

事件循环策略：
  context_builder.build 是同步方法，却在异步 pipeline 的事件循环内被调用，
  因此在其中直接 ``asyncio.run()`` 会抛 "already running" 错误。
  本适配器把协程投递到独立后台线程的事件循环上执行（run_coroutine_threadsafe），
  无论从同步上下文还是运行中的异步循环内调用都安全，不会死锁。
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Optional

from memory.layers.base import MemoryType

_BG_LOOP: Optional[asyncio.AbstractEventLoop] = None
_BG_LOCK = threading.Lock()


def _get_background_loop() -> asyncio.AbstractEventLoop:
    """返回进程级共享的后台事件循环（线程安全，惰性创建）."""
    global _BG_LOOP
    with _BG_LOCK:
        if _BG_LOOP is None or _BG_LOOP.is_closed():
            loop = asyncio.new_event_loop()

            def _run() -> None:
                asyncio.set_event_loop(loop)
                loop.run_forever()

            thread = threading.Thread(
                target=_run,
                name="aerie-memory-bg",
                daemon=True,
            )
            thread.start()
            _BG_LOOP = loop
        return _BG_LOOP


def _coerce_memory_type(value: Any) -> MemoryType:
    if isinstance(value, MemoryType):
        return value
    if isinstance(value, str):
        try:
            return MemoryType(value)
        except ValueError:
            return MemoryType.FACT
    return MemoryType.FACT


class LayeredMemorySyncAdapter:
    """在旧同步 LongTermMemory 接口之上暴露 LayeredMemory."""

    def __init__(
        self,
        layered: Any,
        *,
        timeout: float = 15.0,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        self._layered = layered
        self._timeout = timeout
        self._loop = loop or _get_background_loop()

    def _run(self, coro: Any) -> Any:
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=self._timeout)

    # ── legacy sync interface ──────────────────────────

    def store(
        self,
        user_id: int,
        memory_type: str,
        content: str,
        importance: int = 5,
        *,
        actor_id: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> int:
        metadata: dict[str, Any] = {}
        if actor_id:
            metadata["actor_id"] = actor_id
        if channel:
            metadata["channel"] = channel
        try:
            mid = self._run(
                self._layered.store(
                    user_id=int(user_id),
                    content=str(content),
                    memory_type=_coerce_memory_type(memory_type),
                    importance=float(importance),
                    metadata=metadata,
                )
            )
            sid = str(mid or "")
            return int(sid) if sid.isdigit() else 0
        except Exception:
            return 0

    def retrieve(
        self,
        user_id: int,
        query: str = "",
        limit: int = 5,
        *,
        actor_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        try:
            results = self._run(
                self._layered.search(
                    user_id=int(user_id),
                    query=str(query),
                    limit=int(limit),
                )
            )
        except Exception:
            return []
        rows: list[dict[str, Any]] = []
        for r in results or []:
            item = getattr(r, "item", r)
            mtype = getattr(item, "memory_type", "memory")
            meta = getattr(item, "metadata", None) or {}
            rows.append({
                "content": str(getattr(item, "content", "")),
                "memory_type": (
                    mtype.value if isinstance(mtype, MemoryType) else str(mtype)
                ),
                "importance": getattr(item, "importance", ""),
                "score": float(getattr(r, "score", 0.0)),
                "channel": str(meta.get("channel") or "unknown"),
            })
        return rows[:limit]

    def decay(self) -> None:
        try:
            self._run(self._layered.decay_long_term())
        except Exception:
            pass

    def list_by_user(
        self,
        user_id: int,
        layer: str = "long_term",
        limit: int = 50,
        memory_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """按层列出用户的记忆（只读，供记忆档案页使用）。"""
        from memory.layers.base import MemoryLayer, MemoryType

        try:
            layer_enum = MemoryLayer(layer)
        except ValueError:
            layer_enum = MemoryLayer.LONG_TERM
        mtype: Optional[MemoryType] = None
        if memory_type:
            try:
                mtype = MemoryType(memory_type)
            except ValueError:
                mtype = None
        try:
            items = self._run(
                self._layered.list_by_user(
                    user_id=int(user_id),
                    layer=layer_enum,
                    limit=int(limit),
                    memory_type=mtype,
                )
            )
        except Exception:
            return []
        rows: list[dict[str, Any]] = []
        for item in items or []:
            d = item.to_dict() if hasattr(item, "to_dict") else {}
            rows.append({
                "id": d.get("id"),
                "layer": d.get("layer") or layer_enum.value,
                "memory_type": d.get("memory_type"),
                "content": str(d.get("content", "")),
                "importance": d.get("importance"),
                "source": d.get("source"),
                "created_at": d.get("created_at"),
                "updated_at": d.get("updated_at"),
                "confidence": d.get("confidence"),
                # P3-4 EVENT 记忆召回需要 occurred_at（按时间线排序/过滤）；
                # 新增字段，不改已有字段，缺失时置空由调用方兜底。
                "metadata": d.get("metadata") or {},
            })
        return rows[: int(limit)]
