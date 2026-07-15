"""定时任务功能模块

具体任务的业务逻辑：
- 每日简报聚合（资讯 + 天气 + 待办）
- 晚安问候生成
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger


class BriefAggregator:
    """简报数据聚合器：从多方数据源收集简报需要的数据"""

    def __init__(self, brain=None, todo_manager=None):
        self._brain = brain
        self._todo_manager = todo_manager

    async def aggregate(self, user_id: int = 0) -> Dict[str, Any]:
        """
        聚合每日简报数据。

        Returns:
            {
                "greeting": str,
                "date": str,
                "news": [{"title": str, "source": str, "time": str}],
                "todos": [{"text": str, "done": bool}],
                "weather": {"icon": str, "text": str, "temp": str},
                "system": {"cpu_pct": float, "mem_pct": float, "disk_pct": float},
            }
        """
        result: Dict[str, Any] = {
            "greeting": self._get_greeting(),
            "date": self._get_date_str(),
            "news": [],
            "todos": [],
            "weather": {"icon": "⛅", "text": "", "temp": ""},
            "system": {"cpu_pct": 0, "mem_pct": 0, "disk_pct": 0},
        }

        # 待办
        if self._todo_manager:
            try:
                todos = await self._get_todos()
                result["todos"] = todos
            except Exception as e:
                logger.debug(f"获取待办失败: {e}")

        # 天气
        try:
            weather = await self._get_weather()
            if weather:
                result["weather"] = weather
        except Exception as e:
            logger.debug(f"获取天气失败: {e}")

        # 系统状态
        try:
            sys_status = await self._get_system_status()
            result["system"] = sys_status
        except Exception as e:
            logger.debug(f"获取系统状态失败: {e}")

        return result

    async def generate_goodnight(self, user_id: int = 0) -> str:
        """生成晚安消息"""
        hour = datetime.now().hour
        if 23 <= hour or hour < 5:
            msg = "夜深了，主人早点休息吧～晚安 (。-ω-)zzz"
        else:
            msg = "主人辛苦了，今天也早点休息哦～晚安"
        return msg

    # ===== 内部 =====

    @staticmethod
    def _get_greeting() -> str:
        hour = datetime.now().hour
        if hour < 6:
            return "夜深了，主人还在忙呀 🌙"
        elif hour < 9:
            return "早上好，主人～ ☀️"
        elif hour < 12:
            return "上午好，主人～"
        elif hour < 14:
            return "中午好，主人～"
        elif hour < 18:
            return "下午好，主人～ 🌤"
        else:
            return "晚上好，主人～ 🌙"

    @staticmethod
    def _get_date_str() -> str:
        now = datetime.now()
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        return f"{now.year}年{now.month}月{now.day}日 {weekdays[now.weekday()]}"

    async def _get_todos(self) -> List[Dict[str, Any]]:
        if not self._todo_manager:
            return []
        try:
            # 使用 TodoListTool 的底层存储获取待办
            store = getattr(self._todo_manager, '_store', None)
            if store is None:
                return []
            todos = store.get_all_todos()
            return [{"text": t.title, "done": t.completed} for t in todos[:5]]
        except Exception:
            return []

    async def _get_weather(self) -> Optional[Dict[str, str]]:
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                url = "https://wttr.in/?format=%C+%t+%w&lang=zh"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        parts = text.strip().split(" ")
                        icon_map = {
                            "Sunny": "☀️", "Clear": "🌙", "Partly cloudy": "⛅",
                            "Cloudy": "☁️", "Overcast": "☁️", "Mist": "🌫",
                            "Rain": "🌧", "Light rain": "🌦", "Heavy rain": "⛈",
                            "Snow": "❄️", "Thunderstorm": "⛈",
                        }
                        icon = "⛅"
                        for k, v in icon_map.items():
                            if k.lower() in text.lower():
                                icon = v
                                break
                        return {
                            "icon": icon,
                            "text": text.strip()[:20],
                            "temp": "",
                        }
        except Exception:
            pass
        return None

    async def _get_system_status(self) -> Dict[str, float]:
        try:
            import psutil
            return {
                "cpu_pct": psutil.cpu_percent(interval=0.5),
                "mem_pct": psutil.virtual_memory().percent,
                "disk_pct": psutil.disk_usage("/").percent,
            }
        except Exception:
            return {"cpu_pct": 0, "mem_pct": 0, "disk_pct": 0}
