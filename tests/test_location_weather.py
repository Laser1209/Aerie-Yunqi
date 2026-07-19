import importlib
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def isolated_settings(monkeypatch, tmp_path):
    state = {"weather": {"city": ""}}

    def fake_load_settings():
        return json.loads(json.dumps(state))

    def fake_save_settings(data):
        weather = data.get("weather") or {}
        state.setdefault("weather", {}).update(weather)
        return True

    monkeypatch.setattr("config.persona_loader.load_settings", fake_load_settings)
    monkeypatch.setattr("config.persona_loader.save_settings", fake_save_settings)
    return state


def reload_location_modules(monkeypatch, tmp_path):
    monkeypatch.setenv("AERIE_DATA_DIR", str(tmp_path / "aerie-data"))
    for name in ["core.paths", "core.location_resolver", "core.weather_service", "core.brief_fetcher"]:
        sys.modules.pop(name, None)
    import core.paths as paths
    import core.location_resolver as location_resolver
    import core.weather_service as weather_service
    import core.brief_fetcher as brief_fetcher
    return paths, location_resolver, weather_service, brief_fetcher


def test_city_cache_path_uses_aerie_data_dir(monkeypatch, tmp_path):
    paths, _, _, _ = reload_location_modules(monkeypatch, tmp_path)

    assert paths.city_cache_path() == tmp_path / "aerie-data" / "cache" / "city.json"


def test_manual_city_wins_over_ip_cache(monkeypatch, tmp_path, isolated_settings):
    isolated_settings["weather"]["city"] = "东京"
    paths, location_resolver, _, _ = reload_location_modules(monkeypatch, tmp_path)
    paths.city_cache_path().parent.mkdir(parents=True, exist_ok=True)
    paths.city_cache_path().write_text(json.dumps({"city": "上海", "ts": 9999999999}, ensure_ascii=False), encoding="utf-8")

    location = location_resolver.resolve_location()

    assert location["city"] == "东京"
    assert location["manual"] is True
    assert location["source"] == "manual"


@pytest.mark.asyncio
async def test_clearing_manual_city_uses_auto_location(monkeypatch, tmp_path, isolated_settings):
    isolated_settings["weather"]["city"] = ""
    _, location_resolver, _, _ = reload_location_modules(monkeypatch, tmp_path)

    async def fake_ip_location():
        return {"content": {"address_detail": {"city": "首尔"}}}

    monkeypatch.setattr(location_resolver, "_call_map_ip_location_async", fake_ip_location)

    location = await location_resolver.resolve_location_async(force_refresh=True)

    assert location["city"] == "首尔"
    assert location["manual"] is False
    assert location["source"] == "ip"


@pytest.mark.asyncio
async def test_fetch_weather_returns_standard_stub_when_mcp_unavailable(monkeypatch, tmp_path, isolated_settings):
    isolated_settings["weather"]["city"] = "巴黎"
    _, _, weather_service, _ = reload_location_modules(monkeypatch, tmp_path)

    weather = await weather_service.fetch_weather_for_current_location()

    assert weather["city"] == "巴黎"
    assert weather["manual"] is True
    assert weather["source"] == "manual"
    assert weather["forecast"] == []
    assert weather["stub"] is True


def test_update_today_weather_updates_cached_brief(monkeypatch, tmp_path):
    paths, _, _, brief_fetcher = reload_location_modules(monkeypatch, tmp_path)
    brief_dir = paths.briefs_dir()
    brief_dir.mkdir(parents=True, exist_ok=True)
    brief_path = brief_dir / "2026-07-19.json"
    brief_path.write_text(json.dumps({"ai_news": [], "weather": {"city": "上海"}}, ensure_ascii=False), encoding="utf-8")

    updated = brief_fetcher.update_brief_weather("2026-07-19", {"city": "巴黎", "temp": "21", "forecast": []})

    assert updated["weather"]["city"] == "巴黎"
    assert json.loads(brief_path.read_text(encoding="utf-8"))["weather"]["city"] == "巴黎"


@pytest.mark.asyncio
async def test_location_set_returns_weather_and_updates_brief(monkeypatch, tmp_path, isolated_settings):
    paths, _, _, brief_fetcher = reload_location_modules(monkeypatch, tmp_path)
    today = "2026-07-19"
    monkeypatch.setattr("core.api_server.datetime", type("FakeDateTime", (), {"now": staticmethod(lambda: type("D", (), {"strftime": lambda self, fmt: today})())}), raising=False)
    brief_fetcher.save_brief(today, {"ai_news": [], "weather": {"city": "上海"}})

    from core import api_server

    monkeypatch.setattr(api_server, "save_settings", lambda data: isolated_settings["weather"].update(data.get("weather", {})) or True)
    monkeypatch.setattr(api_server, "load_settings", lambda: isolated_settings)
    monkeypatch.setattr(api_server, "_fetch_current_weather", AsyncMock(return_value={"city": "巴黎", "temp": "21", "forecast": [], "manual": True, "source": "manual"}), raising=False)

    class Request:
        async def json(self):
            return {"city": "巴黎"}

    response = await api_server.location_set(Request())

    assert response["status"] == "ok"
    assert response["city"] == "巴黎"
    assert response["weather"]["city"] == "巴黎"
