"""Tests for core.persona_hub.persona_generator — 人设 AI 智能生成器.

Covers the 5-stage generation pipeline (concept → detail → assemble → prompt →
finalize), its deterministic fallback path, task storage, and the HTTP API
wrapper (POST /api/persona/hub/generate).

Isolation: every test redirects AERIE_DATA_DIR to a fresh temp directory and
resets the PersonaManager singleton before running, so nothing is ever written
to the real data/ directory. api_server (optional API test) is imported only
after the temp env + singleton reset so its import-time get_persona_manager()
binds to a temp dir.
"""

from __future__ import annotations

import asyncio
import copy
import os
import re
import shutil
import tempfile
import time

import pytest

from core.persona_hub.persona_generator import (
    PersonaGenerator,
    _prompt_user_text,
    build_minimal_skeleton,
    build_skeleton,
    create_generation_task,
    extract_json,
    fallback_story_concepts,
    get_generation_task,
    merge_into_skeleton,
    neutralize_skeleton_for_generation,
    recommend_story_concepts,
    sanitize_id,
)
from core.persona_hub.persona_manager import PersonaManager, get_persona_manager
from core.persona_hub.persona_validator import PersonaValidator

_ID_PATTERN = re.compile(r"^[a-z0-9_-]{2,64}$")

# ── Data-dir isolation (never touch the real data/) ──────────
_ORIG_INSTANCE = getattr(PersonaManager, "_instance", None)
_ORIG_DATA_DIR = os.environ.get("AERIE_DATA_DIR")
_PG_TMP = tempfile.mkdtemp(prefix="aerie-pg-test-")
os.environ["AERIE_DATA_DIR"] = _PG_TMP
PersonaManager._instance = None  # next get_persona_manager() uses a temp dir


def _restore_pg_state() -> None:
    """Put the singleton + AERIE_DATA_DIR back to their pre-module values."""
    PersonaManager._instance = _ORIG_INSTANCE
    if _ORIG_DATA_DIR is None:
        os.environ.pop("AERIE_DATA_DIR", None)
    else:
        os.environ["AERIE_DATA_DIR"] = _ORIG_DATA_DIR


@pytest.fixture(autouse=True)
def _pg_isolated(tmp_path):
    """Point the PersonaManager singleton + AERIE_DATA_DIR at a temp dir."""
    PersonaManager._instance = None
    os.environ["AERIE_DATA_DIR"] = str(tmp_path)
    yield
    _restore_pg_state()


@pytest.fixture(scope="module", autouse=True)
def _pg_tmpdir_cleanup():
    """Remove the module-level temp dir used by the optional api_server import."""
    yield
    shutil.rmtree(_PG_TMP, ignore_errors=True)


# ── Optional API coverage ───────────────────────────────────
# Import api_server AFTER the temp-dir env + singleton reset above so its
# import-time get_persona_manager() binds to the temp dir. If the import is
# impossible in this environment, the API test is skipped instead of failing.
try:
    from fastapi.testclient import TestClient  # noqa: E402

    import core.api_server as api_server  # noqa: E402

    _API_AVAILABLE = True
    _API_IMPORT_ERROR: Exception | None = None
except Exception as _api_import_err:  # pragma: no cover - environment dependent
    _API_AVAILABLE = False
    _API_IMPORT_ERROR = _api_import_err


# ══════════════════════════════════════════════════════════
# 1. extract_json
# ══════════════════════════════════════════════════════════

def test_extract_json_pure_dict():
    data = extract_json('{"name": "小伊", "age": 25}')
    assert data == {"name": "小伊", "age": 25}


def test_extract_json_wrapped_in_prose():
    text = '解析结果如下：\n{"name": "星野", "age": 22}\n请确认。'
    data = extract_json(text)
    assert data == {"name": "星野", "age": 22}


def test_extract_json_garbage_returns_none():
    assert extract_json("这根本不是 JSON 内容") is None


def test_extract_json_empty_returns_none():
    assert extract_json("") is None
    assert extract_json("   ") is None


# ══════════════════════════════════════════════════════════
# 2. sanitize_id
# ══════════════════════════════════════════════════════════

def test_sanitize_id_chinese_falls_back():
    assert _ID_PATTERN.match(sanitize_id("伊塔"))
    assert sanitize_id("伊塔") == "custom"


