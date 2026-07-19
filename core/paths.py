from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    configured = (os.environ.get("AERIE_DATA_DIR") or "").strip()
    if configured:
        return Path(configured)
    return project_root() / "data"


def cache_dir() -> Path:
    return data_dir() / "cache"


def briefs_dir() -> Path:
    return data_dir() / "briefs"


def city_cache_path() -> Path:
    return cache_dir() / "city.json"
