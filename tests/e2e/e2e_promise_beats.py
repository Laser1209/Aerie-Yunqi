"""Aerie · E2E: Promise Beats 承诺节拍全链路（一图一测试）.

用真实模块（BeatStore + PromiseBeatsRunner）+ 可控假世界/假出图端口，
验证承诺从排期到兑现的完整链路与 8 条健身函数：

  1. 到期触发：世界先出门、状态自洽（outdoor=True），再出图
  2. fired → 出图（成功路径发布 role_in_scene 候选）
  3. 恰好一次：fired 后再次 tick 不重复出图
  4. 触发时间落在 [due, due+10min]
  5. 幂等：同原话窗口内外部重复排期被拒
  6. 出图失败 → 解释文段投递（无失败弹窗语义），beat fired
  7. 超窗：连续失败 max_attempts 后标 failed（不静默丢失）
  8. flag 关闭：到期也不触发

纯本地（无网络/DB/LLM：brain 与出图均为假端口）。
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import types

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.promise_beats_runner import PromiseBeatsRunner  # noqa: E402
from core.scheduled_beats import BeatStore  # noqa: E402

T0 = 1_756_000_000.0
HOUR = 3600.0
_failures: list[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    symbol = "✓" if ok else "✗"
    print(f"  {symbol} {label}  {detail}")
    if not ok:
        _failures.append(label)


class FakeWorld:
    """记录世界状态：go_out 后 snapshot 变 outdoor（验证世界自洽）。"""

    def __init__(self) -> None:
        self.outdoor = False
        self.outdoor_place = ""
        self.go_out_calls: list[tuple[str, str]] = []

    def go_out(self, place: str, source: str) -> None:
        self.go_out_calls.append((place, source))
        self.outdoor = True
        self.outdoor_place = place or "江边步道"


class FakeBrain:
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        return types.SimpleNamespace(text=self._text)


class _Clock:
    """可变时钟：store 的 schedule/due/fired 时间全部由它控制。"""

    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class Rig:
    def __init__(
        self,
        *,
        image_result: dict,
        brain_text: str = "先忙会儿。一会儿找你",
        flag_enabled: bool = True,
        max_attempts: int = 3,
        deliver_result: bool = True,
    ) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.clock = _Clock(T0)
        self.store = BeatStore(
            os.path.join(self.tmpdir.name, "beats.json"), clock=self.clock,
        )
        self.world = FakeWorld()
        self.order: list[str] = []
        self.payloads: list[dict] = []
        self.delivered: list[str] = []
        self.brain = FakeBrain(brain_text)
        self._image_result = image_result
        self._publish_raises = False
        self._deliver_result = deliver_result

        def world_action(place: str) -> None:
            self.order.append("world")
            self.world.go_out(place, "self_promise")

        def snapshot() -> dict:
            return {
                "outdoor": self.world.outdoor,
                "outdoor_place": self.world.outdoor_place,
                "phase": "afternoon",
                "activity": "散步",
            }

        async def image_publisher(payload: dict) -> dict:
            # 出图时世界必须已经在外面（世界先行）。
            self.order.append("image")
            self.payloads.append(payload)
            if self._publish_raises:
                raise RuntimeError("workflow down")
            return self._image_result

        async def text_deliverer(text: str) -> bool:
            self.delivered.append(text)
            return self._deliver_result

        self.runner = PromiseBeatsRunner(
            brain=self.brain,
            feature_flags=types.SimpleNamespace(
                is_enabled=lambda name: flag_enabled
            ),
            settings={"promise_beats": {"poll_sec": 60, "max_pending": 2}},
            world_action=world_action,
            world_snapshot=snapshot,
            delivery_context=lambda: {
                "master_id": "42", "channel": "qq", "persona_id": "yita",
            },
            image_publisher=image_publisher,
            text_deliverer=text_deliverer,
            store=self.store,
            max_attempts=max_attempts,
        )

    def schedule(self, *, source: str = "好几天闷家里了 想出去走走",
                 delay: float = 2 * HOUR) -> str:
        beat = self.store.schedule(
            kind="go_out", topic="想出去走走", source_text=source,
            delay_sec=delay, place_hint="江边步道",
        )
        assert beat is not None, "schedule unexpectedly rejected"
        return beat.id

    def cleanup(self) -> None:
        self.tmpdir.cleanup()


_COMPLETED = {"consumed": [{"status": "completed"}]}
_FAILED = {"consumed": [{"status": "failed"}]}


def case_due_world_first_then_image() -> tuple[str, Rig]:
    """健身函数 1/2：due 后世界先出门且自洽，随后出图，beat fired。"""
    rig = Rig(image_result=_COMPLETED)
    beat_id = rig.schedule(delay=2 * HOUR)
    due_at = rig.store.get(beat_id).due_at

    # 未到期不触发。
    asyncio.run(rig.runner.tick())
    pre_due = len(rig.payloads)

    # 推进到 due+1 分钟（健身函数 4：[due, due+10min]）。
    rig.clock.value = due_at + 60
    asyncio.run(rig.runner.tick())

    beat = rig.store.get(beat_id)
    _check("未到期不触发", pre_due == 0)
    _check("世界先于出图", rig.order[:2] == ["world", "image"],
           str(rig.order))
    _check("世界自洽 outdoor=True", rig.world.outdoor
           and rig.world.outdoor_place == "江边步道")
    _check("出门来源 self_promise",
           rig.world.go_out_calls == [("江边步道", "self_promise")],
           str(rig.world.go_out_calls))
    _check("发布 role_in_scene 候选",
           rig.payloads and rig.payloads[0]["prompt_key"] == "role_in_scene"
           and rig.payloads[0]["scene"] == "promise_beat")
    _check("beat fired", beat.status == "fired")
    _check("触发时间在 [due, due+10min]",
           due_at <= beat.fired_at <= due_at + 600,
           f"due={due_at} fired_at={beat.fired_at}")
    return beat_id, rig


def case_exactly_once(rig: Rig) -> None:
    """健身函数 3：fired 后再次 tick 不重复出图。"""
    asyncio.run(rig.runner.tick())
    asyncio.run(rig.runner.tick())
    _check("fired 后恰好一次", len(rig.payloads) == 1,
           f"payloads={len(rig.payloads)}")


def case_idempotent_external_schedule() -> None:
    """健身函数 5：外部 store 实例同原话窗口内（300s）重复排期被拒。"""
    rig = Rig(image_result=_COMPLETED)
    rig.schedule(delay=HOUR)  # 时钟停在排期时刻 T0
    external = BeatStore(
        os.path.join(rig.tmpdir.name, "beats.json"), clock=rig.clock,
    )
    duplicate = external.schedule(
        kind="go_out", topic="想出去走走",
        source_text="好几天闷家里了 想出去走走", delay_sec=HOUR,
    )
    _check("同原话窗口内幂等", duplicate is None)
    rig.cleanup()


def case_image_failure_fallback() -> None:
    """健身函数 6：出图失败 → 解释文段投递，beat fired（无失败弹窗）。"""
    rig = Rig(image_result=_FAILED)
    beat_id = rig.schedule(delay=HOUR)
    due_at = rig.store.get(beat_id).due_at
    rig.clock.value = due_at

    asyncio.run(rig.runner.tick())

    text = rig.delivered[0] if rig.delivered else ""
    lines = text.split("\n")
    ok_rules = (
        bool(text)
        and all("。" not in line and "——" not in line for line in lines)
        and all(len(line) <= 20 for line in lines)
        and len(lines) <= 2
    )
    _check("解释文段已投递", bool(text), f"text={text!r}")
    _check("文段符合表达规范（无句号/破折号、短、≤2条）", ok_rules)
    _check("出图未成功只发一次候选", len(rig.payloads) == 1)
    _check("承诺仍标 fired（以解释兑现）",
           rig.store.get(beat_id).status == "fired")
    rig.cleanup()


def case_retry_window_to_failed() -> None:
    """健身函数 7：出图与解释均失败，超 max_attempts 标 failed。"""
    rig = Rig(image_result=_FAILED, brain_text="", max_attempts=2)
    beat_id = rig.schedule(delay=HOUR)
    due_at = rig.store.get(beat_id).due_at
    rig.clock.value = due_at

    asyncio.run(rig.runner.tick())
    after_one = rig.store.get(beat_id).status
    asyncio.run(rig.runner.tick())
    final = rig.store.get(beat_id)

    _check("首次失败保持 pending 重试", after_one == "pending")
    _check("超窗标 failed 不静默丢失",
           final.status == "failed" and final.attempts == 2)
    rig.cleanup()


def case_flag_off_no_fire() -> None:
    """健身函数 8：flag 关闭时到期也不触发。"""
    rig = Rig(image_result=_COMPLETED, flag_enabled=False)
    beat_id = rig.schedule(delay=HOUR)
    due_at = rig.store.get(beat_id).due_at
    rig.clock.value = due_at

    asyncio.run(rig.runner.tick())

    _check("flag 关闭不出门不发布",
           not rig.world.outdoor and not rig.payloads)
    _check("beat 保持 pending",
           rig.store.get(beat_id).status == "pending")
    rig.cleanup()


def main() -> int:
    print("=" * 64)
    print("E2E · Promise Beats 承诺节拍全链路（8 健身函数）")
    print("=" * 64)

    _, rig = case_due_world_first_then_image()
    case_exactly_once(rig)
    rig.cleanup()
    case_idempotent_external_schedule()
    case_image_failure_fallback()
    case_retry_window_to_failed()
    case_flag_off_no_fire()

    print("=" * 64)
    if _failures:
        print(f"FAILED ({len(_failures)}): {_failures}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