def test_sanitize_id_cleans_special_chars():
    cleaned = sanitize_id("My Character!")
    assert _ID_PATTERN.match(cleaned), f"非法 id: {cleaned}"
    assert cleaned == "my-character"


def test_sanitize_id_short_kept():
    assert sanitize_id("ab") == "ab"
    assert _ID_PATTERN.match(sanitize_id("ab"))


def test_sanitize_id_empty_uses_fallback():
    assert sanitize_id("") == "custom"
    assert sanitize_id("   ") == "custom"
    assert sanitize_id("", fallback="default_id") == "default_id"


# ══════════════════════════════════════════════════════════
# 3. skeleton builders
# ══════════════════════════════════════════════════════════

def test_build_skeleton_has_system_level_fields():
    skeleton = build_skeleton()
    assert skeleton is not None
    assert isinstance(skeleton, dict)
    for key in (
        "emotion", "desire", "behavior", "capabilities",
        "decision_weights", "cognition_visibility",
    ):
        assert key in skeleton, f"skeleton 缺少系统级字段 {key}"


def test_build_minimal_skeleton_has_recall_and_fields():
    minimal = build_minimal_skeleton()
    assert minimal is not None
    assert isinstance(minimal, dict)
    # 预设骨架文件（yita_default.json）本身没有顶层 recall/mbti，
    # 生成阶段 finalize 会从 minimal 骨架补齐，因此在 minimal 上断言 recall。
    assert "recall" in minimal
    for key in ("emotion", "desire", "behavior", "capabilities", "cognition_visibility"):
        assert key in minimal, f"minimal skeleton 缺少字段 {key}"


# ══════════════════════════════════════════════════════════
# 4. merge_into_skeleton
# ══════════════════════════════════════════════════════════

def test_merge_into_skeleton_overlays_partial_only():
    skeleton = build_skeleton()
    assert skeleton is not None
    partial = {"basic": {"name": "新角色"}, "appearance": {"hair": "银发"}}
    merged = merge_into_skeleton(partial, skeleton)

    # partial 覆盖 basic.name / appearance.hair
    assert merged["basic"]["name"] == "新角色"
    assert merged["appearance"]["hair"] == "银发"
    # skeleton 的系统级字段保持骨架默认，不被 partial 清空
    assert merged["emotion"]["thresholds"]
    assert merged["behavior"]["proactivity_level"] == skeleton["behavior"]["proactivity_level"]
    assert merged["desire"]["variables"]
    # 原 skeleton 未被修改
    assert skeleton["basic"]["name"] == "伊塔"
    assert skeleton["appearance"]["hair"] != "银发"


def test_neutralize_skeleton_strips_yita_identity():
    """A brand-new persona must NOT inherit Yita's physical stats/appearance."""
    skeleton = build_skeleton()
    assert skeleton is not None
    # skeleton carries Yita's own body data
    assert skeleton["basic"].get("height_cm") == 184

    neutral = neutralize_skeleton_for_generation(skeleton)
    # physical stats removed
    for key in ("height_cm", "weight_kg", "measurements", "cup_size", "body_fat_pct", "body_type"):
        assert key not in neutral["basic"]
    # identity/career/tagline removed (must never leak "伊塔")
    for key in ("name", "english_name", "occupation", "one_liner"):
        assert key not in neutral["basic"]
    for key in ("name", "id", "description"):
        assert key not in neutral
    # appearance is neutral, not Yita's silver hair
    assert neutral["appearance"]["hair"] != skeleton["appearance"]["hair"]
    # relationship story / Yita's speech examples dropped
    assert "story" not in neutral["relationship"]
    assert "speech_examples" not in neutral
    # system-level fields survive neutralization
    assert neutral["emotion"]["thresholds"]
    assert neutral["behavior"]["proactivity_level"] == skeleton["behavior"]["proactivity_level"]
    assert neutral["desire"]["variables"]
    # original skeleton untouched
    assert skeleton["basic"].get("height_cm") == 184


def test_fallback_story_concepts_returns_pool():
    concepts = fallback_story_concepts("恋人", "她是我在深夜加班时认识的人")
    assert isinstance(concepts, list) and len(concepts) <= 5
    assert concepts[0]["title"] == "以你为准"  # seed-derived concept first
    assert concepts[0]["tagline"] == "她是我在深夜加班时认识的人"
    for c in concepts:
        assert c["title"] and c["tagline"]
        assert isinstance(c["tags"], list)


