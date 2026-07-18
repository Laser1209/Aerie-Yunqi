"""Aerie v13.0 — Office Tools 办公场景工具集

注册到 tool_registry 供 AI function calling 调用的办公类工具：
- document_create    创建文档（Markdown / TXT）
- document_read      读取本地文档
- spreadsheet_analyze  简单 CSV / TSV 数据分析
- file_search        本地文件搜索
- text_summary       文本摘要
- calendar_event     日历事件管理（读/创建）
"""

from __future__ import annotations

import csv
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 办公文件默认保存目录
OFFICE_DIR = Path(os.path.expanduser("~/AerieOffice"))
OFFICE_DIR.mkdir(parents=True, exist_ok=True)


# ── 工具函数 ──────────────────────────────────────


def tool_document_create(
    filename: str,
    content: str,
    format: str = "markdown",
) -> dict:
    """创建一个办公文档并保存到本地。

    Args:
        filename: 文件名（不含路径，会保存在 AerieOffice 目录下）
        content: 文档内容
        format: 文档格式（markdown / txt）

    Returns:
        保存结果（路径、大小、格式）
    """
    try:
        ext_map = {
            "markdown": ".md",
            "md": ".md",
            "txt": ".txt",
            "text": ".txt",
        }
        ext = ext_map.get(format.lower(), ".md")

        # 确保文件名安全
        safe_name = "".join(c for c in filename if c.isalnum() or c in "._-  ")
        if not safe_name:
            safe_name = f"document_{int(datetime.now().timestamp())}"
        if not safe_name.endswith(ext):
            safe_name += ext

        file_path = OFFICE_DIR / safe_name
        file_path.parent.mkdir(parents=True, exist_ok=True)

        file_path.write_text(content, encoding="utf-8")
        size = file_path.stat().st_size

        return {
            "success": True,
            "path": str(file_path),
            "filename": safe_name,
            "format": format,
            "size_bytes": size,
            "message": f"文档已保存到 {file_path}",
        }
    except Exception as e:
        logger.exception("document_create error")
        return {"success": False, "error": str(e)}


def tool_document_read(filepath: str) -> dict:
    """读取本地文档内容。

    Args:
        filepath: 文件路径（绝对路径或相对 AerieOffice 的路径）

    Returns:
        文档内容和元信息
    """
    try:
        path = Path(filepath)
        if not path.is_absolute():
            path = OFFICE_DIR / filepath

        if not path.exists():
            return {"success": False, "error": f"文件不存在: {path}"}

        if not path.is_file():
            return {"success": False, "error": f"不是文件: {path}"}

        # 安全检查：只允许读取 AerieOffice 和常见文档目录
        allowed_parents = [
            OFFICE_DIR.resolve(),
            Path(os.path.expanduser("~/Desktop")).resolve(),
            Path(os.path.expanduser("~/Documents")).resolve(),
            Path(os.path.expanduser("~/Downloads")).resolve(),
        ]
        resolved = path.resolve()
        allowed = any(str(resolved).startswith(str(p)) for p in allowed_parents)
        if not allowed:
            return {"success": False, "error": "出于安全考虑，仅允许读取桌面/文档/下载/AerieOffice 目录下的文件"}

        # 大小限制：10MB
        size = path.stat().st_size
        if size > 10 * 1024 * 1024:
            return {"success": False, "error": f"文件过大（{size/1024/1024:.1f}MB），最大支持 10MB"}

        content = path.read_text(encoding="utf-8", errors="ignore")

        # 截断超长内容
        truncated = False
        if len(content) > 8000:
            content = content[:8000] + "\n\n... [内容已截断，完整内容请查看原文件]"
            truncated = True

        return {
            "success": True,
            "path": str(resolved),
            "filename": path.name,
            "size_bytes": size,
            "content": content,
            "truncated": truncated,
            "line_count": content.count("\n") + 1,
        }
    except Exception as e:
        logger.exception("document_read error")
        return {"success": False, "error": str(e)}


