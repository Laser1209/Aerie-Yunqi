"""Versioned, redacted runtime configuration authority.

The service deliberately uses a small standalone JSON document instead of the
main application database.  Reading configuration has no side effects; the
state directory is created only when an accepted update is persisted.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


RUNTIME_CONFIG_SCHEMA_VERSION = 1
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


class RuntimeConfigError(RuntimeError):
    """Base error with a stable public error code."""

    code = "runtime_config_error"


class RuntimeConfigConflict(RuntimeConfigError):
    code = "revision_conflict"

    def __init__(self, *, expected: int, current: int) -> None:
        super().__init__(f"expected revision {expected}, current revision {current}")
        self.expected = expected
        self.current = current


class RuntimeConfigValidationError(RuntimeConfigError):
    code = "validation_failed"

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        super().__init__("runtime configuration validation failed")
        self.errors = errors


class RuntimeConfigReadOnlyError(RuntimeConfigError):
    code = "read_only_override"


@dataclass(frozen=True)
class RuntimeConfigSpec:
    key: str
    default: Any = None
    value_type: str = "string"
    env_name: str = ""
    mutable: bool = True
    requires_restart: bool = False
    dependencies: tuple[str, ...] = ()
    secret: bool = False
    allowed_values: tuple[Any, ...] = ()


DEFAULT_RUNTIME_CONFIG_SPECS: tuple[RuntimeConfigSpec, ...] = (
    RuntimeConfigSpec(
        key="primary_user_id",
        default=None,
        value_type="identity",
        env_name="AERIE_PRIMARY_USER_ID",
    ),
    RuntimeConfigSpec(
        key="runtime_control_v1",
        default=False,
        value_type="bool",
        env_name="AERIE_FEATURE_RUNTIME_CONTROL_V1",
        requires_restart=True,
    ),
    RuntimeConfigSpec(
        key="world_sidecar_v1",
        default=False,
        value_type="bool",
        env_name="AERIE_FEATURE_WORLD_SIDECAR_V1",
    ),
    RuntimeConfigSpec(
        key="world_process_supervision_v1",
        default=False,
        value_type="bool",
        env_name="AERIE_FEATURE_WORLD_PROCESS_SUPERVISION_V1",
        dependencies=("runtime_control_v1", "world_sidecar_v1"),
        requires_restart=True,
    ),
    RuntimeConfigSpec(
        key="world_dashboard_control_v1",
        default=False,
        value_type="bool",
        env_name="AERIE_FEATURE_WORLD_DASHBOARD_CONTROL_V1",
        dependencies=(
            "runtime_control_v1",
            "world_sidecar_v1",
            "world_process_supervision_v1",
        ),
    ),
    RuntimeConfigSpec(
        key="world_runtime_loop_v1",
        default=False,
        value_type="bool",
        env_name="AERIE_FEATURE_WORLD_RUNTIME_LOOP_V1",
        dependencies=("world_sidecar_v1",),
    ),
    RuntimeConfigSpec(
        key="world_desired",
        default="stopped",
        value_type="enum",
        env_name="AERIE_WORLD_DESIRED",
        allowed_values=("stopped", "running", "paused"),
    ),
)


class RuntimeConfigService:
    """Resolve and atomically update a whitelisted runtime config snapshot."""

    def __init__(
        self,
        *,
        state_path: str | Path | None = None,
        defaults: Mapping[str, Any] | None = None,
        env: Mapping[str, str] | None = None,
        specs: tuple[RuntimeConfigSpec, ...] = DEFAULT_RUNTIME_CONFIG_SPECS,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.state_path = Path(state_path) if state_path else None
        self._env = env if env is not None else os.environ
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._specs = {spec.key: spec for spec in specs}
        self._defaults = {
            key: (defaults[key] if defaults and key in defaults else spec.default)
            for key, spec in self._specs.items()
        }
        self._lock = threading.RLock()
        self._revision = 0
        self._local_values: dict[str, Any] = {}
        self._updated_at = ""
        self._load()

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def get_effective(self, key: str, default: Any = None) -> Any:
        """Return the internal effective value without changing persistent state."""

        normalized = str(key or "").strip()
        spec = self._specs.get(normalized)
        if spec is None:
            return default
        with self._lock:
            value, _source, errors = self._resolve(spec)
        return default if errors else value

    def source_for(self, key: str) -> str:
        spec = self._specs.get(str(key or "").strip())
        if spec is None:
            return "unknown"
        with self._lock:
            _value, source, _errors = self._resolve(spec)
        return source

    def snapshot(self) -> dict[str, Any]:
        """Return a deterministic snapshot safe to expose through an API."""

        with self._lock:
            entries: dict[str, dict[str, Any]] = {}
            dependency_errors = self._dependency_errors()
            all_errors: list[dict[str, Any]] = []
            for key in sorted(self._specs):
                spec = self._specs[key]
                value, source, value_errors = self._resolve(spec)
                validation_errors = [*value_errors, *dependency_errors.get(key, [])]
                all_errors.extend(validation_errors)
                entry: dict[str, Any] = {
                    "key": key,
                    "source": source,
                    "mutable": spec.mutable and source != "environment",
                    "requiresRestart": spec.requires_restart,
                    "dependencies": list(spec.dependencies),
                    "validationErrors": validation_errors,
                }
                if spec.secret:
                    entry["configured"] = value not in (None, "", False)
                else:
                    entry["effectiveValue"] = value
                entries[key] = entry

            return {
                "schemaVersion": RUNTIME_CONFIG_SCHEMA_VERSION,
                "revision": self._revision,
                "updatedAt": self._updated_at,
                "values": entries,
                "validationErrors": _dedupe_errors(all_errors),
            }

    def update(
        self,
        changes: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        """Validate and persist a complete revision using optimistic locking."""

        requested = dict(changes or {})
        with self._lock:
            if int(expected_revision) != self._revision:
                raise RuntimeConfigConflict(
                    expected=int(expected_revision),
                    current=self._revision,
                )

            candidate = dict(self._local_values)
            errors: list[dict[str, Any]] = []
            for raw_key, raw_value in requested.items():
                key = str(raw_key or "").strip()
                spec = self._specs.get(key)
                if spec is None:
                    errors.append(_error(key, "unknown_key"))
                    continue
                if not spec.mutable:
                    errors.append(_error(key, "immutable_key"))
                    continue
                if spec.env_name and spec.env_name in self._env:
                    errors.append(_error(key, "environment_override_read_only"))
                    continue
                try:
                    candidate[key] = _coerce(raw_value, spec)
                except (TypeError, ValueError):
                    errors.append(_error(key, "invalid_value"))

            if errors:
                raise RuntimeConfigValidationError(errors)

            dependency_errors = self._dependency_errors(candidate)
            errors = [item for values in dependency_errors.values() for item in values]
            if errors:
                raise RuntimeConfigValidationError(errors)

            if candidate == self._local_values:
                return self.snapshot()

            next_revision = self._revision + 1
            updated_at = self._now().astimezone(timezone.utc).isoformat()
            self._persist(
                {
                    "schema_version": RUNTIME_CONFIG_SCHEMA_VERSION,
                    "revision": next_revision,
                    "updated_at": updated_at,
                    "values": candidate,
                }
            )
            self._local_values = candidate
            self._revision = next_revision
            self._updated_at = updated_at
            return self.snapshot()

    def _load(self) -> None:
        if self.state_path is None or not self.state_path.exists():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return
            if int(payload.get("schema_version") or 0) != RUNTIME_CONFIG_SCHEMA_VERSION:
                return
            values = payload.get("values")
            if not isinstance(values, dict):
                return
            accepted: dict[str, Any] = {}
            for key, raw_value in values.items():
                spec = self._specs.get(str(key))
                if spec is None:
                    continue
                try:
                    accepted[str(key)] = _coerce(raw_value, spec)
                except (TypeError, ValueError):
                    continue
            self._local_values = accepted
            self._revision = max(0, int(payload.get("revision") or 0))
            self._updated_at = str(payload.get("updated_at") or "")
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            # A corrupt optional local override must not prevent safe defaults.
            return

    def _resolve(self, spec: RuntimeConfigSpec) -> tuple[Any, str, list[dict[str, Any]]]:
        if spec.env_name and spec.env_name in self._env:
            raw_value = self._env[spec.env_name]
            source = "environment"
        elif spec.key in self._local_values:
            raw_value = self._local_values[spec.key]
            source = "local"
        else:
            raw_value = self._defaults.get(spec.key, spec.default)
            source = "default"
        try:
            return _coerce(raw_value, spec), source, []
        except (TypeError, ValueError):
            return spec.default, source, [_error(spec.key, "invalid_value")]

    def _dependency_errors(
        self,
        candidate: Mapping[str, Any] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        original = self._local_values
        if candidate is not None:
            self._local_values = dict(candidate)
        try:
            effective = {
                key: self._resolve(spec)[0]
                for key, spec in self._specs.items()
            }
        finally:
            self._local_values = original

        errors: dict[str, list[dict[str, Any]]] = {}
        for key, spec in self._specs.items():
            if effective.get(key) is not True:
                continue
            missing = [dep for dep in spec.dependencies if effective.get(dep) is not True]
            if missing:
                errors[key] = [
                    _error(key, "dependency_disabled", dependencies=missing)
                ]
        return errors

    def _persist(self, payload: dict[str, Any]) -> None:
        if self.state_path is None:
            raise RuntimeConfigReadOnlyError("no runtime config state path configured")
        parent = self.state_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        backup = self.state_path.with_suffix(self.state_path.suffix + ".bak")
        if self.state_path.exists():
            shutil.copy2(self.state_path, backup)

        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.state_path.name}.",
            suffix=".tmp",
            dir=str(parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.state_path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass


def _coerce(value: Any, spec: RuntimeConfigSpec) -> Any:
    if spec.value_type == "bool":
        if isinstance(value, bool):
            return value
        normalized = str(value or "").strip().lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
        raise ValueError("invalid boolean")
    if spec.value_type == "identity":
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        if len(normalized) > 128 or any(ord(char) < 32 for char in normalized):
            raise ValueError("invalid identity")
        return normalized
    if spec.value_type == "enum":
        normalized = str(value or "").strip().lower()
        if normalized not in spec.allowed_values:
            raise ValueError("invalid enum")
        return normalized
    normalized = str(value or "").strip()
    if len(normalized) > 1000 or any(ord(char) < 32 for char in normalized):
        raise ValueError("invalid string")
    return normalized


def _error(key: str, code: str, **extra: Any) -> dict[str, Any]:
    return {"key": str(key), "code": str(code), **extra}


def _dedupe_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for error in errors:
        marker = json.dumps(error, ensure_ascii=False, sort_keys=True)
        if marker not in seen:
            seen.add(marker)
            result.append(error)
    return result
