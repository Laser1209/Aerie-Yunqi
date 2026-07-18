"""Aerie · 云栖 v13.9.8 — stderr event bridge + in-process event bus.

Writes [CHAT_EVENT] lines to stderr so Electron's main process can parse
them and broadcast via IPC to all renderer windows.

Phase 9: also publishes to ``core.event_stream`` so the same event flow
is reachable via the /api/events/stream SSE endpoint (used by the
brain-center UI as a real-time secondary channel).
"""

from __future__ import annotations
import json
import sys
import time

PREFIX = "[CHAT_EVENT]"


def emit(event_type: str, **payload: object) -> None:
    """Write a structured JSON event line to stderr + in-process bus.

    Used from Pipeline after persisting user/assistant messages and from
    CognitionEngine for every stage trace.
    """
    payload["type"] = event_type
    payload["ts"] = int(time.time())
    line = PREFIX + json.dumps(payload, ensure_ascii=False)
    print(line, file=sys.stderr, flush=True)

    # Phase 9: also publish to the in-process event bus so SSE clients
    # can subscribe. Failure here must never affect the stderr bridge.
    try:
        from core import event_stream
        event_stream.publish(event_type, dict(payload))
    except Exception:
        # event_stream is only importable when running under the API server
        pass
