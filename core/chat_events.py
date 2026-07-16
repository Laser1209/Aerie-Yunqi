"""Aerie · 云栖 v9.0 — stderr event bridge.

Writes [CHAT_EVENT] lines to stderr so Electron's main process can parse
them and broadcast via IPC to all renderer windows.
"""

from __future__ import annotations
import json
import sys
import time

PREFIX = "[CHAT_EVENT]"


def emit(event_type: str, **payload: object) -> None:
    """Write a structured JSON event line to stderr.

    Used from Pipeline after persisting user/assistant messages.
    """
    payload["type"] = event_type
    payload["ts"] = int(time.time())
    line = PREFIX + json.dumps(payload, ensure_ascii=False)
    print(line, file=sys.stderr, flush=True)