def test_generate_injects_selected_story_concept(monkeypatch):
    """The user-picked story concept must flow into the generated persona."""
    monkeypatch.setenv("AERIE_DISABLE_MODEL_CALLS", "1")

    async def _drive():
        return await PersonaGenerator().generate(
            "温柔的职业女性",
            {
                "story_concept": {
                    "title": "双向救赎",
                    "tagline": "在彼此最低谷时相遇，她先伸出了手",
                    "tags": ["#救赎"],
                }
            },
        )

    persona = asyncio.run(_drive())
    story = persona["relationship"]["story"]
    assert "双向救赎" in story or "在彼此最低谷时相遇" in story


def test_recommend_story_concepts_fallback_without_llm(monkeypatch):
    """recommend_story_concepts returns the preset pool when the LLM is off."""
    monkeypatch.setenv("AERIE_DISABLE_MODEL_CALLS", "1")

    async def _drive():
        return await recommend_story_concepts("恋人", "深夜加班认识")

    concepts = asyncio.run(_drive())
    assert concepts and concepts[0]["title"] == "以你为准"


# ══════════════════════════════════════════════════════════
# 5. deterministic fallback path (AERIE_DISABLE_MODEL_CALLS=1)
# ══════════════════════════════════════════════════════════

def test_fallback_path_when_llm_disabled(monkeypatch):
    monkeypatch.setenv("AERIE_DISABLE_MODEL_CALLS", "1")

    async def _drive():
        return await PersonaGenerator().generate(
            "银发红瞳的温柔御姐设计师，是我的恋人，占有欲强但很宠我",
            {"name": "小伊"},
        )

    result = asyncio.run(_drive())

    ok, errors = PersonaValidator.validate(result)
    assert ok, f"兜底人设未通过校验: {errors}"
    assert _ID_PATTERN.match(result["id"]), f"非法 id: {result['id']}"
    assert result["is_builtin"] is False
    assert result["basic"]["name"] == "小伊"
    sp = result["prompt_overrides"]["system_prompt"]
    assert "屏幕隔空铁律" in sp and "消息结构约定" in sp
    assert result["emotion"]["thresholds"], "emotion.thresholds 不应为空"
    assert isinstance(result["behavior"]["proactivity_level"], (int, float))
    assert result["recall"], "recall 应存在且非空"


# ══════════════════════════════════════════════════════════
# 6. LLM success path (subclass with fake LLM results)
# ══════════════════════════════════════════════════════════

_CONCEPT_DICT = {
    "name": "星野",
    "english_name": "Hoshino",
    "age": 22,
    "occupation": "占星师",
    "one_liner": "一个能看到星星未来的占星师。",
    "personality_archetype": "温柔知性",
    "core_tags": ["#温柔", "#知性"],
    "big_five": {
        "extraversion": 0.5,
        "agreeableness": 0.8,
        "neuroticism": 0.4,
        "openness": 0.7,
        "conscientiousness": 0.6,
    },
    "mbti": "INFJ",
    "gender": "female",
}

_DETAIL_DICT = {
    "appearance": {
        "hair": "银白色长发",
        "eyes": "星空般紫色",
        "marks": [],
        "skin": "白皙",
    },
    "personality": {
        "cores": [{"name": "温柔", "en": "Gentle", "desc": "对重要的人永远轻声细语"}],
        "values": [],
        "speech_style": "温柔安静，轻声细语",
        "core_tags": ["#温柔"],
    },
    "relationship": {
        "relationship_type": "恋人",
        "style": "温柔守护",
        "user_address_default": "你",
        "user_intimate_terms": ["宝贝"],
        "story": "三年前她在天文台遇见了他……",
    },
    "speech_examples": {
        "phrases": ["今晚星星很好看。", "我想你了。"],
        "long_examples": ["夜深了，但想到你，我舍不得睡。"],
    },
}


class FakeGenerator(PersonaGenerator):
    """Stub LLM: returns fixed concept/detail dicts and a fixed prompt body."""

    async def _llm_json(self, system_prompt_text, user_text, llm):
        if "one_liner" in system_prompt_text:
            return copy.deepcopy(_CONCEPT_DICT)
        if "appearance" in system_prompt_text:
            return copy.deepcopy(_DETAIL_DICT)
        return None

    async def _llm_text(self, system_prompt_text, user_text, llm):
        return "我是星野（Hoshino），22岁，占星师。我能看到星星的未来，却只想看清你的现在。"


