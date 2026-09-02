from __future__ import annotations

import pytest

from core.companion_studio_adapter import CompanionStudioAdapter


@pytest.mark.asyncio
async def test_disabled_adapter_is_explicit_and_side_effect_free() -> None:
    adapter = CompanionStudioAdapter("")
    assert adapter.enabled is False
    assert await adapter.health() == {
        "ok": False,
        "status": "disabled",
        "reason": "url_not_configured",
        "service": "companion-studio",
        "base_url_configured": False,
    }


@pytest.mark.asyncio
async def test_adapter_normalizes_studio_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"code": 0, "message": "ok", "data": {"reply": "hello"}}

    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def request(self, method: str, url: str, json: dict[str, object] | None = None) -> FakeResponse:
            assert method == "POST"
            assert url == "http://127.0.0.1:8899/api/talk"
            assert json == {"text": "hi", "source": "text"}
            return FakeResponse()

    monkeypatch.setattr("core.companion_studio_adapter.httpx.AsyncClient", FakeClient)
    adapter = CompanionStudioAdapter("http://127.0.0.1:8899/")
    assert await adapter.talk("hi") == {
        "ok": True,
        "status": "healthy",
        "reply": "hello",
    }
