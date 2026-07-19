"""Aerie · 云栖 v0.1.0-beta.1 — Multimodal Input Processor.

Handles image understanding, OCR, and audio transcription,
seamlessly integrating with the Agent perception pipeline.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class AttachmentType(str, Enum):
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"
    UNKNOWN = "unknown"


class OCRQuality(str, Enum):
    LOW = "low"          # fast, keyword extraction
    STANDARD = "standard"  # balanced
    HIGH = "high"        # detailed, layout-aware


@dataclass
class ImageAttachment:
    path: str
    mime_type: str = "image/png"
    width: int = 0
    height: int = 0
    size_bytes: int = 0
    caption: str = ""           # LLM-generated caption
    ocr_text: str = ""          # OCR extracted text
    description: str = ""       # full visual description
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.path and Path(self.path).exists():
            try:
                if self.size_bytes == 0:
                    self.size_bytes = Path(self.path).stat().st_size
                if not self.mime_type or self.mime_type == "image/png":
                    import mimetypes
                    guessed = mimetypes.guess_type(self.path)[0]
                    if guessed:
                        self.mime_type = guessed
            except Exception:
                pass

    @property
    def is_valid(self) -> bool:
        return bool(self.path) and Path(self.path).exists()

    def to_base64(self) -> str:
        if not self.is_valid:
            return ""
        data = Path(self.path).read_bytes()
        return base64.b64encode(data).decode("ascii")

    def data_url(self) -> str:
        b64 = self.to_base64()
        return f"data:{self.mime_type};base64,{b64}" if b64 else ""


@dataclass
class AudioAttachment:
    path: str
    mime_type: str = "audio/wav"
    duration_sec: float = 0.0
    size_bytes: int = 0
    transcript: str = ""
    language: str = "zh"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.path and Path(self.path).exists():
            try:
                if self.size_bytes == 0:
                    self.size_bytes = Path(self.path).stat().st_size
                if not self.mime_type or self.mime_type == "audio/wav":
                    import mimetypes
                    guessed = mimetypes.guess_type(self.path)[0]
                    if guessed:
                        self.mime_type = guessed
            except Exception:
                pass

    @property
    def is_valid(self) -> bool:
        return bool(self.path) and Path(self.path).exists()


@dataclass
class MultimodalResult:
    """Result of processing a multimodal message."""
    text_content: str = ""
    images: list[ImageAttachment] = field(default_factory=list)
    audio: list[AudioAttachment] = field(default_factory=list)
    files: list[dict] = field(default_factory=list)
    ocr_texts: list[str] = field(default_factory=list)
    transcripts: list[str] = field(default_factory=list)
    has_vision: bool = False
    has_audio: bool = False
    combined_prompt: str = ""

    def summary_text(self) -> str:
        parts = [self.text_content] if self.text_content else []
        for i, img in enumerate(self.images):
            label = f"[图片 {i+1}]"
            if img.description:
                parts.append(f"{label}: {img.description}")
            elif img.caption:
                parts.append(f"{label}: {img.caption}")
            if img.ocr_text:
                parts.append(f"{label} OCR:\n{img.ocr_text}")
        for i, aud in enumerate(self.audio):
            if aud.transcript:
                parts.append(f"[语音 {i+1}]: {aud.transcript}")
        return "\n\n".join(parts)


class OCRService:
    """Lightweight OCR service.

    Priority:
    1. pytesseract (if installed)
    2. easyocr (if installed)
    3. fallback: image metadata only
    """

    def __init__(self, quality: OCRQuality = OCRQuality.STANDARD) -> None:
        self.quality = quality
        self._tesseract_available = False
        self._easyocr_reader = None
        self._init_backends()

    def _init_backends(self) -> None:
        try:
            import pytesseract  # noqa: F401
            self._tesseract_available = True
            logger.debug("OCR: pytesseract available")
        except ImportError:
            pass

        if not self._tesseract_available:
            try:
                import easyocr  # noqa: F401
                self._easyocr_reader = easyocr.Reader(
                    ["ch_sim", "en"], gpu=False, verbose=False
                )
                logger.debug("OCR: easyocr available")
            except ImportError:
                pass

        if not self._tesseract_available and self._easyocr_reader is None:
            logger.info("OCR: no backend available, will return empty text")

    @property
    def is_available(self) -> bool:
        return self._tesseract_available or self._easyocr_reader is not None

    def extract_text(self, image_path: str, lang: str = "chi_sim+eng") -> str:
        if not Path(image_path).exists():
            return ""

        if self._tesseract_available:
            try:
                import pytesseract
                from PIL import Image
                img = Image.open(image_path)
                text = pytesseract.image_to_string(img, lang=lang)
                return text.strip()
            except Exception as e:
                logger.debug("pytesseract OCR failed: %s", e)

        if self._easyocr_reader is not None:
            try:
                results = self._easyocr_reader.readtext(image_path, detail=0)
                return "\n".join(results).strip()
            except Exception as e:
                logger.debug("easyocr failed: %s", e)

        return ""


class ImageAnalyzer:
    """Image understanding via multimodal LLM providers.

    Supports:
    - Caption generation (short)
    - Detailed description
    - Visual Q&A
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model: str = "gpt-4o-mini",
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.api_base = api_base or os.getenv("OPENAI_API_BASE", "")
        self.model = model
        self._client = None
        if self.api_key:
            try:
                from openai import AsyncOpenAI
                kwargs = {"api_key": self.api_key}
                if self.api_base:
                    kwargs["base_url"] = self.api_base
                self._client = AsyncOpenAI(**kwargs)
            except ImportError:
                logger.warning("openai package not available — image analysis disabled")

    @property
    def is_available(self) -> bool:
        return self._client is not None and bool(self.api_key)

    async def caption(self, image_path: str, prompt: str = "用一句话描述这张图片") -> str:
        if not self.is_available:
            return ""
        try:
            return await self._analyze(image_path, prompt, max_tokens=100)
        except Exception as e:
            logger.warning("Image caption failed: %s", e)
            return ""

    async def describe(self, image_path: str) -> str:
        if not self.is_available:
            return ""
        prompt = "请详细描述这张图片的内容，包括主体、背景、颜色、构图、文字等所有可见元素。"
        try:
            return await self._analyze(image_path, prompt, max_tokens=500)
        except Exception as e:
            logger.warning("Image description failed: %s", e)
            return ""

    async def _analyze(self, image_path: str, prompt: str, max_tokens: int = 300) -> str:
        if not self._client or not Path(image_path).exists():
            return ""

        mime = mimetypes.guess_type(image_path)[0] or "image/png"
        b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"

        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""


