"""NapCat WebUI HTTP client.

The bundled NapCat Shell exposes its login flow through a local WebUI
(default port 6099). The on-disk ``cache/qrcode.png`` is written only once
per process start and goes stale quickly; the authoritative login state and
QR renewal must be driven through these endpoints:

    POST /api/auth/login                 {hash: sha256(token + ".napcat")}
    POST /api/QQLogin/CheckLoginStatus
    POST /api/QQLogin/RefreshQRcode
    POST /api/QQLogin/GetQuickLoginListNew
    POST /api/QQLogin/SetQuickLogin       {uin}
    GET  /api/OB11Config/GetConfig
    POST /api/OB11Config/SetConfig        {config: json string}
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_WEBUI_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)


class NapCatWebUIError(RuntimeError):
    """Raised when the WebUI is unreachable or rejects a request."""


def load_webui_settings(napcat_dir: Path) -> dict[str, Any]:
    """Read host/port/token from ``<napcat_dir>/config/webui.json``."""
    path = napcat_dir / "config" / "webui.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise NapCatWebUIError(f"webui.json unavailable: {exc}") from exc
    if not isinstance(payload, dict) or not payload.get("token"):
        raise NapCatWebUIError("webui.json is missing the token")
    host = str(payload.get("host") or "127.0.0.1")
    if host in ("::", "0.0.0.0"):
        host = "127.0.0.1"
    return {
        "host": host,
        "port": int(payload.get("port") or 6099),
        "token": str(payload["token"]),
    }


class NapCatWebUIClient:
    def __init__(
        self,
        napcat_dir: Path,
        *,
        settings: dict[str, Any] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._napcat_dir = napcat_dir
        self._owns_http_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=_WEBUI_TIMEOUT)
        resolved = settings or load_webui_settings(napcat_dir)
        self.port = resolved["port"]
        self._base_url = f"http://{resolved['host']}:{resolved['port']}/api"
        self._token_hash = hashlib.sha256(
            f"{resolved['token']}.napcat".encode("utf-8")
        ).hexdigest()
        self._credential: str | None = None

    async def close(self) -> None:
        if self._owns_http_client:
            await self._http.aclose()

    async def _ensure_credential(self) -> str:
        if self._credential is None:
            try:
                response = await self._http.post(
                    f"{self._base_url}/auth/login",
                    json={"hash": self._token_hash},
                )
                data = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise NapCatWebUIError(f"webui auth request failed: {exc}") from exc
            credential = (data.get("data") or {}).get("Credential")
            if data.get("code") != 0 or not isinstance(credential, str):
                raise NapCatWebUIError(
                    f"webui auth rejected: {data.get('message') or 'unknown'}"
                )
            self._credential = credential
        return self._credential

    async def _post(
        self,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        _retry: bool = True,
    ) -> Any:
        credential = await self._ensure_credential()
        try:
            response = await self._http.post(
                f"{self._base_url}{path}",
                json=body or {},
                headers={"Authorization": f"Bearer {credential}"},
            )
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise NapCatWebUIError(f"webui request {path} failed: {exc}") from exc
        code = data.get("code")
        if code == -1 and data.get("message") == "Unauthorized" and _retry:
            # Credential expired mid-session → re-auth once.
            self._credential = None
            return await self._post(path, body, _retry=False)
        if code != 0:
            raise NapCatWebUIError(
                f"webui {path} rejected: {data.get('message') or 'unknown'}"
            )
        return data.get("data")

    async def check_login_status(self) -> dict[str, Any]:
        """Return {is_login, is_offline, qrcode_url, login_error}."""
        data = await self._post("/QQLogin/CheckLoginStatus") or {}
        return {
            "is_login": bool(data.get("isLogin")),
            "is_offline": bool(data.get("isOffline")),
            "qrcode_url": str(data.get("qrcodeurl") or ""),
            "login_error": str(data.get("loginError") or ""),
        }

    async def refresh_qrcode(self) -> None:
        await self._post("/QQLogin/RefreshQRcode")

    async def get_quick_login_list(self) -> list[dict[str, Any]]:
        data = await self._post("/QQLogin/GetQuickLoginListNew")
        return data if isinstance(data, list) else []

    async def quick_login(self, uin: str) -> None:
        await self._post("/QQLogin/SetQuickLogin", {"uin": str(uin)})

    async def get_ob11_config(self) -> dict[str, Any]:
        data = await self._post("/OB11Config/GetConfig")
        if isinstance(data, str):
            data = json.loads(data)
        if not isinstance(data, dict):
            raise NapCatWebUIError("OB11 config is not an object")
        return data

    async def set_ob11_config(self, config: dict[str, Any]) -> None:
        await self._post(
            "/OB11Config/SetConfig", {"config": json.dumps(config, ensure_ascii=False)}
        )
