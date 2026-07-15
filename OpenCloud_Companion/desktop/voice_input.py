"""语音输入模块

使用 SpeechRecognition 实现离线语音识别（Vosk）
- 按住录音、松开识别
- 支持中文普通话
"""
from __future__ import annotations

import threading
import queue
from typing import Optional, Callable

from loguru import logger


class VoiceInput:
    """语音输入管理器"""

    def __init__(self):
        self._recognizer = None
        self._microphone = None
        self._available = False
        self._init_speech_recognition()

    def _init_speech_recognition(self):
        try:
            import speech_recognition as sr
            self._recognizer = sr.Recognizer()
            self._available = True
            logger.info("SpeechRecognition 已就绪")
        except ImportError:
            logger.warning("speech_recognition 未安装，语音输入不可用")
        except Exception as e:
            logger.warning(f"语音输入初始化失败: {e}")

    @property
    def available(self) -> bool:
        return self._available

    def listen_once(
        self,
        timeout: float = 5.0,
        phrase_time_limit: float = 10.0,
    ) -> Optional[str]:
        """
        监听一次语音输入，返回识别文本。

        Args:
            timeout: 等待开始说话的超时（秒）
            phrase_time_limit: 单次录音最长时长（秒）

        Returns:
            识别文本或 None
        """
        if not self._available:
            logger.warning("语音输入不可用")
            return None

        try:
            import speech_recognition as sr

            with sr.Microphone() as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.5)
                logger.debug("正在聆听...")
                audio = self._recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit,
                )

            # 尝试离线识别（Vosk）
            try:
                text = self._recognizer.recognize_vosk(audio, language="zh-CN")
                # Vosk 返回 JSON: {"text": "..."}
                import json
                result = json.loads(text)
                text = result.get("text", "").strip()
                if text:
                    logger.info(f"语音识别 (Vosk): {text}")
                    return text
            except Exception:
                pass

            # 回退到 Google 在线识别
            try:
                text = self._recognizer.recognize_google(audio, language="zh-CN")
                logger.info(f"语音识别 (Google): {text}")
                return text
            except Exception:
                pass

            logger.debug("语音识别无结果")
            return None

        except sr.WaitTimeoutError:
            logger.debug("聆听超时")
            return None
        except Exception as e:
            logger.warning(f"语音识别异常: {e}")
            return None

    def listen_async(self, on_result: Callable[[Optional[str]], None]):
        """异步监听（在独立线程中运行）"""
        def _run():
            result = self.listen_once()
            on_result(result)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
