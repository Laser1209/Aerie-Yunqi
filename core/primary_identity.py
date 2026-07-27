"""Resolve the desktop primary user without guessing a zero identity."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from core.paths import data_dir


LOCAL_CONFIG_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PrimaryIdentitySelection:
    """A validated primary user id together with its effective source."""

    user_id: int
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {"primaryUserId": self.user_id, "source": self.source}


class PrimaryIdentityResolver:
    """Apply the primary identity precedence shared by desktop services.

    Precedence is intentionally independent from QQ process state:
    ``AERIE_PRIMARY_USER_ID`` -> ``SELF_QQ`` -> versioned local runtime
    config -> ``settings.yaml``. Invalid and zero values are ignored; the
    resolver returns ``None`` instead of manufacturing ``user_id=0``.
    """

    def __init__(
        self,
        *,
        runtime_config_service: Any | None = None,
        local_config_path: str | Path | None = None,
    ) -> None:
        self.runtime_config_service = runtime_config_service
        self.local_config_path = Path(
            local_config_path or data_dir() / "runtime_config.json"
        )

    def resolve(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        settings: Mapping[str, Any] | None = None,
        runtime_config_service: Any | None = None,
    ) -> PrimaryIdentitySelection | None:
        env = os.environ if environ is None else environ
        for name in ("AERIE_PRIMARY_USER_ID", "SELF_QQ"):
            user_id = _positive_int(env.get(name))
            if user_id is not None:
                return PrimaryIdentitySelection(user_id, f"env:{name}")

        service = (
            runtime_config_service
            if runtime_config_service is not None
            else self.runtime_config_service
        )
        service_value, service_source = _runtime_service_value(service)
        user_id = _positive_int(service_value)
        if user_id is not None:
            source = service_source or "effective"
            return PrimaryIdentitySelection(
                user_id,
                f"runtime_config:{source}",
            )

        local_value, local_source = self._read_local_config()
        user_id = _positive_int(local_value)
        if user_id is not None:
            return PrimaryIdentitySelection(
                user_id,
                f"local_config:{local_source or 'persisted'}",
            )

        qq = settings.get("qq") if isinstance(settings, Mapping) else None
        yaml_value = qq.get("self_qq") if isinstance(qq, Mapping) else None
        user_id = _positive_int(yaml_value)
        if user_id is not None:
            return PrimaryIdentitySelection(user_id, "yaml:qq.self_qq")
        return None

    def _read_local_config(self) -> tuple[Any, str | None]:
        path = self.local_config_path
        if not path.exists():
            return None, None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                return None, None
            schema_version = payload.get(
                "schema_version",
                payload.get("schemaVersion"),
            )
            if int(schema_version or 0) != LOCAL_CONFIG_SCHEMA_VERSION:
                return None, None
            return _snapshot_value(payload)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None, None


def _runtime_service_value(service: Any | None) -> tuple[Any, str | None]:
    if service is None:
        return None, None
    getter = getattr(service, "get_effective", None)
    if callable(getter):
        try:
            value = getter("primary_user_id")
            extracted, embedded_source = _entry_value(value)
            source_getter = getattr(service, "source_for", None)
            source = embedded_source
            if callable(source_getter):
                source = str(source_getter("primary_user_id") or "") or source
            if extracted not in (None, ""):
                return extracted, source
        except Exception:
            pass
    snapshotter = getattr(service, "snapshot", None)
    if callable(snapshotter):
        try:
            snapshot = snapshotter()
            if isinstance(snapshot, Mapping):
                return _snapshot_value(snapshot)
        except Exception:
            pass
    return None, None


def _snapshot_value(snapshot: Mapping[str, Any]) -> tuple[Any, str | None]:
    values = snapshot.get("values")
    if isinstance(values, Mapping):
        for key in ("primary_user_id", "primaryUserId"):
            if key in values:
                return _entry_value(values[key])
    for key in ("primary_user_id", "primaryUserId"):
        if key in snapshot:
            return _entry_value(snapshot[key])
    return None, None


def _entry_value(entry: Any) -> tuple[Any, str | None]:
    if not isinstance(entry, Mapping):
        return entry, None
    source = entry.get("source")
    for key in ("effectiveValue", "effective_value", "value"):
        if key in entry:
            return entry[key], str(source or "") or None
    return None, str(source or "") or None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    normalized = str(value).strip()
    if not normalized.isdecimal():
        return None
    parsed = int(normalized)
    return parsed if parsed > 0 else None

