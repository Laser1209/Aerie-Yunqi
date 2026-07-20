from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


_DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "config" / "settings.yaml"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
    return False


class FeatureFlags:
    def __init__(self, settings_path: str | Path = _DEFAULT_SETTINGS_PATH) -> None:
        self.settings_path = Path(settings_path)
        self._flags = self._load_flags()

    def _load_flags(self) -> dict[str, bool]:
        if not self.settings_path.exists():
            return {}
        data: dict[str, Any] = yaml.safe_load(
            self.settings_path.read_text(encoding="utf-8")
        ) or {}
        flags = data.get("feature_flags") or {}
        return {str(name): _parse_bool(value) for name, value in flags.items()}

    def is_enabled(self, name: str) -> bool:
        env_value = os.environ.get(f"AERIE_FEATURE_{name.upper()}")
        if env_value is not None:
            return _parse_bool(env_value)
        return self._flags.get(name, False)