def tool_spreadsheet_analyze(filepath: str, max_rows: int = 100) -> dict:
    """分析 CSV / TSV 表格文件，输出统计摘要。

    Args:
        filepath: CSV/TSV 文件路径
        max_rows: 最多分析的行数

    Returns:
        列名、行数、每列统计（数值列的均值/最大最小值）
    """
    try:
        path = Path(filepath)
        if not path.is_absolute():
            path = OFFICE_DIR / filepath

        if not path.exists():
            return {"success": False, "error": f"文件不存在: {path}"}

        # 检测分隔符
        ext = path.suffix.lower()
        delimiter = ","
        if ext == ".tsv":
            delimiter = "\t"
        elif ext == ".csv":
            # 嗅探一下
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                first_line = f.readline()
                if "\t" in first_line and "," not in first_line:
                    delimiter = "\t"

        rows: list[dict] = []
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for i, row in enumerate(reader):
                if i >= max_rows:
                    break
                rows.append(row)

        if not rows:
            return {"success": False, "error": "表格为空或无法解析"}

        columns = list(rows[0].keys())
        col_stats: dict[str, dict] = {}

        for col in columns:
            values = [row.get(col, "") for row in rows]
            non_empty = [v for v in values if v.strip()]

            # 尝试识别数值列
            numeric_values = []
            for v in non_empty:
                try:
                    numeric_values.append(float(v))
                except (ValueError, TypeError):
                    pass

            if len(numeric_values) >= len(non_empty) * 0.7 and len(numeric_values) > 0:
                col_stats[col] = {
                    "type": "numeric",
                    "count": len(non_empty),
                    "mean": round(sum(numeric_values) / len(numeric_values), 4),
                    "min": min(numeric_values),
                    "max": max(numeric_values),
                }
            else:
                unique_vals = list(set(non_empty))
                col_stats[col] = {
                    "type": "text",
                    "count": len(non_empty),
                    "unique_count": len(unique_vals),
                    "sample_values": unique_vals[:5],
                }

        return {
            "success": True,
            "path": str(path),
            "total_rows": len(rows),
            "columns": columns,
            "column_count": len(columns),
            "column_stats": col_stats,
            "preview": rows[:5],
        }
    except Exception as e:
        logger.exception("spreadsheet_analyze error")
        return {"success": False, "error": str(e)}


def tool_file_search(
    keyword: str,
    directory: str = "",
    file_type: str = "",
    max_results: int = 20,
) -> dict:
    """在本地搜索文件（按文件名关键词）。

    Args:
        keyword: 文件名关键词
        directory: 搜索目录（默认：桌面 + 文档 + 下载 + AerieOffice）
        file_type: 限定文件类型（doc/excel/ppt/pdf/image/code/all）
        max_results: 最多返回结果数

    Returns:
        匹配的文件列表
    """
    try:
        # 搜索范围
        search_dirs = []
        if directory:
            p = Path(directory)
            if p.exists():
                search_dirs.append(p.resolve())
        else:
            for d in ["~/Desktop", "~/Documents", "~/Downloads"]:
                p = Path(os.path.expanduser(d))
                if p.exists():
                    search_dirs.append(p.resolve())
            search_dirs.append(OFFICE_DIR.resolve())

        # 文件类型过滤
        ext_map = {
            "doc": [".md", ".txt", ".doc", ".docx", ".pdf"],
            "excel": [".csv", ".tsv", ".xls", ".xlsx"],
            "ppt": [".ppt", ".pptx"],
            "pdf": [".pdf"],
            "image": [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"],
            "code": [".py", ".js", ".ts", ".html", ".css", ".java", ".go", ".rs", ".cpp"],
            "all": [],
        }
        allowed_exts = ext_map.get(file_type.lower(), [])

        results = []
        keyword_lower = keyword.lower()

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for root, dirs, files in os.walk(search_dir):
                # 跳过隐藏目录
                dirs[:] = [d for d in dirs if not d.startswith(".")]

                for fname in files:
                    if keyword_lower not in fname.lower():
                        continue

                    fpath = Path(root) / fname

                    # 扩展名过滤
                    if allowed_exts and fpath.suffix.lower() not in allowed_exts:
                        continue

                    try:
                        stat = fpath.stat()
                        results.append({
                            "name": fname,
                            "path": str(fpath),
                            "size_bytes": stat.st_size,
                            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                        })
                    except Exception:
                        continue

                    if len(results) >= max_results:
                        break
                if len(results) >= max_results:
                    break
            if len(results) >= max_results:
                break

        return {
            "success": True,
            "keyword": keyword,
            "count": len(results),
            "files": results,
            "search_dirs": [str(d) for d in search_dirs],
        }
    except Exception as e:
        logger.exception("file_search error")
        return {"success": False, "error": str(e)}


def tool_text_summary(text: str, max_length: int = 300) -> dict:
    """对文本进行简要摘要（抽取式）。

    Args:
        text: 要摘要的文本
        max_length: 摘要最大字数

    Returns:
        摘要结果
    """
    try:
        if not text or not text.strip():
            return {"success": False, "error": "文本为空"}

        # 简单的抽取式摘要：取前几句话 + 关键词
        sentences = [s.strip() for s in text.replace("。", "。\n").replace("！", "！\n").replace("？", "？\n").split("\n") if s.strip()]

        summary_parts = []
        current_len = 0
        for sent in sentences:
            if current_len + len(sent) > max_length and summary_parts:
                break
            summary_parts.append(sent)
            current_len += len(sent)

        summary = "".join(summary_parts)
        if len(text) > len(summary) and not summary.endswith("。"):
            summary += "..."

        # 提取高频词（简单版）
        words = []
        for char in text:
            if "\u4e00" <= char <= "\u9fff":
                words.append(char)
        word_freq: dict[str, int] = {}
        for i in range(len(words) - 1):
            bigram = words[i] + words[i + 1]
            word_freq[bigram] = word_freq.get(bigram, 0) + 1
        top_keywords = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            "success": True,
            "summary": summary,
            "original_length": len(text),
            "summary_length": len(summary),
            "compression_ratio": round(len(summary) / len(text), 3) if text else 0,
            "top_keywords": [kw for kw, _ in top_keywords],
        }
    except Exception as e:
        logger.exception("text_summary error")
        return {"success": False, "error": str(e)}


