"""MultiLayerDecision (L1-L4) contracts.

Pins the multi-layer weighted decision from §10.2: every candidate
gets a per-layer score and the weighted sum is sampled via softmax.
This guards against the P2-A regression where the weight lookup key
mismatched the WEIGHTS dict and raised KeyError on every call.
"""

from __future__ import annotations

from core.decision import Candidate, MultiLayerDecision


def test_decide_for_message_returns_full_trace():
    d = MultiLayerDecision()
    out = d.decide_for_message(
        user_id=1,
        route_mode="FULL",
        source="local",
    )
    assert out["chosen"] in {"reply", "tool_call", "recall", "silence"}
    assert set(out["scores"]) == {"reply", "tool_call", "recall", "silence"}
    assert set(out["layers"]) == {"reply", "tool_call", "recall", "silence"}
    # every candidate has all 4 layer scores
    for layers in out["layers"].values():
        assert set(layers) == {"L1", "L2", "L3", "L4"}
    assert out["weights"] == {
        "L1_core": 0.50,
        "L2_personality": 0.30,
        "L3_mood": 0.15,
        "L4_context": 0.05,
    }


def test_weighted_score_matches_l1_l4_breakdown():
    d = MultiLayerDecision()
    out = d.decide_for_message(
        user_id=1,
        route_mode="FULL",
        source="local",
        emotion_label="neutral",
    )
    # reply at FULL/neutral: L1=0.85, L2=0.65, L3=0.50, L4=0.55
    expected = (
        0.50 * 0.85 + 0.30 * 0.65 + 0.15 * 0.50 + 0.05 * 0.55
    )
    assert abs(out["scores"]["reply"] - round(expected, 4)) < 1e-6


def test_empty_candidates_returns_none_chosen():
    d = MultiLayerDecision()
    out = d.decide([], {})
    assert out["chosen"] is None
    assert out["scores"] == {}


def test_user_busy_boosts_silence_l1():
    d = MultiLayerDecision()
    out = d.decide(
        [
            Candidate("reply", "reply"),
            Candidate("silence", "proactive_silence"),
        ],
        {"user_busy": True, "emotion_label": "neutral", "route_mode": "FULL"},
    )
    assert out["layers"]["silence"]["L1"] == 0.95
    assert out["layers"]["reply"]["L1"] == 0.85


def test_tool_call_suppressed_when_not_full_route():
    d = MultiLayerDecision()
    out = d.decide(
        [
            Candidate("reply", "reply"),
            Candidate("tool_call", "tool_call", {"available": False}),
        ],
        {"route_mode": "AUTO", "emotion_label": "neutral", "tools_offered": False},
    )
    assert out["layers"]["tool_call"]["L1"] == 0.05
    assert out["layers"]["tool_call"]["L4"] == 0.10


def test_sad_emotion_suppresses_tool_call_and_pushes_reply():
    d = MultiLayerDecision()
    out = d.decide(
        [
            Candidate("reply", "reply"),
            Candidate("tool_call", "tool_call", {"available": True}),
        ],
        {"emotion_label": "sad", "route_mode": "FULL", "tools_offered": True},
    )
    assert out["layers"]["reply"]["L3"] == 0.90
    assert out["layers"]["tool_call"]["L3"] == 0.30
