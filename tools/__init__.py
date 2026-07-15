"""Tool registry setup. All 14 tools (per spec R11) are registered here.

Each tool function is async and returns a string result suitable for
LLM consumption.
"""

from __future__ import annotations

import os
import platform
import subprocess
import asyncio
import logging
from typing import Any

from core.tool_registry import ToolRegistry
from knowledge.kb import KnowledgeBase
from memory.memory_store import LongTermMemory
from core.database import Database
from config.persona_loader import load_settings


logger = logging.getLogger(__name__)


def _run_shell(cmd: str, timeout: int = 5) -> tuple[int, str, str]:
    try:
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW
        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, creationflags=creationflags,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as e:
        return -1, "", str(e)


async def _tool_query_knowledge(keyword: str = "", **_: Any) -> str:
    kb = KnowledgeBase()
    hits = kb.search(keyword, top_k=3)
    if not hits:
        return "知识库无相关条目。"
    return "\n".join([f"- {h.get('title', '')}: {h.get('content', '')[:200]}" for h in hits])


async def _tool_add_todo(title: str, user_id: int = 0, description: str = "", due_at: str = "", priority: int = 5, **_: Any) -> str:
    db = Database()
    tid = db.insert("todo", {
        "user_id": user_id, "title": title, "description": description,
        "due_at": due_at, "priority": priority,
    })
    return f"已添加待办 #{tid}: {title}"


async def _tool_list_todos(user_id: int = 0, status: str = "pending", **_: Any) -> str:
    db = Database()
    rows = db.query(
        "SELECT id, title, due_at, priority FROM todo WHERE user_id = ? AND status = ? ORDER BY priority DESC, id ASC",
        (user_id, status),
    )
    if not rows:
        return "无待办事项。"
    return "\n".join([f"#{r['id']} {r['title']}" + (f" (截止 {r['due_at']})" if r['due_at'] else "") for r in rows])


async def _tool_mark_todo_done(todo_id: int, **_: Any) -> str:
    db = Database()
    n = db.update("todo", {"status": "done"}, "id = ?", (todo_id,))
    return "已完成。" if n else "未找到该待办。"


async def _tool_search_music(keyword: str = "", **_: Any) -> str:
    return f"音乐搜索功能（{keyword}）需要接入第三方平台，目前为占位实现。"


async def _tool_play_local_music(path: str = "", **_: Any) -> str:
    if not path or not os.path.exists(path):
        return "文件不存在。"
    try:
        if platform.system() == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", path])
        return f"已播放 {path}"
    except Exception as e:
        return f"播放失败: {e}"


async def _tool_set_reminder(title: str = "提醒", when: str = "", **_: Any) -> str:
    db = Database()
    tid = db.insert("todo", {
        "user_id": 0, "title": f"[提醒] {title}", "due_at": when, "reminder_at": when, "priority": 8,
    })
    return f"已设置提醒 #{tid}: {title} @ {when}"


async def _tool_get_weather(city: str = "北京", **_: Any) -> str:
    # Placeholder: real implementation could call 和风天气 / OpenWeather etc.
    return f"{city} 天气占位：晴 20°C（需接入真实 API）"


async def _tool_search_web(query: str = "", **_: Any) -> str:
    return f"网页搜索占位：{query}（需接入真实搜索 API）"


async def _tool_open_application(name: str = "", **_: Any) -> str:
    if not name:
        return "请提供应用名。"
    try:
        # Use Popen to avoid PATH issues (project memory note)
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW
        subprocess.Popen(name, creationflags=creationflags)
        return f"已尝试打开 {name}"
    except Exception as e:
        return f"打开失败: {e}"


async def _tool_close_application(name: str = "", **_: Any) -> str:
    rc, _, _ = _run_shell(f"taskkill /IM {name}.exe /F" if platform.system() == "Windows" else f"pkill {name}")
    return f"已尝试关闭 {name} (rc={rc})"


async def _tool_screenshot(path: str = "data/screenshot.png", **_: Any) -> str:
    try:
        import pyautogui  # type: ignore
        Path = os.path.dirname(path) or "."
        os.makedirs(Path, exist_ok=True)
        img = pyautogui.screenshot()
        img.save(path)
        return f"截图已保存到 {path}"
    except Exception as e:
        return f"截图失败: {e}"


async def _tool_get_system_status(**_: Any) -> str:
    from core.system_monitor import SystemMonitor
    s = SystemMonitor().get_stats()
    return (
        f"CPU {s['cpu_percent']}% | 内存 {s['memory']['percent']}% "
        f"({s['memory']['used_mb']}MB) | 磁盘 {s['disk']['percent']}% | "
        f"Python {s['python_proc']['rss_mb']}MB"
    )


async def _tool_send_proactive_msg(scene: str = "morning_brief", **_: Any) -> str:
    """Trigger a proactive push via the global messenger."""
    from core.companion import get_companion
    comp = get_companion()
    if not comp or not comp.messenger:
        return "主动消息器未就绪。"
    settings = load_settings()
    master_id = int(settings.get("qq", {}).get("self_qq", 0))
    template = "……"
    try:
        result = await comp.messenger.push(scene, master_id, template)
        return f"主动消息 {scene}: {result.get('status')}"
    except Exception as e:
        return f"主动消息失败: {e}"


