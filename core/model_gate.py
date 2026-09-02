"""Shared process-wide gate for outbound model/provider calls."""

from __future__ import annotations

import os


_TRUE_VALUES = {"1", "true", "yes", "on"}


def model_calls_disabled() -> bool:
    """Return whether all optional model/provider network calls are disabled."""

    return os.environ.get("AERIE_DISABLE_MODEL_CALLS", "").strip().lower() in _TRUE_VALUES

