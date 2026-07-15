"""知识采集器：五种来源提取知识

来源：
1. 对话提取：从聊天记录中分析提取结构化知识
2. 文件吸收：读取文件 → Markitdown 转换 → 分块 → 提取知识
3. 网页提取：从 URL 内容中提取知识
4. 主动投喂：用户直接指定 "记住 XXX"
5. 文件系统发现：定期扫描工作目录（可配置开关）
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from knowledge.store import KnowledgeStore


class KnowledgeIngestor:
    """知识采集器"""

    def __init__(self, store: KnowledgeStore, embedder=None):
        """
        Args:
            store: KnowledgeStore 实例
            embedder: 嵌入函数 async embed(text: str) -> np.ndarray
        """
        self._store = store
        self._embedder = embedder

    # ===== 源1：对话提取 =====
    async def ingest_from_conversation(
        self,
        messages: List[Dict[str, str]],
        user_id: int = 0,
    ) -> List[str]:
        """
        从对话中提取知识条目。

        Args:
            messages: [{"role": "user/assistant", "content": "..."}, ...]
            user_id: 用户 QQ 号

        Returns:
            新增的 entry_id 列表
        """
        if not self._embedder:
            logger.warning("未配置 embedder，对话知识提取将跳过嵌入")
            return []

        # 简单策略：提取 user 消息中长于 15 字的消息作为潜在知识
        ids = []
        for msg in messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "").strip()
            if len(content) < 15:
                continue
            # 过滤纯闲聊（简单启发式）
            if any(kw in content for kw in ["哈哈", "嗯嗯", "好的", "哦", "行", "知道了"]):
                continue

            try:
                embedding = await self._embedder(content)
            except Exception as e:
                logger.debug(f"嵌入失败: {e}")
                continue

            entry_id = await self._store.add_entry(
                content=content,
                embedding=embedding,
                source="conversation",
                source_ref=f"user_{user_id}",
                user_id=user_id,
            )
            ids.append(entry_id)

        if ids:
            logger.info(f"从对话中提取 {len(ids)} 条知识")

        return ids

    # ===== 源2：文件吸收 =====
    async def ingest_from_file(
        self,
        file_path: str,
        user_id: int = 0,
    ) -> List[str]:
        """
        从文件中吸收知识（Markitdown 转换后分块提取）。

        Args:
            file_path: 文件路径
            user_id: 用户 QQ 号

        Returns:
            新增的 entry_id 列表
        """
        if not self._embedder:
            logger.warning("未配置 embedder，文件知识吸收将跳过嵌入")
            return []

        # 尝试用 Markitdown 转换
        md_content = await self._file_to_markdown(file_path)
        if not md_content:
            logger.warning(f"无法解析文件: {file_path}")
            return []

        # 按段落分块
        chunks = self._chunk_text(md_content, max_chunk_size=2000)
        ids = []
        filename = Path(file_path).name

        for i, chunk in enumerate(chunks):
            if len(chunk.strip()) < 30:
                continue
            try:
                embedding = await self._embedder(chunk)
            except Exception as e:
                logger.debug(f"嵌入失败: {e}")
                continue

            entry_id = await self._store.add_entry(
                content=chunk,
                embedding=embedding,
                source="file_ingest",
                source_ref=f"{file_path}#chunk_{i}",
                user_id=user_id,
                tags=[f"file:{filename}"],
            )
            ids.append(entry_id)

        if ids:
            logger.info(f"从文件 {filename} 中吸收 {len(ids)} 条知识")

        return ids

    # ===== 源3：网页提取 =====
    async def ingest_from_web(
        self,
        url: str,
        content: str,
        user_id: int = 0,
    ) -> List[str]:
        """
        从网页内容中提取知识。

        Args:
            url: 网页 URL
            content: 已提取的文本内容
            user_id: 用户 QQ 号

        Returns:
            新增的 entry_id 列表
        """
        if not self._embedder:
            return []

        chunks = self._chunk_text(content, max_chunk_size=2000)
        ids = []

        for i, chunk in enumerate(chunks):
            if len(chunk.strip()) < 30:
                continue
            try:
                embedding = await self._embedder(chunk)
            except Exception as e:
                logger.debug(f"嵌入失败: {e}")
                continue

            entry_id = await self._store.add_entry(
                content=chunk,
                embedding=embedding,
                source="web",
                source_ref=url,
                user_id=user_id,
            )
            ids.append(entry_id)

        if ids:
            logger.info(f"从网页 {url[:60]}... 提取 {len(ids)} 条知识")

        return ids

    # ===== 源4：主动投喂 =====
    async def ingest_direct(
        self,
        content: str,
        tags: Optional[List[str]] = None,
        user_id: int = 0,
    ) -> Optional[str]:
        """
        用户主动指定 "记住 XXX" → 直接入库。

        Returns:
            entry_id 或 None
        """
        embedding = None
        if self._embedder:
            try:
                embedding = await self._embedder(content)
            except Exception as e:
                logger.debug(f"嵌入失败: {e}")

        entry_id = await self._store.add_entry(
            content=content,
            embedding=embedding,
            source="direct_feed",
            source_ref="user_command",
            confidence=1.0,
            tags=tags,
            user_id=user_id,
        )
        logger.info(f"主动投喂知识: {entry_id}")
        return entry_id

    # ===== 源5：文件系统发现 =====
    async def ingest_from_filesystem(
        self,
        root_dir: str,
        user_id: int = 0,
        max_files: int = 50,
    ) -> List[str]:
        """
        扫描工作目录，记录文件/文件夹结构（不读内容）。

        Args:
            root_dir: 扫描根目录
            user_id: 用户 QQ 号
            max_files: 最大发现文件数

        Returns:
            新增的 entry_id 列表
        """
        root = Path(root_dir)
        if not root.exists():
            logger.warning(f"扫描目录不存在: {root_dir}")
            return []

        ids = []
        count = 0

        for entry in root.rglob("*"):
            if count >= max_files:
                break
            # 跳过隐藏文件和常见忽略目录
            if entry.name.startswith("."):
                continue
            if any(p in entry.parts for p in ["node_modules", "__pycache__", ".git", ".venv", "venv"]):
                continue
            if entry.is_file():
                entry_type = "file"
                size = entry.stat().st_size
                content = f"[{root.name}] {entry.relative_to(root)} ({self._format_size(size)})"
            else:
                entry_type = "directory"
                content = f"[{root.name}] {entry.relative_to(root)}/ (目录)"

            embedding = None
            if self._embedder:
                try:
                    embedding = await self._embedder(content)
                except Exception:
                    pass

            entry_id = await self._store.add_entry(
                content=content,
                embedding=embedding,
                source="filesystem_discovery",
                source_ref=str(entry),
                tags=[f"fs:{entry_type}", f"root:{root.name}"],
                confidence=0.8,
                user_id=user_id,
            )
            ids.append(entry_id)
            count += 1

        if ids:
            logger.info(f"文件系统发现 {len(ids)} 条 ({root_dir})")

        return ids

    # ===== 辅助 =====

    async def _file_to_markdown(self, file_path: str) -> Optional[str]:
        """将文件转换为 Markdown 文本"""
        ext = Path(file_path).suffix.lower()

        # 纯文本文件直接读
        if ext in (".txt", ".md", ".py", ".js", ".ts", ".html", ".css",
                   ".json", ".yaml", ".yml", ".xml", ".csv", ".log",
                   ".java", ".go", ".rs", ".cpp", ".c", ".h"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return f.read()
            except (UnicodeDecodeError, OSError):
                pass

        # Markitdown 转换
        try:
            from markitdown import MarkItDown
            md = MarkItDown()
            result = md.convert(file_path)
            return result.text_content
        except ImportError:
            logger.debug("markitdown 未安装，跳过格式转换")
            return None
        except Exception as e:
            logger.debug(f"Markitdown 转换失败: {e}")
            return None

    @staticmethod
    def _chunk_text(text: str, max_chunk_size: int = 2000) -> List[str]:
        """按段落分块文本"""
        paragraphs = text.split("\n\n")
        chunks = []
        current = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if len(current) + len(para) <= max_chunk_size:
                current += ("\n\n" if current else "") + para
            else:
                if current:
                    chunks.append(current)
                current = para if len(para) <= max_chunk_size else para[:max_chunk_size]

        if current:
            chunks.append(current)

        return chunks if chunks else [text[:max_chunk_size]]

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """格式化文件大小"""
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f}{unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f}TB"
