"""聊天要图：**主体**（拍什么）与形态（特写/她的视角）的完整契约。

背景（真机事故 2026-09-29 00:24）
--------------------------------
用户说：「嗯？这头发多顺滑呀，衣柜上，我送你的小挂件还在那儿吗？发张照片给我看看」
期望：一张**衣柜上那个挂件**的照片（主角是物）。
实际：她的**自拍**（主角是人）。而且她的文字是对的（"我对着衣柜拍一张 你找找看"），
说明"听懂"没坏，坏的是出图。

两处根因，本文件逐条钉住：

1. **路由**：`role_selfie` 词表里混着通用短语"照片给我"，被"发张照片给我看看"命中，
   于是关键词层直接返回 ok、**语义层根本没被调用** —— 而语义层早就认得
   `environment_object`（它的示例就是"看看你厨房"）。
2. **主体无处安放**：组合器的可组合维度全是围绕人的（部位/姿态/机位/…），
   而 `environment_object` 取画面内容的来源只有世界话题（`world_visual:<topic>`）；
   聊天要图的 reason_code 是 `user_requested`、不带话题，所以用户那句"衣柜上的挂件"
   **永远进不了提示词**，只能退化成空镜或人物照。
"""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.image_service import VisualIntentRouter

# ── 1 · 路由：通用出图短语不再越权决定主体 ─────────────────────────────


def test_generic_photo_phrase_does_not_pick_a_subject():
    """「发张照片给我看看」说不出要拍什么 → 必须交给语义层，不能自己挑主体。

    修复前：命中 role_selfie 的"照片给我" → status=ok → 语义层被跳过 → 判成自拍。
    """
    routed = VisualIntentRouter().route(
        prompt="嗯？这头发多顺滑呀，衣柜上，我送你的小挂件还在那儿吗？发张照片给我看看",
    )

    assert routed["status"] == "needs_clarification"
    assert routed["reason"] == "generic_photo_request"
    assert routed["visual_intent"] == "unknown"


def test_generic_phrase_alone_still_needs_clarification():
    for phrase in ("发张照片给我看看", "拍张照我瞅瞅", "帮我拍一张", "照片给我"):
        routed = VisualIntentRouter().route(prompt=phrase)
        assert routed["status"] == "needs_clarification", phrase
        assert routed["reason"] == "generic_photo_request", phrase


def test_subject_bearing_keywords_still_decide_directly():
    """带主体的关键词不受影响：命中即定意图，不必多花一次 LLM。"""
    router = VisualIntentRouter()

    selfie = router.route(prompt="发张你的自拍")
    assert selfie["status"] == "ok"
    assert selfie["visual_intent"] == "role_selfie"

    object_shot = router.route(prompt="拍一下桌上的西瓜")
    assert object_shot["status"] == "ok"
    assert object_shot["visual_intent"] == "environment_object"

    couple = router.route(prompt="我们合照一张")
    assert couple["visual_intent"] == "couple_photo"


def test_no_signal_at_all_reports_no_keywords():
    routed = VisualIntentRouter().route(prompt="今天天气不错")
    assert routed["status"] == "needs_clarification"
    assert routed["reason"] == "no_intent_keywords_matched"


# ── 2 · 语义层：把「拍什么」与「哪种形态」一起读出来 ──────────────────


def _brain_returning(text: str):
    return SimpleNamespace(chat=AsyncMock(return_value=SimpleNamespace(text=text)))


def _pipeline_for_judge():
    from core.pipeline import Pipeline

    pipe = Pipeline.__new__(Pipeline)
    pipe._strip_think = lambda value: value
    return pipe


def test_judge_reads_subject_and_form():
    """用户原话 → 主体是"衣柜上那个挂件"，形态是特写（他要确认东西还在不在）。"""
    pipe = _pipeline_for_judge()
    brain = _brain_returning(json.dumps({
        "visual_intent": "environment_object",
        "subject": "衣柜上挂着的小挂件",
        "subject_form": "closeup",
    }))

    request = asyncio.run(
        pipe._run_photo_judge(brain, "judge-prompt", "衣柜上的挂件还在吗", label="test")
    )

    assert request.intent == "environment_object"
    assert request.subject == "衣柜上挂着的小挂件"
    assert request.subject_form == "closeup"


