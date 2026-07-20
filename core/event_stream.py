"""Aerie · 云栖 v0.1.0-beta.1 — Process-wide chat event bus + SSE bridge (Phase 9).

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
from collections import deque
from typing import Any, AsyncGenerator

logger = logging.getLogger(__name__)

# ── In-process subscriber pool ─────────────────────────
# A list of asyncio.Queue, one per SSE / WebSocket subscriber.
# When emit() is called, the event is pushed to every queue.
_subscribers: list[asyncio.Queue[dict[str, Any]]] = []
_subscribers_lock = asyncio.Lock()

# Maximum events buffered per subscriber before the oldest is dropped.
# Keeps memory bounded when a client is slow to consume.
_PER_SUBSCRIBER_BUFFER = 200
_REPLAY_BUFFER_SIZE = 500


_replay_buffer: deque[dict[str, Any]] = deque(maxlen=_REPLAY_BUFFER_SIZE)


async def _add_subscriber() -> asyncio.Queue[dict[str, Any]]:
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
        maxsize=_PER_SUBSCRIBER_BUFFER
    )
    async with _subscribers_lock:
        _subscribers.append(q)
    return q


async def _remove_subscriber(q: asyncio.Queue[dict[str, Any]]) -> None:
    async with _subscribers_lock:
        try:
            _subscribers.remove(q)
        except ValueError:
            pass


def _event_id(event: dict[str, Any]) -> str:
    value = event.get("event_id")
    return str(value) if value else ""


def _make_event(event_type: str, payload: dict) -> dict[str, Any]:
    return {"type": event_type, "ts": int(time.time() * 1000), **payload}


def _format_sse_event(
    event: dict[str, Any],
    *,
    include_event_id: bool = False,
) -> str:
    data = json.dumps(event, ensure_ascii=False)
    event_id = _event_id(event)
    if include_event_id and event_id:
        return f"id: {event_id}\ndata: {data}\n\n"
    return f"data: {data}\n\n"


def _events_after(last_event_id: str | None) -> list[dict[str, Any]]:
    """Return replay-window events after ``last_event_id``.

    No cursor means "live only"; an unknown cursor means the cursor fell
    outside this process-local recovery window, so replay the whole bounded
    window and let renderer-side event_id de-duplication collapse overlap.
    """
    if not last_event_id:
        return []

    events = list(_replay_buffer)
    for index, event in enumerate(events):
        if _event_id(event) == last_event_id:
            return events[index + 1 :]
    return events


def _broadcast_sync(event_type: str, payload: dict) -> None:
    """Push a single event to every subscriber's queue (sync, fire-and-forget)."""
    event = _make_event(event_type, payload)
    if _event_id(event):
        _replay_buffer.append(event)

    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # Drop the oldest to make room, never block the publisher
            try:
                q.get_nowait()
                q.put_nowait(event)
            except Exception:
                pass
        except Exception:
            # Queue closed / loop dead — remove silently
            try:
                _subscribers.remove(q)
            except ValueError:
                pass


async def stream(
    *,
    last_event_id: str | None = None,
    replay: bool = False,
    include_event_id: bool = False,
) -> AsyncGenerator[str, None]:
    """Async generator yielding SSE-formatted lines.

    Legacy format: ``data: <json>\\n\\n``.

    When Phase 05 ``chat_stream_v1`` is enabled by the API layer,
    ``include_event_id`` emits standards-compliant SSE ``id:`` lines and
    ``replay`` replays missed events from the bounded process-local recovery
    window after ``last_event_id``.
    """
    q = await _add_subscriber()
    try:
        # Send a "hello" frame so the EventSource knows it's connected
        yield f"data: {json.dumps({'type': 'stream_open', 'ts': int(time.time()*1000)}, ensure_ascii=False)}\n\n"
        if replay:
            for event in _events_after(last_event_id):
                yield _format_sse_event(
                    event,
                    include_event_id=include_event_id,
                )
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=15.0)
                yield _format_sse_event(
                    event,
                    include_event_id=include_event_id,
                )
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


def _reset_for_tests() -> None:
    """Clear process-local stream state for deterministic unit tests."""
    _subscribers.clear()
    _replay_buffer.clear()
