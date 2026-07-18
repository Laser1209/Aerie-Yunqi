"""Aerie · 云栖 v13.9.8 — Process-wide chat event bus + SSE bridge (Phase 9).

Architecture
------------
The Python backend is launched as a child process by Electron's main.js.
Electron's main process reads [CHAT_EVENT] lines from our stderr and
re-broadcasts them to renderer windows via IPC.

To expose the same event stream via HTTP for the brain-center UI
(so the panel can show real-time stages even when the Electron
relay hiccups), we also keep an in-process subscriber list. Every
call to ``emit()`` publishes the event onto that list as well.

The HTTP layer (``core.api_server``) exposes a Server-Sent Events
endpoint at ``/api/events/stream`` that pulls from this subscriber
list, so any SSE client (browser EventSource, curl, etc.) can
subscribe to the same event stream.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

# ── In-process subscriber pool ─────────────────────────
# A list of asyncio.Queue, one per SSE / WebSocket subscriber.
# When emit() is called, the event is pushed to every queue.
_subscribers: list[asyncio.Queue[str]] = []
_subscribers_lock = asyncio.Lock()

# Maximum events buffered per subscriber before the oldest is dropped.
# Keeps memory bounded when a client is slow to consume.
_PER_SUBSCRIBER_BUFFER = 200


async def _add_subscriber() -> asyncio.Queue[str]:
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=_PER_SUBSCRIBER_BUFFER)
    async with _subscribers_lock:
        _subscribers.append(q)
    return q


async def _remove_subscriber(q: asyncio.Queue[str]) -> None:
    async with _subscribers_lock:
        try:
            _subscribers.remove(q)
        except ValueError:
            pass


def _broadcast_sync(event_type: str, payload: dict) -> None:
    """Push a single event to every subscriber's queue (sync, fire-and-forget)."""
    if not _subscribers:
        return
    line = json.dumps(
        {"type": event_type, "ts": int(time.time() * 1000), **payload},
        ensure_ascii=False,
    )
    for q in list(_subscribers):
        try:
            q.put_nowait(line)
        except asyncio.QueueFull:
            # Drop the oldest to make room, never block the publisher
            try:
                q.get_nowait()
                q.put_nowait(line)
            except Exception:
                pass
        except Exception:
            # Queue closed / loop dead — remove silently
            try:
                _subscribers.remove(q)
            except ValueError:
                pass


async def stream() -> AsyncGenerator[str, None]:
    """Async generator yielding SSE-formatted lines.

    Format: ``data: <json>\\n\\n``
    """
    q = await _add_subscriber()
    try:
        # Send a "hello" frame so the EventSource knows it's connected
        yield f"data: {json.dumps({'type': 'stream_open', 'ts': int(time.time()*1000)}, ensure_ascii=False)}\n\n"
        while True:
            try:
                line = await asyncio.wait_for(q.get(), timeout=15.0)
                yield f"data: {line}\n\n"
            except asyncio.TimeoutError:
                # Heartbeat keeps the connection alive through proxies
                yield ": heartbeat\n\n"
    except asyncio.CancelledError:
        raise
    finally:
        await _remove_subscriber(q)


def publish(event_type: str, payload: dict) -> None:
    """Publish an event to all SSE subscribers.

    Safe to call from sync code (the chat_events stderr emit).
    Failure here must never block the main pipeline.
    """
    try:
        _broadcast_sync(event_type, payload)
    except Exception:
        logger.exception("event stream publish error")
