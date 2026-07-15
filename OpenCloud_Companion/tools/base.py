"""Tool 基类 + OpenAI Function Calling Schema 生成 + 路径安全

所有工具继承 Tool，实现：
- name: 工具名称（snake_case）
- description: 工具描述（给 AI 看的）
- parameters: JSON Schema 参数定义
- execute(**kwargs): 执行逻辑，返回 (success: bool, result: str)
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


# ===== 路径安全白名单 =====
_SAFE_ROOTS: List[Path] = []
_initialized = False


def init_safe_paths() -> None:
    """初始化安全路径白名单（首次导入时自动调用）"""
    global _SAFE_ROOTS, _initialized
    if _initialized:
        return

    home = Path(os.path.expanduser("~"))
    _SAFE_ROOTS = [
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
        home / "Pictures",
        home / "Music",
        home / "Videos",
        Path(os.path.dirname(os.path.abspath(__file__))).parent,  # PROJECT_ROOT
    ]
    _initialized = True
    logger.debug(f"工具安全路径已初始化: {len(_SAFE_ROOTS)} 个白名单目录")


def is_safe_path(target: str | Path) -> bool:
    """检查路径是否在白名单内且无路径遍历攻击"""
    init_safe_paths()

    try:
        resolved = Path(target).resolve()
    except (OSError, ValueError):
        return False

    # 禁止路径遍历：确保 target 规范后不包含 ..
    if ".." in str(Path(target)):
        return False

    for safe_root in _SAFE_ROOTS:
        try:
            resolved.relative_to(safe_root)
            return True
        except ValueError:
            continue

    return False


class Tool(ABC):
    """工具基类"""

    # 子类必须定义
    name: str = ""
    description: str = ""

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """OpenAI Function Calling parameters JSON Schema"""
        ...

    def to_openai_tool(self) -> Dict[str, Any]:
        """生成 OpenAI Function Calling 格式的 tool 定义"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    @abstractmethod
    async def execute(self, **kwargs) -> Tuple[bool, str]:
        """
        执行工具。

        Args:
            **kwargs: AI 传入的参数

        Returns:
            (success, result_message)
            - success=True: result 是成功结果
            - success=False: result 是错误描述
        """
        ...

    def __repr__(self) -> str:
        return f"Tool({self.name})"
