#!/usr/bin/env python3
"""
OpenCloud Companion - Phase 2 入口

新增功能：
- 性格引擎（动态 System Prompt + 记忆注入）
- 对话意图分类器（闲聊 / 命令 / 查询）
- 聊天日志存储（SQLite 异步读写）
- 长期记忆检索（回退 chat_log + Phase 3 Mem0 就绪）
- 上下文构建器（性格 + 记忆 + 历史 + 当前消息 统一编排）

启动前请确认：
1. NapCatQQ 已运行且登录了 QQ 号 B（伊塔 3998874040）
2. .env 文件中已配置至少一个 API Key
3. OneBot11 WebSocket 地址正确（默认 ws://localhost:3001）

用法：
    python main.py
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import yaml
from pathlib import Path
from typing import Any, Dict

import dotenv
from loguru import logger

from communication.message import IncomingMessage, OutgoingReply
from communication.qq_client import QQClient
from core.brain import AIBrain
from core.personality import PersonalityEngine
from core.classifier import IntentClassifier
from memory.chat_log import ChatLogger
from memory.mem0_store import MemoryStore
from memory.context_builder import ContextBuilder

# ===== 项目根目录 =====
PROJECT_ROOT = Path(__file__).resolve().parent


def load_env() -> None:
    """加载 .env 环境变量"""
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        dotenv.load_dotenv(env_file)
        logger.info(f"已加载环境变量: {env_file}")
    else:
        logger.warning(
            f".env 文件不存在: {env_file}\n"
            f"请复制 .env.example 为 .env 并填入 API Key"
        )


def load_yaml(path: Path) -> Dict[str, Any]:
    """加载 YAML 配置文件，支持 ${VAR:default} 格式的环境变量替换"""
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
    """初始化日志系统"""
    log_config = config.get("logging", {})
    logger.remove()

    level = log_config.get("level", "INFO")
    log_file = PROJECT_ROOT / log_config.get("file", "logs/companion.log")
    rotation = log_config.get("rotation", "10 MB")
    retention = log_config.get("retention", "7 days")

    log_file.parent.mkdir(parents=True, exist_ok=True)

    logger.add(
        log_file,
        rotation=rotation,
        retention=retention,
        level=level,
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} [{level}] {message}",
    )

    logger.add(
        sys.stderr,
        level=level,
        colorize=True,
        format="<green>{time:HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<level>{message}</level>",
    )

    logger.info(f"日志已初始化: level={level}, file={log_file}")


def load_config() -> Dict[str, Any]:
    """加载所有配置"""
    settings_path = PROJECT_ROOT / "config" / "settings.yaml"
    if not settings_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {settings_path}")

    config = load_yaml(settings_path)
    logger.info(f"配置已加载: {settings_path}")
    return config


def load_persona() -> Dict[str, Any]:
    """加载性格配置"""
    persona_path = PROJECT_ROOT / "config" / "persona.yaml"
    if persona_path.exists():
        persona = load_yaml(persona_path)
        logger.info(f"性格配置已加载: {persona.get('name', 'unknown')}")
        return persona
    else:
        logger.warning(f"性格配置文件不存在: {persona_path}，使用默认")
        return {}


class Companion:
    """OpenCloud Companion - Phase 2 主应用"""

    def __init__(self):
        # ===== 加载配置 =====
        load_env()
        self.config = load_config()
        init_logging(self.config)
        self.persona_config = load_persona()

        # ===== 初始化模块（按依赖拓扑顺序）=====
        # 1. AI 提供商（无依赖）
        ai_config = self.config.get("ai", {})
        self.brain = AIBrain(ai_config)

        # 2. 性格引擎（无依赖）
        self.personality = PersonalityEngine(self.persona_config)

        # 3. 聊天日志（无依赖）
        memory_config = self.config.get("memory", {})
        chat_log_path = memory_config.get("chat_log_path", "data/chat_log.db")
        self.chat_log = ChatLogger(chat_log_path)

        # 4. 记忆存储（依赖 chat_log）
        self.memory_store = MemoryStore(self.chat_log, memory_config)

        # 5. 上下文构建器（依赖 personality + chat_log + memory_store）
        self.context_builder = ContextBuilder(
            personality=self.personality,
            chat_log=self.chat_log,
            memory_store=self.memory_store,
            config=memory_config,
        )

        # 6. 意图分类器（依赖 brain）
        self.classifier = IntentClassifier(self.brain)

        # 7. QQ 通信（无依赖）
        napcat_config = self.config.get("napcat", {})
        ws_uri = napcat_config.get("ws_uri", "ws://localhost:3001")
        self.qq_client = QQClient(uri=ws_uri)

        # ===== 状态 =====
        self._running = False
        self._msg_count = 0

    async def handle_message(self, msg: IncomingMessage) -> OutgoingReply | None:
        """
        Phase 2 消息处理流水线：
        1. 分类意图
        2. 存储到聊天日志
        3. 构建上下文（性格 + 记忆 + 历史 + 当前消息）
        4. AI 生成回复
        5. 存储回复到聊天日志
        6. 返回回复
        """
        self._msg_count += 1
        logger.info(f"[#{self._msg_count}] 收到: {msg.summary()}")

        # Step 1: 意图分类
        intent_result = await self.classifier.classify(msg.content)
        intent_label = intent_result.intent.value

        # Step 2: 存储收到的消息
        await self.chat_log.log_incoming(msg, intent=intent_label)

        # Step 3: 构建上下文
        try:
            messages = await self.context_builder.build(msg)
        except Exception as e:
            logger.exception(f"上下文构建失败: {e}")
            messages = self.context_builder.personality.build_system_message()
            messages.append({"role": "user", "content": msg.content})

        # Step 4: AI 生成回复
        try:
            ai_reply = await self.brain.generate_reply(messages)
        except RuntimeError as e:
            logger.exception(f"AI 调用失败: {e}")
            ai_reply = "主人对不起...我现在脑子有点转不动了，稍等一下再找我好不好 (´;ω;`)"

        # Step 5: 包装回复 & 存储
        reply = OutgoingReply(
            user_id=msg.user_id, content=ai_reply, msg_type=msg.msg_type
        )
        await self.chat_log.log_outgoing(reply)

        return reply

    async def start(self) -> None:
        """启动 Companion（Phase 2）"""
        self._running = True
        persona_name = self.persona_config.get("name", "伊塔")

        logger.info(f"✨ {persona_name} 正在启动 (Phase 2)...")

        # 初始化聊天日志数据库
        await self.chat_log.initialize()

        # 打印启动统计
        stats = await self.chat_log.get_stats()
        if stats and stats.get("user_msgs", 0) > 0:
            logger.info(
                f"聊天记录: {stats.get('user_msgs', 0)} 条用户消息, "
                f"{stats.get('assistant_msgs', 0)} 条 Assistant 回复"
            )

        logger.info(f"分类器已就绪（规则引擎 + LLM 辅助）")
        logger.info(
            f"记忆模式: {'Mem0 向量检索' if self.config.get('memory', {}).get('mem0_enabled') else 'chat_log 代理'}"
        )

        try:
            await self.qq_client.listen(self.handle_message)
        except asyncio.CancelledError:
            logger.info("收到停止信号")
        except Exception as e:
            logger.exception(f"运行异常: {e}")
        finally:
            await self.qq_client.stop()
            await self.chat_log.close()
            logger.info(f"{persona_name} 已下线")

    async def stop(self) -> None:
        """停止 Companion"""
        self._running = False
        await self.qq_client.stop()
        await self.chat_log.close()


async def main() -> None:
    """主函数"""
    companion = Companion()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def signal_handler():
        logger.info("收到中断信号，正在关闭...")
        stop_event.set()

    if sys.platform == "win32":
        signal.signal(signal.SIGINT, signal_handler)
    else:
        loop.add_signal_handler(signal.SIGINT, signal_handler)
        loop.add_signal_handler(signal.SIGTERM, signal_handler)

    start_task = asyncio.create_task(companion.start())

    await stop_event.wait()
    start_task.cancel()
    try:
        await start_task
    except asyncio.CancelledError:
        pass

    logger.info("再见～")


if __name__ == "__main__":
    asyncio.run(main())
