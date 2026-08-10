"""世界模拟真实化：真实天气注入 + 每日随机事件 + world_reality 兜底。

覆盖三个方向：
1. world_reality.fetch_reality 在任何 provider 缺失时都不抛、结构稳定。
2. WorldSimulation 注入真实天气/附近地点/实时事件。
3. random_events 同天稳定、跨天不同、0 关闭。
"""

from __future__ import annotations

from datetime import datetime, timezone

from core.world_simulation import WorldSimulation


def _stub_baidu_maps(monkeypatch, places):
    """百度 Web 服务 REST：mock core.world_reality._http_get_json 的 place 检索响应。

    替换前代码依赖 MCP 模块 mcp_Bai_Du_Di_Tu（测试环境无法导入）；替换后走
    weather_service.baidu_ak + _http_get_json，这里给 AK 并 stub HTTP 响应。
    """
    monkeypatch.setenv("BAIDU_MAP_AK", "test-ak")

    def _fake_http_get_json(url: str):
        results = [
            {
                "name": p.get("name", "") if isinstance(p, dict) else str(p),
                "address": p.get("addr", "") if isinstance(p, dict) else "",
                "area": p.get("area", "") if isinstance(p, dict) else "",
                "detail_info": {"tag": p.get("tag", "") if isinstance(p, dict) else ""},
            }
            for p in places
        ]
        return {"status": 0, "results": results}

    monkeypatch.setattr("core.world_reality._http_get_json", _fake_http_get_json)
    return _fake_http_get_json


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

    # 用未知城市：百度不可用、内置数据也无此城市 → 全部保持空、结构稳定、不抛。
    reality = asyncio.run(wr.fetch_reality("不存在的城市"))
    assert reality["city"] == "不存在的城市"
    assert reality["weather"] == {}
    assert reality["nearby_places"] == []
    assert reality["city_events"] == []
    assert reality["error"]  # 记录了失败原因
    assert reality["stub"] is True


def test_fetch_reality_falls_back_to_builtin_places_without_ak(monkeypatch):
    """未配置百度 AK 时，已知城市（重庆）回退内置地点/本地活动，开箱即用。"""
    import core.world_reality as wr

    async def _weather(city, location=None):
        return {"city": "重庆", "temp": "32", "desc": "毛毛雨"}

    async def _news(limit=4):
        return [], None

    monkeypatch.setenv("BAIDU_MAP_AK", "")
    monkeypatch.setattr("core.weather_service.fetch_weather_for_city", _weather)
    monkeypatch.setattr("core.brief_fetcher.fetch_cn_news", _news)

    import asyncio

    reality = asyncio.run(wr.fetch_reality("重庆"))
    names = [p["name"] for p in reality["nearby_places"]]
    assert "洪崖洞" in names and "磁器口古镇" in names
    titles = [e["title"] for e in reality["city_events"]]
    assert "洪崖洞夜景灯光秀" in titles


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
    # 附近地点与"她的房间物件"合并：既有窗外/附近城市地点，也有公寓物件。
    assert {"人民公园", "静安寺"} <= set(snap.nearby_objects)
    assert any(
        o in snap.nearby_objects
        for o in ("gray_sofa", "design_desk", "bookshelf", "window")
    )
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
