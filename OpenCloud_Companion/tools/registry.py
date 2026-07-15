"""工具注册中心

职责：
- 注册所有工具实例
- 生成 OpenAI Function Calling tools 列表
- 按名称查找工具并调度执行
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from tools.base import Tool


class ToolRegistry:
    """工具注册中心"""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册一个工具"""
        if tool.name in self._tools:
            logger.warning(f"工具 {tool.name} 已注册，将被覆盖")
        self._tools[tool.name] = tool
        logger.debug(f"工具已注册: {tool.name}")

    def register_all(self, tools: List[Tool]) -> None:
        """批量注册工具"""
        for tool in tools:
            self.register(tool)

    def get(self, name: str) -> Optional[Tool]:
        """按名称查找工具"""
        return self._tools.get(name)

    def get_openai_tools(self) -> List[Dict[str, Any]]:
        """生成所有已注册工具的 OpenAI Function Calling 格式"""
        return [tool.to_openai_tool() for tool in self._tools.values()]

    async def execute(self, name: str, **kwargs) -> Tuple[bool, str]:
        """
        按名称调度执行工具。

        Args:
            name: 工具名称
            **kwargs: AI 传入的参数

        Returns:
            (success, result_message)
        """
        tool = self.get(name)
        if tool is None:
            error_msg = f"未知工具: {name}，可用工具: {list(self._tools.keys())}"
            logger.warning(error_msg)
            return False, error_msg

        logger.info(f"执行工具: {name}({', '.join(f'{k}={v}' for k, v in kwargs.items())})")
        try:
            return await tool.execute(**kwargs)
        except Exception as e:
            logger.exception(f"工具 {name} 执行异常: {e}")
            return False, f"工具执行失败: {e}"

    @property
    def tool_names(self) -> List[str]:
        return list(self._tools.keys())

    @property
    def count(self) -> int:
        return len(self._tools)
