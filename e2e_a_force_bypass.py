"""Aerie · 云栖 v9.0 — E2E: A · force=True 旁路验证 (5 cases).

R8.1 收口验证 A 节的 force=True 路径：
  - push_scheduler._dispatch 入口：force=True 跳过 ProactiveJudge
    与 policy.can_push。
  - push_scheduler._dispatch_desire_text：force=True 时不调用
    policy.record（避免 boot_greeting 污染 daily_count / cooldown）。
  - config/proactive.yaml 的 boot_greeting.force: true 必须在位。

5 个用例 (T1)：
  1. _dispatch 在 force=True 时跳过 ProactiveJudge.evaluate
  2. _dispatch 在 force=True 时跳过 policy.can_push（即使 daily_limit）
  3. _dispatch_desire_text 在 force=True 时不调 policy.record
  4. _dispatch_desire_text 在 force=False 时正常调 policy.record
  5. config/proactive.yaml boot_greeting.force: true 在位

纯本地（不依赖 backend / DB / LLM）。Mock judge / policy / dispatcher。
"""
from __future__ import annotations
import sys
# R7.5+: force UTF-8 on Windows (default GBK chokes on ✓/✗)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import asyncio
import os
import sys
from unittest.mock import MagicMock, AsyncMock

# Ensure repo root on path
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.push_scheduler import CronScheduler  # noqa: E402


def _check(label: str, ok: bool, detail: str = "") -> None:
    sym = "✓" if ok else "✗"
    print(f"  {sym} {label}  {detail}")


def _make_scheduler() -> CronScheduler:
    """Build a minimal CronScheduler with boot_greeting + idle_care scenes."""
    config = {
        "proactive": {
            "enabled": True,
            "max_per_day": 5,
            "min_interval_min": 30,
            "quiet_start": "23:30",
            "quiet_end": "07:00",
            "exempt_scenes": [],
        },
        "scenes": {
            "boot_greeting": {
                "template": "刚醒。",
                "custom_dispatcher": "boot_greeting",
                "force": True,
            },
            "idle_care": {
                "template": "在干嘛。",
                "custom_dispatcher": "desire_care",
            },
        },
    }
    return CronScheduler(config)


# ── Case 1: _dispatch with force=True bypasses judge ────────────
async def case_1_dispatch_force_bypasses_judge() -> bool:
    sched = _make_scheduler()
    judge = MagicMock()
    sched.judge = judge
    dispatcher = AsyncMock(return_value=True)
    sched.set_dispatcher(dispatcher)
    policy_record = MagicMock()
    sched.policy.record = policy_record
    policy_can_push = MagicMock(return_value=(True, "ok"))
    sched.policy.can_push = policy_can_push

    ok = await sched._dispatch(
        "boot_greeting",
        {"template": "刚醒。", "custom_dispatcher": "boot_greeting", "force": True},
    )
    judge_never_called = not judge.evaluate.called
    ok_flag = ok is True and judge_never_called
    _check(
        "Case 1 · _dispatch force=True 不调 judge.evaluate",
        ok_flag,
        f"ok={ok} judge.evaluate.called={judge.evaluate.called}",
    )
    return ok_flag


# ── Case 2: _dispatch with force=True bypasses policy.can_push ──
async def case_2_dispatch_force_bypasses_policy_can_push() -> bool:
    sched = _make_scheduler()
    judge = MagicMock()
    sched.judge = judge
    dispatcher = AsyncMock(return_value=True)
    sched.set_dispatcher(dispatcher)
    # policy.can_push returns (False, "daily_limit") — would normally reject
    policy_can_push = MagicMock(return_value=(False, "daily_limit"))
    sched.policy.can_push = policy_can_push
    policy_record = MagicMock()
    sched.policy.record = policy_record

    ok = await sched._dispatch(
        "boot_greeting",
        {"template": "刚醒。", "custom_dispatcher": "boot_greeting", "force": True},
    )
    # dispatcher must have been called even though policy.can_push said no
    ok_flag = ok is True and dispatcher.called
    _check(
        "Case 2 · _dispatch force=True 跳过 can_push=False 仍放行",
        ok_flag,
        f"ok={ok} dispatcher.called={dispatcher.called}",
    )
    return ok_flag


# ── Case 3: _dispatch_desire_text with force=True skips policy.record ──
async def case_3_desire_text_force_skips_record() -> bool:
    sched = _make_scheduler()
    dispatcher = AsyncMock(return_value=True)
    sched.set_dispatcher(dispatcher)
    policy_record = MagicMock()
    sched.policy.record = policy_record

    ok = await sched._dispatch_desire_text(
        "boot_greeting",
        {"template": "刚醒。", "force": True},
        kind="care",
    )
    # dispatcher must be called; policy.record must NOT be called
    ok_flag = ok is True and dispatcher.called and not policy_record.called
    _check(
        "Case 3 · _dispatch_desire_text force=True 不调 policy.record",
        ok_flag,
        f"ok={ok} dispatcher.called={dispatcher.called} "
        f"policy.record.called={policy_record.called}",
    )
    return ok_flag


# ── Case 4: _dispatch_desire_text without force records on policy ─
async def case_4_desire_text_no_force_records() -> bool:
    sched = _make_scheduler()
    dispatcher = AsyncMock(return_value=True)
    sched.set_dispatcher(dispatcher)
    policy_record = MagicMock()
    sched.policy.record = policy_record

    ok = await sched._dispatch_desire_text(
        "idle_care",
        {"template": "在干嘛。"},   # no force
        kind="care",
    )
    # dispatcher must be called; policy.record MUST be called
    ok_flag = ok is True and dispatcher.called and policy_record.called
    _check(
        "Case 4 · _dispatch_desire_text force=False 正常调 policy.record",
        ok_flag,
        f"ok={ok} dispatcher.called={dispatcher.called} "
        f"policy.record.called={policy_record.called}",
    )
    return ok_flag


# ── Case 5: proactive.yaml boot_greeting.force: true is in place ─
def case_5_proactive_yaml_force_true() -> bool:
    yaml_path = os.path.join(_REPO_ROOT, "config", "proactive.yaml")
    if not os.path.exists(yaml_path):
        _check("Case 5 · proactive.yaml boot_greeting.force: true", False,
               f"file missing: {yaml_path}")
        return False
    with open(yaml_path, "r", encoding="utf-8") as f:
        text = f.read()
    has_scene = "boot_greeting" in text
    has_force = "force: true" in text
    ok_flag = has_scene and has_force
    _check(
        "Case 5 · proactive.yaml boot_greeting 含 force: true",
        ok_flag,
        f"has_scene={has_scene} has_force={has_force}",
    )
    return ok_flag


async def main() -> int:
    print("=" * 60)
    print("E2E T1 · A 节 force=True 旁路验证 (5 用例)")
    print("=" * 60)
    results: list[bool] = []
    results.append(await case_1_dispatch_force_bypasses_judge())
    results.append(await case_2_dispatch_force_bypasses_policy_can_push())
    results.append(await case_3_desire_text_force_skips_record())
    results.append(await case_4_desire_text_no_force_records())
    results.append(case_5_proactive_yaml_force_true())
    passed = sum(1 for r in results if r)
    failed = sum(1 for r in results if not r)
    print("=" * 60)
    print(f"  Total: passed={passed}  failed={failed}")
    if failed == 0:
        print("  ✓ e2e_a_force_bypass 全部通过")
    else:
        print("  ✗ e2e_a_force_bypass 有失败用例")
    print("=" * 60)
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
