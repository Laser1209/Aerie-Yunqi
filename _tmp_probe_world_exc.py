"""Temporary probe: reproduce why _image_prompt_for returned empty on 2026-08-11.

Loads the REAL in-process world adapter + companion helper methods, runs the
prompt chain against a REAL world snapshot, and prints exactly where an
exception surfaces (if any). Also tests a hostile snapshot that mimics what
the world could have produced.
"""
import asyncio
import sys
import types
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import solar_time
from core.ephemeris import moon_phase
from core.companion import Companion


async def main() -> None:
    # ── 1) Real in-process world snapshot ──
    real_world = None
    try:
        from core.world_port import build_world_port
        from core.runtime_config import RuntimeConfigService
        flags = types.SimpleNamespace(is_enabled=lambda name: name in ("world_inprocess_v1", "world_sidecar_v1") and name == "world_inprocess_v1")
        wp = build_world_port(
            flags,
            config={},
            runtime_config=RuntimeConfigService(state_path=Path(r"e:\Agent_reply\data\runtime_config.json")),
        )
        snap = wp.get_world_snapshot()
        print("real snapshot type:", type(snap).__name__)
        print("real snapshot keys:", sorted(snap.keys())[:20] if isinstance(snap, dict) else "N/A")
        real_world = snap
    except Exception:
        print("real world unavailable:", traceback.format_exc()[-400:])

    # ── 2) Run companion prompt chain against real snapshot ──
    fake = types.SimpleNamespace()
    if real_world is not None:
        fake.world_port = types.SimpleNamespace(get_world_snapshot=lambda: real_world)
    else:
        # hostile snapshot mimicking a malformed world payload
        fake.world_port = types.SimpleNamespace(
            get_world_snapshot=lambda: {
                "phase": "night",
                "iso_time": "not-a-date!!",
                "weather_mood": "rainy",
                "city": "重庆",
                "location": "home",
            }
        )
    fake.brain = types.SimpleNamespace(chat=None)
    for name in ("_compose_base_image_prompt", "_image_world_context", "_image_prompt_for",
                 "_world_context_text", "_light_relay_refine_prompt", "_inject_world_context_fallback",
                 "_world_snapshot_for_context"):
        setattr(fake, name, getattr(Companion, name).__get__(fake, Companion))

    candidate = {
        "prompt_key": "role_selfie",
        "reason_code": "user_requested",
        "scene": "local_send",
        "channel": "qq",
        "target": "3489352115",
        "size": "768x1344",
        "created_at": "2026-08-11T08:03:55.022479+00:00",
    }

    print("\n--- base prompt ---")
    try:
        base = fake._compose_base_image_prompt("role_selfie", candidate)
        print("len:", len(base or ""))
    except Exception:
        print("EXC:", traceback.format_exc()[-300:])

    print("\n--- _image_world_context (pre-fix behaviour) ---")
    try:
        ctx = fake._image_world_context(candidate)
        print("ctx len:", len(ctx or {}))
        if ctx:
            print("light:", (ctx.get("time_of_day_light") or "")[:60])
    except Exception:
        print("EXC:", traceback.format_exc()[-500:])

    print("\n--- _image_prompt_for (pre-fix behaviour) ---")
    try:
        final = await fake._image_prompt_for("role_selfie", candidate)
        print("FINAL len:", len(final or ""), "| head:", (final or "")[:60])
    except Exception:
        print("EXC:", traceback.format_exc()[-400:])


if __name__ == "__main__":
    asyncio.run(main())
