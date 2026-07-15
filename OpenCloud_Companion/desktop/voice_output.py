"""语音输出模块

使用 pyttsx3 实现本地 TTS 语音合成
- 离线可用，零 API 费用
- 支持语速/音量调节
"""
from __future__ import annotations

import asyncio
import queue
import threading
from typing import Optional

from loguru import logger


class VoiceOutput:
    """本地 TTS 语音输出"""

    def __init__(self):
        self._engine = None
        self._available = False
        self._speaking = False
        self._queue: queue.Queue = queue.Queue()
        self._init_tts()

    def _init_tts(self):
        try:
            import pyttsx3
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", 180)  # 语速
            self._engine.setProperty("volume", 0.9)  # 音量

            # 尝试设置中文语音
            voices = self._engine.getProperty("voices")
            for voice in voices:
                if "chinese" in voice.name.lower() or "zh" in voice.id.lower():
                    self._engine.setProperty("voice", voice.id)
                    break

            self._available = True
            logger.info("TTS 语音合成已就绪")

            # 启动消费线程
            t = threading.Thread(target=self._run_loop, daemon=True, name="TTS-Thread")
            t.start()
        except ImportError:
            logger.warning("pyttsx3 未安装，语音输出不可用")
        except Exception as e:
            logger.warning(f"TTS 初始化失败: {e}")

    @property
    def available(self) -> bool:
        return self._available

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def say(self, text: str, rate: Optional[int] = None, volume: Optional[float] = None):
        """
        朗读文本（非阻塞，放入队列）。

        Args:
            text: 要朗读的文本
            rate: 语速（默认 180）
            volume: 音量 (0.0-1.0，默认 0.9)
        """
        if not self._available:
            return

        self._queue.put((text, rate, volume))

    def say_sync(self, text: str):
        """同步朗读（阻塞直到完成）"""
        if not self._engine:
            return
        try:
            self._speaking = True
            self._engine.say(text)
            self._engine.runAndWait()
        except Exception as e:
            logger.warning(f"TTS 朗读失败: {e}")
        finally:
            self._speaking = False

    def stop(self):
        """停止当前朗读"""
        if self._engine:
            try:
                self._engine.stop()
            except Exception:
                pass
        self._speaking = False
        # 清空队列
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _run_loop(self):
        """消费线程：逐个朗读队列中的文本"""
        while self._available:
            try:
                text, rate, volume = self._queue.get(timeout=1)
                if self._engine:
                    if rate:
                        self._engine.setProperty("rate", rate)
                    if volume is not None:
                        self._engine.setProperty("volume", volume)
                    self._speaking = True
                    self._engine.say(text)
                    self._engine.runAndWait()
                    self._speaking = False
            except queue.Empty:
                continue
            except Exception as e:
                logger.warning(f"TTS 线程异常: {e}")
                self._speaking = False