def test_judge_accepts_legacy_payload_without_subject():
    """老格式（只有 visual_intent）仍要解析成功 —— 少一个字段不等于"没有诉求"。"""
    pipe = _pipeline_for_judge()
    brain = _brain_returning('{"visual_intent": "role_selfie"}')

    request = asyncio.run(
        pipe._run_photo_judge(brain, "judge-prompt", "看看你", label="test")
    )

    assert request.intent == "role_selfie"
    assert request.subject == ""
    assert request.subject_form == "closeup"


def test_judge_parses_wrapped_json_with_prose():
    """模型偶尔在 JSON 外面裹一层说明 —— 逐字段正则兜底，不能整条丢掉。"""
    pipe = _pipeline_for_judge()
    brain = _brain_returning(
        '好的，判断如下：\n{"visual_intent": "environment_object", '
        '"subject": "窗外的雨", "subject_form": "pov"}\n以上。'
    )

    request = asyncio.run(
        pipe._run_photo_judge(brain, "judge-prompt", "拍一下窗外的雨", label="test")
    )

    assert request.intent == "environment_object"
    assert request.subject == "窗外的雨"
    assert request.subject_form == "pov"


def test_judge_rejects_unknown_form_and_garbage():
    pipe = _pipeline_for_judge()

    weird = asyncio.run(pipe._run_photo_judge(
        _brain_returning('{"visual_intent": "environment_object", "subject_form": "x"}'),
        "p", "text", label="test",
    ))
    assert weird.subject_form == "closeup"

    garbage = asyncio.run(pipe._run_photo_judge(
        _brain_returning("我不知道"), "p", "text", label="test",
    ))
    assert garbage.intent == ""
    assert not garbage


def test_photo_request_truthiness():
    from core.pipeline import PhotoRequest

    assert not PhotoRequest()
    assert PhotoRequest(intent="role_selfie")
    # 只有主体没有意图 = 不是出图诉求（意图才是开关）
    assert not PhotoRequest(subject="衣柜")


def test_judge_needs_brain():
    """brain 不可用时返回空诉求，不抛异常。"""
    from core.pipeline import PhotoRequest

    pipe = _pipeline_for_judge()
    assert asyncio.run(pipe._judge_photo_request("衣柜上的挂件还在吗")) == PhotoRequest()
    assert asyncio.run(pipe._judge_reply_photo_request("我对着衣柜拍一张")) == PhotoRequest()


# ── 3 · 主体必须穿过三道显式白名单 ─────────────────────────────────────
#
# 2026-09-28 已踩过一次同款坑：白名单漏字段 = 静默丢弃。这里把 subject 也钉住。


def _candidate_with_subject() -> dict:
    return {
        "candidate_id": "c-wardrobe",
        "idempotency_key": "k-wardrobe",
        "scene": "local_send",
        "channel": "local_chat",
        "prompt_key": "environment_object",
        "subject": "衣柜上挂着的小挂件",
        "subject_form": "closeup",
    }


def test_inprocess_redaction_keeps_subject():
    from core.world_port import redact_image_candidate

    public = redact_image_candidate(_candidate_with_subject())
    assert public["subject"] == "衣柜上挂着的小挂件"
    assert public["subject_form"] == "closeup"


def test_sidecar_redaction_keeps_subject():
    from world_service.storage.sqlite_store import _image_candidate_payload

    public = _image_candidate_payload(_candidate_with_subject())
    assert public["subject"] == "衣柜上挂着的小挂件"
    assert public["subject_form"] == "closeup"