def tool_calendar_list(
    start_date: str = "",
    end_date: str = "",
    max_results: int = 20,
) -> dict:
    """获取日历事件列表。

    Args:
        start_date: 开始日期 YYYY-MM-DD（默认今天）
        end_date: 结束日期 YYYY-MM-DD（默认 7 天后）
        max_results: 最多返回数量

    Returns:
        事件列表
    """
    try:
        from core.calendar_db import get_calendar_db
        db = get_calendar_db()

        if not start_date:
            start_date = datetime.now().strftime("%Y-%m-%d")
        if not end_date:
            from datetime import timedelta
            end_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

        events = db.list_events(start_date=start_date, end_date=end_date, limit=max_results)
        return {
            "success": True,
            "start_date": start_date,
            "end_date": end_date,
            "count": len(events),
            "events": events,
        }
    except Exception as e:
        logger.exception("calendar_list error")
        return {"success": False, "error": str(e)}


def tool_calendar_create(
    title: str,
    date: str,
    time: str = "",
    description: str = "",
    category: str = "work",
) -> dict:
    """创建日历事件。

    Args:
        title: 事件标题
        date: 日期 YYYY-MM-DD
        time: 时间 HH:MM（可选）
        description: 描述（可选）
        category: 分类（work/personal/reminder 等）

    Returns:
        创建结果
    """
    try:
        from core.calendar_db import get_calendar_db
        db = get_calendar_db()

        event_data = {
            "title": title,
            "date": date,
            "time": time or None,
            "description": description or None,
            "category": category,
        }

        event_id = db.create_event(event_data)
        event = db.get_event(event_id)

        return {
            "success": True,
            "event_id": event_id,
            "event": event,
            "message": f"已创建事件：{title}",
        }
    except Exception as e:
        logger.exception("calendar_create error")
        return {"success": False, "error": str(e)}


# ── 注册到 ToolRegistry ──────────────────────────

