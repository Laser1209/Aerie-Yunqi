"""Aerie v11.3 · S4 M4.2 多模态输出验证

验证项：
  T1 VoiceStyle 枚举与场景配置
  T2 TTSCache 读写与容量限制
  T3 EnhancedTTSEngine 初始化与配置
  T4 EnhancedTTSEngine 场景化配置获取
  T5 TTSResult 数据模型
  T6 ImageResult 数据模型
  T7 ImageGenerator 初始化与 doodle fallback
  T8 ImageGenerator 生成 SVG 占位图
  T9 MultimodalOutputEngine 初始化
  T10 MultimodalOutputEngine 场景列表
  T11 与现有 TTSEngine 兼容（voice/tts_engine.py）
"""

from __future__ import annotations
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from voice.multimodal_output import (
    EnhancedTTSEngine,
    ImageGenerator,
    ImageProvider,
    ImageResult,
    MultimodalOutputEngine,
    SCENE_VOICE_STYLES,
    TTSCache,
    TTSProvider,
    TTSResult,
    VoiceStyle,
)


def t1_voice_style_enum() -> tuple[bool, str]:
    """T1 VoiceStyle 枚举与场景配置"""
    styles = list(VoiceStyle)
    scenes = list(SCENE_VOICE_STYLES.keys())
    checks = []
    checks.append(len(styles) >= 7)  # warm, calm, playful, serious, intimate, morning, night
    checks.append(VoiceStyle.WARM in styles)
    checks.append(len(scenes) >= 6)  # at least 6 scenes
    checks.append("boot_greeting" in scenes)
    checks.append("morning_brief" in scenes)
    checks.append("anniversary" in scenes)
    return all(checks), f"styles={len(styles)}, scenes={len(scenes)}"


def t2_tts_cache() -> tuple[bool, str]:
    """T2 TTSCache 读写与容量限制"""
    with tempfile.TemporaryDirectory() as td:
        cache = TTSCache(cache_dir=td, max_entries=3)

        # 写入空文件模拟缓存
        fake_path = Path(td) / "test1.wav"
        fake_path.write_bytes(b"fake audio 1")
        cache.put("你好世界", VoiceStyle.WARM.value, "minimax", str(fake_path))

        # 读取缓存
        result = cache.get("你好世界", VoiceStyle.WARM.value, "minimax")
        checks = []
        checks.append(result is not None)
        checks.append(str(fake_path) in result)

        # 容量限制测试
        for i in range(5):
            p = Path(td) / f"audio_{i}.wav"
            p.write_bytes(b"x")
            cache.put(f"text_{i}", VoiceStyle.WARM.value, "minimax", str(p))

        # 应该只剩下 3 条
        remaining = sum(
            1 for k in cache._index
            if Path(cache._index[k]["path"]).exists()
        )
        checks.append(len(cache._index) <= 3)

        # 未命中
        miss = cache.get("不存在的文本", VoiceStyle.WARM.value, "minimax")
        checks.append(miss is None)

        return all(checks), f"hit={result is not None}, index_size={len(cache._index)}, miss={miss is None}"


def t3_enhanced_tts_init() -> tuple[bool, str]:
    """T3 EnhancedTTSEngine 初始化"""
    engine = EnhancedTTSEngine(
        api_key="",
        provider=TTSProvider.MINIMAX,
        default_style=VoiceStyle.CALM,
    )
    checks = []
    checks.append(engine.provider == TTSProvider.MINIMAX)
    checks.append(engine.default_style == VoiceStyle.CALM)
    checks.append(engine.cache is not None)
    # 没有 key 也可能可用（edge_tts）
    checks.append(hasattr(engine, '_edge_tts_available'))
    return all(checks), f"provider={engine.provider.value}, style={engine.default_style.value}"


def t4_scene_config() -> tuple[bool, str]:
    """T4 场景化配置获取"""
    engine = EnhancedTTSEngine(api_key="")
    boot_cfg = engine._get_scene_config("boot_greeting")
    morning_cfg = engine._get_scene_config("morning_brief")
    unknown_cfg = engine._get_scene_config("nonexistent_scene")

    checks = []
    checks.append(boot_cfg.get("style") == VoiceStyle.WARM)
    checks.append(morning_cfg.get("style") == VoiceStyle.MORNING)
    checks.append(0.5 < boot_cfg.get("speed", 0) < 1.5)
    checks.append(unknown_cfg.get("style") == engine.default_style)
    return all(checks), f"boot_style={boot_cfg.get('style').value}, morning_style={morning_cfg.get('style').value}"


def t5_tts_result_model() -> tuple[bool, str]:
    """T5 TTSResult 数据模型"""
    with tempfile.TemporaryDirectory() as td:
        # 成功结果
        p = Path(td) / "ok.wav"
        p.write_bytes(b"fake")
        ok = TTSResult(success=True, audio_path=str(p), text="测试", style="warm", provider="test")
        checks = []
        checks.append(ok.is_valid)
        checks.append(ok.text == "测试")
        checks.append(ok.style == "warm")

        # 失败结果
        fail = TTSResult(success=False, error="no key")
        checks.append(not fail.is_valid)
        checks.append(fail.error == "no key")

        # 缓存命中
        cached = TTSResult(success=True, audio_path=str(p), cached=True)
        checks.append(cached.cached)

        return all(checks), f"valid={ok.is_valid}, error={fail.error}, cached={cached.cached}"


