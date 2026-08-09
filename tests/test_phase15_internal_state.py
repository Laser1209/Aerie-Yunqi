"""Phase 15 Batch 3 (B3.1): internal-state model (needs / fatigue / neuro-like).

Covers the deterministic computation engine and the read-only API endpoints
``/api/internal/state`` and ``/api/internal/history``. All metrics are
deliberately computation-only and must never use medical wording.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient

from core import api_server
from core.api_server import app
from core.internal_state import InternalStateEngine, public_neuro_labels

client = TestClient(app)


def _world(*, activity="working", phase="day", energy=0.6):
    return {"activity": activity, "phase": phase, "energy": energy}


def _emotion(*, P=0.5, A=0.5, D=0.5):
    return {"pad": {"P": P, "A": A, "D": D}}


# ── engine: source tracking (Gate B3.1) ──────────────────────────────

def test_internal_state_source():
    """每个指标都带 source / confidence / updated_at（来源可追溯）。"""
    engine = InternalStateEngine()
    snap = engine.compute(_world(), _emotion(), now=1_700_000_000)
    for group in ("needs", "neurochemicals"):
        for name, metric in snap[group].items():
            assert isinstance(metric, dict), name
            assert "source" in metric and metric["source"], name
            assert "confidence" in metric and 0 < metric["confidence"] <= 1, name
            assert "updated_at" in metric and metric["updated_at"] > 0, name
            assert 0 <= metric["value"] <= 1, name
    fatigue = snap["fatigue"]
    assert "source" in fatigue and "confidence" in fatigue and "updated_at" in fatigue
    assert 0 <= fatigue["value"] <= 1


def test_internal_state_no_medical_terms():
    """Gate B3.1: 无医学措辞；固定标注"计算模型，非生物测量"。"""
    engine = InternalStateEngine()
    snap = engine.compute(_world(), _emotion())
    assert snap["label"] == "计算模型，非生物测量"
    # 类神经化学标签只能是"活力/平静/压力（类xxx）"的非医学写法
    labels = public_neuro_labels()
    assert "多巴胺" in labels["vitality"] or "活力" in labels["vitality"]
    assert "血清素" in labels["calm"] or "平静" in labels["calm"]
    assert "皮质醇" in labels["strain"] or "压力" in labels["strain"]
    forbidden = ("诊断", "患病", "抑郁", "焦虑障碍", "clinically", "disorder", "depression")
    serialized = str(snap).lower()
    for term in forbidden:
        assert term not in serialized, term


def test_internal_history_trend():
    """Gate B3.1: history 返回趋势序列，且随时间变化。"""
    engine = InternalStateEngine()
    for i in range(30):
        engine.compute(
            _world(activity="working" if i % 2 == 0 else "sleeping"),
            _emotion(P=0.4 + i * 0.01),
            now=1_700_000_000 + i * 3600,
        )
    history = engine.history(limit=100)
    assert len(history) == 30
    # 最旧在前
    assert history[0]["sampledAt"] < history[-1]["sampledAt"]
    # 疲劳随时间/活动变化，非恒定
    fatigue_values = {h["fatigue"]["value"] for h in history}
    assert len(fatigue_values) >= 2


def test_internal_values_change_over_time_and_activity():
    """Gate B3.1: 数值随时间/活动变化（连续两次采样有差异）。"""
    engine = InternalStateEngine()
    a = engine.compute(_world(activity="working"), _emotion(P=0.3), now=1_700_000_000)
    b = engine.compute(_world(activity="sleeping"), _emotion(P=0.8), now=1_700_000_000 + 12 * 3600)
    # 需求/疲劳至少一项有变化
    changed = any(a["needs"][k]["value"] != b["needs"][k]["value"] for k in a["needs"])
    assert changed or a["fatigue"]["value"] != b["fatigue"]["value"]


def test_internal_deterministic_same_inputs():
    """相同输入 → 相同输出（可复现、可测试）。"""
    engine = InternalStateEngine()
    snap1 = engine.compute(_world(), _emotion(), now=1_700_000_000)
    snap2 = engine.compute(_world(), _emotion(), now=1_700_000_000)
    assert snap1["needs"] == snap2["needs"]
    assert snap1["fatigue"] == snap2["fatigue"]
    assert snap1["neurochemicals"] == snap2["neurochemicals"]


def test_internal_engine_tolerates_empty_inputs():
    """world/emotion 为空也不抛错，返回带来源的默认指标。"""
    engine = InternalStateEngine()
    snap = engine.compute(None, None, now=1_700_000_000)
    assert snap["label"] == "计算模型，非生物测量"
    assert len(snap["needs"]) == 4
    assert len(snap["neurochemicals"]) == 3


def test_internal_history_mirrors_pad_and_relationship_for_trends():
    """Gate B3.2: 单条 history 同时携带 PAD 与关系摘要，供三张趋势图复用。"""
    engine = InternalStateEngine()
    for i in range(10):
        engine.compute(
            _world(),
            _emotion(P=0.3 + i * 0.05, A=0.5, D=0.6),
            relationship={"attachment": 0.4 + i * 0.04, "trust": 0.5, "security": 0.6, "conflict": 0.1},
            now=1_700_000_000 + i * 300,
        )
    history = engine.history(limit=100)
    assert len(history) == 10
    assert history[0]["pad"]["P"] != history[-1]["pad"]["P"]
    assert history[-1]["relationship"]["attachment"] > history[0]["relationship"]["attachment"]
    assert history[0]["relationship"]["trust"] == 0.5


def test_internal_relationship_mirror_absent_without_data():
    """无关系数据时 snapshot 的 relationship 为 None，不影响其余指标。"""
    engine = InternalStateEngine()
    snap = engine.compute(_world(), _emotion(), now=1_700_000_000)
    assert snap["relationship"] is None
    assert "needs" in snap and "neurochemicals" in snap


# ── API: read-only endpoints ─────────────────────────────────────────

def test_api_internal_state_returns_snapshot(monkeypatch):
    engine = InternalStateEngine()
    companion = SimpleNamespace(
        internal_state=engine,
        get_internal_state=Mock(return_value=engine.compute(_world(), _emotion(), now=1_700_000_000)),
    )
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)
    response = client.get("/api/internal/state")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["label"] == "计算模型，非生物测量"
    assert "needs" in data and "fatigue" in data and "neurochemicals" in data
    # 无医学措辞
    assert "diagnos" not in response.text.lower()


def test_api_internal_history_returns_trend(monkeypatch):
    engine = InternalStateEngine()
    for i in range(20):
        engine.compute(_world(), _emotion(), now=1_700_000_000 + i * 60)
    companion = SimpleNamespace(get_internal_history=Mock(return_value=engine.history(limit=20)))
    monkeypatch.setattr(api_server, "get_companion", lambda: companion)
    response = client.get("/api/internal/history")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert isinstance(data["items"], list) and len(data["items"]) == 20
    assert data["items"][0]["sampledAt"] <= data["items"][-1]["sampledAt"]


def test_api_internal_missing_handler_degrades_without_404(monkeypatch):
    monkeypatch.setattr(api_server, "get_companion", lambda: SimpleNamespace())
    state = client.get("/api/internal/state")
    hist = client.get("/api/internal/history")
    assert state.status_code == 200
    assert state.json()["status"] == "backend_unavailable"
    assert hist.status_code == 200
    assert hist.json()["status"] == "backend_unavailable"