class AudioTranscriber:
    """Audio-to-text transcription service.

    Supports:
    - Multiple OpenAI-compatible Whisper API providers (auto-fallback)
    - Local whisper (if installed)
    - Fallback: empty transcript
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model: str = "whisper-1",
    ) -> None:
        self._providers: list[dict] = []
        self._local_model = None
        self._init_providers(api_key, api_base, model)
        self._init_local()

    def _init_providers(self, api_key: Optional[str], api_base: Optional[str], model: str) -> None:
        import os

        explicit_key = api_key or os.getenv("OPENAI_API_KEY", "")
        explicit_base = api_base or os.getenv("OPENAI_API_BASE", "")
        if explicit_key and explicit_base:
            self._providers.append({
                "name": "openai",
                "key": explicit_key,
                "base_url": explicit_base,
                "model": model,
            })

        provider_specs = [
            ("DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1",
             "DASHSCOPE_WHISPER_MODEL", "qwen-long", "qwen"),
        ]

        for key_env, url_env, default_url, model_env, default_model, name in provider_specs:
            key = os.getenv(key_env, "")
            if not key:
                continue
            if any(p["name"] == name for p in self._providers):
                continue
            base_url = os.getenv(url_env, "") or default_url
            model_name = os.getenv(model_env, "") or default_model
            self._providers.append({
                "name": name,
                "key": key,
                "base_url": base_url,
                "model": model_name,
            })

        if self._providers:
            logger.info("AudioTranscriber: %d API provider(s) configured: %s",
                        len(self._providers),
                        ", ".join(p["name"] for p in self._providers))

    def _init_local(self) -> None:
        try:
            import os
            ffmpeg_dir = Path(__file__).parent.parent / "ffmpeg" / "ffmpeg-7.1-essentials_build" / "bin"
            if ffmpeg_dir.exists():
                os.environ["PATH"] = str(ffmpeg_dir) + os.pathsep + os.environ.get("PATH", "")
            import whisper
            self._local_model = whisper.load_model("base")
            logger.debug("AudioTranscriber: local whisper available (base model)")
            return
        except ImportError:
            pass
        except Exception as e:
            logger.warning("AudioTranscriber: local whisper init failed: %s", e)

        try:
            import vosk
            model_path = Path(__file__).parent.parent / "models" / "vosk-cn" / "vosk-model-small-cn-0.22"
            if model_path.exists():
                self._local_model = vosk.Model(str(model_path))
                logger.debug("AudioTranscriber: vosk local ASR available")
            else:
                logger.debug("AudioTranscriber: vosk model not found at %s", model_path)
        except ImportError:
            pass
        except Exception as e:
            logger.warning("AudioTranscriber: vosk init failed: %s", e)

    @property
    def is_available(self) -> bool:
        return len(self._providers) > 0 or self._local_model is not None

    @property
    def providers(self) -> list[dict]:
        return [{"name": p["name"], "model": p["model"]} for p in self._providers]

    async def transcribe(self, audio_path: str, language: str = "zh") -> str:
        if not Path(audio_path).exists():
            return ""

        if self._local_model is not None:
            try:
                import vosk
                if isinstance(self._local_model, vosk.Model):
                    import wave
                    wf = wave.open(audio_path, "rb")
                    if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getcomptype() != "NONE":
                        logger.warning("AudioTranscriber: vosk requires 16kHz mono PCM")
                        wf.close()
                    else:
                        rec = vosk.KaldiRecognizer(self._local_model, wf.getframerate())
                        rec.SetWords(True)
                        text_parts = []
                        while True:
                            data = wf.readframes(4000)
                            if len(data) == 0:
                                break
                            if rec.AcceptWaveform(data):
                                result = rec.Result()
                                text_parts.append(result)
                        final_result = rec.FinalResult()
                        if final_result:
                            text_parts.append(final_result)
                        wf.close()
                        import json
                        text = ""
                        for part in text_parts:
                            try:
                                j = json.loads(part)
                                text += j.get("text", "") + " "
                            except:
                                pass
                        text = text.strip()
                        if text:
                            logger.debug("AudioTranscriber: vosk succeeded")
                            return text
                else:
                    try:
                        import numpy as np
                        import soundfile as sf
                        audio_data, sr = sf.read(audio_path)
                        if len(audio_data.shape) > 1:
                            audio_data = audio_data.mean(axis=1)
                        if sr != 16000:
                            import librosa
                            audio_data = librosa.resample(audio_data, orig_sr=sr, target_sr=16000)
                        audio_data = audio_data.astype(np.float32)
                        logger.info("AudioTranscriber: whisper input: shape=%s, dtype=%s", audio_data.shape, audio_data.dtype)
                        result = self._local_model.transcribe(audio_data, language=language)
                        text = result.get("text", "").strip()
                        logger.info("AudioTranscriber: whisper output: '%s'", text)
                        if text:
                            logger.debug("AudioTranscriber: whisper succeeded (local)")
                            return text
                    except Exception as e:
                        logger.warning("AudioTranscriber: whisper with soundfile failed: %s", e)
                        try:
                            import av
                            import numpy as np
                            container = av.open(audio_path)
                            sr = container.streams.audio[0].rate if container.streams.audio else 16000
                            audio_frames = []
                            for frame in container.decode(audio=0):
                                arr = frame.to_ndarray()
                                if arr.ndim > 1:
                                    arr = arr.mean(axis=0)
                                audio_frames.append(arr)
                            container.close()
                            if audio_frames:
                                max_len = max(len(f) for f in audio_frames)
                                padded = []
                                for f in audio_frames:
                                    if len(f) < max_len:
                                        f = np.pad(f, (0, max_len - len(f)))
                                    padded.append(f)
                                audio_data = np.concatenate(padded)
                                if sr != 16000:
                                    import librosa
                                    audio_data = librosa.resample(audio_data, orig_sr=sr, target_sr=16000)
                                audio_data = audio_data.astype(np.float32)
                                result = self._local_model.transcribe(audio_data, language=language)
                                text = result.get("text", "").strip()
                                if text:
                                    logger.debug("AudioTranscriber: whisper succeeded (PyAV)")
                                    return text
                        except Exception as e2:
                            logger.warning("AudioTranscriber: whisper with PyAV failed: %s", e2)
            except Exception as e:
                logger.warning("AudioTranscriber: local fallback failed: %s", e)

        for provider in self._providers:
            try:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(
                    api_key=provider["key"],
                    base_url=provider["base_url"],
                )
                with open(audio_path, "rb") as f:
                    resp = await client.audio.transcriptions.create(
                        model=provider["model"],
                        file=f,
                        language=language if language and language != "auto" else "",
                    )
                text = resp.text.strip()
                if text:
                    logger.debug("AudioTranscriber: %s succeeded", provider["name"])
                    return text
            except Exception as e:
                logger.warning("AudioTranscriber: %s failed: %s", provider["name"], e)
                continue

        return ""


def detect_attachment_type(file_path: str) -> AttachmentType:
    """Detect attachment type from file extension/mime."""
    ext = Path(file_path).suffix.lower()
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".svg"}
    audio_exts = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".wma", ".opus"}
    video_exts = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv"}

    if ext in image_exts:
        return AttachmentType.IMAGE
    if ext in audio_exts:
        return AttachmentType.AUDIO
    if ext in video_exts:
        return AttachmentType.VIDEO
    return AttachmentType.FILE


class MultimodalInputProcessor:
    """Unified multimodal input processor.

    Orchestrates OCR, image analysis, and audio transcription
    to produce a combined text representation of the message.
    """

    def __init__(
        self,
        image_analyzer: Optional[ImageAnalyzer] = None,
        ocr_service: Optional[OCRService] = None,
        audio_transcriber: Optional[AudioTranscriber] = None,
        enable_ocr: bool = True,
        enable_image_caption: bool = True,
        enable_transcription: bool = True,
    ) -> None:
        self.image_analyzer = image_analyzer or ImageAnalyzer()
        self.ocr_service = ocr_service or OCRService()
        self.audio_transcriber = audio_transcriber or AudioTranscriber()
        self.enable_ocr = enable_ocr
        self.enable_image_caption = enable_image_caption
        self.enable_transcription = enable_transcription

    async def process_message(
        self,
        text: str,
        attachments: Optional[list[dict]] = None,
    ) -> MultimodalResult:
        """Process a message with text + attachments into a MultimodalResult."""
        result = MultimodalResult(text_content=text or "")

        if not attachments:
            result.combined_prompt = result.summary_text()
            return result

        for att in attachments:
            path = att.get("path") or att.get("file") or ""
            if not path:
                continue

            att_type = detect_attachment_type(path)

            if att_type == AttachmentType.IMAGE:
                img = await self._process_image(path, att)
                result.images.append(img)
                if img.ocr_text:
                    result.ocr_texts.append(img.ocr_text)
                result.has_vision = True

            elif att_type == AttachmentType.AUDIO:
                aud = await self._process_audio(path, att)
                result.audio.append(aud)
                if aud.transcript:
                    result.transcripts.append(aud.transcript)
                result.has_audio = True

            else:
                result.files.append(att)

        result.combined_prompt = result.summary_text()
        return result

    async def _process_image(self, path: str, att_meta: dict) -> ImageAttachment:
        img = ImageAttachment(
            path=path,
            mime_type=att_meta.get("mime_type") or mimetypes.guess_type(path)[0] or "image/png",
            size_bytes=Path(path).stat().st_size if Path(path).exists() else 0,
            metadata={k: v for k, v in att_meta.items() if k not in {"path", "file", "mime_type"}},
        )

        # Try to get image dimensions
        try:
            from PIL import Image
            with Image.open(path) as pil_img:
                img.width, img.height = pil_img.size
        except Exception:
            pass

        # OCR
        if self.enable_ocr and self.ocr_service.is_available:
            img.ocr_text = self.ocr_service.extract_text(path)

        # Caption / description via vision LLM
        if self.enable_image_caption and self.image_analyzer.is_available:
            img.caption = await self.image_analyzer.caption(path)
            if img.ocr_text:
                # If we have OCR, do a detailed description too
                img.description = await self.image_analyzer.describe(path)

        return img

    async def _process_audio(self, path: str, att_meta: dict) -> AudioAttachment:
        aud = AudioAttachment(
            path=path,
            mime_type=att_meta.get("mime_type") or mimetypes.guess_type(path)[0] or "audio/wav",
            size_bytes=Path(path).stat().st_size if Path(path).exists() else 0,
            language=att_meta.get("language", "zh"),
            metadata={k: v for k, v in att_meta.items() if k not in {"path", "file", "mime_type", "language"}},
        )

        if self.enable_transcription and self.audio_transcriber.is_available:
            aud.transcript = await self.audio_transcriber.transcribe(path, aud.language)

        return aud
