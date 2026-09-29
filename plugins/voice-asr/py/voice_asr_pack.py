"""voice-asr 功能包 —— 离线语音识别（sherpa-onnx + SenseVoice）。

契约要点：

- **顶层不 import sherpa_onnx / numpy**：重库推迟到 `start(companion)`；
- **模型路径走 `ctx.pack_path("models", ...)`**，绝不在代码里写死盘符；
- **失败软着陆**：模型缺失 / 依赖缺失时工具返回
  `{"status": "unavailable", "error": ...}` 并说清缺什么；
- `start()` 成功后把真 provider 挂进 `companion.voice_service.asr_provider`，
  让既有的语音投递链路直接受益（不必改核心代码）。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_CTX: Any = None
_RECOGNIZER: Optional[Any] = None
_ERROR: str = ""

# 模型目录与常见文件名（发布产物由 build_plugin_pack 装配）
_MODEL_SUBDIR = "models/sensevoice"
_DEFAULT_SAMPLE_RATE = 16000


def _state() -> dict[str, Any]:
    return {"ready": _RECOGNIZER is not None, "error": _ERROR}


def _unavailable(reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "error": reason or "ASR 未就绪",
        "hint": "确认 voice-asr 功能包已安装（含 models/sensevoice 下的模型与 tokens.txt）",
    }


def _model_dir() -> Optional[Path]:
    try:
        if _CTX is None:
            return None
        return Path(_CTX.pack_path(*_MODEL_SUBDIR.split("/")))
    except Exception:
        logger.debug("voice-asr: 解析模型目录失败", exc_info=True)
        return None


def _pick_model_file(model_dir: Path) -> Optional[Path]:
    """挑一个可用的模型文件：优先 int8（体积小、CPU 友好）。"""
    for name in ("model.int8.onnx", "model.onnx", "sense-voice.int8.onnx"):
        candidate = model_dir / name
        if candidate.is_file():
            return candidate
    onnx_files = sorted(model_dir.glob("*.onnx"))
    return onnx_files[0] if onnx_files else None


def _read_wav(path: Path) -> tuple[Any, int]:
    """读 16-bit PCM wav → (float32 归一化采样, 采样率)。只用 stdlib + numpy。"""
    import numpy as np
    import wave

    with wave.open(str(path), "rb") as fh:
        channels = fh.getnchannels()
        width = fh.getsampwidth()
        rate = fh.getframerate()
        frames = fh.readframes(fh.getnframes())

    if width != 2:
        raise ValueError(f"只支持 16-bit PCM wav，当前 {width * 8}-bit")

    samples = np.frombuffer(frames, dtype=np.int16).astype("float32") / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate


def start(companion: Any) -> None:
    """惰性加载 sherpa-onnx SenseVoice；失败只记录原因，核心继续跑。"""
    global _RECOGNIZER, _ERROR

    config: dict[str, Any] = {}
    try:
        if _CTX is not None:
            config = _CTX.get_config() or {}
    except Exception:
        logger.debug("voice-asr: 读取配置失败，用默认值", exc_info=True)

    model_dir = _model_dir()
    if model_dir is None or not model_dir.is_dir():
        _RECOGNIZER = None
        _ERROR = f"模型目录不存在：{_MODEL_SUBDIR}"
        logger.warning("voice-asr: %s", _ERROR)
        return

    model_file = _pick_model_file(model_dir)
    tokens = model_dir / "tokens.txt"
    if model_file is None or not tokens.is_file():
        _RECOGNIZER = None
        _ERROR = f"模型文件不完整（需要 *.onnx 与 tokens.txt）：{model_dir}"
        logger.warning("voice-asr: %s", _ERROR)
        return

    try:
        import sherpa_onnx

        _RECOGNIZER = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model_file),
            tokens=str(tokens),
            num_threads=int(config.get("num_threads", 2) or 2),
            sample_rate=_DEFAULT_SAMPLE_RATE,
            use_itn=bool(config.get("use_itn", True)),
            language=str(config.get("language", "") or ""),
            provider="cpu",
        )
        _ERROR = ""
        logger.info("voice-asr: SenseVoice 就绪 (%s)", model_file.name)
    except Exception as exc:  # noqa: BLE001
        _RECOGNIZER = None
        _ERROR = f"{type(exc).__name__}: {exc}"
        logger.warning("voice-asr: 加载失败（%s）", _ERROR)
        return

    # 把真 provider 接进既有语音链路（不改核心代码，只替换协议实现）。
    try:
        service = getattr(companion, "voice_service", None)
        if service is not None:
            service.asr_provider = SenseVoiceAsrProvider()
            logger.info("voice-asr: 已接管 voice_service.asr_provider")
    except Exception:
        logger.debug("voice-asr: 挂接 voice_service 失败（不影响工具调用）", exc_info=True)


def stop() -> None:
    global _RECOGNIZER
    _RECOGNIZER = None


# ── 转写 ────────────────────────────────────────────────

def transcribe(audio_path: str) -> dict[str, Any]:
    """把音频文件转成文本。"""
    if _RECOGNIZER is None:
        return _unavailable(_ERROR)
    target = Path(str(audio_path or "")).expanduser()
    if not target.is_file():
        return {"error": f"音频文件不存在：{target}"}

    try:
        samples, rate = _read_wav(target)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"读取音频失败：{exc}"}

    try:
        stream = _RECOGNIZER.create_stream()
        stream.accept_waveform(rate, samples)
        _RECOGNIZER.decode_stream(stream)
        text = str(stream.result.text or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("voice-asr: 转写失败", exc_info=True)
        return {"status": "error", "error": str(exc)[:300]}

    return {
        "status": "ok",
        "text": text,
        "duration_sec": round(len(samples) / float(rate or 1), 2),
        "sample_rate": rate,
    }


class SenseVoiceAsrProvider:
    """`core.voice_service.AsrProvider` 协议的真实现（sherpa-onnx SenseVoice）。"""

    provider_id = "sherpa_sensevoice"
    model = "sensevoice-int8"

    def transcribe(
        self,
        *,
        audio_ref: str,
        request_id: str,
        owner_id: str,
        metadata: dict[str, Any],
    ) -> Any:
        from core.voice_service import AsrTranscript

        del metadata
        if _RECOGNIZER is None:
            return AsrTranscript(
                status="unavailable",
                error_code="asr_unavailable",
                provider_id=self.provider_id,
                model=self.model,
                metadata={"request_id": request_id, "owner_id": owner_id, "error": _ERROR},
            )

        result = transcribe(audio_ref)
        if result.get("status") != "ok":
            return AsrTranscript(
                status="error",
                error_code="transcribe_failed",
                provider_id=self.provider_id,
                model=self.model,
                metadata={
                    "request_id": request_id,
                    "owner_id": owner_id,
                    "error": str(result.get("error") or result)[:300],
                },
            )
        return AsrTranscript(
            status="ok",
            text=str(result["text"]),
            duration_sec=float(result.get("duration_sec") or 0.0),
            confidence=0.0,   # SenseVoice 不吐置信度，如实留 0 而不是编一个
            provider_id=self.provider_id,
            model=self.model,
            metadata={"request_id": request_id, "owner_id": owner_id},
        )


# ── 注册 ────────────────────────────────────────────────

def register(ctx: Any) -> None:
    global _CTX
    _CTX = ctx

    ctx.tool_registry.register(
        "voice_asr_transcribe",
        transcribe,
        {
            "type": "function",
            "function": {
                "name": "voice_asr_transcribe",
                "description": "把本机上的音频文件离线转写成文本（sherpa-onnx SenseVoice，无需联网）。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "audio_path": {"type": "string", "description": "音频文件绝对路径（16-bit PCM wav）"},
                    },
                    "required": ["audio_path"],
                },
            },
        },
        provider_hint="text",
        category="utility",
    )