async def _tool_poke_user(user_id: int = 0, **_: Any) -> str:
    """Send a poke (戳一戳) to the user via QQ."""
    from core.companion import get_companion
    comp = get_companion()
    if not comp or not comp.qq:
        return "QQ 未连接。"
    ok = await comp.qq.send_poke(user_id)
    return "已发送戳一戳。" if ok else "戳一戳发送失败。"


async def _tool_send_voice(text: str = "", user_id: int = 0, **_: Any) -> str:
    """Generate TTS audio and send as voice message via QQ."""
    if not text.strip():
        return "请提供要转语音的文字内容。"
    from core.companion import get_companion
    comp = get_companion()
    if not comp or not comp.qq:
        return "QQ 未连接。"

    from voice.tts_engine import TTSEngine
    from voice.silk_encoder import wav_to_silk
    from pathlib import Path
    import time

    tts = TTSEngine()
    wav_path = await tts.synthesize(text)
    if not wav_path:
        return "语音合成失败（请检查 MiniMax TTS API Key 是否可用）。"

    # Encode to Silk for NapCat
    silk_path = wav_to_silk(wav_path)
    file_to_send = silk_path or wav_path

    ok = await comp.qq.send_voice(user_id, str(file_to_send))
    if ok:
        import shutil
        try:
            shutil.move(str(file_to_send), f"data/tts/sent_{int(time.time())}.silk")
        except Exception:
            pass
        return "已发送语音。"
    return "语音发送失败。"


def register_all_tools(registry: ToolRegistry) -> None:
    """Register all 14 tools into the given registry."""
    registry.register(
        "query_knowledge", _tool_query_knowledge,
        schema={"type": "object", "properties": {"keyword": {"type": "string"}}, "required": []},
        category="knowledge",
        description="查询本地知识库（persona/user/world/task 四类）",
    )
    registry.register(
        "add_todo", _tool_add_todo,
        schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "due_at": {"type": "string"},
                "priority": {"type": "integer"},
            },
            "required": ["title"],
        },
        category="productivity",
        description="添加待办事项",
    )
    registry.register(
        "list_todos", _tool_list_todos,
        schema={"type": "object", "properties": {"user_id": {"type": "integer"}, "status": {"type": "string"}}, "required": []},
        category="productivity",
        description="列出待办（默认 pending）",
    )
    registry.register(
        "mark_todo_done", _tool_mark_todo_done,
        schema={"type": "object", "properties": {"todo_id": {"type": "integer"}}, "required": ["todo_id"]},
        category="productivity",
        description="标记待办完成",
    )
    registry.register(
        "search_music", _tool_search_music,
        schema={"type": "object", "properties": {"keyword": {"type": "string"}}, "required": []},
        category="media",
        description="搜索音乐（占位）",
    )
    registry.register(
        "play_local_music", _tool_play_local_music,
        schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        category="media",
        description="播放本地音乐",
    )
    registry.register(
        "set_reminder", _tool_set_reminder,
        schema={"type": "object", "properties": {"title": {"type": "string"}, "when": {"type": "string"}}, "required": ["title"]},
        category="productivity",
        description="设置提醒（写入 todo 表）",
    )
    registry.register(
        "get_weather", _tool_get_weather,
        schema={"type": "object", "properties": {"city": {"type": "string"}}, "required": []},
        category="info",
        description="查询天气（占位）",
    )
    registry.register(
        "search_web", _tool_search_web,
        schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": []},
        category="info",
        description="网页搜索（占位）",
    )
    registry.register(
        "open_application", _tool_open_application,
        schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        category="system",
        description="打开应用（subprocess.Popen）",
    )
    registry.register(
        "close_application", _tool_close_application,
        schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        category="system",
        description="关闭应用（taskkill / pkill）",
    )
    registry.register(
        "screenshot", _tool_screenshot,
        schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": []},
        category="system",
        description="桌面截屏（pyautogui）",
    )
    registry.register(
        "get_system_status", _tool_get_system_status,
        schema={"type": "object", "properties": {}, "required": []},
        category="system",
        description="获取 CPU/内存/磁盘等状态",
    )
    registry.register(
        "send_proactive_msg", _tool_send_proactive_msg,
        schema={"type": "object", "properties": {"scene": {"type": "string"}}, "required": []},
        category="proactive",
        description="触发一次主动推送",
    )
    registry.register(
        "poke_user", _tool_poke_user,
        schema={"type": "object", "properties": {"user_id": {"type": "integer"}}, "required": []},
        category="interaction",
        description="发送戳一戳（QQ poke）给用户",
    )
    registry.register(
        "send_voice", _tool_send_voice,
        schema={"type": "object", "properties": {"text": {"type": "string"}, "user_id": {"type": "integer"}}, "required": ["text"]},
        category="media",
        description="将文字转为语音并发送（伊塔声线）",
    )
