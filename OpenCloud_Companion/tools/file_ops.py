"""文件操作工具

支持操作：
- read_file — 读取文件内容
- write_file — 写入文件
- list_dir — 列出目录内容
- search_files — 按名称搜索文件
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Tuple

from loguru import logger

from tools.base import Tool, is_safe_path


class ReadFileTool(Tool):
    name = "read_file"
    description = "读取指定文件的文本内容。传入文件的绝对路径。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要读取的文件绝对路径",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "最多读取的行数，默认 100",
                },
            },
            "required": ["path"],
        }

    async def execute(self, path: str = "", max_lines: int = 100, **kwargs) -> Tuple[bool, str]:
        if not path:
            return False, "错误：未提供文件路径"

        if not is_safe_path(path):
            return False, f"安全限制：不允许访问 {path}"

        p = Path(path)
        if not p.exists():
            return False, f"文件不存在: {path}"
        if not p.is_file():
            return False, f"路径不是文件: {path}"

        try:
            lines = p.read_text(encoding="utf-8").splitlines()
            if len(lines) > max_lines:
                result = "\n".join(lines[:max_lines])
                result += f"\n... [截断: 共 {len(lines)} 行, 显示前 {max_lines} 行]"
            else:
                result = "\n".join(lines)
            logger.debug(f"read_file: {path} ({min(len(lines), max_lines)} 行)")
            return True, result
        except UnicodeDecodeError:
            return False, f"文件不是文本格式: {path}"
        except Exception as e:
            return False, f"读取失败: {e}"


class WriteFileTool(Tool):
    name = "write_file"
    description = "将内容写入文件。如果文件已存在则覆盖。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要写入的文件绝对路径",
                },
                "content": {
                    "type": "string",
                    "description": "要写入的内容",
                },
            },
            "required": ["path", "content"],
        }

    async def execute(self, path: str = "", content: str = "", **kwargs) -> Tuple[bool, str]:
        if not path:
            return False, "错误：未提供文件路径"

        if not is_safe_path(path):
            return False, f"安全限制：不允许写入 {path}"

        p = Path(path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            logger.debug(f"write_file: {path}")
            return True, f"已写入 {path} ({len(content)} 字符)"
        except Exception as e:
            return False, f"写入失败: {e}"


class ListDirTool(Tool):
    name = "list_dir"
    description = "列出指定目录下的文件和子目录"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要列出的目录绝对路径",
                },
            },
            "required": ["path"],
        }

    async def execute(self, path: str = "", **kwargs) -> Tuple[bool, str]:
        if not path:
            path = os.path.expanduser("~/Desktop")

        if not is_safe_path(path):
            return False, f"安全限制：不允许访问 {path}"

        p = Path(path)
        if not p.exists():
            return False, f"目录不存在: {path}"
        if not p.is_dir():
            return False, f"路径不是目录: {path}"

        try:
            items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            lines = []
            for item in items:
                icon = "📁" if item.is_dir() else "📄"
                size = ""
                if item.is_file():
                    try:
                        s = item.stat().st_size
                        if s < 1024:
                            size = f" ({s}B)"
                        elif s < 1024 * 1024:
                            size = f" ({s / 1024:.1f}KB)"
                        else:
                            size = f" ({s / (1024 * 1024):.1f}MB)"
                    except OSError:
                        pass
                lines.append(f"{icon} {item.name}{size}")

            result = f"📂 {p}\n" + "\n".join(lines)
            logger.debug(f"list_dir: {path} ({len(items)} 项)")
            return True, result
        except Exception as e:
            return False, f"列出目录失败: {e}"


class SearchFilesTool(Tool):
    name = "search_files"
    description = "在指定目录及其子目录中搜索文件名包含关键词的文件"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "文件名搜索关键词（不区分大小写）",
                },
                "directory": {
                    "type": "string",
                    "description": "搜索起始目录的绝对路径",
                },
                "max_results": {
                    "type": "integer",
                    "description": "最大返回结果数，默认 20",
                },
            },
            "required": ["keyword", "directory"],
        }

    async def execute(
        self, keyword: str = "", directory: str = "", max_results: int = 20, **kwargs
    ) -> Tuple[bool, str]:
        if not keyword:
            return False, "错误：未提供搜索关键词"
        if not directory:
            return False, "错误：未提供搜索目录"

        if not is_safe_path(directory):
            return False, f"安全限制：不允许搜索 {directory}"

        p = Path(directory)
        if not p.is_dir():
            return False, f"目录不存在: {directory}"

        try:
            results = []
            keyword_lower = keyword.lower()

            for f in p.rglob("*"):
                if keyword_lower in f.name.lower():
                    if is_safe_path(f):
                        results.append(str(f))
                    if len(results) >= max_results:
                        break

            if results:
                logger.debug(f"search_files: {keyword} → {len(results)} 结果")
                return True, "\n".join(results)
            return True, f"未找到包含「{keyword}」的文件"
        except Exception as e:
            return False, f"搜索失败: {e}"