_OFFICE_TOOL_SCHEMAS = {
    "document_create": {
        "type": "function",
        "function": {
            "name": "document_create",
            "description": "创建并保存一个办公文档（Markdown/TXT格式）到本地 AerieOffice 目录。用于写报告、方案、总结、邮件草稿等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "文件名（不需要路径和后缀）",
                    },
                    "content": {
                        "type": "string",
                        "description": "文档完整内容",
                    },
                    "format": {
                        "type": "string",
                        "description": "文档格式：markdown 或 txt",
                        "enum": ["markdown", "txt"],
                        "default": "markdown",
                    },
                },
                "required": ["filename", "content"],
            },
        },
    },
    "document_read": {
        "type": "function",
        "function": {
            "name": "document_read",
            "description": "读取本地文档内容（支持 md/txt/csv 等文本文件）。仅允许读取桌面/文档/下载/AerieOffice 目录下的文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "文件路径（绝对路径或相对 AerieOffice 的路径）",
                    },
                },
                "required": ["filepath"],
            },
        },
    },
    "spreadsheet_analyze": {
        "type": "function",
        "function": {
            "name": "spreadsheet_analyze",
            "description": "分析 CSV/TSV 表格文件，输出列名、行数、数值列统计（均值/最大最小）、数据预览。",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "CSV/TSV 文件路径",
                    },
                    "max_rows": {
                        "type": "integer",
                        "description": "最多分析的行数",
                        "default": 100,
                    },
                },
                "required": ["filepath"],
            },
        },
    },
    "file_search": {
        "type": "function",
        "function": {
            "name": "file_search",
            "description": "在本地搜索文件（按文件名关键词）。默认搜索桌面、文档、下载、AerieOffice 目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "文件名关键词",
                    },
                    "directory": {
                        "type": "string",
                        "description": "指定搜索目录（留空则搜索默认位置）",
                    },
                    "file_type": {
                        "type": "string",
                        "description": "文件类型过滤",
                        "enum": ["all", "doc", "excel", "ppt", "pdf", "image", "code"],
                        "default": "all",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最多返回结果数",
                        "default": 20,
                    },
                },
                "required": ["keyword"],
            },
        },
    },
    "text_summary": {
        "type": "function",
        "function": {
            "name": "text_summary",
            "description": "对长文本进行快速摘要，提取核心内容和关键词。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "要摘要的文本内容",
                    },
                    "max_length": {
                        "type": "integer",
                        "description": "摘要最大字数",
                        "default": 300,
                    },
                },
                "required": ["text"],
            },
        },
    },
    "calendar_list": {
        "type": "function",
        "function": {
            "name": "calendar_list",
            "description": "查看日历事件列表，了解近期日程安排。",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "开始日期 YYYY-MM-DD（默认今天）",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "结束日期 YYYY-MM-DD（默认 7 天后）",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最多返回数量",
                        "default": 20,
                    },
                },
                "required": [],
            },
        },
    },
    "calendar_create": {
        "type": "function",
        "function": {
            "name": "calendar_create",
            "description": "创建日历事件，安排会议、提醒、待办事项等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "事件标题",
                    },
                    "date": {
                        "type": "string",
                        "description": "日期 YYYY-MM-DD",
                    },
                    "time": {
                        "type": "string",
                        "description": "时间 HH:MM（可选）",
                    },
                    "description": {
                        "type": "string",
                        "description": "事件描述（可选）",
                    },
                    "category": {
                        "type": "string",
                        "description": "分类",
                        "enum": ["work", "personal", "reminder", "meeting"],
                        "default": "work",
                    },
                },
                "required": ["title", "date"],
            },
        },
    },
}


def register_office_tools(registry) -> int:
    """注册所有办公工具到 ToolRegistry。返回注册的工具数量。"""
    from .tool_registry import ToolRegistry

    tool_funcs = {
        "document_create": tool_document_create,
        "document_read": tool_document_read,
        "spreadsheet_analyze": tool_spreadsheet_analyze,
        "file_search": tool_file_search,
        "text_summary": tool_text_summary,
        "calendar_list": tool_calendar_list,
        "calendar_create": tool_calendar_create,
    }

    count = 0
    for name, func in tool_funcs.items():
        schema = _OFFICE_TOOL_SCHEMAS.get(name)
        if schema:
            registry.register(name, func, schema)
            count += 1

    logger.info("registered %d office tools", count)
    return count