def test_llm_success_path_builds_full_persona():
    async def _drive():
        return await FakeGenerator().generate("星野 温柔占星师 恋人")

    result = asyncio.run(_drive())

    ok, errors = PersonaValidator.validate(result)
    assert ok, f"LLM 路径生成结果未通过校验: {errors}"
    assert result["basic"]["name"] == "星野"
    assert result["appearance"]["hair"] == "银白色长发"
    assert "天文台" in result["relationship"]["story"]
    sp = result["prompt_overrides"]["system_prompt"]
    assert "屏幕隔空铁律" in sp and "消息结构约定" in sp
    # 第一人称自洽：角色=名字，用户=你（杜绝"你是塞纳。我是店员"式人称断裂）
    assert sp.startswith("我是星野（Hoshino）")


def test_generate_never_leaks_yita_identity():
    """"伊塔" must never leak into a generated persona's name or system prompt."""
    async def _drive():
        return await FakeGenerator().generate("星野 温柔占星师 恋人")

    result = asyncio.run(_drive())
    assert result["basic"]["name"] == "星野"
    assert result["name"] == "星野"
    assert result["description"] != "温柔大姐姐+病娇·直球版"
    sp = result["prompt_overrides"]["system_prompt"]
    assert "伊塔" not in sp
    assert "Ita" not in sp
    assert sp.startswith("我是星野（Hoshino）")


def test_prompt_user_text_injects_user_name():
    """The user's nickname must reach the prompt-writer LLM and be marked
    as the user (你), never confused with the character name."""
    text = _prompt_user_text(
        {"basic": {"name": "塞纳"}},
        "固定规则",
        "阿明",
    )
    assert "阿明" in text
    assert "用户的称呼" in text
    assert "basic.name" in text
    # empty user_name → no extra hint appended
    text2 = _prompt_user_text({"basic": {"name": "塞纳"}}, "固定规则")
    assert "用户的称呼" not in text2


# ══════════════════════════════════════════════════════════
# 7. generation task storage
# ══════════════════════════════════════════════════════════

def test_generation_task_end_to_end(monkeypatch):
    monkeypatch.setenv("AERIE_DISABLE_MODEL_CALLS", "1")

    async def _drive():
        tid = create_generation_task("测试角色描述", {})
        task = None
        for _ in range(200):
            task = get_generation_task(tid)
            if task and task["state"] in ("done", "error"):
                break
            await asyncio.sleep(0.05)
        return task

    task = asyncio.run(_drive())

    assert task is not None, "生成任务未出现"
    assert task["state"] == "done", f"生成任务失败: {task.get('error')}"
    assert task["persona_id"], "persona_id 不应为空"
    assert task["persona"], "persona 不应为空"
    ok, errors = PersonaValidator.validate(task["persona"])
    assert ok, f"任务产出人设未通过校验: {errors}"
    assert task["progress"] == 100


# ══════════════════════════════════════════════════════════
# 8. HTTP API wrapper (optional)
# ══════════════════════════════════════════════════════════

@pytest.mark.skipif(
    not _API_AVAILABLE,
    reason=f"api_server 无法在当前环境导入: {_API_IMPORT_ERROR}",
)
def test_api_generate_endpoint(monkeypatch):
    monkeypatch.setenv("AERIE_DISABLE_MODEL_CALLS", "1")
    # 确保路由使用的 persona 管理器指向当前临时目录（防 import 顺序把单例绑到真实 data/）
    prev_mgr = api_server._persona_mgr
    api_server._persona_mgr = get_persona_manager()
    try:
        client = TestClient(api_server.app)

        resp = client.post(
            "/api/persona/hub/generate",
            json={"description": "测试描述", "options": {"name": "测试"}},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["status"] == "ok"
        task_id = payload["task_id"]
        assert task_id, "task_id 不应为空"

        task = None
        for _ in range(200):
            status_resp = client.get(f"/api/persona/hub/generate/{task_id}")
            assert status_resp.status_code == 200
            task = status_resp.json()["task"]
            if task["state"] in ("done", "error"):
                break
            time.sleep(0.05)

        assert task is not None, "API 生成任务未出现"
        assert task["state"] == "done", f"API 生成任务失败: {task.get('error')}"
        assert task["persona"], "API 生成的人设不应为空"
        ok, errors = PersonaValidator.validate(task["persona"])
        assert ok, f"API 生成人设未通过校验: {errors}"
    finally:
        api_server._persona_mgr = prev_mgr
