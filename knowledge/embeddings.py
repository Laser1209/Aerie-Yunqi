"""Aerie · 云栖 v9.0 — Embedding helpers (placeholder).

Real implementation can use sentence-transformers or external APIs.
This module provides a deterministic hash-based pseudo-embedding so
search code can be exercised without network access.
"""

from __future__ import annotations

import hashlib
from typing import Iterable


def pseudo_embed(text: str, dim: int = 64) -> list[float]:
    """Deterministic pseudo-embedding for offline testing."""
    digest = hashlib.sha256((text or "").encode("utf-8")).digest()
    out: list[float] = []
    for i in range(dim):
        byte = digest[i % len(digest)]
        out.append((byte - 128) / 128.0)
    return out


def cosine_similarity(a: Iterable[float], b: Iterable[float]) -> float:
    """Standard cosine similarity over two equal-length vectors."""
    va = list(a)
    vb = list(b)
    if len(va) != len(vb) or not va:
        return 0.0
    dot = sum(x * y for x, y in zip(va, vb))
    na = sum(x * x for x in va) ** 0.5
    nb = sum(x * x for x in vb) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
