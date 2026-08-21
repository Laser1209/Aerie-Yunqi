from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any


_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "token",
    "secret",
    "password",
}


class ImageProductionTimeline:
    def __init__(self, path: Path | str = Path("logs") / "image_production_timeline.jsonl") -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._sequences: dict[str, int] = {}

    def record(self, trace_id: str, stage: str, **payload: Any) -> dict[str, Any]:
        normalized_trace_id = str(trace_id or "unknown")
        if normalized_trace_id.startswith("world-image:"):
            normalized_trace_id = normalized_trace_id[len("world-image:"):]
        with self._lock:
            sequence = self._sequences.get(normalized_trace_id, 0) + 1
            self._sequences[normalized_trace_id] = sequence
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "trace_id": normalized_trace_id,
                "sequence": sequence,
                "stage": str(stage or "unknown"),
                **self._redact(payload),
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as output:
                output.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return record

    def _redact(self, value: Any, key: str = "") -> Any:
        if key.lower() in _SENSITIVE_KEYS:
            return "***"
        if isinstance(value, dict):
            return {str(item_key): self._redact(item_value, str(item_key)) for item_key, item_value in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._redact(item) for item in value]
        return value


image_production_timeline = ImageProductionTimeline()


def record_image_stage(trace_id: str, stage: str, **payload: Any) -> dict[str, Any]:
    return image_production_timeline.record(trace_id, stage, **payload)
