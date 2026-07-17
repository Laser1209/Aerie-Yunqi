"""Aerie · 云栖 v9.0 — Phase 9 Batch 8 E2E: Proactive Judge 综合判断全链路.

End-to-end smoke test for the 心情+想法+用户上下文 主动 push 决策。

Steps:
  1. ProactiveJudge 6 mock states — 覆盖 scene / tone / suppress 三类信号
  2. CronScheduler._dispatch — judge 抑制路径 (dispatcher 不被调)
  3. CronScheduler._dispatch — judge 通过路径 (tone_hint 透传)
  4. Brain.generate_push — tone_hint 解析 + 屏幕隔空铁律注入
  5. 端到端联调 — ProactiveJudge → _dispatch → 模拟 dispatcher 收到 tone

Pure local — 不依赖 LLM / DB / backend.

Usage:
  python e2e_proactive_judge.py
"""
from __future__ import annotations
import sys
# R7.5+: force UTF-8 on Windows (default GBK chokes on ✓/✗)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import asyncio
import sys
from typing import Any

from core.brain import TONE_PROMPTS, MOOD_TO_TONE
from core.proactive_judge import (
    ProactiveJudge,
    SCENE_THRESHOLDS,
    TONE_BY_DOMINANT,
    Decision,
)
from core.push_scheduler import CronScheduler, PushPolicy


# ── helpers ────────────────────────────────────────────────
def _check(label: str, ok: bool, detail: str = "") -> None:
    sym = "✓" if ok else "✗"
    suffix = f"  {detail}" if detail else ""
    print(f"  {sym} {label}{suffix}")


def _stage(name: str) -> None:
    print(f"\n── {name} ──")


# ══════════════════════════════════════════════════
# 6 mock state 矩阵 (覆盖 6 维主决策)
# ══════════════════════════════════════════════════
MOCK_STATES: list[dict[str, Any]] = [
    {
        "name": "深夜 23:30,desire 高 + 离线 5h → goodnight + longing 系 tone",
        "override": {
            "desire_score": 60.0,
            "emotion_score": 40.0,
            "context_score": 100.0,
            "environment_score": 35.0,
            "user_minutes_since_last": 300.0,
        },
        "scene": "goodnight",
        "expect_suppress_prefix": "",
        "expect_score_ge": 50,
    },
    {
        "name": "早晨 6:30,低欲望但环境加成 → morning_brief 通过",
        "override": {
            "desire_score": 10.0,
            "emotion_score": 50.0,
            "context_score": 50.0,
            "environment_score": 60.0,
            "user_minutes_since_last": 480.0,
        },
        "scene": "morning_brief",
        "expect_suppress_prefix": "",
        "expect_score_ge": 25,
    },
    {
        "name": "用户 1 分钟前刚发消息 → user_recent_active 抑制",
        "override": {
            "desire_score": 80.0,
            "emotion_score": 80.0,
            "context_score": 100.0,
            "environment_score": 50.0,
            "user_minutes_since_last": 1.0,
        },
        "scene": "idle_care",
        "expect_suppress_prefix": "user_recent_active",
        "expect_score_ge": 0,
    },
    {
        "name": "cooldown 还有 25 分钟 → cooldown_active 抑制",
        "override": {
            "desire_score": 80.0,
            "emotion_score": 60.0,
            "context_score": 80.0,
            "environment_score": 50.0,
            "cooldown_minutes_remaining": 25.0,
        },
        "scene": "idle_care",
        "expect_suppress_prefix": "cooldown_active",
        "expect_score_ge": 0,
    },
    {
        "name": "情绪爆发 (anxiety 满) → emotion_comfort + collapse_seeking",
        "override": {
            "desire_score": 50.0,
            "emotion_score": 90.0,
            "context_score": 50.0,
            "environment_score": 30.0,
            "force_tone": "collapse_seeking",
        },
        "scene": "emotion_comfort",
        "expect_suppress_prefix": "",
        "expect_tone": "collapse_seeking",
        "expect_score_ge": 50,
    },
    {
        "name": "voice_miss desire 80,context 80 → 通过 (score ≥ 50)",
        "override": {
            "desire_score": 80.0,
            "emotion_score": 60.0,
            "context_score": 80.0,
            "environment_score": 50.0,
        },
        "scene": "voice_miss",
        "expect_suppress_prefix": "",
        "expect_score_ge": 50,
    },
]


