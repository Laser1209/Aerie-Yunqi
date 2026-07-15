#!/usr/bin/env python3
"""
OpenCloud Companion - Phase 5+ 入口

新增功能：
- 工具系统（文件/系统/网页/待办）+ Function Calling
- 命令执行流水线（COMMAND/QUERY → AI决策 → 工具执行 → QQ回复）
- 桌面悬浮球（PyQt6）+ 对话窗口 + 每日简报卡片
- 知识库（文档导入/检索/问答）+ 技能市场
- 定时任务：每日简报 + 晚安问候 + 天气更新
- 语音输入/输出（本地离线）

用法：
    python main.py                    # 完整启动（QQ + UI + 定时任务）
    python main.py --no-ui            # 仅后台服务（无桌面 UI）
    python main.py --ui-only          # 仅桌面 UI（调试用）
    python main.py --no-scheduler     # 禁用定时任务
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import threading
import yaml
from pathlib import Path
from typing import Any, Dict, Optional

import dotenv
from loguru import logger

from communication.message import IncomingMessage, OutgoingReply, Intent
from communication.qq_client import QQClient
from core.brain import AIBrain
from core.personality import PersonalityEngine
from core.classifier import IntentClassifier
from core.pipeline import CommandPipeline
from memory.chat_log import ChatLogger
from memory.mem0_store import MemoryStore
from memory.context_builder import ContextBuilder
from tools.registry import ToolRegistry
from tools.file_ops import ReadFileTool, WriteFileTool, ListDirTool, SearchFilesTool
from tools.system_ops import OpenAppTool, SystemStatusTool
from tools.web_ops import WebSearchTool, WeatherTool, FetchUrlTool
from tools.todo_manager import TodoCreateTool, TodoListTool, TodoCompleteTool, TodoDeleteTool
from knowledge import KnowledgeBase
from tools.skill_manager import SkillManager
from tools.doc_pipeline import DocumentPipeline, ConvertDocumentTool
from scheduler import TaskScheduler
from scheduler.tasks import BriefAggregator

PROJECT_ROOT = Path(__file__).resolve().parent


def load_env() -> None:
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        dotenv.load_dotenv(env_file)
        logger.info(f"已加载环境变量: {env_file}")
    else:
        logger.warning(f".env 文件不存在: {env_file}")


def load_yaml(path: Path) -> Dict[str, Any]:
    import re
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    def replace_env(match):
        var = match.group(1)
        default = match.group(2) if match.group(2) else ""
        return os.getenv(var, default)
    content = re.sub(r"\$\{(\w+):?([^}]*)\}", replace_env, content)
    return yaml.safe_load(content)


def init_logging(config: Dict[str, Any]) -> None:
    log_config = config.get("logging", {})
    logger.remove()
    level = log_config.get("level", "INFO")
    log_file = PROJECT_ROOT / log_config.get("file", "logs/companion.log")
    rotation = log_config.get("rotation", "10 MB")
    retention = log_config.get("retention", "7 days")
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger.add(log_file, rotation=rotation, retention=retention, level=level, encoding="utf-8",
               format="{time:YYYY-MM-DD HH:mm:ss} [{level}] {message}")
    logger.add(sys.stderr, level=level, colorize=True,
               format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")
    logger.info(f"日志已初始化: level={level}, file={log_file}")


def load_config() -> Dict[str, Any]:
    settings_path = PROJECT_ROOT / "config" / "settings.yaml"
    if not settings_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {settings_path}")
    config = load_yaml(settings_path)
    logger.info(f"配置已加载: {settings_path}")
    return config


def load_persona() -> Dict[str, Any]:
    persona_path = PROJECT_ROOT / "config" / "persona.yaml"
    if persona_path.exists():
        persona = load_yaml(persona_path)
        logger.info(f"性格配置已加载: {persona.get('name', 'unknown')}")
        return persona
    logger.warning(f"性格配置文件不存在: {persona_path}，使用默认")
    return {}


def _create_tool_registry() -> ToolRegistry:
    """创建并注册所有工具"""
    registry = ToolRegistry()
    registry.register_all([
        ReadFileTool(), WriteFileTool(), ListDirTool(), SearchFilesTool(),
        OpenAppTool(), SystemStatusTool(),
        WebSearchTool(), WeatherTool(), FetchUrlTool(),
        TodoCreateTool(), TodoListTool(), TodoCompleteTool(), TodoDeleteTool(),
    ])
    logger.info(f"工具已注册: {registry.tool_names}")
    return registry


class Companion:
    """OpenCloud Companion - Phase 4 主应用"""

    def __init__(self):
        load_env()
        self.config = load_config()
        init_logging(self.config)
        self.persona_config = load_persona()

        ai_config = self.config.get("ai", {})
        self.brain = AIBrain(ai_config)

        self.personality = PersonalityEngine(self.persona_config)

        memory_config = self.config.get("memory", {})
        chat_log_path = memory_config.get("chat_log_path", "data/chat_log.db")
        self.chat_log = ChatLogger(chat_log_path)
        self.memory_store = MemoryStore(self.chat_log, memory_config)
        self.classifier = IntentClassifier(self.brain)
        self.tool_registry = _create_tool_registry()

        # Phase 4: 知识库 + 技能市场
        knowledge_config = self.config.get("knowledge", {})
        self._embedder = self._create_embedder()
        self.knowledge_base = KnowledgeBase(
            db_path=knowledge_config.get("db_path", "data/knowledge.db"),
            embedding_dim=knowledge_config.get("embedding_dim", 1024),
            brain=self.brain,
            embedder=self._embedder,
        )

        self.doc_pipeline = DocumentPipeline(brain=self.brain)
        self.tool_registry.register(ConvertDocumentTool(self.doc_pipeline))

        napcat_config = self.config.get("napcat", {})
        ws_uri = napcat_config.get("ws_uri", "ws://localhost:3001")
        self.qq_client = QQClient(uri=ws_uri)

        self.skill_manager = SkillManager(
            skills_dir=self.config.get("skills", {}).get("dir", "skills"),
            tool_registry=self.tool_registry,
            qq_sender=self.qq_client.send_message,
        )

        self.context_builder = ContextBuilder(
            personality=self.personality, chat_log=self.chat_log,
            memory_store=self.memory_store,
            knowledge_base=self.knowledge_base,
            embedder=self._embedder,
            config=memory_config,
        )

        self.command_pipeline = CommandPipeline(
            brain=self.brain, personality=self.personality,
            context_builder=self.context_builder, tool_registry=self.tool_registry,
            chat_log=self.chat_log,
        )

        self._running = False
        self._msg_count = 0
        self._floating_ball: Any = None
        self._chat_window: Any = None

        # Phase 5+: 定时任务 + 简报聚合 + 语音
        self.scheduler = TaskScheduler()
        self.brief_aggregator = BriefAggregator(
            brain=self.brain,
            todo_manager=None,  # 使用 tools 层的 todo_manager
        )
        self._setup_scheduler_callbacks()
        # 语音模块（延迟初始化，按需加载）
        self._voice_input: Any = None
        self._voice_output: Any = None

    def _create_embedder(self):
        """创建嵌入函数（使用硅基流动 embedding API）"""
        import numpy as np
        from openai import AsyncOpenAI

        silicon_key = os.getenv("SILICONFLOW_API_KEY", "")
        if not silicon_key:
            return None

        client = AsyncOpenAI(
            api_key=silicon_key,
            base_url="https://api.siliconflow.cn/v1",
        )

        async def embed(text: str) -> np.ndarray:
            try:
                resp = await client.embeddings.create(
                    model="BAAI/bge-large-zh-v1.5",
                    input=text,
                )
                return np.array(resp.data[0].embedding, dtype=np.float32)
            except Exception as e:
                logger.warning(f"嵌入失败: {e}")
                raise

        return embed

    def _setup_scheduler_callbacks(self):
        """注册定时任务回调"""

        async def on_daily_brief():
            """每日简报推送"""
            data = await self.brief_aggregator.aggregate()
            if not self._floating_ball:
                return
            brief = self._floating_ball.brief
            brief.set_greeting(data["greeting"], data["date"])
            brief.clear_sections()
            if data.get("weather"):
                w = data["weather"]
                brief.add_weather(w.get("icon", "⛅"), w.get("text", ""), w.get("temp", ""))
            if data.get("todos"):
                brief.add_todos(data["todos"])
            if data.get("system"):
                s = data["system"]
                brief.add_system_status(s.get("cpu_pct", 0), s.get("mem_pct", 0), s.get("disk_pct", 0))

            brief.set_on_closed(lambda: brief.hide())
            self._floating_ball.show_daily_brief()
            logger.info("每日简报已推送")

        async def on_goodnight(user_id: int):
            """晚安问候推送"""
            msg = await self.brief_aggregator.generate_goodnight(user_id)
            try:
                await self.qq_client.send_message(user_id, msg)
                logger.info("晚安问候已发送")
            except Exception as e:
                logger.warning(f"晚安问候发送失败: {e}")

        self.scheduler.set_callbacks(
            on_brief=on_daily_brief,
            on_goodnight=on_goodnight,
        )

    def _init_voice(self):
        """延迟初始化语音模块"""
        try:
            from desktop.voice_input import VoiceInput
            from desktop.voice_output import VoiceOutput
            self._voice_input = VoiceInput()
            self._voice_output = VoiceOutput()
            logger.info(
                f"语音模块: 输入={'可用' if self._voice_input.available else '不可用'}, "
                f"输出={'可用' if self._voice_output.available else '不可用'}"
            )
        except Exception as e:
            logger.debug(f"语音模块加载跳过: {e}")

    async def handle_message(self, msg: IncomingMessage) -> OutgoingReply | None:
        """Phase 4 消息处理流水线"""
        self._msg_count += 1
        logger.info(f"[#{self._msg_count}] 收到: {msg.summary()}")

        # 意图分类
        intent_result = await self.classifier.classify(msg.content)
        intent_label = intent_result.intent.value
        await self.chat_log.log_incoming(msg, intent=intent_label)

        # 桌面托盘通知（新消息到达）
        if self._floating_ball:
            self._floating_ball.set_unread(self._floating_ball._unread_count + 1)

        # 分流：闲聊走 Phase 2 流程，命令/查询走 Phase 3 工具流水线
        if intent_result.intent in (Intent.COMMAND, Intent.QUERY):
            try:
                reply = await self.command_pipeline.execute(msg)
                return reply
            except Exception as e:
                logger.exception(f"命令流水线失败: {e}")
                return OutgoingReply(
                    user_id=msg.user_id,
                    content=f"主人，执行操作时出错了 (´;ω;`)\n{str(e)[:200]}",
                )

        # 闲聊路径
        try:
            messages = await self.context_builder.build(msg)
            ai_reply = await self.brain.generate_reply(messages)
        except RuntimeError as e:
            logger.exception(f"AI 调用失败: {e}")
            ai_reply = "主人对不起...我现在脑子有点转不动了，稍等一下再找我好不好 (´;ω;`)"

        reply = OutgoingReply(user_id=msg.user_id, content=ai_reply, msg_type=msg.msg_type)
        await self.chat_log.log_outgoing(reply)
        return reply

    async def start(self) -> None:
        """
        Phase 5+ 启动入口（仅业务逻辑，不包含 UI 事件循环）。
        UI 由 main() 在主线程创建 QApplication + 启动 Qt 事件循环。
        """
        self._running = True
        persona_name = self.persona_config.get("name", "伊塔")

        logger.info(f"✨ {persona_name} 正在启动 (Phase 5)...")

        await self.chat_log.initialize()
        await self.knowledge_base.initialize()
        kb_stats = await self.knowledge_base.get_stats()
        logger.info(f"知识库: {kb_stats['total_active']} 条活跃, {kb_stats['categories']} 个分类")

        stats = await self.chat_log.get_stats()
        if stats and stats.get("user_msgs", 0) > 0:
            logger.info(f"聊天记录: {stats.get('user_msgs', 0)} 条用户消息, "
                        f"{stats.get('assistant_msgs', 0)} 条 Assistant 回复")

        logger.info(f"分类器已就绪（规则引擎 + LLM 辅助）")
        logger.info(f"工具系统: {self.tool_registry.count} 个工具已注册")
        logger.info(f"Function Calling 已启用（tool_choice=auto）")

        # Phase 7: 启动期校验 AI 模型名（防止 401 静默失败）
        try:
            await self.brain.startup_check()
        except Exception as e:
            logger.warning(f"启动期模型校验异常（已忽略）: {e}")

        # Phase 5+: 启动定时任务调度器
        if "--no-scheduler" not in sys.argv:
            try:
                await self.scheduler.start()
            except Exception as e:
                logger.warning(f"定时任务调度器启动失败: {e}")

        # Phase 5+: 延迟初始化语音模块
        self._init_voice()

        try:
            await self.qq_client.listen(self.handle_message)
        except asyncio.CancelledError:
            logger.info("收到停止信号")
        except Exception as e:
            logger.exception(f"运行异常: {e}")
        finally:
            await self.qq_client.stop()
            await self.scheduler.stop()
            await self.chat_log.close()
            await self.knowledge_base.close()
            logger.info(f"{persona_name} 已下线")

    def _start_desktop_ui(self, persona_name: str) -> None:
        """
        在主线程启动 PyQt6 悬浮球（仅初始化 widget，不启动事件循环）。
        事件循环由 main() 在主线程调 app.exec() 启动。
        注意：Companion 的 QApplication 必须在主线程创建（PyQt6 强制要求）。
        """
        from desktop.floating_ball import FloatingBall

        self._floating_ball = FloatingBall(
            app_name=persona_name,
            on_chat_window=self._create_chat_window,
        )
        logger.info(f"桌面悬浮球已创建: {persona_name}")

    def _create_chat_window(self) -> None:
        """创建并显示对话窗口"""
        try:
            from desktop.chat_window import ChatWindow
            from communication.message import IncomingMessage, MessageType, Sender
            from datetime import datetime

            async def on_send(text: str) -> str:
                msg = IncomingMessage(
                    msg_id=0, user_id=0, user_nickname="桌面",
                    msg_type=MessageType.PRIVATE, content=text,
                    raw_message=text, timestamp=datetime.now(),
                    sender=Sender(user_id=0, nickname="桌面"),
                    self_id=0,
                )
                messages = await self.context_builder.build(msg, capability_level="phase4")
                return await self.brain.generate_reply(messages)

            window = ChatWindow(
                companion_name=self.persona_config.get("name", "伊塔"),
                on_send=on_send,
            )
            window.show()
            self._chat_window = window
            logger.info("对话窗口已打开")
        except Exception as e:
            logger.exception(f"对话窗口创建失败: {e}")
            # ===== 新增：错误提示反馈 =====
            # 主人下次点托盘时如果还有问题，能直接看到错误而非仅看日志
            try:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.critical(
                    None,
                    "对话窗口启动失败",
                    f"打开对话窗口时遇到问题：\n\n"
                    f"{type(e).__name__}: {e}\n\n"
                    f"详细日志：logs/companion.log",
                )
            except Exception:
                pass  # 弹窗本身失败也不能崩主流程

    async def stop(self) -> None:
        self._running = False
        await self.qq_client.stop()
        await self.chat_log.close()


async def _async_worker(companion: "Companion", qapp) -> None:
    """子线程运行的 asyncio 协程（QQ 连接 + 调度器）"""
    try:
        await companion.start()
    except Exception as e:
        logger.exception(f"asyncio worker crashed: {e}")
    finally:
        if qapp:
            try:
                from PyQt6.QtCore import QMetaObject, Qt as QtNS
                QMetaObject.invokeMethod(qapp, "quit", QtNS.ConnectionType.QueuedConnection)
            except Exception:
                pass


def main() -> None:
    """
    主入口（同步）：
    - 主线程创建 QApplication + 启动 Qt 事件循环（UI 友好）
    - 子线程运行 asyncio 事件循环（QQ 连接 + 调度器）
    - 两线程通过 QMetaObject 跨线程通信
    """
    enable_ui = "--no-ui" not in sys.argv

    # 1. 主线程创建 QApplication（PyQt6 强制要求）
    qapp = None
    if enable_ui:
        try:
            from PyQt6.QtWidgets import QApplication
            qapp = QApplication.instance() or QApplication(sys.argv)
            qapp.setQuitOnLastWindowClosed(False)
        except Exception as e:
            logger.warning(f"PyQt6 初始化失败，UI 不可用: {e}")
            qapp = None

    # 2. 创建 Companion
    companion = Companion()

    # 3. 主线程创建 FloatingBall widget（不调 exec()）
    if enable_ui and qapp:
        persona_name = companion.persona_config.get("name", "伊塔")
        try:
            companion._start_desktop_ui(persona_name)
        except Exception as e:
            logger.warning(f"桌面 UI 创建失败: {e}")

    # 4. 子线程跑 asyncio（QQ + 调度器）
    import threading
    async_thread = threading.Thread(
        target=lambda: asyncio.run(_async_worker(companion, qapp)),
        daemon=True,
        name="Asyncio-Loop",
    )
    async_thread.start()
    logger.info("asyncio worker thread started")

    # 5. 主线程：阻塞在 Qt 事件循环 / 等待异步线程结束
    if qapp:
        rc = qapp.exec()
        sys.exit(rc)
    else:
        async_thread.join()


if __name__ == "__main__":
    main()
