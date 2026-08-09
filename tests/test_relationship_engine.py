"""Task 4: relationship判定复用情绪愉悦度 P（替代关键词判定）。"""

from __future__ import annotations

from core.relationship_engine import RelationshipEngine


def _sum_state(state: dict):
    """汇总需随正负而变化的关系字段，便于断言净增/净减。"""
    positive = (
        state["agent_to_user"]["attachment"]
        + state["agent_to_user"]["trust"]
        + state["agent_to_user"]["care"]
        + state["user_to_agent"]["warmth"]
        + state["user_to_agent"]["engagement"]
        + state["user_to_agent"]["trust"]
        + state["security"]
    )
    return positive - state["conflict"]


def test_pleasure_positive_increases_relationship_and_valence():
    """TR-4.1: pleasure>0 → 关系净增，且 valence 为正值。"""
    engine = RelationshipEngine()
    before = engine.get_state(user_id=1)
    state = engine.observe_user_message(user_id=1, text="随便说的话", pleasure=0.8)
    assert state["user_emotion"]["valence"] > 0
    assert state["user_emotion"]["label"] == "positive"
    assert _sum_state(state) > _sum_state(before)


def test_pleasure_negative_decreases_relationship():
    """TR-4.2: pleasure<0 → 关系净减。"""
    engine = RelationshipEngine()
    before = engine.get_state(user_id=2)
    state = engine.observe_user_message(user_id=2, text="随便说的话", pleasure=-0.6)
    assert state["user_emotion"]["valence"] < 0
    assert state["user_emotion"]["label"] == "negative"
    assert _sum_state(state) < _sum_state(before)


def test_pleasure_zero_is_neutral():
    """TR-4.2 补充: pleasure=0 → neutral，走中性分支。"""
    engine = RelationshipEngine()
    state = engine.observe_user_message(user_id=3, text="随便说的话", pleasure=0.0)
    assert state["user_emotion"]["label"] == "neutral"
    assert state["user_emotion"]["valence"] == 0.0


def test_pleasure_clamped_to_range():
    """pleasure 超出 [-0.95, 0.95] 时被 clamp。"""
    engine = RelationshipEngine()
    hi = engine.observe_user_message(user_id=4, text="x", pleasure=5.0)
    lo = engine.observe_user_message(user_id=5, text="x", pleasure=-9.0)
    assert hi["user_emotion"]["valence"] == 0.95
    assert lo["user_emotion"]["valence"] == -0.95


def test_no_pleasure_falls_back_to_keyword_estimation():
    """TR-4.3: 不传 pleasure → 走 _estimate_valence 回退，行为与原一致。"""
    engine = RelationshipEngine()
    pos = engine.observe_user_message(user_id=6, text="谢谢你，我很喜欢")
    assert pos["user_emotion"]["label"] == "positive"
    assert pos["user_emotion"]["valence"] == 0.35
    neg = engine.observe_user_message(user_id=6, text="别担心")
    assert neg["user_emotion"]["label"] == "negative"
    assert neg["user_emotion"]["valence"] == -0.35
    neu = engine.observe_user_message(user_id=6, text="今天天气不错")
    assert neu["user_emotion"]["label"] == "neutral"
    assert neu["user_emotion"]["valence"] == 0.0


def test_strong_emotion_moves_relationship_more():
    """TR-5.1: 相同 learning_rate，强情感(|P| 大)比弱情感涨跌更明显。"""
    engine = RelationshipEngine()
    strong = engine.observe_user_message(user_id=7, text="随便说的话", pleasure=0.9)
    weak = engine.observe_user_message(user_id=8, text="随便说的话", pleasure=0.2)
    assert strong["agent_to_user"]["attachment"] > weak["agent_to_user"]["attachment"]
    assert strong["agent_to_user"]["trust"] > weak["agent_to_user"]["trust"]


def test_conflict_reparable_under_positive_interaction():
    """TR-5.2: 连续正向互动可让 conflict 从初始值下降。"""
    engine = RelationshipEngine(defaults={"conflict": 0.5})
    for _ in range(5):
        engine.observe_user_message(user_id=9, text="随便说的话", pleasure=0.9)
    state = engine.get_state(user_id=9)
    assert state["conflict"] < 0.5