"""Aerie · 云栖 v9.0 — E2E: T4 · Persona 9/10 全文件基线守门 (12 cases).

R8.1 三原则之「零回退」要求所有跟人格相关的参数都被守门。
本套件直接读 4 类源（YAML 文件 + Python 常量）验证 9/10 基线：
  - config/persona.yaml 5 项
  - config/persona_behavior.yaml 4 项
  - core/context_builder.py 2 项（L1 + L2）
  - core/brain.py 1 项（TONE_PROMPTS）

12 个用例 (T4)：
  1.  persona.yaml.big_five.extraversion == 0.78
  2.  persona.yaml.big_five.agreeableness == 0.85
  3.  persona.yaml.archetype 字符串含 "9/10" 和 "直球"
  4.  persona.yaml.example_phrases 含直球措辞关键字
  5.  persona.yaml.system_prompt 含 "9/10"
  6.  persona_behavior.yaml.thresholds.patience.initial_value == 45
  7.  persona_behavior.yaml.thresholds.anxiety.initial_value == 25
  8.  persona_behavior.yaml.thresholds.desire.initial_value == 55
  9.  persona_behavior.yaml.thresholds.tenderness.initial_value == 15
  10. context_builder._PERSONA_L1 含 "9/10"
  11. context_builder._PERSONA_L2 含直球表达关键字
  12. brain.TONE_PROMPTS["warm_with_light_flirt"] 含 "想你" 且不含 "克制"

纯本地（直接读文件 + import Python 模块，不依赖 backend / DB / LLM）。
"""
from __future__ import annotations
import sys
# R7.5+: force UTF-8 on Windows (default GBK chokes on ✓/✗)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import os
import sys

# Ensure repo root on path
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from config.persona_loader import load_persona  # noqa: E402
from core.context_builder import _PERSONA_L1, _PERSONA_L2  # noqa: E402
from core.brain import TONE_PROMPTS  # noqa: E402


def _check(label: str, ok: bool, detail: str = "") -> None:
    sym = "✓" if ok else "✗"
    print(f"  {sym} {label}  {detail}")


# ── Case 1: persona.yaml.big_five.extraversion == 0.78 ──────
def case_1_extraversion_078() -> bool:
    cfg = load_persona() or {}
    profile = (cfg.get("persona") or {}).get("profile") or {}
    big_five = profile.get("big_five") or {}
    extraversion = big_five.get("extraversion")
    ok_flag = extraversion == 0.78
    _check(
        "Case 1 · persona.yaml big_five.extraversion == 0.78",
        ok_flag,
        f"extraversion={extraversion}",
    )
    return ok_flag


# ── Case 2: persona.yaml.big_five.agreeableness == 0.85 ─────
def case_2_agreeableness_085() -> bool:
    cfg = load_persona() or {}
    profile = (cfg.get("persona") or {}).get("profile") or {}
    big_five = profile.get("big_five") or {}
    agreeableness = big_five.get("agreeableness")
    ok_flag = agreeableness == 0.85
    _check(
        "Case 2 · persona.yaml big_five.agreeableness == 0.85",
        ok_flag,
        f"agreeableness={agreeableness}",
    )
    return ok_flag


# ── Case 3: archetype contains "9/10" and "直球" ─────────────
def case_3_archetype_9_10_and_direct() -> bool:
    cfg = load_persona() or {}
    profile = (cfg.get("persona") or {}).get("profile") or {}
    archetype = profile.get("personality_archetype", "")
    ok_flag = ("9/10" in archetype) and ("直球" in archetype)
    _check(
        "Case 3 · persona.yaml archetype 含 '9/10' 和 '直球'",
        ok_flag,
        f"archetype={archetype!r}",
    )
    return ok_flag


# ── Case 4: example_phrases has ≥ 3 direct keywords ──────────
def case_4_example_phrases_direct() -> bool:
    cfg = load_persona() or {}
    speech = ((cfg.get("persona") or {}).get("speech") or {})
    phrases = speech.get("example_phrases") or []
    text = " ".join(phrases)
    # 直球关键字列表（9/10 基线下的典型措辞）
    direct_keywords = ["不许不接", "立刻", "马上", "不许", "必须", "现在就"]
    found = [kw for kw in direct_keywords if kw in text]
    ok_flag = len(found) >= 3
    _check(
        "Case 4 · example_phrases 含 ≥ 3 个直球措辞关键字",
        ok_flag,
        f"found={found} phrases_count={len(phrases)}",
    )
    return ok_flag


# ── Case 5: system_prompt contains "9/10" ────────────────────
def case_5_system_prompt_9_10() -> bool:
    cfg = load_persona() or {}
    persona = (cfg.get("persona") or {})
    system_prompt = persona.get("system_prompt", "")
    ok_flag = "9/10" in system_prompt
    _check(
        "Case 5 · persona.yaml system_prompt 含 '9/10'",
        ok_flag,
        f"system_prompt head: {system_prompt[:120]!r}",
    )
    return ok_flag


