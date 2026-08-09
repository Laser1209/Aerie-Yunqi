"""世界模拟真实化：真实天气注入 + 每日随机事件 + world_reality 兜底。

覆盖三个方向：
1. world_reality.fetch_reality 在任何 provider 缺失时都不抛、结构稳定。
2. WorldSimulation 注入真实天气/附近地点/实时事件。
3. random_events 同天稳定、跨天不同、0 关闭。
"""

from __future__ import annotations

import sys
import types
from datetime import datetime, timezone

from core.world_simulation import WorldSimulation


def _stub_baidu_maps(monkeypatch, places):
    """mcp_Bai_Du_Di_Tu 是 MCP 工具而非项目内模块，测试环境无法导入。

    先在 sys.modules 注入一个 stub 模块，再 monkeypatch 其 map_search_places。
    """
    mod = types.ModuleType("mcp_Bai_Du_Di_Tu")
    mod.map_search_places = lambda query, region: places
    sys.modules["mcp_Bai_Du_Di_Tu"] = mod
    monkeypatch.setattr("mcp_Bai_Du_Di_Tu.map_search_places", mod.map_search_places)
    return mod


def _sim(config=None, *, ts=datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc)):
    return WorldSimulation(config=config or {}, clock=lambda: ts)


# ── world_reality 兜底 ──────────────────────────────────────────
def test_fetch_reality_never_raises_and_has_stable_shape(monkeypatch):
    import core.world_reality as wr

    async def _bad_weather(city, location=None):
        raise RuntimeError("boom")

    async def _bad_news(limit=4):
        raise RuntimeError("boom")

    monkeypatch.setattr("core.weather_service.fetch_weather_for_city", _bad_weather)
    monkeypatch.setattr("core.brief_fetcher.fetch_cn_news", _bad_news)

    import asyncio

    reality = asyncio.run(wr.fetch_reality("上海"))
    assert reality["city"] == "上海"
    assert reality["weather"] == {}
    assert reality["nearby_places"] == []
    assert reality["city_events"] == []
    assert reality["error"]  # 记录了失败原因
    assert reality["stub"] is True


def test_fetch_reality_normalizes_places_and_events(monkeypatch):
    import core.world_reality as wr

    async def _weather(city, location=None):
        return {"city": "上海", "temp": "21", "desc": "中雨"}

    async def _news(limit=4):
        return [{"title": "某城市今日热点", "url": "https://x", "source": "cn"}], None

    monkeypatch.setattr("core.weather_service.fetch_weather_for_city", _weather)
    monkeypatch.setattr("core.brief_fetcher.fetch_cn_news", _news)
    _stub_baidu_maps(monkeypatch, [{"name": "人民公园"}, {"name": "静安寺"}])

    import asyncio

    reality = asyncio.run(wr.fetch_reality("上海"))
    assert reality["weather"]["desc"] == "中雨"
    assert [p["name"] for p in reality["nearby_places"]] == ["人民公园", "静安寺"]
    assert reality["city_events"][0]["title"] == "某城市今日热点"


# ── WorldSimulation 真实注入 ────────────────────────────────────
def test_world_snapshot_injects_real_weather_nearby_and_events():
    sim = _sim({"random_events_per_day": 0})
    sim.set_reality(
        {
            "city": "上海",
            "weather": {"desc": "中雨", "temp": "21", "city": "上海"},
            "nearby_places": [{"name": "人民公园"}, {"name": "静安寺"}],
            "city_events": [{"title": "某城市今日热点", "url": "", "source": "cn"}],
        }
    )
    snap = sim.tick()
    assert snap.weather_mood == "rain"  # 中雨 → rain
    assert snap.weather_detail == "上海 21 中雨"
    assert snap.city == "上海"
    assert snap.nearby_objects == ["人民公园", "静安寺"]
    assert snap.city_events and snap.city_events[0]["title"] == "某城市今日热点"


def test_world_snapshot_falls_back_without_reality():
    # 无真实数据 → 仍确定性派生，不报错。
    snap = _sim().tick()
    assert snap.weather_mood in {"neutral", "clear", "partly_cloudy", "cloudy", "rain", "windy", "fog"}
    assert snap.city == ""
    assert snap.city_events == []


# ── 每日随机事件 ────────────────────────────────────────────────
def test_random_events_stable_within_day_differs_across_days():
    ts1 = datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 7, 29, 9, 0, tzinfo=timezone.utc)
    s1 = _sim({"random_events_per_day": 3}, ts=ts1).tick().random_events
    s2 = _sim({"random_events_per_day": 3}, ts=ts1).tick().random_events
    s3 = _sim({"random_events_per_day": 3}, ts=ts2).tick().random_events
    assert s1 == s2          # 同天稳定
    assert len(s1) == 3      # 条数 = 配置
    assert s1 != s3          # 跨天不同


def test_random_events_disabled_when_zero():
    assert _sim({"random_events_per_day": 0}).tick().random_events == []