def t6_image_result_model() -> tuple[bool, str]:
    """T6 ImageResult 数据模型"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "img.svg"
        p.write_text("<svg></svg>")
        ok = ImageResult(success=True, image_path=str(p), prompt="测试图", width=512, height=512)
        fail = ImageResult(success=False, error="no api")

        checks = []
        checks.append(ok.is_valid)
        checks.append(ok.width == 512)
        checks.append(ok.height == 512)
        checks.append(not fail.is_valid)
        checks.append(fail.error == "no api")
        return all(checks), f"valid={ok.is_valid}, size={ok.width}x{ok.height}"


def t7_image_generator_init() -> tuple[bool, str]:
    """T7 ImageGenerator 初始化"""
    gen = ImageGenerator(api_key="", provider=ImageProvider.DOODLE)
    checks = []
    checks.append(gen.provider == ImageProvider.DOODLE)
    checks.append(gen.output_dir.exists())
    checks.append(hasattr(gen, '_doodle_fallback'))
    return all(checks), f"provider={gen.provider.value}, dir={gen.output_dir.name}"


def t8_image_doodle_fallback() -> tuple[bool, str]:
    """T8 doodle fallback 生成 SVG 占位图"""
    with tempfile.TemporaryDirectory() as td:
        gen = ImageGenerator(api_key="", provider=ImageProvider.DOODLE, output_dir=td)
        result = gen._doodle_fallback("星空下的猫", 512, 384)
        checks = []
        checks.append(result.success)
        checks.append(result.is_valid)
        checks.append(result.provider == "doodle")
        checks.append(result.width == 512)
        checks.append(result.height == 384)
        checks.append(result.image_path and result.image_path.endswith(".svg"))
        # 检查 SVG 内容
        if result.image_path:
            content = Path(result.image_path).read_text(encoding="utf-8")
            checks.append("<svg" in content)
            checks.append("星空" in content)
        return all(checks), f"w={result.width}, h={result.height}, provider={result.provider}, svg={'<svg' in Path(result.image_path).read_text() if result.image_path else False}"


def t9_multimodal_output_init() -> tuple[bool, str]:
    """T9 MultimodalOutputEngine 初始化"""
    engine = MultimodalOutputEngine(enable_tts=True, enable_image=True)
    checks = []
    checks.append(engine.tts is not None)
    checks.append(engine.image_gen is not None)
    checks.append(engine.enable_tts)
    checks.append(engine.enable_image)
    return all(checks), f"tts_ok={engine.tts is not None}, img_ok={engine.image_gen is not None}"


def t10_scene_list() -> tuple[bool, str]:
    """T10 场景列表获取"""
    engine = MultimodalOutputEngine()
    scenes = engine.get_available_scenes()
    checks = []
    checks.append(len(scenes) >= 6)
    keys = [s["key"] for s in scenes]
    checks.append("boot_greeting" in keys)
    checks.append("morning_brief" in keys)
    checks.append("anniversary" in keys)
    checks.append(all("description" in s for s in scenes))
    return all(checks), f"scenes={len(scenes)}, keys={[s['key'] for s in scenes[:3]]}..."


def t11_compat_legacy_tts() -> tuple[bool, str]:
    """T11 与现有 TTSEngine 兼容"""
    try:
        from voice.tts_engine import TTSEngine
        engine = TTSEngine(api_key="")
        checks = []
        checks.append(hasattr(engine, 'synthesize'))
        checks.append(hasattr(engine, 'synthesize_to_path'))
        checks.append(engine.voice_id == "female-qingxin")
        return all(checks), f"has_synthesize={hasattr(engine, 'synthesize')}, voice={engine.voice_id}"
    except ImportError as e:
        return False, f"import failed: {e}"


def main() -> int:
    tests = [
        t1_voice_style_enum,
        t2_tts_cache,
        t3_enhanced_tts_init,
        t4_scene_config,
        t5_tts_result_model,
        t6_image_result_model,
        t7_image_generator_init,
        t8_image_doodle_fallback,
        t9_multimodal_output_init,
        t10_scene_list,
        t11_compat_legacy_tts,
    ]

    print("=" * 60)
    print("Aerie v11.3 · S4 M4.2 多模态输出验证")
    print("=" * 60)

    passed = 0
    for test in tests:
        ok, detail = test()
        status = "✓" if ok else "✗"
        name = test.__doc__ or test.__name__
        print(f"  {status} {name}  {detail}")
        if ok:
            passed += 1

    total = len(tests)
    print()
    print("=" * 60)
    print(f"结果: {passed}/{total} 通过")
    print("=" * 60)

    if passed == total:
        print("\n🎉 M4.2 多模态输出全部通过！")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 项未通过，请检查。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
