"""Markitdown 文档管道：任意格式 → Markdown → AI → 原格式

核心价值：文档进 AI 前先"脱衣服"（去除格式噪音），省 90%+ token。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from tools.base import Tool


class DocumentPipeline:
    """文档处理管道"""

    def __init__(self, brain=None):
        """
        Args:
            brain: AIBrain 实例（用于 AI 处理文档内容）
        """
        self._brain = brain
        self._md = None
        try:
            from markitdown import MarkItDown
            self._md = MarkItDown()
            logger.info("Markitdown 已就绪")
        except ImportError:
            logger.warning("markitdown 未安装，文档转换功能不可用")

    @property
    def available(self) -> bool:
        return self._md is not None

    async def to_markdown(self, file_path: str) -> Optional[str]:
        """
        任意格式 → Markdown 纯文本。

        Returns:
            Markdown 文本或 None
        """
        if not self._md:
            return await self._fallback_read(file_path)

        try:
            result = self._md.convert(file_path)
            return result.text_content
        except Exception as e:
            logger.warning(f"Markitdown 转换失败 ({file_path}): {e}")
            return await self._fallback_read(file_path)

    async def process_document(
        self,
        file_path: str,
        instruction: str,
        messages: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        完整文档处理：文件→MD→AI处理→结果。

        Args:
            file_path: 文档路径
            instruction: 处理指令（如 "帮我审一下这份合同"）
            messages: 已有的 messages 上下文

        Returns:
            {"result": str, "file": Optional[str], "token_saved_pct": float}
        """
        # Step 1: 转换
        md_content = await self.to_markdown(file_path)
        if not md_content:
            return {"result": "无法读取或解析该文件", "file": None, "token_saved_pct": 0}

        # 估算 token 节省
        try:
            original_size = os.path.getsize(file_path)
        except OSError:
            original_size = 0
        md_size = len(md_content.encode("utf-8"))
        token_saved = max(0, (1 - md_size / max(original_size, 1)) * 100)

        logger.info(f"文档转换: {Path(file_path).name} ({original_size}→{md_size} bytes, 省 {token_saved:.0f}%)")

        if not self._brain:
            return {"result": md_content, "file": None, "token_saved_pct": token_saved}

        # Step 2: AI 处理
        try:
            ctx = messages or []
            ctx.append({
                "role": "user",
                "content": f"文档内容：\n{md_content}\n\n{instruction}",
            })
            result = await self._brain.generate_reply(ctx)
            return {"result": result, "file": None, "token_saved_pct": token_saved}
        except Exception as e:
            logger.exception(f"AI 处理文档失败: {e}")
            return {"result": f"处理失败: {e}", "file": None, "token_saved_pct": token_saved}

    async def to_format(
        self,
        markdown_content: str,
        output_path: str,
        fmt: str = "docx",
    ) -> Optional[str]:
        """Markdown → 目标格式（docx/pdf/html）"""
        format_map = {"docx": "docx", "pdf": "pdf", "html": "html", "pptx": "pptx"}
        output_fmt = format_map.get(fmt, "docx")

        try:
            import pypandoc
            # 写临时 md
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, encoding="utf-8"
            ) as f:
                f.write(markdown_content)
                tmp_path = f.name

            pypandoc.convert_file(tmp_path, output_fmt, outputfile=output_path)
            os.unlink(tmp_path)
            logger.info(f"格式转换: Markdown → {fmt} ({output_path})")
            return output_path
        except ImportError:
            logger.warning("pypandoc 未安装，无法反向转换格式")
            # 回退：直接写 .md 文件
            md_path = output_path.rsplit(".", 1)[0] + ".md"
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(markdown_content)
            return md_path
        except Exception as e:
            logger.warning(f"格式转换失败: {e}")
            return None

    async def _fallback_read(self, file_path: str) -> Optional[str]:
        """纯文本文件直接读取（回退策略）"""
        ext = Path(file_path).suffix.lower()
        text_exts = {".txt", ".md", ".py", ".js", ".ts", ".html", ".css",
                     ".json", ".yaml", ".yml", ".xml", ".csv", ".log"}
        if ext in text_exts:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass
        return None


class ConvertDocumentTool(Tool):
    """文档转换工具：将文档转为纯文本 Markdown，供 AI 处理"""

    name = "convert_document"
    description = "将 Word/PDF/Excel/PPT 等文档转换为纯文本 Markdown，便于 AI 阅读和处理。节省大量 token。"

    def __init__(self, pipeline: Optional[DocumentPipeline] = None):
        self._pipeline = pipeline or DocumentPipeline()

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "要转换的文档完整路径",
                },
            },
            "required": ["file_path"],
        }

    async def execute(self, file_path: str = "", **kwargs) -> Tuple[bool, str]:
        if not file_path:
            return False, "请提供文档路径"
        if not os.path.isfile(file_path):
            return False, f"文件不存在: {file_path}"

        result = await self._pipeline.to_markdown(file_path)
        if result:
            return True, result[:3000]  # 限制返回长度
        return False, f"无法转换文件: {file_path}"
