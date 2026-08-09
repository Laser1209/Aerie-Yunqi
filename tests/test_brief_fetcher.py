import json
import sys

import pytest


def _make_brief_fetcher(monkeypatch, tmp_path):
    monkeypatch.setenv("AERIE_DATA_DIR", str(tmp_path / "aerie-data"))
    sys.modules.pop("core.brief_fetcher", None)
    import core.brief_fetcher as bf
    return bf


def test_accumulated_trend_marks_steady_and_new(monkeypatch, tmp_path):
    """累积趋势应区分：历史多次出现的 → steady/rising；仅今日出现的 → new。"""
    bf = _make_brief_fetcher(monkeypatch, tmp_path)

    history = [
        "大模型 新发布", "大模型 升级", "大模型 生态报告", "大模型 Agent 落地",
    ]  # 大模型在历史中命中 4 条
    today_items = [
        {"title": "大模型 Agent 发布"},           # 大模型 今日 1 条
        {"title": "全新量子计算 芯片 突破"},       # 芯片 今日 1 条，历史无
    ]
    trends = bf._generate_trends_accumulated(
        today_items, history_titles=history, days=7
    )

    by_title = {t["title"]: t for t in trends}
    # 大模型：历史 4 条 → accum_days>=3，且非 new
    mt = next(t for k, t in by_title.items() if "大模型" in k)
    assert mt["accum_days"] >= 3
    assert mt["new_today"] == 1
    assert mt["momentum"] in ("rising", "steady")

    # 芯片：历史无 → new
    ct = next(t for k, t in by_title.items() if "芯片" in k)
    assert ct["momentum"] == "new"
    assert ct["accum_days"] == 1


def test_accumulated_trend_loads_history_from_files(monkeypatch, tmp_path):
    """`_load_history_titles` 应读取近 7 天 brief JSON 的新闻标题。"""
    bf = _make_brief_fetcher(monkeypatch, tmp_path)
    brief_dir = bf.briefs_dir()
    brief_dir.mkdir(parents=True, exist_ok=True)

    (brief_dir / "2026-08-01.json").write_text(
        json.dumps({"ai_news": [{"title": "旧新闻"}], "it_news": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    (brief_dir / "2026-08-05.json").write_text(
        json.dumps({"ai_news": [{"title": "大模型 发布"}], "it_news": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    trends = bf._generate_trends_accumulated(
        [{"title": "大模型 今日"}], history_titles=None, days=7
    )
    by_title = {t["title"]: t for t in trends}
    assert any("大模型" in k for k in by_title)
