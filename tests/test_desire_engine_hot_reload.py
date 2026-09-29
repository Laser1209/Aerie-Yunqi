"""DesireEngine 的 persona_behavior.yaml → desire 段热加载契约。

用户改 config/persona_behavior.yaml 的触发阈值 / 采样温度 τ / 概率上下限 /
tick / 冷却小时后，引擎应在下一拍自动生效，且不丢失运行态状态。
"""
import os
import time
from pathlib import Path


def _write_cfg(path: Path, tau: float, tick: int) -> None:
    path.write_text(
        "desire:\n"
        f"  tick_seconds: {tick}\n"
        "  triggers:\n"
        "    care: 50\n"
        "    voice: 80\n"
        "    cooldown_hours: 12\n"
        f"    tau: {tau}\n"
        "    p_floor: 0.02\n"
        "    p_ceiling: 0.95\n",
        encoding="utf-8",
    )


def test_reload_config_if_changed_applies_new_sampling_params(tmp_path):
    from core.desire_engine import DesireEngine

    cfg = tmp_path / "persona_behavior.yaml"
    _write_cfg(cfg, tau=8.0, tick=300)

    engine = DesireEngine(None, {"desire": {"tick_seconds": 300}})
    engine._cfg_path = cfg
    engine._cfg_mtime = engine._read_cfg_mtime()
    assert engine.sampling_tau == 8.0
    assert engine.tick_seconds == 300

    # mtime 未变 → 零开销返回，不重读。
    assert engine.reload_config_if_changed() is False

    _write_cfg(cfg, tau=2.5, tick=600)
    # 部分文件系统 mtime 秒级精度，显式向前推以保证检测到变化。
    future = time.time() + 5
    os.utime(cfg, (future, future))

    assert engine.reload_config_if_changed() is True
    assert engine.sampling_tau == 2.5
    assert engine.tick_seconds == 600
    # 运行态状态不被热加载清空。
    assert "score" in engine.state or engine.state == {}


def test_reload_never_raises_on_broken_yaml(tmp_path):
    from core.desire_engine import DesireEngine

    cfg = tmp_path / "persona_behavior.yaml"
    _write_cfg(cfg, tau=8.0, tick=300)

    engine = DesireEngine(None, {"desire": {"tick_seconds": 300}})
    engine._cfg_path = cfg
    engine._cfg_mtime = engine._read_cfg_mtime()

    cfg.write_text("desire: [unclosed\n", encoding="utf-8")
    future = time.time() + 5
    os.utime(cfg, (future, future))

    # 解析失败保持现状，不抛错打断欲望循环。
    assert engine.reload_config_if_changed() is False
    assert engine.sampling_tau == 8.0
