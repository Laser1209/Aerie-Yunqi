#!/usr/bin/env python3
"""
OpenCloud Companion - Phase 1 入口

功能：连接 NapCatQQ → 接收 QQ 私聊消息 → AI 生成回复 → QQ 返回

启动前请确认：
1. NapCatQQ 已运行且登录了 QQ 号 B
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

    # 替换 ${VAR:default} 模式
    def replace_env(match):
        var = match.group(1)
        default = match.group(2) if match.group(2) else ""
        return os.getenv(var, default)

    content = re.sub(r"\$\{(\w+):?([^}]*)\}", replace_env, content)
    return yaml.safe_load(content)


def init_logging(config: Dict[str, Any]) -> None:
    """初始化日志系统"""
    log_config = config.get("logging", {})
    logger.remove()  # 移除默认 handler

    level = log_config.get("level", "INFO")
    log_file = PROJECT_ROOT / log_config.get("file", "logs/companion.log")
    rotation = log_config.get("rotation", "10 MB")
    retention = log_config.get("retention", "7 days")

    # 确保日志目录存在
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # 文件输出（带轮转）
    logger.add(
        log_file,
        rotation=rotation,
        retention=retention,
        level=level,
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} [{level}] {message}",
    )

    # 控制台输出
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
    """OpenCloud Companion 主应用"""

    def __init__(self):
        load_env()
        self.config = load_config()
        init_logging(self.config)
        self.persona = load_persona()

        # 初始化模块
        napcat_config = self.config.get("napcat", {})
        ws_uri = napcat_config.get("ws_uri", "ws://localhost:3001")

        ai_config = self.config.get("ai", {})
        self.brain = AIBrain(ai_config, self.persona)
        self.qq_client = QQClient(uri=ws_uri)

        self._running = False

    async def handle_message(self, msg: IncomingMessage) -> OutgoingReply | None:
        """
        处理收到的 QQ 消息：交给 AI 生成回复。

        Args:
            msg: 收到的消息

        Returns:
            要发送的回复，如果 AI 失败则返回错误提示
        """
        try:
            ai_reply = await self.brain.generate_reply(msg)
            return self.brain.format_reply(msg, ai_reply)
        except RuntimeError as e:
            logger.exception(f"AI 调用失败: {e}")
            return OutgoingReply(
                user_id=msg.user_id,
                content="主人对不起...我现在脑子有点转不动了，稍等一下再找我好不好 (´;ω;`)",
            )

    async def start(self) -> None:
        """启动 Companion"""
        self._running = True

        persona_name = self.persona.get("name", "伊塔")
        logger.info(f"✨ {persona_name} 正在启动...")

        try:
            await self.qq_client.listen(self.handle_message)
        except asyncio.CancelledError:
            logger.info("收到停止信号")
        except Exception as e:
            logger.exception(f"运行异常: {e}")
        finally:
            await self.qq_client.stop()
            logger.info(f"{persona_name} 已下线")

    async def stop(self) -> None:
        """停止 Companion"""
        self._running = False
        await self.qq_client.stop()


async def main() -> None:
    """主函数"""
    companion = Companion()

    # 注册 Ctrl+C 信号处理
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

    # 启动
    start_task = asyncio.create_task(companion.start())

    # 等待停止信号
    await stop_event.wait()
    start_task.cancel()
    try:
        await start_task
    except asyncio.CancelledError:
        pass

    logger.info("再见～")


if __name__ == "__main__":
    asyncio.run(main())