def test_candidate_reconstruction_keeps_subject():
    from core.world_image_candidates import WorldImageCandidateConsumer

    consumer = WorldImageCandidateConsumer(
        feature_flags=SimpleNamespace(is_enabled=lambda _n: True),
        image_workflow=None,
    )
    event = SimpleNamespace(
        event_type="world.image_candidate.published",
        topic="",
        event_id="e-1",
        occurred_at="2026-09-29T00:24:00+08:00",
        payload=_candidate_with_subject(),
    )

    candidate = consumer._candidate_from_event(event)

    assert candidate is not None
    assert candidate["subject"] == "衣柜上挂着的小挂件"
    assert candidate["subject_form"] == "closeup"


# ── 4 · 组合器：物件照真的以"那个东西"为主角 ──────────────────────────


def _compose(prompt_key: str, candidate: dict) -> str:
    from core.companion import Companion

    comp = Companion.__new__(Companion)
    return comp._compose_base_image_prompt(prompt_key, candidate)


def test_closeup_object_prompt_names_the_subject_and_excludes_her():
    """特写形态：点明主体 + 明确不许出现人物（否则模型默认把人画进去）。"""
    prompt = _compose(
        "environment_object",
        {"subject": "衣柜上挂着的小挂件", "subject_form": "closeup", "size": "1344x768"},
    )

    assert "衣柜上挂着的小挂件" in prompt
    assert "画面主角是" in prompt
    assert "不出现人物" in prompt
    # 不得把人物外貌写进去（那会把画面拉回"她"）
    assert "银灰色长发" not in prompt
    assert "28岁的中国女性" not in prompt


def test_pov_object_prompt_keeps_first_person_view():
    prompt = _compose(
        "environment_object",
        {"subject": "窗外的雨", "subject_form": "pov", "size": "1344x768"},
    )

    assert "窗外的雨" in prompt
    assert "第一人称视角" in prompt


# ── 5 · 接力重写：不许把主体"顺手改写"掉 ──────────────────────────────
#
# 真机事故（2026-09-29 00:54:21）：同一条链路，00:56:27 保住了「你床头柜」，
# 00:54:21 却把它写成了「她工作台前的一角」——差别只在那一轮走了 LLM 接力。
# 接力的 system prompt 当时只声明"保留人物外貌/身材/风格/画幅/拍摄手法"，
# 对"主体（物件）"一字未提，于是模型按世界上下文自由发挥，主体丢失。
# 修法：显式告知 + 出口校验，校验不过退回确定性兜底。

_SUBJECT = "你床头柜上摆的东西"


class _RelayBrain:
    """假 brain：按预设文本返回，用来模拟接力模型的输出。"""

    def __init__(self, text: str) -> None:
        self.text = text
        self.messages: list[dict] | None = None

    async def chat(self, messages, **kwargs):
        self.messages = messages
        text = self.text

        class _Resp:
            pass

        resp = _Resp()
        resp.text = text
        return resp


def _relay_context() -> dict:
    return {
        "prompt_key": "environment_object",
        "time_of_day_light": "深夜，屋内暖灯亮着",
        "outdoor": False,
        "city": "重庆",
    }


def _relay_candidate() -> dict:
    return {
        "prompt_key": "environment_object",
        "subject": _SUBJECT,
        "subject_form": "closeup",
    }


def _relay_comp(relay_text: str, monkeypatch):
    from core.companion import Companion

    monkeypatch.setattr("core.companion._image_light_preference", lambda: (None, None))
    comp = Companion.__new__(Companion)
    brain = _RelayBrain(relay_text)
    comp.brain = brain
    return comp, brain


def test_relay_rejects_output_that_dropped_the_subject(monkeypatch):
    """接力把主体改写成"工作台前的一角" → 判定不合格，退回确定性兜底。"""
    dropped = (
        "一张写实真实感照片，竖构图，近距离取景，画面主角是她工作台前的一角，"
        "细节清晰可辨。这是她用手机在深夜拍下来给恋人确认的一角，画面自然、生活化。"
    )
    comp, _brain = _relay_comp(dropped, monkeypatch)

    refined = asyncio.run(
        comp._light_relay_refine_prompt(
            "一张写实真实感照片，画面主角是你床头柜上摆的东西，细节清晰可辨。",
            _relay_context(),
            _relay_candidate(),
        )
    )

    assert refined is None


