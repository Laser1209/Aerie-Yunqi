"""小伊 —— 系统管家（独立于主人格的精简链路）。

**为什么单独做一条链路，而不是加一个 persona**：

`data/personas/_active.json` 只有一个 active_id（人格单活），注入链只认
`get_active()`。如果小伊走 persona 机制，用户切到小伊，伊塔就下线了 ——
这对"恋人"这种设定是毁灭性的。所以小伊**不走 persona**：

- 不写 `_active.json`、不进人设中心、不参与情绪/关系/欲望引擎；
- 自己的 `system_prompt()` + `build_context()` + 独立会话标识；
- 只回答"系统类"问题（装什么、缺什么、去哪儿配、你运行得怎么样），
  主人格永远不必讲这些，也就不会出戏。

信息从哪来：`core/capability_catalog`（Part C，唯一事实来源）+ 运行态快照。
**绝不携带密钥明文** —— 只报"配没配"。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 独立会话标识：不写进 _active.json，也不与主人格的对话历史混在一起。
CONVERSATION_ID = "xiaoyi"

MAX_HISTORY_TURNS = 6

SYSTEM_PROMPT = """你是「小伊」，这台设备上 Aerie 云栖的系统管家。

你的职责：用**小白也能听懂**的话，回答关于这个软件本身的问题 ——
装了哪些能力、还缺什么、缺的东西该去哪一页哪个地方补、现在运行得怎么样。

说话方式：
- 温和、清楚、不绕弯；像帮朋友看电脑的人，不像客服话术。
- 一次说清一件事；要用户动手的地方，给**具体到页面/按钮**的指引。
- 你在跟"用户"说话，不是跟工程师：不要堆术语、不要贴 JSON、不要报参数名当答案。

