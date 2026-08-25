from __future__ import annotations

import base64
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.paths import data_dir
from core.windows_dpapi import DPAPIError, protect_data, unprotect_data


class CredentialsError(RuntimeError):
    pass


@dataclass(frozen=True)
class ILinkCredentials:
    bot_token: str
    bot_id: str
    user_id: str
    base_url: str


class ILinkCredentialsStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or data_dir() / "ilink_credentials.json")

    def save(self, credentials: ILinkCredentials) -> None:
        payload = json.dumps(
            asdict(credentials),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            ciphertext = protect_data(payload)
        except DPAPIError as exc:
            raise CredentialsError("Unable to protect iLink credentials") from exc
        envelope = {
            "version": 1,
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write_atomic(
            json.dumps(envelope, separators=(",", ":")).encode("utf-8")
        )

    def load(self) -> ILinkCredentials | None:
        if not self.path.exists():
            return None
        try:
            envelope = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(envelope, dict) or set(envelope) != {
                "version",
                "ciphertext",
                "saved_at",
            }:
                raise ValueError("Invalid credential envelope")
            if envelope["version"] != 1 or not isinstance(envelope["ciphertext"], str):
                raise ValueError("Unsupported credential envelope")
            ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
            payload = json.loads(unprotect_data(ciphertext).decode("utf-8"))
            return self._parse_credentials(payload)
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError, DPAPIError) as exc:
            raise CredentialsError("Unable to load iLink credentials") from exc

    def delete(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise CredentialsError("Unable to delete iLink credentials") from exc

    def _write_atomic(self, content: bytes) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self.path)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise CredentialsError("Unable to save iLink credentials") from exc

    @staticmethod
    def _parse_credentials(payload: Any) -> ILinkCredentials:
        if not isinstance(payload, dict) or set(payload) != {
            "bot_token",
            "bot_id",
            "user_id",
            "base_url",
        }:
            raise ValueError("Invalid credential payload")
        if any(not isinstance(value, str) or not value for value in payload.values()):
            raise ValueError("Invalid credential value")
        return ILinkCredentials(**payload)
