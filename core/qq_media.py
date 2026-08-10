"""Aerie · 云栖 — QQ 语音 / 表情包多模态预处理.

把 QQ 收到的 ``[CQ:record]`` 语音与 ``[CQ:image]`` / ``[CQ:face]`` 表情包，
从只能看到 CQ 码 / JSON 的原始状态，转成 AI 能理解 + 前端能好看呈现的内容：

- 语音 (record)  : 调 NapCat ``get_record`` 下载并转 mp3 → ASR 转写文字。
- 图片 (image)   : 调 NapCat ``get_image`` 拿到本地文件 → 视觉模型先分类（真实照片/表情包）再解析含义 → 落库缩略图。
- QQ 自带表情(face): 内置 id → 文字含义映射（无需图像）。
- 商城表情(mface): 直接用其 summary 字段。

对外只暴露 :class:`QQMediaPreprocessor`。任何一步失败都回退成干净的占位文案，
绝不把原始 CQ 码泄漏给 AI / 前端，也绝不让整条消息处理崩溃。
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 内置 ffmpeg 目录（与 multimodal_input 保持一致），用于 ffprobe 取语音时长。
_FFMPEG_DIR = _PROJECT_ROOT / "ffmpeg" / "ffmpeg-7.1-essentials_build" / "bin"

# ── QQ 自带表情 face id → 文字含义（常用子集）────────────────
# 参考社区维护的 QQ 表情对照表；未收录的 id 回退成 "[QQ表情 <id>]"。
FACE_TEXT: dict[str, str] = {
    "0": "惊讶", "1": "撇嘴", "2": "色", "3": "发呆", "4": "得意",
    "5": "流泪", "6": "害羞", "7": "闭嘴", "8": "睡", "9": "大哭",
    "10": "尴尬", "11": "发怒", "12": "调皮", "13": "呲牙", "14": "微笑",
    "15": "难过", "16": "酷", "17": "冷汗", "18": "抓狂", "19": "吐",
    "20": "偷笑", "21": "可爱", "22": "白眼", "23": "傲慢", "24": "饥饿",
    "25": "困", "26": "惊恐", "27": "流汗", "28": "憨笑", "29": "大兵",
    "30": "奋斗", "31": "咒骂", "32": "疑问", "33": "嘘", "34": "晕",
    "35": "折磨", "36": "衰", "37": "骷髅", "38": "敲打", "39": "再见",
    "41": "发抖", "42": "爱情", "43": "跳跳", "44": "猪头", "46": "拥抱",
    "49": "蛋糕", "53": "鞭炮", "54": "灯笼", "56": "点赞", "57": "不屑",
    "59": "抱拳", "60": "拳头", "61": "弱", "62": "耶", "63": "抠鼻",
    "64": "哈欠", "65": "委屈", "66": "快哭了", "67": "阴险", "68": "亲亲",
    "69": "吓", "70": "可怜", "74": "微笑", "76": "吐舌", "77": "斜眼笑",
    "78": "捂脸", "79": "妙", "80": "让我看看", "81": "高兴", "82": "哇",
    "83": "哼", "84": "脸红", "85": "破涕为笑", "86": "狂笑", "87": "酸了",
    "88": "发怒", "89": "无语", "90": "吐舌头", "91": "开心", "92": "干杯",
    "96": "得意", "97": "舔屏", "98": "吃瓜", "99": "加油", "100": "捂嘴笑",
    "101": "捂脸", "102": "飞吻", "103": "太棒了", "104": "花痴", "105": "抱抱",
    "106": "棒棒哒", "107": "嫌弃", "108": "生气", "109": "尴尬", "110": "汗",
    "111": "委屈", "112": "捂眼", "113": "戳一戳", "114": "开心", "115": "点赞",
    "116": "疑问", "117": "鼓掌", "118": "欢呼", "119": "加油", "120": "爱你",
    "121": "比心", "122": "666", "123": "加油鸭", "124": "么么哒", "125": "抱抱",
    "126": "开心", "127": "亲亲", "128": "生气", "129": "委屈", "130": "流泪",
    "131": "哈哈", "132": "哼", "133": "微笑", "134": "调皮", "135": "得意",
    "136": "哭", "137": "白眼", "138": "生气", "139": "心碎", "140": "害羞",
    "141": "飞吻", "142": "晚安", "143": "抱抱", "144": "庆祝", "145": "鼓掌",
    "146": "鼓掌", "147": "赞", "148": "嘘", "149": "微笑", "177": "抠鼻",
    "178": "赞", "179": "惊讶", "180": "汗", "181": "吐", "182": "憨笑",
    "183": "委屈", "184": "尴尬", "185": "酷", "186": "得意", "187": "开心",
    "188": "大哭", "189": "流泪", "190": "害羞", "191": "可爱", "192": "飞吻",
    "193": "比心", "194": "加油", "195": "666", "196": "爱你", "197": "棒棒哒",
    "198": "点赞", "199": "鼓掌", "200": "庆祝",
    # 178-200 为 QQ 官方较新的常见表情；其余 id 未收录走 "[QQ表情 <id>]" 回退
}

_CQ_CODE = re.compile(r"\[CQ:[^\]]*\]")


def face_text(face_id: str | int) -> str:
    """把 QQ 表情 id 转成文字含义；未收录则回退成占位文案。"""
    key = str(face_id or "").strip()
    if not key:
        return "[QQ表情]"
    return FACE_TEXT.get(key, f"[QQ表情 {key}]")


# ── 文件路径/字节解析 ─────────────────────────────
def _resolve_local_file(data: dict) -> Optional[str]:
    """从 get_record / get_image 返回的 data 中解析出本地文件路径。

    NapCat 在本机运行时 ``data.file`` 是本地绝对路径；远程部署或返回字节时
    可能是 ``base64://`` / 纯 base64 / http(s) 链接。本地路径直接返回，
    base64 写盘后返回新路径，http(s) 返回空（交给调用方决定）。
    """
    raw = data.get("file") or data.get("path") or data.get("url") or ""
    if not isinstance(raw, str) or not raw:
        return None
    raw = raw.strip()
    if raw.startswith("file:///"):
        p = Path(raw[len("file:///") :])
        return str(p) if p.exists() else None
    if raw.startswith("http://") or raw.startswith("https://"):
        return None
    if raw.startswith("base64://"):
        raw = raw[len("base64://") :]
    # 本地绝对路径
    p = Path(raw)
    if p.is_absolute() and p.exists():
        return str(p)
    # 可能带路径前缀的相对路径
    if p.exists():
        return str(p)
    # 剩下的视为 base64 字节
    try:
        payload = base64.b64decode(raw, validate=False)
    except Exception:
        return None
    if not payload:
        return None
    media_dir = _media_dir()
    media_dir.mkdir(parents=True, exist_ok=True)
    dest = media_dir / f"qq_media_{uuid.uuid4().hex}.bin"
    dest.write_bytes(payload)
    return str(dest)


def _media_dir() -> Path:
    return _PROJECT_ROOT / "data" / "qq_media"


def _audio_duration(path: str) -> float:
    """用内置 ffprobe 取音频时长（秒）；不可用返回 0.0。"""
    ffprobe = _FFMPEG_DIR / "ffprobe.exe" if os.name == "nt" else _FFMPEG_DIR / "ffprobe"
    if not ffprobe.exists():
        # 尝试 PATH 中的 ffprobe
        ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    import subprocess
    try:
        out = subprocess.run(
            [str(ffprobe), "-v", "quiet", "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=15,
        )
        if out.returncode == 0 and out.stdout:
            info = json.loads(out.stdout)
            return float(info["format"]["duration"] or 0.0)
    except Exception:
        return 0.0
    return 0.0


# ── SiliconFlow ASR / Vision 客户端 ───────────────
class _SFClient:
    """SiliconFlow OpenAI 兼容客户端：语音转写 + 图片理解。"""

    def __init__(self) -> None:
        self.api_key = os.getenv("SILICONFLOW_API_KEY", "").strip()
        self.base_url = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.com/v1").strip()
        self.asr_model = "FunAudioLLM/SenseVoiceSmall"
        self.vision_model = (
            os.getenv("VISION_MODEL", "Qwen/Qwen3-VL-8B-Instruct").strip()
            or "Qwen/Qwen3-VL-8B-Instruct"
        )
        self._client = None
        if self.api_key:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
            except Exception as e:  # pragma: no cover
                logger.warning("SiliconFlow client init failed: %s", e)

    @property
    def available(self) -> bool:
        return self._client is not None

    async def transcribe(self, audio_path: str, language: str = "zh") -> str:
        """语音转文字（SenseVoiceSmall），失败返回空串。"""
        if not self.available or not Path(audio_path).exists():
            return ""
        try:
            with open(audio_path, "rb") as f:
                resp = await self._client.audio.transcriptions.create(
                    model=self.asr_model,
                    file=f,
                    language=language if language and language != "auto" else "auto",
                )
            return (getattr(resp, "text", "") or "").strip()
        except Exception as e:
            logger.warning("SiliconFlow ASR failed: %s", e)
            return ""

    async def classify_and_describe(self, image_path: str) -> tuple[str, str]:
        """图片分类 + 描述（Qwen3-VL），失败返回 ("unknown", "")。

        先让视觉模型判定这张图是真实照片/截图，还是表情包/贴纸/梗图，
        再给出含义描述。返回 (kind, desc)，kind ∈ {"photo", "sticker", "unknown"}。
        """
        if not self.available or not Path(image_path).exists():
            return "unknown", ""
        import mimetypes
        mime = mimetypes.guess_type(image_path)[0] or "image/png"
        try:
            b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        except Exception as e:
            logger.warning("read image for vision classify failed: %s", e)
            return "unknown", ""
        data_url = f"data:{mime};base64,{b64}"
        question = (
            "请先判断这张图片的类型，再一句话描述其内容/含义。\n"
            "类型只能是以下两种之一：\n"
            "- photo：真实照片、截图、生活照、风景、实物拍摄等纪实影像\n"
            "- sticker：表情包、贴纸、梗图、Q版卡通表情、网络meme\n"
            "输出格式（严格两行）：\n"
            "type: photo 或 type: sticker\n"
            "desc: <一句话描述>"
        )
        try:
            resp = await self._client.chat.completions.create(
                model=self.vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": question},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    }
                ],
                max_tokens=160,
            )
            raw = (resp.choices[0].message.content or "").strip()
        except Exception as e:
            logger.warning("SiliconFlow vision classify failed: %s", e)
            return "unknown", ""
        return self._parse_classify(raw)

    @staticmethod
    def _parse_classify(raw: str) -> tuple[str, str]:
        """解析视觉模型输出的 ``type/desc`` 两行结构，容错回退。"""
        if not raw:
            return "unknown", ""
        kind = "unknown"
        desc = ""
        for line in raw.splitlines():
            line = line.strip()
            low = line.lower()
            if low.startswith("type"):
                if "sticker" in low:
                    kind = "sticker"
                elif "photo" in low:
                    kind = "photo"
            elif low.startswith("desc"):
                desc = line.split(":", 1)[1].strip() if ":" in line else line[4:].strip()
        if not desc:
            # 兜底：模型没按格式走时，去掉 type 行，把剩余文本当描述
            desc = "\n".join(
                l.strip() for l in raw.splitlines()
                if l.strip() and not l.strip().lower().startswith("type")
            ).strip()
        return kind, desc


class QQMediaPreprocessor:
    """把一条 QQ 入站消息里的语音 / 表情包段解析成可理解内容。

    用法（在 _on_qq_message 里，submit 之前）::

        pre = QQMediaPreprocessor(qq_client=self.qq)
        content, attachments = await pre.preprocess(msg)
        msg.content = content
        msg.attachments = attachments
    """

    def __init__(
        self,
        qq_client: Any = None,
        sf_client: Optional[_SFClient] = None,
        media_dir: str | Path | None = None,
    ) -> None:
        self.qq = qq_client
        self.sf = sf_client or _SFClient()
        self.media_dir = Path(media_dir) if media_dir else _media_dir()
        self.media_dir.mkdir(parents=True, exist_ok=True)

    async def preprocess(self, msg: Any) -> tuple[str, list[dict]]:
        """返回 (content, attachments)。content 为处理后的可读文本，attachments 供前端渲染。"""
        segments = self._segments(msg)
        if not segments:
            return msg.content or "", []

        text_parts: list[str] = []
        attachments: list[dict] = []

        for seg in segments:
            seg_type = (seg.get("type") or "").strip().lower()
            data = seg.get("data") or {}
            try:
                if seg_type == "record":
                    await self._handle_record(data, text_parts, attachments)
                elif seg_type == "image":
                    await self._handle_image(data, text_parts, attachments)
                elif seg_type == "face":
                    text_parts.append(f"[表情:{face_text(data.get('id'))}]")
                elif seg_type == "mface":
                    summary = str(data.get("summary") or "").strip()
                    text_parts.append(f"[表情:{summary}]" if summary else "[表情]")
                elif seg_type == "text":
                    t = str(data.get("text") or "").strip()
                    if t:
                        text_parts.append(t)
            except Exception:
                logger.exception("QQ media segment %s processing failed", seg_type)

        # 兜底：若没有任何可读段，给一个占位，避免空消息/原始 CQ 泄漏
        content = "\n".join(p for p in text_parts if p).strip()
        if not content:
            content = "[多媒体消息]"

        return content, attachments

    def _segments(self, msg: Any) -> list[dict]:
        # 优先用结构化 message 数组；拿不到再退回 CQ 码字符串解析。
        arr = getattr(msg, "raw_event", {})
        if isinstance(arr, dict):
            message = arr.get("message")
            if isinstance(message, list) and message:
                return [s for s in message if isinstance(s, dict)]
        raw = getattr(msg, "content", "") or ""
        return self._parse_cq(raw)

    def _parse_cq(self, raw: str) -> list[dict]:
        """从 CQ 码字符串解析出段列表（保序）。"""
        out: list[dict] = []
        pos = 0
        for m in _CQ_CODE.finditer(raw):
            if m.start() > pos:
                out.append({"type": "text", "data": {"text": raw[pos:m.start()]}})
            body = m.group()[4:-1]  # 去掉 [CQ: 和 ]
            if "," in body:
                seg_type, _, params = body.partition(",")
                data = {}
                for kv in params.split(","):
                    if "=" in kv:
                        k, _, v = kv.partition("=")
                        data[k] = v
                out.append({"type": seg_type, "data": data})
            else:
                out.append({"type": body, "data": {}})
            pos = m.end()
        if pos < len(raw):
            out.append({"type": "text", "data": {"text": raw[pos:]}})
        return out

    # ── 语音 ─────────────────────────────────────
    async def _handle_record(self, data: dict, text_parts: list[str], attachments: list[dict]) -> None:
        file_ref = str(data.get("file") or "").strip()
        label = "[语音]"
        audio_path: Optional[str] = None
        duration = 0.0

        if self.qq and file_ref:
            try:
                resp = await self.qq.get_record(file=file_ref, out_format="mp3")
                if resp and resp.get("status") == "ok":
                    audio_path = _resolve_local_file((resp.get("data") or {}))
            except Exception as e:
                logger.warning("QQ get_record failed for %s: %s", file_ref, e)

        # 也尝试直接从段的 url 下载（NapCat 有时只给 raw silk url）
        if audio_path is None:
            seg_url = str(data.get("url") or "").strip()
            if seg_url.startswith(("http://", "https://")):
                audio_path = await self._download(seg_url, suffix=".amr")

        transcript = ""
        if audio_path:
            duration = _audio_duration(audio_path)
            transcript = await self._transcribe(audio_path)

        if transcript:
            text_parts.append(f"{label} 转写：{transcript}")
        else:
            text_parts.append(label)

        attachments.append({
            "category": "audio",
            "name": "语音",
            "duration": round(duration, 1),
            "transcript": transcript or "",
            "size": Path(audio_path).stat().st_size if audio_path and Path(audio_path).exists() else 0,
        })

    async def _transcribe(self, audio_path: str) -> str:
        # 优先云端 SenseVoice；不可用/失败则回退本地 AudioTranscriber
        text = await self.sf.transcribe(audio_path, language="zh")
        if text:
            return text
        try:
            from core.multimodal_input import AudioTranscriber
            local = AudioTranscriber()
            if local.is_available:
                return await local.transcribe(audio_path, language="zh")
        except Exception as e:
            logger.debug("local ASR fallback failed: %s", e)
        return ""

    # ── 图片 / 表情包 ─────────────────────────────
    async def _handle_image(self, data: dict, text_parts: list[str], attachments: list[dict]) -> None:
        file_ref = str(data.get("file") or "").strip()
        image_path: Optional[str] = None

        if self.qq and file_ref:
            try:
                resp = await self.qq.get_image(file=file_ref)
                if resp and resp.get("status") == "ok":
                    image_path = _resolve_local_file((resp.get("data") or {}))
            except Exception as e:
                logger.warning("QQ get_image failed for %s: %s", file_ref, e)

        if image_path is None:
            seg_url = str(data.get("url") or "").strip()
            if seg_url.startswith(("http://", "https://")):
                image_path = await self._download(seg_url, suffix=".png")

        # 落库到 uploads，拿到前端可展示的 url + thumbnail
        attach = {"category": "image", "name": "图片"}
        if image_path and Path(image_path).exists():
            try:
                from core.attachment_handler import process_image_upload
                raw = Path(image_path).read_bytes()
                content_type = "image/gif" if Path(image_path).suffix.lower() == ".gif" else "image/png"
                saved = process_image_upload(
                    filename=f"qq_image_{uuid.uuid4().hex[:8]}.png",
                    content=raw,
                    content_type=content_type,
                    upload_base=_PROJECT_ROOT / "uploads",
                )
                if saved.get("status") == "ok":
                    attach["url"] = saved.get("url", "")
                    attach["thumbnailUrl"] = saved.get("thumbnail_url", "")
                    attach["thumbnail_url"] = saved.get("thumbnail_url", "")
                    attach["size"] = saved.get("size", 0)
                    attach["saved_as"] = saved.get("saved_as", "")
            except Exception as e:
                logger.warning("QQ image persistence failed: %s", e)

        # 视觉分类 + 描述：区分真实照片 / 表情包，再决定标签与展示名
        kind, desc = ("unknown", "")
        if image_path and Path(image_path).exists():
            kind, desc = await self.sf.classify_and_describe(image_path)

        is_sticker = kind == "sticker"
        if desc:
            text_parts.append(f"[{'表情包' if is_sticker else '图片'}:{desc}]")
        else:
            text_parts.append("[表情包]" if is_sticker else "[图片]")
        if is_sticker:
            attach["name"] = "表情包"
        attachments.append(attach)

    async def _download(self, url: str, suffix: str = ".bin") -> Optional[str]:
        """下载 http(s) 资源到本地 media 目录，失败返回 None。"""
        import httpx
        dest = self.media_dir / f"qq_dl_{uuid.uuid4().hex}{suffix}"
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
            return str(dest)
        except Exception as e:
            logger.warning("QQ media download failed (%s): %s", url[:60], e)
            return None