def test_relay_accepts_output_that_keeps_the_subject(monkeypatch):
    kept = (
        "一张写实真实感照片，竖构图，近距离取景，画面主角是你床头柜上摆的东西，"
        "细节清晰可辨，暖灯下的材质纹理真实。画面中不出现人物。"
    )
    comp, _brain = _relay_comp(kept, monkeypatch)

    refined = asyncio.run(
        comp._light_relay_refine_prompt(
            "一张写实真实感照片，画面主角是你床头柜上摆的东西，细节清晰可辨。",
            _relay_context(),
            _relay_candidate(),
        )
    )

    assert refined == kept


def test_relay_prompt_declares_subject_as_hard_constraint(monkeypatch):
    """光校验不够：接力 prompt 必须显式点名主体是"不可改"的。"""
    comp, brain = _relay_comp(
        "一张写实真实感照片，画面主角是你床头柜上摆的东西，细节清晰。",
        monkeypatch,
    )

    asyncio.run(
        comp._light_relay_refine_prompt(
            "一张写实真实感照片，画面主角是你床头柜上摆的东西。",
            _relay_context(),
            _relay_candidate(),
        )
    )

    user_msg = str(brain.messages[1]["content"])
    assert _SUBJECT in user_msg
    assert "主体不可改" in user_msg


def test_subject_survives_when_relay_drops_it(monkeypatch):
    """端到端口径（§14.6 #66）：接力吞掉主体时，最终提示词里主体必须还在。"""
    comp, _brain = _relay_comp(
        "一张写实真实感照片，竖构图，画面主角是她工作台前的一角，暖灯下材质清晰。",
        monkeypatch,
    )
    candidate = _relay_candidate()
    context = _relay_context()
    base = comp._compose_base_image_prompt("environment_object", candidate)

    refined = asyncio.run(comp._light_relay_refine_prompt(base, context, candidate))
    prompt = refined or comp._inject_world_context_fallback(base, context, candidate)

    assert _SUBJECT in prompt
    assert "工作台" not in prompt


def test_object_prompt_without_subject_keeps_world_topic_fallback():
    """主动发图/世界话题那条路（没有 subject）行为不变。"""
    prompt = _compose(
        "environment_object",
        {"reason_code": "world_visual:reading_time", "size": "1344x768"},
    )

    assert "随手拍下眼前的一角" in prompt


# ── 5 · 提示词干跑闸门（审计用，不真出图） ────────────────────────────


def test_dryrun_flag_reads_env(monkeypatch):
    from core.world_image_candidates import prompt_dryrun_enabled

    monkeypatch.delenv("AERIE_PHOTO_PROMPT_DRYRUN", raising=False)
    assert prompt_dryrun_enabled() is False
    for value in ("1", "true", "yes", "TRUE"):
        monkeypatch.setenv("AERIE_PHOTO_PROMPT_DRYRUN", value)
        assert prompt_dryrun_enabled() is True, value
    monkeypatch.setenv("AERIE_PHOTO_PROMPT_DRYRUN", "0")
    assert prompt_dryrun_enabled() is False


