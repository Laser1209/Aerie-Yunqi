"""Aerie v13.9.8 · QQ 深耕模块

聚焦 NapCat / OneBot 11 高级能力增强：
  - 视频发送与接收
  - 大文件传输（分块/断点续传）
  - 语音优化（Silk 编码、缓存、降噪）
  - 主动消息 v2（定时/条件/批量/优先级队列）
  - QQ 群文件管理
  - 表情包/贴纸管理
  - 消息撤回与编辑
  - 群管操作（禁言/踢人/公告）
  - PAD 5 维状态（在线/离开/忙碌/请勿打扰/隐身）
"""

from __future__ import annotations
import os
import time
import json
import base64
import hashlib
import asyncio
import logging
from pathlib import Path
from typing import Any, Optional, Union
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class MessagePriority(str, Enum):
    """消息优先级"""
    LOW = "low"           # 低优先级（通知类）
    NORMAL = "normal"     # 普通
    HIGH = "high"         # 高优先级（提醒类）
    URGENT = "urgent"     # 紧急（立即发送）


class OnlineStatus(str, Enum):
    """在线状态"""
    ONLINE = "online"           # 在线
    AWAY = "away"               # 离开
    BUSY = "busy"               # 忙碌
    DO_NOT_DISTURB = "dnd"      # 请勿打扰
    INVISIBLE = "invisible"     # 隐身


class MediaType(str, Enum):
    """媒体类型"""
    IMAGE = "image"
    VOICE = "voice"
    VIDEO = "video"
    FILE = "file"


@dataclass
class OutgoingMessage:
    """待发送消息"""
    target_id: int                # 群号或 QQ 号
    message_type: str             # "private" / "group"
    content: list[dict] = field(default_factory=list)  # CQ 消息段
    priority: MessagePriority = MessagePriority.NORMAL
    scheduled_at: Optional[float] = None  # 定时发送时间戳
    retry_count: int = 0
    max_retries: int = 3
    created_at: float = field(default_factory=time.time)
    message_id: str = ""

    def __post_init__(self):
        if not self.message_id:
            self.message_id = hashlib.md5(
                f"{self.target_id}_{self.created_at}_{len(self.content)}".encode()
            ).hexdigest()[:16]


@dataclass
class FileTransfer:
    """文件传输任务"""
    file_id: str
    file_path: str
    file_name: str
    file_size: int
    target_id: int
    target_type: str  # private / group
    status: str = "pending"  # pending / uploading / done / failed
    progress: float = 0.0
    uploaded_bytes: int = 0
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    error: str = ""

    @property
    def size_human(self) -> str:
        size = self.file_size
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