# ══════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════
def main() -> int:
    print("=" * 60)
    print("Phase 9 Batch 8 E2E — ProactiveJudge 全链路")
    print("=" * 60)
    passed = failed = 0

    def expect(name: str, ok: bool, detail: str = "") -> None:
        nonlocal passed, failed
        if ok:
            passed += 1
        else:
            failed += 1
        _check(name, ok, detail)

    judge = ProactiveJudge()

    # ── 1. 6 mock states ─────────────────────────────
    _stage("1. ProactiveJudge · 6 mock states")
    for i, case in enumerate(MOCK_STATES, 1):
        d = judge.evaluate(case["scene"], context_override=case["override"])
        prefix = case.get("expect_suppress_prefix", "")
        tone_expect = case.get("expect_tone")
        score_expect = case.get("expect_score_ge", 0)

        if prefix:
            ok = d.suppress_reason.startswith(prefix)
        else:
            ok = not d.suppress_reason.startswith("score_below_threshold")
        if tone_expect:
            ok = ok and d.tone == tone_expect
        if score_expect:
            ok = ok and d.score >= score_expect
        expect(
            f"case {i}: {case['name'][:48]}",
            ok,
            f"scene={d.scene} tone={d.tone} score={d.score} suppress={d.suppress_reason!r}",
        )

    # ── 2. Tone 矩阵完整性 ──────────────────────────
    _stage("2. TONE_BY_DOMINANT 矩阵完整")
    expected_keys = {
        "joy", "affection", "missing", "loneliness", "sadness", "stress",
        "neutral", "anger", "fear",
        "patience_eruption", "anxiety_eruption", "desire_eruption",
        "tenderness_eruption",
    }
    missing = expected_keys - set(TONE_BY_DOMINANT.keys())
    expect("TONE_BY_DOMINANT 13 键齐全", not missing, f"missing={missing}")
    # 同时 TONE_PROMPTS 也必须覆盖 tone 矩阵
    missing_p = set(TONE_BY_DOMINANT.values()) - set(TONE_PROMPTS.keys())
    expect("TONE_PROMPTS 覆盖所有 tone", not missing_p, f"missing={missing_p}")

    # ── 3. SCENE_THRESHOLDS 完整性 ───────────────────
    _stage("3. SCENE_THRESHOLDS 完整性")
    expect("SCENE_THRESHOLDS ≥ 8 个场景", len(SCENE_THRESHOLDS) >= 8,
           f"got {len(SCENE_THRESHOLDS)}")
    expect("morning_brief 阈值 = 30", SCENE_THRESHOLDS.get("morning_brief") == 30)
    expect("emotion_comfort 阈值 = 50", SCENE_THRESHOLDS.get("emotion_comfort") == 50)

    # ── 4. _dispatch · judge 抑制路径 ───────────────
    _stage("4. _dispatch · judge 抑制路径 (user_recent_active)")

    async def step4() -> None:
        nonlocal passed, failed
        cfg = {
            "proactive": {
                "enabled": True,
                "max_per_day": 5,
                "min_interval_min": 30,
                "quiet_start": "23:30",
                "quiet_end": "07:00",
                "exempt_scenes": ["morning_brief", "goodnight"],
            },
            "scenes": {
                "idle_care": {"template": "在干嘛。"},
            },
        }
        sched = CronScheduler(cfg)
        sched.judge = ProactiveJudge()

        called: list[tuple[str, dict]] = []

        async def mock_dispatch(scene: str, scene_cfg: dict) -> bool:
            called.append((scene, scene_cfg))
            return True

        sched.set_dispatcher(mock_dispatch)
        # 用户刚发消息 → judge 抑制
        result = await sched._dispatch(
            "idle_care",
            {
                "template": "在干嘛。",
                "judge_override": {
                    "desire_score": 80.0,
                    "emotion_score": 80.0,
                    "context_score": 100.0,
                    "environment_score": 50.0,
                    "user_minutes_since_last": 1.0,
                },
            },
        )
        expect("_dispatch 返回 False (被抑制)", result is False, f"got {result}")
        expect("dispatcher 未被调用", len(called) == 0, f"called={len(called)}")
        expect(
            "last_decision 记录到 suppress_reason",
            sched.last_decision is not None
            and sched.last_decision.suppress_reason == "user_recent_active",
        )

    asyncio.run(step4())

    # ── 5. _dispatch · judge 通过 + tone 透传 ──────
    _stage("5. _dispatch · judge 通过 + tone 透传")

    async def step5() -> None:
        nonlocal passed, failed
        cfg = {
            "proactive": {
                "enabled": True,
                "max_per_day": 5,
                "min_interval_min": 30,
                "quiet_start": "23:30",
                "quiet_end": "07:00",
                "exempt_scenes": ["morning_brief", "goodnight"],
            },
            "scenes": {
                "goodnight": {"template": "晚安。"},
            },
        }
        sched = CronScheduler(cfg)
        sched.judge = ProactiveJudge()
        sched.policy.last_push_at = None
        sched.policy.daily_count = 0

        captured: dict[str, Any] = {}

        async def mock_dispatch(scene: str, scene_cfg: dict) -> bool:
            captured["scene"] = scene
            captured["cfg"] = scene_cfg
            return True

        sched.set_dispatcher(mock_dispatch)
        result = await sched._dispatch(
            "goodnight",
            {
                "template": "晚安。",
                "judge_override": {
                    "desire_score": 60.0,
                    "emotion_score": 80.0,
                    "context_score": 100.0,
                    "environment_score": 35.0,
                    "user_minutes_since_last": 300.0,
                    "force_tone": "tame_soft",
                },
            },
        )
        expect("_dispatch 返回 True (放行)", result is True, f"got {result}")
        expect("dispatcher 收到 tone_hint",
               captured.get("cfg") is not None
               and captured["cfg"].get("tone_hint") == "tame_soft",
               f"got {captured.get('cfg', {}).get('tone_hint')!r}")
        expect("judge_context 透传 (含 components)",
               isinstance(captured.get("cfg", {}).get("judge_context"), dict)
               and "components" in captured["cfg"]["judge_context"])
        expect("policy.daily_count 累加",
               sched.policy.daily_count == 1, f"got {sched.policy.daily_count}")
    asyncio.run(step5())

    # ── 6. Brain.generate_push · tone_hint 解析 ─────
    _stage("6. Brain.generate_push · tone_hint + 屏幕隔空铁律")

    async def step6() -> None:
        nonlocal passed, failed
        from core.brain import Brain
        b = Brain()
        # 没设 LLM,会走 fallback。但 system_msg 在 chat() 之前组装,
        # 我们用 monkey patch 拦截 chat 看 prompt。
        from core.brain import Brain as _Brain
        original_chat = _Brain.chat
        seen_system: list[str] = []

        async def stub_chat(self, messages, *a, **kw):  # type: ignore
            for m in messages:
                if m.get("role") == "system":
                    seen_system.append(m["content"])
            # 模拟 LLM 不可用 → 让 generate_push 走 fallback
            raise RuntimeError("no provider")

        _Brain.chat = stub_chat
        try:
            # tone=collapse_seeking
            out = await b.generate_push(
                "你还在吗。",
                mood="neutral",
                tone_hint="collapse_seeking",
                judge_context={
                    "score": 78,
                    "components": {
                        "emotion_score": 90.0,
                        "user_minutes_since_last": 240.0,
                    },
                },
            )
            expect("fallback 仍输出原模板", out == "你还在吗。", f"got {out!r}")
        finally:
            _Brain.chat = original_chat

        expect("system_msg 至少生成 1 次", len(seen_system) >= 1)
        if seen_system:
            sm = seen_system[0]
            expect("system_msg 含屏幕隔空铁律", "屏幕" in sm and "摸不到" in sm)
            expect("system_msg 含坍塌 tone",
                   TONE_PROMPTS["collapse_seeking"] in sm)
            expect("system_msg 含 judge context (心情强度 78)",
                   "心情强度 78" in sm)
            expect("system_msg 含用户离线 4.0h",
                   "4.0h" in sm or "4 小时" in sm)

    asyncio.run(step6())

    # ── 7. 端到端联调 ───────────────────────────────
    _stage("7. 端到端联调 · ProactiveJudge → _dispatch → 模拟 dispatcher")

    async def step7() -> None:
        nonlocal passed, failed
        cfg = {
            "proactive": {
                "enabled": True,
                "max_per_day": 5,
                "min_interval_min": 30,
                "quiet_start": "23:30",
                "quiet_end": "07:00",
                "exempt_scenes": ["morning_brief", "goodnight"],
            },
            "scenes": {
                "morning_brief": {"template": "早安。今天也请多指教。"},
            },
        }
        sched = CronScheduler(cfg)
        sched.judge = ProactiveJudge(companion=None)
        sched.policy.last_push_at = None
        sched.policy.daily_count = 0

        received: list[dict] = []

        async def mock_dispatch(scene: str, scene_cfg: dict) -> bool:
            received.append({
                "scene": scene,
                "tone": scene_cfg.get("tone_hint"),
                "score": (
                    scene_cfg.get("judge_context", {}).get("score")
                ),
            })
            return True

        sched.set_dispatcher(mock_dispatch)
        # 早晨场景,通过 — 喂一个合理的 override 让 score ≥ 30
        ok = await sched._dispatch("morning_brief", {
            "template": "早安。今天也请多指教。",
            "judge_override": {
                "desire_score": 30.0,
                "emotion_score": 50.0,
                "context_score": 50.0,
                "environment_score": 60.0,
            },
        })
        d_judge = sched.last_decision
        expect("judge 不抑制 morning_brief",
               d_judge is not None and d_judge.suppress_reason == "",
               f"suppress={d_judge.suppress_reason if d_judge else None!r}")
        expect("dispatch 返回 True", ok is True)
        expect("dispatcher 收到 tone_hint",
               received and received[0].get("tone") in TONE_PROMPTS,
               f"got {received}")
        expect("dispatcher 收到 score (int)",
               received and isinstance(received[0].get("score"), int),
               f"got {received}")

    asyncio.run(step7())

    # ── summary ─────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"总计: {passed} 通过 / {failed} 失败 / {passed + failed} 用例")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