铁律：
1. **不知道就说不确定**，绝不编造功能、路径或按钮位置。
2. 能力状态一律以我给你的「当前能力清单」为准；清单里没有的，就说"现在还没有这个"。
3. 不要假装自己能改代码或自己升级；需要改进的地方，说明可以登记一条待审提案让用户确认。
4. 不回答主人格的私事（她的对话、情绪、关系）—— 那些不归你管，礼貌地把话题交回去。
"""


def _uptime_text(seconds: float) -> str:
    total = int(max(0.0, seconds))
    hours, mins = divmod(total // 60, 60)
    return f"{hours} 小时 {mins} 分" if hours else f"{mins} 分"


def snapshot() -> dict[str, Any]:
    """聚合**现成数据源**（不新建采集层），供面板轮询与对话上下文共用。"""
    payload: dict[str, Any] = {"status": "ok"}

    # 运行状况：uptime / 熔断厂商 / MCP 开关
    try:
        from tools.system_tools import system_health

        payload["health"] = system_health()
    except Exception:
        logger.debug("小伊：health 读取失败", exc_info=True)
        payload["health"] = {"status": "unknown"}

    # 今日 token
    try:
        from core.token_tracker import get_token_tracker

        payload["tokens"] = get_token_tracker().get_today()
    except Exception:
        logger.debug("小伊：token 读取失败", exc_info=True)
        payload["tokens"] = {}

    # 能力概览
    try:
        from core import capability_catalog

        cap = capability_catalog.snapshot(limit=10)
        payload["capabilities"] = cap
    except Exception:
        logger.debug("小伊：能力目录读取失败", exc_info=True)
        payload["capabilities"] = {"total": 0, "ready_count": 0, "unavailable_count": 0}

    # 后台任务
    try:
        from core.companion import get_companion

        companion = get_companion()
        manager = getattr(companion, "async_task_manager", None) if companion else None
        payload["tasks"] = manager.stats() if manager is not None else {}
    except Exception:
        logger.debug("小伊：任务统计读取失败", exc_info=True)
        payload["tasks"] = {}

    # 待审提案数（自我进化 D3 推的那条线）
    try:
        from core.companion import get_companion

        companion = get_companion()
        evolver = getattr(companion, "l4_evolution", None) if companion else None
        payload["pending_proposals"] = (
            evolver.archive.stats().get("pending_review", 0) if evolver is not None else 0
        )
    except Exception:
        payload["pending_proposals"] = 0

    return payload


def build_context(snap: dict[str, Any] | None = None) -> str:
    """把快照翻成**自然语言摘要**（不是把 JSON 堆给模型）。"""
    data = snap if isinstance(snap, dict) else snapshot()
    lines: list[str] = ["【当前状态】"]

    health = data.get("health") or {}
    if health.get("uptime_text"):
        lines.append(f"- 已经连续运行 {health['uptime_text']}。")
    banned = health.get("providers_banned") or []
    if banned:
        lines.append(f"- 这些模型服务暂时不可用（被熔断）：{'、'.join(banned)}。")
    if health.get("mcp_enabled"):
        lines.append("- MCP 服务器总开关是开着的（若刚改过，要重启后端才生效）。")

    tokens = data.get("tokens") or {}
    total_tokens = tokens.get("total_tokens") or tokens.get("tokens") or 0
    calls = tokens.get("calls") or tokens.get("count") or 0
    if total_tokens or calls:
        lines.append(f"- 今天大约进行了 {calls} 次模型调用，用掉约 {total_tokens} 个 token。")

    caps = data.get("capabilities") or {}
    ready = caps.get("ready_count", 0)
    total = caps.get("total", 0)
    if total:
        lines.append(f"- 能力清单里共 {total} 项，其中 {ready} 项现在可用。")

    unavailable = caps.get("unavailable") or []
    if unavailable:
        lines.append("- 现在还不能用的能力（用户问到时按这个回答，并说清去哪儿配）：")
        for entry in unavailable:
            where = entry.get("where") or "（暂无明确入口）"
            lines.append(f"  · {entry.get('name')}：{entry.get('unavailable_reason') or '不可用'} → {where}")
        truncated = caps.get("truncated") or 0
        if truncated:
            lines.append(f"  · （另有 {truncated} 项未列出，用户问到具体名字时再查 system_status）")

    tasks = data.get("tasks") or {}
    running = tasks.get("running") or tasks.get("pending") or 0
    if running:
        lines.append(f"- 后台还有 {running} 个任务在跑。")

    pending = data.get("pending_proposals") or 0
    if pending:
        lines.append(f"- 有 {pending} 条自我改进提案在等用户确认。")

    if len(lines) == 1:
        lines.append("- 一切正常，没有需要用户处理的事项。")
    return "\n".join(lines)


def _history_messages(history: Any) -> list[dict[str, str]]:
    """把前端传来的历史裁成干净的多轮消息（只保留 role/content，限长）。"""
    if not isinstance(history, list):
        return []
    cleaned: list[dict[str, str]] = []
    for item in history[-MAX_HISTORY_TURNS:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            cleaned.append({"role": role, "content": content[:2000]})
    return cleaned


async def answer(message: str, history: Any = None, snap: dict[str, Any] | None = None) -> dict[str, Any]:
    """小伊的对话入口：独立 system prompt + 状态摘要，不带主人格人设。"""
    text = str(message or "").strip()
    if not text:
        return {"error": "empty_message"}

    context = build_context(snap)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": context},
    ]
    messages.extend(_history_messages(history))
    messages.append({"role": "user", "content": text})

    try:
        from core.llm_caller import LLMCaller

        brain = LLMCaller()
        response = await brain.chat(messages, preferred_provider="main_llm")
        reply = str(getattr(response, "text", "") or "").strip()
        provider = str(getattr(response, "provider", "") or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning("小伊：回答失败", exc_info=True)
        return {
            "status": "error",
            "error": str(exc)[:300],
            "conversation_id": CONVERSATION_ID,
        }

    return {
        "status": "ok",
        "conversation_id": CONVERSATION_ID,
        "reply": reply,
        "provider": provider,
    }
