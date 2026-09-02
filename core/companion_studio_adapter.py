"""Optional adapter for the local Companion Studio service.

The adapter keeps the Studio process independent from Aerie.  It is enabled
only when ``AERIE_COMPANION_STUDIO_URL`` is configured; network failures are
reported as a structured unavailable result and never block core chat.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class CompanionStudioAdapter:
    def __init__(self, base_url: str | None = None, timeout: float = 8.0) -> None:
        configured = base_url if base_url is not None else os.getenv(
            "AERIE_COMPANION_STUDIO_URL", ""
        )
        self.base_url = configured.strip().rstrip("/")
        self.timeout = max(1.0, float(timeout))

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def _disabled(self) -> dict[str, Any]:
        return {"ok": False, "status": "disabled", "reason": "url_not_configured"}

    async def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self.enabled:
            return self._disabled()
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                response = await client.request(method, self.base_url + path, json=payload)
                response.raise_for_status()
                body = response.json()
            if isinstance(body, dict) and isinstance(body.get("data"), dict):
                return {"ok": True, "status": "healthy", **body["data"]}
            return {"ok": True, "status": "healthy", "data": body}
        except (httpx.HTTPError, ValueError) as exc:
            return {"ok": False, "status": "unavailable", "reason": type(exc).__name__}

    async def health(self) -> dict[str, Any]:
        result = await self._request("GET", "/api/health")
        result.setdefault("service", "companion-studio")
        result["base_url_configured"] = self.enabled
        return result

    async def talk(self, text: str, source: str = "text") -> dict[str, Any]:
        return await self._request("POST", "/api/talk", {"text": text, "source": source})

    async def speak(self, text: str, echo: bool | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"text": text}
        if echo is not None:
            payload["echo"] = echo
        return await self._request("POST", "/api/speak", payload)

    async def asr(self, audio_base64: str, audio_format: str = "wav") -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/asr",
            {"audioBase64": audio_base64, "format": audio_format},
        )