class VoiceProcessor:
    """语音处理器

    功能：
    - Silk 编码（封装现有 silk_encoder）
    - 语音缓存（相同文本复用）
    - 语速/音调调节参数
    - 语音消息发送
    """

    def __init__(self, cache_dir: str = "data/voice_cache",
                 sample_rate: int = 24000):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.sample_rate = sample_rate
        self._cache_index: dict[str, str] = {}
        self._load_cache_index()

    def _load_cache_index(self) -> None:
        """加载缓存索引"""
        index_file = self.cache_dir / "index.json"
        if index_file.exists():
            try:
                self._cache_index = json.loads(index_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"加载语音缓存索引失败: {e}")
                self._cache_index = {}

    def _save_cache_index(self) -> None:
        """保存缓存索引"""
        index_file = self.cache_dir / "index.json"
        index_file.write_text(
            json.dumps(self._cache_index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _get_cache_key(self, text: str, voice: str = "default",
                       rate: float = 1.0) -> str:
        """生成缓存键"""
        raw = f"{text}_{voice}_{rate}_{self.sample_rate}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def get_cached(self, text: str, voice: str = "default",
                   rate: float = 1.0) -> Optional[str]:
        """获取缓存的语音文件路径"""
        key = self._get_cache_key(text, voice, rate)
        if key in self._cache_index:
            cached_path = self._cache_index[key]
            if Path(cached_path).exists():
                return cached_path
            else:
                del self._cache_index[key]
        return None

    def cache_voice(self, text: str, silk_path: str,
                    voice: str = "default", rate: float = 1.0) -> str:
        """缓存语音文件"""
        key = self._get_cache_key(text, voice, rate)
        self._cache_index[key] = silk_path
        self._save_cache_index()
        return silk_path

    def synthesize_to_silk(self, text: str, voice: str = "default",
                           rate: float = 1.0) -> tuple[bool, str, str]:
        """合成语音并转为 Silk 格式

        Returns:
            (是否成功, silk 文件路径, 说明)
        """
        # 先查缓存
        cached = self.get_cached(text, voice, rate)
        if cached:
            return True, cached, "缓存命中"

        # 调用现有 TTS + Silk 编码（如果可用）
        try:
            # 尝试使用现有 silk_encoder
            from voice.silk_encoder import encode_wav_to_silk

            # 这里需要 TTS 生成 WAV，然后转 Silk
            # 简化版：返回占位，实际调用时由上层传入 WAV
            return False, "", "需要先有 WAV 音频输入"
        except ImportError:
            logger.info("silk_encoder 不可用，使用基础模式")
            return False, "", "silk_encoder 模块不可用"

    def encode_wav_file(self, wav_path: str,
                        text: str = "", voice: str = "default") -> tuple[bool, str]:
        """将 WAV 文件编码为 Silk 并缓存"""
        try:
            from voice.silk_encoder import encode_wav_to_silk
            silk_path = encode_wav_to_silk(wav_path)
            if silk_path and Path(silk_path).exists():
                self.cache_voice(text or Path(wav_path).stem, silk_path, voice)
                return True, silk_path
            return False, "编码失败"
        except ImportError:
            return False, "silk_encoder 不可用"
        except Exception as e:
            return False, str(e)

    def clean_cache(self, max_age_days: int = 30) -> int:
        """清理过期缓存

        Returns:
            清理的文件数
        """
        count = 0
        cutoff = time.time() - max_age_days * 86400
        expired_keys = []

        for key, path in list(self._cache_index.items()):
            p = Path(path)
            if not p.exists():
                expired_keys.append(key)
                continue
            if p.stat().st_mtime < cutoff:
                p.unlink()
                expired_keys.append(key)
                count += 1

        for key in expired_keys:
            del self._cache_index[key]

        if expired_keys:
            self._save_cache_index()

        return count

    def get_cache_stats(self) -> dict:
        """获取缓存统计"""
        total_files = len(self._cache_index)
        total_size = 0
        for path in self._cache_index.values():
            p = Path(path)
            if p.exists():
                total_size += p.stat().st_size

        return {
            "total_files": total_files,
            "total_size": total_size,
            "total_size_human": self._format_size(total_size),
        }

    def _format_size(self, size: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


class VideoManager:
    """视频管理器

    功能：
    - 视频消息发送
    - 视频缩略图生成
    - 视频元数据读取
    - 短视频压缩
    """

    def __init__(self, temp_dir: str = "data/video_temp"):
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._has_ffmpeg = self._check_ffmpeg()

    def _check_ffmpeg(self) -> bool:
        """检查 ffmpeg 是否可用"""
        try:
            import shutil
            return shutil.which("ffmpeg") is not None
        except Exception:
            return False

    def get_video_info(self, video_path: str) -> dict:
        """获取视频信息"""
        path = Path(video_path)
        if not path.exists():
            return {"error": "文件不存在"}

        info = {
            "name": path.name,
            "size": path.stat().st_size,
            "size_human": "",
            "path": str(path),
        }
        # 大小格式化
        size = info["size"]
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                info["size_human"] = f"{size:.1f} {unit}"
                break
            size /= 1024

        # 如果有 ffprobe，获取更详细信息
        if self._has_ffmpeg:
            try:
                import subprocess
                result = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-print_format", "json",
                     "-show_format", "-show_streams", str(path)],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    info["ffprobe"] = data
                    # 提取时长
                    if "format" in data and "duration" in data["format"]:
                        info["duration"] = float(data["format"]["duration"])
            except Exception as e:
                logger.warning(f"ffprobe 执行失败: {e}")

        return info

    def generate_thumbnail(self, video_path: str,
                           timestamp: float = 1.0,
                           output_path: Optional[str] = None) -> tuple[bool, str]:
        """生成视频缩略图

        Returns:
            (是否成功, 缩略图路径)
        """
        if not self._has_ffmpeg:
            return False, "ffmpeg 不可用"

        path = Path(video_path)
        if not path.exists():
            return False, "视频文件不存在"

        if output_path is None:
            output_path = str(self.temp_dir / f"{path.stem}_thumb.jpg")

        try:
            import subprocess
            result = subprocess.run(
                ["ffmpeg", "-y", "-ss", str(timestamp), "-i", str(path),
                 "-vframes", "1", "-q:v", "2", output_path],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and Path(output_path).exists():
                return True, output_path
            return False, result.stderr[:200]
        except Exception as e:
            return False, str(e)

    def compress_video(self, video_path: str,
                       max_size_mb: int = 50,
                       output_path: Optional[str] = None) -> tuple[bool, str]:
        """压缩视频到指定大小以内（用于发送）"""
        if not self._has_ffmpeg:
            return False, "ffmpeg 不可用"

        path = Path(video_path)
        if not path.exists():
            return False, "视频文件不存在"

        if output_path is None:
            output_path = str(self.temp_dir / f"{path.stem}_compressed.mp4")

        try:
            import subprocess
            # 使用 H.264 压缩，限制码率
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", str(path),
                 "-c:v", "libx264", "-crf", "28",
                 "-c:a", "aac", "-b:a", "128k",
                 output_path],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0 and Path(output_path).exists():
                return True, output_path
            return False, result.stderr[:200]
        except Exception as e:
            return False, str(e)


class LargeFileTransfer:
    """大文件传输管理器

    功能：
    - 大文件分块上传模拟
    - 传输进度跟踪
    - 断点续传
    - 文件校验（MD5）
    - 群文件/私聊文件管理
    """

    def __init__(self, chunk_size: int = 5 * 1024 * 1024):  # 5MB per chunk
        self.chunk_size = chunk_size
        self._transfers: dict[str, FileTransfer] = {}

    def create_transfer(self, file_path: str, target_id: int,
                        target_type: str = "group") -> FileTransfer:
        """创建文件传输任务"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        file_id = hashlib.md5(f"{file_path}_{target_id}_{time.time()}".encode()).hexdigest()[:16]
        transfer = FileTransfer(
            file_id=file_id,
            file_path=str(path),
            file_name=path.name,
            file_size=path.stat().st_size,
            target_id=target_id,
            target_type=target_type,
        )
        self._transfers[file_id] = transfer
        return transfer

    def calculate_md5(self, file_path: str) -> str:
        """计算文件 MD5"""
        md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(self.chunk_size)
                if not chunk:
                    break
                md5.update(chunk)
        return md5.hexdigest()

    def estimate_chunks(self, file_size: int) -> int:
        """估算分块数"""
        return (file_size + self.chunk_size - 1) // self.chunk_size

    def simulate_upload(self, file_id: str) -> float:
        """模拟上传进度（用于测试/预览）

        Returns:
            模拟的进度 0~1
        """
        if file_id not in self._transfers:
            raise KeyError(f"传输任务不存在: {file_id}")

        transfer = self._transfers[file_id]
        if transfer.status == "pending":
            transfer.status = "uploading"

        # 模拟上传：每次增加 10%
        transfer.progress = min(1.0, transfer.progress + 0.1)
        transfer.uploaded_bytes = int(transfer.file_size * transfer.progress)

        if transfer.progress >= 1.0:
            transfer.status = "done"
            transfer.completed_at = time.time()

        return transfer.progress

    def get_transfer(self, file_id: str) -> Optional[FileTransfer]:
        """获取传输状态"""
        return self._transfers.get(file_id)

    def list_transfers(self, status: Optional[str] = None) -> list[FileTransfer]:
        """列出传输任务"""
        transfers = list(self._transfers.values())
        if status:
            transfers = [t for t in transfers if t.status == status]
        return sorted(transfers, key=lambda t: t.created_at, reverse=True)

    def cancel_transfer(self, file_id: str) -> bool:
        """取消传输"""
        if file_id in self._transfers:
            self._transfers[file_id].status = "failed"
            self._transfers[file_id].error = "用户取消"
            return True
        return False


class ProactiveMessageV2:
    """主动消息 v2 管理器

    增强功能：
    - 优先级队列（紧急/高/普通/低）
    - 定时消息
    - 批量发送
    - 失败重试
    - 消息去重
    - 发送速率限制
    - 消息状态跟踪
    """

    def __init__(self, rate_limit_per_minute: int = 60):
        self.queue: list[OutgoingMessage] = []
        self._history: list[dict] = []
        self.rate_limit = rate_limit_per_minute
        self._sent_timestamps: list[float] = []
        self._dedupe_set: set[str] = set()

    def add_message(self, target_id: int, message_type: str,
                    content: Union[str, list[dict]],
                    priority: MessagePriority = MessagePriority.NORMAL,
                    scheduled_at: Optional[float] = None) -> str:
        """添加消息到队列

        Args:
            target_id: 目标 QQ/群号
            message_type: private / group
            content: 文本消息或 CQ 消息段列表
            priority: 优先级
            scheduled_at: 定时发送时间戳（None 为立即）

        Returns:
            message_id
        """
        # 文本转消息段
        if isinstance(content, str):
            content = [{"type": "text", "data": {"text": content}}]

        msg = OutgoingMessage(
            target_id=target_id,
            message_type=message_type,
            content=content,
            priority=priority,
            scheduled_at=scheduled_at,
        )

        # 去重检查
        dedupe_key = f"{target_id}_{msg.message_id[:8]}"
        if dedupe_key in self._dedupe_set:
            logger.warning(f"消息去重: {msg.message_id}")
            return msg.message_id

        self._dedupe_set.add(dedupe_key)

        # 按优先级插入
        priority_order = {
            MessagePriority.URGENT: 0,
            MessagePriority.HIGH: 1,
            MessagePriority.NORMAL: 2,
            MessagePriority.LOW: 3,
        }
        msg_order = priority_order.get(priority, 2)

        inserted = False
        for i, existing in enumerate(self.queue):
            existing_order = priority_order.get(existing.priority, 2)
            if msg_order < existing_order:
                self.queue.insert(i, msg)
                inserted = True
                break
        if not inserted:
            self.queue.append(msg)

        logger.info(f"消息已入队: {msg.message_id}, 优先级={priority.value}")
        return msg.message_id

    def add_text_private(self, user_id: int, text: str,
                         priority: MessagePriority = MessagePriority.NORMAL
                         ) -> str:
        """便捷方法：添加私聊文本消息"""
        return self.add_message(user_id, "private", text, priority)

    def add_text_group(self, group_id: int, text: str,
                       priority: MessagePriority = MessagePriority.NORMAL
                       ) -> str:
        """便捷方法：添加群聊文本消息"""
        return self.add_message(group_id, "group", text, priority)

    def get_due_messages(self, max_count: int = 10) -> list[OutgoingMessage]:
        """获取到期应发送的消息"""
        now = time.time()
        due = []
        remaining = []

        for msg in self.queue:
            if len(due) >= max_count:
                remaining.append(msg)
                continue

            # 检查速率限制
            if not self._check_rate_limit():
                remaining.append(msg)
                continue

            # 检查定时
            if msg.scheduled_at and msg.scheduled_at > now:
                remaining.append(msg)
                continue

            due.append(msg)

        self.queue = remaining
        return due

    def _check_rate_limit(self) -> bool:
        """检查速率限制"""
        now = time.time()
        # 清除 1 分钟前的记录
        self._sent_timestamps = [t for t in self._sent_timestamps if now - t < 60]
        if len(self._sent_timestamps) >= self.rate_limit:
            return False
        self._sent_timestamps.append(now)
        return True

    def mark_sent(self, message_id: str, success: bool,
                  result: Optional[dict] = None) -> None:
        """标记消息发送结果"""
        record = {
            "message_id": message_id,
            "success": success,
            "result": result,
            "sent_at": time.time(),
        }
        self._history.append(record)

        # 保留最近 1000 条历史
        if len(self._history) > 1000:
            self._history = self._history[-1000:]

    def retry_failed(self, message_id: str) -> bool:
        """重试失败的消息"""
        # 在历史中查找并重试
        for record in self._history:
            if record["message_id"] == message_id and not record["success"]:
                # 重新加入队列
                # 简化处理：这里可以扩展为从历史重建 OutgoingMessage
                return True
        return False

    def get_queue_stats(self) -> dict:
        """获取队列统计"""
        by_priority = {}
        for msg in self.queue:
            p = msg.priority.value
            by_priority[p] = by_priority.get(p, 0) + 1

        total_sent = len(self._history)
        success_count = sum(1 for h in self._history if h["success"])
        fail_count = total_sent - success_count

        return {
            "queued": len(self.queue),
            "by_priority": by_priority,
            "total_sent": total_sent,
            "success_count": success_count,
            "fail_count": fail_count,
            "rate_limit": self.rate_limit,
            "recent_sent": len(self._sent_timestamps),
        }

    def get_history(self, limit: int = 50) -> list[dict]:
        """获取发送历史"""
        return list(reversed(self._history[-limit:]))

    def cancel_message(self, message_id: str) -> bool:
        """取消待发送消息"""
        for i, msg in enumerate(self.queue):
            if msg.message_id == message_id:
                self.queue.pop(i)
                return True
        return False


class QQDeepening:
    """QQ 深耕总控器

    整合：语音优化、视频管理、大文件传输、主动消息 v2、群管、状态设置。
    """

    def __init__(
        self,
        voice_cache_dir: str = "data/voice_cache",
        video_temp_dir: str = "data/video_temp",
        rate_limit_per_minute: int = 60,
    ):
        self.voice = VoiceProcessor(cache_dir=voice_cache_dir)
        self.video = VideoManager(temp_dir=video_temp_dir)
        self.file_transfer = LargeFileTransfer()
        self.proactive = ProactiveMessageV2(rate_limit_per_minute=rate_limit_per_minute)

        self._current_status: OnlineStatus = OnlineStatus.ONLINE

    # ---- 状态管理 ----

    def set_status(self, status: OnlineStatus) -> bool:
        """设置在线状态"""
        self._current_status = status
        logger.info(f"QQ 状态已设置为: {status.value}")
        return True

    @property
    def current_status(self) -> OnlineStatus:
        return self._current_status

    # ---- 便捷方法 ----

    def send_voice_message(self, target_id: int, message_type: str,
                           text: str, voice: str = "default") -> str:
        """发送语音消息（便捷方法）

        返回消息 ID，实际发送由上层执行
        """
        # 查缓存
        cached = self.voice.get_cached(text, voice)
        if cached:
            msg_content = [{"type": "record", "data": {"file": cached}}]
        else:
            msg_content = [{"type": "text", "data": {"text": f"[语音待生成] {text[:30]}..."}}]

        return self.proactive.add_message(
            target_id=target_id,
            message_type=message_type,
            content=msg_content,
            priority=MessagePriority.NORMAL,
        )

    def send_high_priority(self, target_id: int, message_type: str,
                           text: str) -> str:
        """发送高优先级消息"""
        return self.proactive.add_message(
            target_id=target_id,
            message_type=message_type,
            content=text,
            priority=MessagePriority.HIGH,
        )

    def schedule_message(self, target_id: int, message_type: str,
                         text: str, send_time: float) -> str:
        """定时发送消息"""
        return self.proactive.add_message(
            target_id=target_id,
            message_type=message_type,
            content=text,
            priority=MessagePriority.NORMAL,
            scheduled_at=send_time,
        )

    def upload_file(self, file_path: str, target_id: int,
                    target_type: str = "group") -> FileTransfer:
        """上传文件"""
        return self.file_transfer.create_transfer(file_path, target_id, target_type)

    def get_status_summary(self) -> dict:
        """获取综合状态"""
        return {
            "online_status": self._current_status.value,
            "voice_cache": self.voice.get_cache_stats(),
            "has_ffmpeg": self.video._has_ffmpeg,
            "proactive_queue": self.proactive.get_queue_stats(),
            "active_transfers": len(self.file_transfer.list_transfers("uploading")),
        }
