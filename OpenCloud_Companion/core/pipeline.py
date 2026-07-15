"""命令执行流水线

编排：分类 → 上下文构建 → AI(tools) → 工具执行 → AI 总结 → QQ 回复

流程：
  COMMAND/QUERY 消息:
    1. context_builder.build(msg, phase3) → messages
    2. brain.generate_with_tools(messages, tools) → ToolCallResult
    3. 如果 tool_calls → 逐个执行 → 追加 assistant/tool 消息 → brain.generate_reply 总结
    4. 如果 content → 直接返回（AI 认为不需要工具）
    5. 返回最终回复
"""

from __future__ import annotations

from typing import Any, Dict, List

from loguru import logger

from communication.message import Intent, IncomingMessage, OutgoingReply
from core.brain import AIBrain, ToolCallResult
from core.personality import PersonalityEngine
from memory.chat_log import ChatLogger
from memory.context_builder import ContextBuilder
from tools.registry import ToolRegistry


class CommandPipeline:
    """命令/查询消息处理流水线"""

    def __init__(
        self,
        brain: AIBrain,
        personality: PersonalityEngine,
        context_builder: ContextBuilder,
        tool_registry: ToolRegistry,
        chat_log: ChatLogger,
    ):
        self._brain = brain
        self._personality = personality
        self._context_builder = context_builder
        self._tools = tool_registry
        self._chat_log = chat_log

    async def execute(self, msg: IncomingMessage) -> OutgoingReply:
        """
        执行命令流水线。

        Args:
            msg: 收到的消息（已分类为 COMMAND 或 QUERY）

        Returns:
            OutgoingReply 或错误回复
        """
        # 1. 构建 Phase 4 上下文（带工具能力 + 知识库）
        messages = await self._context_builder.build(
            msg, capability_level="phase4",
        )

        # 2. 获取 OpenAI tools 定义
        tool_defs = self._tools.get_openai_tools()

        # 3. AI 决策（带工具）
        try:
            result: ToolCallResult = await self._brain.generate_with_tools(
                messages, tool_defs,
            )
        except RuntimeError as e:
            logger.exception(f"AI 调用失败: {e}")
            return OutgoingReply(
                user_id=msg.user_id,
                content=f"主人对不起，我现在执行不了这个操作 (´;ω;`)\n{e}",
            )

        # 4. 纯文本回复（AI 选择不调工具）
        if result.content and not result.tool_calls:
            reply = OutgoingReply(user_id=msg.user_id, content=result.content)
            await self._chat_log.log_outgoing(reply)
            return reply

        # 5. 执行工具调用
        if not result.tool_calls:
            return OutgoingReply(
                user_id=msg.user_id,
                content="嗯…我也不知道该怎么处理这个请求呢 (｡•́︿•̀｡)",
            )

        tool_results = []
        for tc in result.tool_calls:
            success, output = await self._tools.execute(
                tc["name"], **tc["arguments"]
            )
            tool_results.append({
                "tool_name": tc["name"],
                "success": success,
                "output": output,
            })

        # 6. 构建第二轮消息：追加 assistant(tool_calls) + tool results
        followup_messages = list(messages)  # 复制

        # 追加 assistant 消息（含 tool_calls）
        assistant_msg: Dict[str, Any] = {
            "role": "assistant",
            "content": result.content,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": str(tc["arguments"]).replace("'", '"'),
                    },
                }
                for tc in result.tool_calls
            ],
        }
        followup_messages.append(assistant_msg)

        # 追加 tool 结果
        for i, tr in enumerate(tool_results):
            followup_messages.append({
                "role": "tool",
                "tool_call_id": result.tool_calls[i]["id"],
                "content": tr["output"],
            })

        # 7. AI 总结工具结果
        try:
            summary = await self._brain.generate_reply(followup_messages)
        except RuntimeError:
            # 无法总结时直接返回工具结果
            texts = [f"✅ {tr['output']}" if tr["success"] else f"❌ {tr['output']}" for tr in tool_results]
            summary = "\n".join(texts)

        reply = OutgoingReply(user_id=msg.user_id, content=summary)
        await self._chat_log.log_outgoing(reply)
        return reply
