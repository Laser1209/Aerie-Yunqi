from __future__ import annotations

from uuid import uuid4


def generate_id(prefix: str) -> str:
    normalized = prefix.strip().lower()
    if not normalized:
        raise ValueError("ID prefix must not be empty")
    return f"{normalized}_{uuid4().hex}"