# ── Case 6: patience.initial_value == 45 ─────────────────────
def case_6_patience_45() -> bool:
    import yaml as _yaml
    yaml_path = os.path.join(_REPO_ROOT, "config", "persona_behavior.yaml")
    with open(yaml_path, "r", encoding="utf-8") as f:
        cfg = _yaml.safe_load(f) or {}
    patience = (
        (((cfg.get("emotion") or {}).get("thresholds") or {}).get("patience") or {})
    )
    initial = patience.get("initial_value")
    ok_flag = initial == 45
    _check(
        "Case 6 · persona_behavior.yaml patience.initial_value == 45",
        ok_flag,
        f"initial_value={initial}",
    )
    return ok_flag


# ── Case 7: anxiety.initial_value == 25 ──────────────────────
def case_7_anxiety_25() -> bool:
    import yaml as _yaml
    yaml_path = os.path.join(_REPO_ROOT, "config", "persona_behavior.yaml")
    with open(yaml_path, "r", encoding="utf-8") as f:
        cfg = _yaml.safe_load(f) or {}
    anxiety = (
        (((cfg.get("emotion") or {}).get("thresholds") or {}).get("anxiety") or {})
    )
    initial = anxiety.get("initial_value")
    ok_flag = initial == 25
    _check(
        "Case 7 · persona_behavior.yaml anxiety.initial_value == 25",
        ok_flag,
        f"initial_value={initial}",
    )
    return ok_flag


# ── Case 8: desire.initial_value == 55 ───────────────────────
def case_8_desire_55() -> bool:
    import yaml as _yaml
    yaml_path = os.path.join(_REPO_ROOT, "config", "persona_behavior.yaml")
    with open(yaml_path, "r", encoding="utf-8") as f:
        cfg = _yaml.safe_load(f) or {}
    desire = (
        (((cfg.get("emotion") or {}).get("thresholds") or {}).get("desire") or {})
    )
    initial = desire.get("initial_value")
    ok_flag = initial == 55
    _check(
        "Case 8 · persona_behavior.yaml desire.initial_value == 55",
        ok_flag,
        f"initial_value={initial}",
    )
    return ok_flag


# ── Case 9: tenderness.initial_value == 15 ───────────────────
def case_9_tenderness_15() -> bool:
    import yaml as _yaml
    yaml_path = os.path.join(_REPO_ROOT, "config", "persona_behavior.yaml")
    with open(yaml_path, "r", encoding="utf-8") as f:
        cfg = _yaml.safe_load(f) or {}
    tenderness = (
        (((cfg.get("emotion") or {}).get("thresholds") or {}).get("tenderness") or {})
    )
    initial = tenderness.get("initial_value")
    ok_flag = initial == 15
    _check(
        "Case 9 · persona_behavior.yaml tenderness.initial_value == 15",
        ok_flag,
        f"initial_value={initial}",
    )
    return ok_flag


# ── Case 10: _PERSONA_L1 contains "9/10" ─────────────────────
def case_10_persona_l1_9_10() -> bool:
    ok_flag = "9/10" in _PERSONA_L1
    _check(
        "Case 10 · context_builder._PERSONA_L1 含 '9/10'",
        ok_flag,
        f"_PERSONA_L1 has '9/10': {ok_flag}",
    )
    return ok_flag


# ── Case 11: _PERSONA_L2 contains direct-expression marker ───
def case_11_persona_l2_direct_marker() -> bool:
    # _PERSONA_L2 应含 9 分直球版相关标记
    markers = ["9 分直球", "直球", "不许不接"]
    found = [m for m in markers if m in _PERSONA_L2]
    ok_flag = len(found) >= 1
    _check(
        "Case 11 · context_builder._PERSONA_L2 含直球表达标记",
        ok_flag,
        f"found={found}",
    )
    return ok_flag


# ── Case 12: TONE_PROMPTS["warm_with_light_flirt"] contains "想你" ──
def case_12_tone_warm_light_flirt() -> bool:
    tone = TONE_PROMPTS.get("warm_with_light_flirt", "")
    # 9/10 直球版应含"想你"等直球措辞，且不应含"克制"等暗涌表达
    has_thinking = "想你" in tone
    has_restrained = "克制" in tone
    ok_flag = has_thinking and not has_restrained
    _check(
        "Case 12 · brain.TONE_PROMPTS['warm_with_light_flirt'] 含 '想你' 不含 '克制'",
        ok_flag,
        f"has_thinking={has_thinking} has_restrained={has_restrained} "
        f"tone head: {tone[:80]!r}",
    )
    return ok_flag


def main() -> int:
    print("=" * 60)
    print("E2E T4 · Persona 9/10 全文件基线守门 (12 用例)")
    print("=" * 60)
    results: list[bool] = [
        case_1_extraversion_078(),
        case_2_agreeableness_085(),
        case_3_archetype_9_10_and_direct(),
        case_4_example_phrases_direct(),
        case_5_system_prompt_9_10(),
        case_6_patience_45(),
        case_7_anxiety_25(),
        case_8_desire_55(),
        case_9_tenderness_15(),
        case_10_persona_l1_9_10(),
        case_11_persona_l2_direct_marker(),
        case_12_tone_warm_light_flirt(),
    ]
    passed = sum(1 for r in results if r)
    failed = sum(1 for r in results if not r)
    print("=" * 60)
    print(f"  Total: passed={passed}  failed={failed}")
    if failed == 0:
        print("  ✓ e2e_persona_baseline 全部通过")
    else:
        print("  ✗ e2e_persona_baseline 有失败用例")
    print("=" * 60)
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
