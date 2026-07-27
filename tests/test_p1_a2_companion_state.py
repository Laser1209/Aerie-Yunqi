"""TDD RED tests for Task P1-A.2: CompanionState 陪伴状态模型.

覆盖:
  - 创建 CompanionState 包含全部字段
  - add_pain_point / add_joy_point
  - add_pain_point 后自动调度 care_followup
  - add_pending_topic / complete_pending_topic
  - check_due_followups 到期检查
  - 持久化 (JSON 原子写, AERIE_DATA_DIR 隔离)
  - relationship_stage 转换链路
  - recent_pain_points / recent_joy_points 各限 10 条
"""

from __future__ import annotations

import time

import pytest


# ── 创建 ────────────────────────────────────────────
def test_create_companion_state_has_all_fields():
    from core.companion_state import CompanionState

    state = CompanionState()
    assert state.relationship_stage == "stranger"
    assert state.care_followups == []
    assert state.pending_topics == []
    assert state.recent_pain_points == []
    assert state.recent_joy_points == []


# ── pain_point ─────────────────────────────────────
def test_add_pain_point_appends_to_recent_pain_points():
    from core.companion_state import CompanionState

    state = CompanionState()
    state.add_pain_point("工作压力大")
    assert len(state.recent_pain_points) == 1
    assert state.recent_pain_points[0].text == "工作压力大"


def test_add_pain_point_auto_schedules_care_followup():
    from core.companion_state import CompanionState

    state = CompanionState()
    state.add_pain_point("感冒了")
    assert len(state.care_followups) == 1
    assert state.care_followups[0].topic == "感冒了"


# ── joy_point ──────────────────────────────────────
def test_add_joy_point_appends_to_recent_joy_points():
    from core.companion_state import CompanionState

    state = CompanionState()
    state.add_joy_point("考试通过了")
    assert len(state.recent_joy_points) == 1
    assert state.recent_joy_points[0].text == "考试通过了"


# ── pending_topic ─────────────────────────────────
def test_add_pending_topic():
    from core.companion_state import CompanionState

    state = CompanionState()
    state.add_pending_topic("聊聊周末计划")
    assert len(state.pending_topics) == 1
    assert state.pending_topics[0].topic == "聊聊周末计划"


def test_complete_pending_topic_removes_from_list():
    from core.companion_state import CompanionState

    state = CompanionState()
    state.add_pending_topic("未完话题1")
    state.complete_pending_topic("未完话题1")
    assert len(state.pending_topics) == 0


# ── care_followup 到期 ────────────────────────────
def test_check_due_followups_returns_only_due():
    from core.companion_state import CompanionState

    state = CompanionState()
    now = time.time()
    state.schedule_care_followup("旧痛", due_at=now - 100)
    state.schedule_care_followup("新痛", due_at=now + 3600)
    due = state.check_due_followups()
    assert len(due) == 1
    assert due[0].topic == "旧痛"


# ── 持久化 ────────────────────────────────────────
def test_persistence_save_and_reload_state_consistent(tmp_path, monkeypatch):
    from core.companion_state import CompanionState

    monkeypatch.setenv("AERIE_DATA_DIR", str(tmp_path))
    state = CompanionState()
    state.add_pain_point("痛点A")
    state.add_joy_point("乐点B")
    state.add_pending_topic("话题C")
    state.advance_relationship_stage()
    state.save()

    reloaded = CompanionState.load()
    assert reloaded.relationship_stage == state.relationship_stage
    assert len(reloaded.recent_pain_points) == 1
    assert reloaded.recent_pain_points[0].text == "痛点A"
    assert len(reloaded.recent_joy_points) == 1
    assert reloaded.recent_joy_points[0].text == "乐点B"
    assert len(reloaded.pending_topics) == 1
    assert reloaded.pending_topics[0].topic == "话题C"


def test_persistence_uses_aerie_data_dir(tmp_path, monkeypatch):
    from core.companion_state import CompanionState
    from core.paths import data_dir

    isolated = tmp_path / "runtime-data"
    monkeypatch.setenv("AERIE_DATA_DIR", str(isolated))

    state = CompanionState()
    state.add_pain_point("隔离测试")
    state.save()

    expected = isolated / "companion_state.json"
    assert data_dir() == isolated
    assert expected.is_file()
    # 不应写入仓库默认 data 目录
    repo_state = (
        __import__("pathlib").Path(__file__).resolve().parent.parent
        / "data"
        / "companion_state.json"
    )
    assert not repo_state.exists()


# ── relationship_stage 转换 ───────────────────────
def test_relationship_stage_transitions():
    from core.companion_state import CompanionState

    state = CompanionState()
    assert state.relationship_stage == "stranger"
    state.advance_relationship_stage()
    assert state.relationship_stage == "acquaintance"
    state.advance_relationship_stage()
    assert state.relationship_stage == "familiar"
    state.advance_relationship_stage()
    assert state.relationship_stage == "close"
    state.advance_relationship_stage()
    assert state.relationship_stage == "intimate"
    # 顶阶后再 advance 保持 intimate
    state.advance_relationship_stage()
    assert state.relationship_stage == "intimate"


def test_set_relationship_stage_invalid_raises():
    from core.companion_state import CompanionState

    state = CompanionState()
    with pytest.raises(ValueError):
        state.set_relationship_stage("not_a_stage")


# ── 最大数量限制 ──────────────────────────────────
def test_recent_pain_points_limited_to_ten():
    from core.companion_state import CompanionState

    state = CompanionState()
    for i in range(15):
        state.add_pain_point(f"痛点{i}")
    assert len(state.recent_pain_points) == 10
    # 保留最近 10 条 (即 痛点5..痛点14)
    assert state.recent_pain_points[0].text == "痛点5"
    assert state.recent_pain_points[-1].text == "痛点14"


def test_recent_joy_points_limited_to_ten():
    from core.companion_state import CompanionState

    state = CompanionState()
    for i in range(15):
        state.add_joy_point(f"乐点{i}")
    assert len(state.recent_joy_points) == 10
    assert state.recent_joy_points[0].text == "乐点5"
    assert state.recent_joy_points[-1].text == "乐点14"
