from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.ids import generate_id


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    type: str
    ts: str
    request_id: str | None = None
    conversation_id: str | None = None
    turn_id: str | None = None
    message_id: str | None = None
    response_group_id: str | None = None
    sequence: int = 0
    channel: str = "unknown"
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, event_type: str, **data: Any) -> "EventEnvelope":
        contract_fields = {
            key: data.pop(key, None)
            for key in (
                "request_id",
                "conversation_id",
                "turn_id",
                "message_id",
                "response_group_id",
            )
        }
        return cls(
            event_id=str(data.pop("event_id", generate_id("event"))),
            type=event_type,
            ts=str(data.pop("ts", datetime.now(timezone.utc).isoformat())),
            sequence=int(data.pop("sequence", 0) or 0),
            channel=str(data.pop("channel", "unknown") or "unknown"),
            payload=data,
            **contract_fields,
        )

    def to_dict(self) -> dict[str, Any]:
        serialized = asdict(self)
        payload = serialized.pop("payload")
        serialized.update(payload)
        return serialized