def test_dryrun_stops_before_provider(tmp_path, monkeypatch):
    """置位后：拿到提示词就返回 dry_run —— 不判重、不调 provider。"""
    from core.world_image_candidates import WorldImageCandidateConsumer

    monkeypatch.setenv("AERIE_PHOTO_PROMPT_DRYRUN", "1")
    monkeypatch.setattr("core.paths.project_root", lambda: tmp_path)

    calls: list[str] = []
    consumer = WorldImageCandidateConsumer(
        feature_flags=SimpleNamespace(is_enabled=lambda _n: True),
        image_workflow=SimpleNamespace(
            generate_image=MagicMock(side_effect=AssertionError("provider must not run")),
        ),
        prompt_resolver=lambda key, cand: calls.append(key) or "组好的提示词原文",
    )

    result = asyncio.run(consumer._run_workflow({
        "prompt_key": "environment_object",
        "subject": "衣柜上挂着的小挂件",
        "subject_form": "closeup",
        "idempotency_key": "k",
    }))

    assert result["status"] == "dry_run"
    assert result["side_effects"]["provider_called"] is False
    assert calls == ["environment_object"]

    dumped = (tmp_path / "logs" / "photo_prompt_dryrun.log").read_text(encoding="utf-8")
    assert "组好的提示词原文" in dumped
    assert "衣柜上挂着的小挂件" in dumped


def test_workflow_status_detects_dry_run():
    from core.pipeline import _workflow_status_of

    # 真实 publish 结果：顶层 status 已被归约为 completed/failed，
    # 具体终态（dry_run）只在 consumed 明细里 → 必须能从明细里认出来。
    assert _workflow_status_of({"consumed": [{"status": "dry_run"}]}) == "dry_run"
    assert _workflow_status_of({
        "status": "failed", "reason": "prompt_dryrun",
        "consumed": [{"status": "dry_run"}],
    }) == "dry_run"
    assert _workflow_status_of({
        "status": "failed", "consumed": [{"status": "failed"}],
    }) == "failed"
    assert _workflow_status_of({"status": "completed"}) == "completed"
    assert _workflow_status_of(None) == ""


def test_pending_bubble_not_marked_failed_on_dryrun():
    """干跑不是失败：占位气泡不能弹"图片这次没发出来"+重发按钮。"""
    from core.pipeline import Pipeline

    pipe = Pipeline.__new__(Pipeline)
    # request_state=None 时 _event_contract 会解引用失败（真实代码里被 except 吞掉），
    # 这里直接桩掉，让断言只看"占位气泡被推成什么状态"。
    pipe._event_contract = lambda *a, **k: {}
    emitted: list[dict] = []

    import core.pipeline as pipeline_module

    original = pipeline_module.emit
    pipeline_module.emit = lambda *a, **k: emitted.append(k)
    try:
        pipe._emit_photo_pending_result(
            SimpleNamespace(user_id=1, source="local", content="发张照片给我看看"),
            None,
            "pending-1",
            {"status": "failed", "reason": "prompt_dryrun", "consumed": [{"status": "dry_run"}]},
        )
    finally:
        pipeline_module.emit = original

    assert emitted and emitted[0]["status"] == "ready"
    assert emitted[0]["retry_text"] == ""


# ── 6 · 干跑终态不得被归约成 failed（§十四 #65） ───────────────────────


def test_summarize_image_delivery_passes_dry_run_through():
    """`[ChatPhoto] delivered status=%s reason=prompt_dryrun` 里的 status
    不能再是 failed —— 归约层要把非失败终态原样传出。"""
    from core.companion import Companion

    summarize = Companion._summarize_image_delivery

    assert summarize([{"status": "dry_run", "reason": "prompt_dryrun"}]) == (
        "dry_run", "prompt_dryrun", "",
    )
    assert summarize([{"status": "workflow_disabled"}])[0] == "workflow_disabled"
    assert summarize([{"status": "dedup_skipped"}])[0] == "dedup_skipped"


def test_summarize_image_delivery_still_fails_loudly():
    """真正的失败不能被放过，完成态仍优先于一切。"""
    from core.companion import Companion

    summarize = Companion._summarize_image_delivery

    assert summarize([]) == ("failed", "not_consumed", "")
    assert summarize([{"status": "failed", "reason": "workflow_error"}]) == (
        "failed", "workflow_error", "",
    )
    assert summarize([{"status": "dry_run"}, {"status": "completed", "image_path": "a.png"}]) == (
        "completed", "", "a.png",
    )
