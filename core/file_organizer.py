"""Aerie v0.1.0-beta.1 · 文件整理模块

功能：
  - 目录扫描与文件元数据提取
  - AI 智能分类（规则为主，可接入 LLM）
  - 分类预览（dry-run，不实际移动）
  - 执行整理（移动/重命名）
  - 7 天撤销日志（undo）
  - 大文件/近期文件标记

分类规则：
  - 文档类：.pdf .doc .docx .txt .md .xls .xlsx .ppt .pptx 等
  - 图片类：.jpg .jpeg .png .gif .bmp .svg .webp 等
  - 视频类：.mp4 .avi .mkv .mov .wmv .flv 等
  - 音频类：.mp3 .wav .flac .aac .ogg .m4a 等
  - 压缩包：.zip .rar .7z .tar .gz .bz2 等
  - 代码类：.py .js .ts .html .css .java .cpp .go 等
  - 安装包：.exe .msi .apk .dmg .pkg 等
  - 其他：未分类文件
"""

from __future__ import annotations
import os
import time
import json
import shutil
import hashlib
import logging
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class FileCategory(str, Enum):
    """文件分类"""
    DOCUMENTS = "documents"      # 文档
    IMAGES = "images"            # 图片
    VIDEOS = "videos"            # 视频
    AUDIO = "audio"              # 音频
    ARCHIVES = "archives"        # 压缩包
    CODE = "code"                # 代码
    INSTALLERS = "installers"    # 安装包
    OTHER = "other"              # 其他


CATEGORY_NAMES = {
    FileCategory.DOCUMENTS: "文档",
    FileCategory.IMAGES: "图片",
    FileCategory.VIDEOS: "视频",
    FileCategory.AUDIO: "音频",
    FileCategory.ARCHIVES: "压缩包",
    FileCategory.CODE: "代码",
    FileCategory.INSTALLERS: "安装包",
    FileCategory.OTHER: "其他",
}


EXTENSION_MAP = {
    # 文档
    ".pdf": FileCategory.DOCUMENTS,
    ".doc": FileCategory.DOCUMENTS,
    ".docx": FileCategory.DOCUMENTS,
    ".txt": FileCategory.DOCUMENTS,
    ".md": FileCategory.DOCUMENTS,
    ".rtf": FileCategory.DOCUMENTS,
    ".xls": FileCategory.DOCUMENTS,
    ".xlsx": FileCategory.DOCUMENTS,
    ".ppt": FileCategory.DOCUMENTS,
    ".pptx": FileCategory.DOCUMENTS,
    ".csv": FileCategory.DOCUMENTS,
    ".odt": FileCategory.DOCUMENTS,
    ".epub": FileCategory.DOCUMENTS,
    ".mobi": FileCategory.DOCUMENTS,

    # 图片
    ".jpg": FileCategory.IMAGES,
    ".jpeg": FileCategory.IMAGES,
    ".png": FileCategory.IMAGES,
    ".gif": FileCategory.IMAGES,
    ".bmp": FileCategory.IMAGES,
    ".svg": FileCategory.IMAGES,
    ".webp": FileCategory.IMAGES,
    ".ico": FileCategory.IMAGES,
    ".tiff": FileCategory.IMAGES,
    ".tif": FileCategory.IMAGES,
    ".psd": FileCategory.IMAGES,
    ".ai": FileCategory.IMAGES,
    ".raw": FileCategory.IMAGES,
    ".heic": FileCategory.IMAGES,

    # 视频
    ".mp4": FileCategory.VIDEOS,
    ".avi": FileCategory.VIDEOS,
    ".mkv": FileCategory.VIDEOS,
    ".mov": FileCategory.VIDEOS,
    ".wmv": FileCategory.VIDEOS,
    ".flv": FileCategory.VIDEOS,
    ".webm": FileCategory.VIDEOS,
    ".m4v": FileCategory.VIDEOS,
    ".mpeg": FileCategory.VIDEOS,
    ".mpg": FileCategory.VIDEOS,
    ".3gp": FileCategory.VIDEOS,

    # 音频
    ".mp3": FileCategory.AUDIO,
    ".wav": FileCategory.AUDIO,
    ".flac": FileCategory.AUDIO,
    ".aac": FileCategory.AUDIO,
    ".ogg": FileCategory.AUDIO,
    ".m4a": FileCategory.AUDIO,
    ".wma": FileCategory.AUDIO,
    ".ape": FileCategory.AUDIO,
    ".opus": FileCategory.AUDIO,
    ".mid": FileCategory.AUDIO,
    ".midi": FileCategory.AUDIO,

    # 压缩包
    ".zip": FileCategory.ARCHIVES,
    ".rar": FileCategory.ARCHIVES,
    ".7z": FileCategory.ARCHIVES,
    ".tar": FileCategory.ARCHIVES,
    ".gz": FileCategory.ARCHIVES,
    ".bz2": FileCategory.ARCHIVES,
    ".xz": FileCategory.ARCHIVES,
    ".tgz": FileCategory.ARCHIVES,
    ".tbz2": FileCategory.ARCHIVES,
    ".iso": FileCategory.ARCHIVES,

    # 代码
    ".py": FileCategory.CODE,
    ".js": FileCategory.CODE,
    ".ts": FileCategory.CODE,
    ".html": FileCategory.CODE,
    ".css": FileCategory.CODE,
    ".java": FileCategory.CODE,
    ".cpp": FileCategory.CODE,
    ".c": FileCategory.CODE,
    ".h": FileCategory.CODE,
    ".hpp": FileCategory.CODE,
    ".go": FileCategory.CODE,
    ".rs": FileCategory.CODE,
    ".rb": FileCategory.CODE,
    ".php": FileCategory.CODE,
    ".swift": FileCategory.CODE,
    ".kt": FileCategory.CODE,
    ".scala": FileCategory.CODE,
    ".lua": FileCategory.CODE,
    ".sh": FileCategory.CODE,
    ".bat": FileCategory.CODE,
    ".ps1": FileCategory.CODE,
    ".sql": FileCategory.CODE,
    ".json": FileCategory.CODE,
    ".xml": FileCategory.CODE,
    ".yaml": FileCategory.CODE,
    ".yml": FileCategory.CODE,

    # 安装包
    ".exe": FileCategory.INSTALLERS,
    ".msi": FileCategory.INSTALLERS,
    ".apk": FileCategory.INSTALLERS,
    ".dmg": FileCategory.INSTALLERS,
    ".pkg": FileCategory.INSTALLERS,
    ".deb": FileCategory.INSTALLERS,
    ".rpm": FileCategory.INSTALLERS,
    ".appimage": FileCategory.INSTALLERS,
}

# 大文件阈值 (100MB)
LARGE_FILE_THRESHOLD = 100 * 1024 * 1024

# 近期文件阈值 (7天)
RECENT_FILE_THRESHOLD_DAYS = 7

# 撤销日志保留天数
UNDO_RETENTION_DAYS = 7


# v13.9 Batch 2.5: 文件整理预设模板
ORGANIZE_TEMPLATES: dict[str, dict] = {
    "downloads": {
        "id": "downloads",
        "name": "下载文件夹整理",
        "description": "按文件类型分类下载目录",
        "icon": "package",
        "default_source": "~/Downloads",
        "default_target": "~/Downloads",
        "categories": [
            FileCategory.IMAGES.value,
            FileCategory.DOCUMENTS.value,
            FileCategory.VIDEOS.value,
            FileCategory.AUDIO.value,
            FileCategory.ARCHIVES.value,
            FileCategory.INSTALLERS.value,
            FileCategory.OTHER.value,
        ],
        "category_folders": {
            FileCategory.IMAGES.value: "图片",
            FileCategory.DOCUMENTS.value: "文档",
            FileCategory.VIDEOS.value: "视频",
            FileCategory.AUDIO.value: "音频",
            FileCategory.ARCHIVES.value: "压缩包",
            FileCategory.INSTALLERS.value: "安装包",
            FileCategory.CODE.value: "代码",
            FileCategory.OTHER.value: "其他",
        },
    },
    "desktop": {
        "id": "desktop",
        "name": "桌面整理",
        "description": "按用途分类桌面文件，保持桌面整洁",
        "icon": "briefcase",
        "default_source": "~/Desktop",
        "default_target": "~/Desktop",
        "categories": [
            FileCategory.DOCUMENTS.value,
            FileCategory.IMAGES.value,
            FileCategory.VIDEOS.value,
            FileCategory.ARCHIVES.value,
            FileCategory.OTHER.value,
        ],
        "category_folders": {
            FileCategory.DOCUMENTS.value: "工作文档",
            FileCategory.IMAGES.value: "图片素材",
            FileCategory.VIDEOS.value: "视频",
            FileCategory.ARCHIVES.value: "压缩文件",
            FileCategory.OTHER.value: "其他",
        },
    },
    "photos_by_date": {
        "id": "photos_by_date",
        "name": "照片按日期整理",
        "description": "按拍摄日期/修改日期归档照片",
        "icon": "image",
        "default_source": "~/Pictures",
        "default_target": "~/Pictures",
        "categories": [FileCategory.IMAGES.value],
        "group_by": "date_month",
        "category_folders": {
            FileCategory.IMAGES.value: "照片",
        },
    },
    "work_docs": {
        "id": "work_docs",
        "name": "工作文档整理",
        "description": "按项目和年份分类工作文档",
        "icon": "file-text",
        "default_source": "~/Documents",
        "default_target": "~/Documents/工作文档",
        "categories": [
            FileCategory.DOCUMENTS.value,
            FileCategory.ARCHIVES.value,
        ],
        "category_folders": {
            FileCategory.DOCUMENTS.value: "文档",
            FileCategory.ARCHIVES.value: "归档项目",
        },
    },
}


def get_organize_template(template_id: str) -> dict | None:
    """获取整理预设模板"""
    return ORGANIZE_TEMPLATES.get(template_id)


def list_organize_templates() -> list[dict]:
    """列出所有整理预设模板"""
    return [
        {
            "id": t["id"],
            "name": t["name"],
            "description": t["description"],
            "icon": t["icon"],
        }
        for t in ORGANIZE_TEMPLATES.values()
    ]


@dataclass
class FileInfo:
    """文件信息"""
    path: str
    name: str
    size: int
    extension: str
    category: FileCategory
    created_at: float
    modified_at: float
    is_large: bool = False
    is_recent: bool = False

    def __post_init__(self):
        if not self.is_large:
            self.is_large = self.size >= LARGE_FILE_THRESHOLD
        if not self.is_recent:
            self.is_recent = (time.time() - self.modified_at) < RECENT_FILE_THRESHOLD_DAYS * 86400

    @property
    def size_human(self) -> str:
        size = self.size
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "name": self.name,
            "size": self.size,
            "size_human": self.size_human,
            "extension": self.extension,
            "category": self.category.value,
            "category_name": CATEGORY_NAMES[self.category],
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "is_large": self.is_large,
            "is_recent": self.is_recent,
        }


@dataclass
class MoveAction:
    """移动操作"""
    source: str
    target: str
    category: FileCategory
    file_size: int

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "category": self.category.value,
            "file_size": self.file_size,
        }


@dataclass
class OrganizePlan:
    """整理计划"""
    source_dir: str
    target_dir: str
    files: list[FileInfo] = field(default_factory=list)
    actions: list[MoveAction] = field(default_factory=list)
    category_stats: dict[str, dict] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    @property
    def total_files(self) -> int:
        return len(self.files)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def total_size_human(self) -> str:
        size = self.total_size
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    def to_dict(self) -> dict:
        return {
            "source_dir": self.source_dir,
            "target_dir": self.target_dir,
            "total_files": self.total_files,
            "total_size": self.total_size,
            "total_size_human": self.total_size_human,
            "category_stats": self.category_stats,
            "actions": [a.to_dict() for a in self.actions],
            "created_at": self.created_at,
        }


@dataclass
class CleanupPlan:
    """清理计划（下载清理：哈希去重 / mtime 过期清理）

    与 OrganizePlan 类似，但面向"删除/腾退"场景。动作仍用 MoveAction
    表示，目标统一移到回收目录（去重→重复文件、过期→过期文件），
    从而复用 UndoManager 实现可撤销，避免误删。
    """
    source_dir: str
    target_dir: str
    kind: str                                # "dedup" | "expired" | "downloads"
    files: list[FileInfo] = field(default_factory=list)
    actions: list[MoveAction] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    @property
    def total_files(self) -> int:
        return len(self.files)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def total_size_human(self) -> str:
        size = self.total_size
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    def to_dict(self) -> dict:
        return {
            "source_dir": self.source_dir,
            "target_dir": self.target_dir,
            "kind": self.kind,
            "total_files": self.total_files,
            "total_size": self.total_size,
            "total_size_human": self.total_size_human,
            "summary": self.summary,
            "actions": [a.to_dict() for a in self.actions],
            "created_at": self.created_at,
        }


@dataclass
class UndoRecord:
    """撤销记录"""
    undo_id: str
    description: str
    actions: list[MoveAction] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    executed: bool = False
    executed_at: Optional[float] = None

    @property
    def can_undo(self) -> bool:
        """是否在可撤销窗口内"""
        if not self.executed:
            return False
        if self.executed_at is None:
            return False
        return (time.time() - self.executed_at) < UNDO_RETENTION_DAYS * 86400

    @property
    def age_hours(self) -> float:
        """记录存在时间（小时）"""
        if self.executed_at is None:
            return 0
        return (time.time() - self.executed_at) / 3600

    def to_dict(self) -> dict:
        return {
            "undo_id": self.undo_id,
            "description": self.description,
            "actions": [a.to_dict() for a in self.actions],
            "created_at": self.created_at,
            "executed": self.executed,
            "executed_at": self.executed_at,
            "can_undo": self.can_undo,
            "age_hours": round(self.age_hours, 1),
        }


class FileClassifier:
    """文件分类器

    基于扩展名规则分类，可扩展 LLM 智能分类。
    """

    def __init__(self, custom_rules: Optional[dict[str, FileCategory]] = None):
        self.ext_map = EXTENSION_MAP.copy()
        if custom_rules:
            for ext, cat in custom_rules.items():
                self.ext_map[ext.lower()] = cat

    def classify(self, file_path: str | Path) -> FileCategory:
        """分类单个文件"""
        path = Path(file_path)
        ext = path.suffix.lower()
        return self.ext_map.get(ext, FileCategory.OTHER)

    def classify_by_content_hint(self, file_path: str | Path,
                                 hint: str) -> FileCategory:
        """基于内容提示分类（预留 LLM 接口）"""
        # 先用扩展名分类
        ext_cat = self.classify(file_path)

        # 如果扩展名是 OTHER，再根据提示判断
        if ext_cat == FileCategory.OTHER:
            hint_lower = hint.lower()
            if any(kw in hint_lower for kw in ["报告", "文档", "论文", "说明", "readme"]):
                return FileCategory.DOCUMENTS
            if any(kw in hint_lower for kw in ["照片", "截图", "图片", "screenshot"]):
                return FileCategory.IMAGES
            if any(kw in hint_lower for kw in ["视频", "电影", "mv", "video"]):
                return FileCategory.VIDEOS

        return ext_cat


class DirectoryScanner:
    """目录扫描器"""

    def __init__(self, classifier: Optional[FileClassifier] = None):
        self.classifier = classifier or FileClassifier()

    def scan(self, directory: str | Path,
             recursive: bool = True,
             include_hidden: bool = False,
             min_size: int = 0) -> list[FileInfo]:
        """扫描目录

        Args:
            directory: 要扫描的目录
            recursive: 是否递归子目录
            include_hidden: 是否包含隐藏文件
            min_size: 最小文件大小（字节）

        Returns:
            文件信息列表
        """
        dir_path = Path(directory)
        if not dir_path.exists() or not dir_path.is_dir():
            raise ValueError(f"目录不存在或不是目录: {directory}")

        files: list[FileInfo] = []
        now = time.time()
        recent_threshold = RECENT_FILE_THRESHOLD_DAYS * 86400

        try:
            if recursive:
                iterator = dir_path.rglob("*")
            else:
                iterator = dir_path.iterdir()

            for path in iterator:
                try:
                    if path.is_dir():
                        continue

                    if not include_hidden and path.name.startswith("."):
                        continue

                    stat = path.stat()

                    if stat.st_size < min_size:
                        continue

                    ext = path.suffix.lower()
                    category = self.classifier.classify(path)
                    is_large = stat.st_size >= LARGE_FILE_THRESHOLD
                    is_recent = (now - stat.st_mtime) < recent_threshold

                    file_info = FileInfo(
                        path=str(path),
                        name=path.name,
                        size=stat.st_size,
                        extension=ext,
                        category=category,
                        created_at=stat.st_ctime,
                        modified_at=stat.st_mtime,
                        is_large=is_large,
                        is_recent=is_recent,
                    )
                    files.append(file_info)
                except (PermissionError, OSError) as e:
                    logger.debug(f"跳过文件 {path}: {e}")
                    continue
        except Exception as e:
            logger.error(f"扫描目录失败: {e}")
            raise

        return files


class OrganizePlanner:
    """整理计划生成器"""

    def __init__(self, classifier: Optional[FileClassifier] = None):
        self.classifier = classifier or FileClassifier()
        self.scanner = DirectoryScanner(self.classifier)

    def create_plan(self, source_dir: str | Path,
                    target_dir: Optional[str | Path] = None,
                    recursive: bool = False,
                    include_subdirs: bool = False) -> OrganizePlan:
        """创建整理计划

        Args:
            source_dir: 源目录
            target_dir: 目标目录（默认在源目录下按分类创建子文件夹）
            recursive: 是否递归扫描子目录
            include_subdirs: 是否把子目录里的文件也移到分类目录

        Returns:
            整理计划（dry-run，不实际移动）
        """
        src = Path(source_dir)
        tgt = Path(target_dir) if target_dir else src

        # 扫描文件
        files = self.scanner.scan(src, recursive=recursive)

        # 过滤：排除已经在分类目录里的文件
        category_dirs = {cat.value for cat in FileCategory}
        filtered = []
        for f in files:
            rel = Path(f.path).relative_to(src)
            parts = rel.parts
            # 如果文件已经在分类目录里，跳过
            if parts and parts[0] in category_dirs:
                continue
            filtered.append(f)

        files = filtered

        # 生成移动操作
        actions: list[MoveAction] = []
        category_stats: dict[str, dict] = {}

        for f in files:
            cat_dir = tgt / f.category.value
            target_path = cat_dir / f.name

            # 处理重名
            if target_path.exists() and str(target_path.resolve()) != Path(f.path).resolve():
                stem = Path(f.name).stem
                suffix = Path(f.name).suffix
                counter = 1
                while target_path.exists():
                    new_name = f"{stem}_{counter}{suffix}"
                    target_path = cat_dir / new_name
                    counter += 1

            action = MoveAction(
                source=f.path,
                target=str(target_path),
                category=f.category,
                file_size=f.size,
            )
            actions.append(action)

            # 统计
            cat_key = f.category.value
            if cat_key not in category_stats:
                category_stats[cat_key] = {
                    "name": CATEGORY_NAMES[f.category],
                    "count": 0,
                    "total_size": 0,
                }
            category_stats[cat_key]["count"] += 1
            category_stats[cat_key]["total_size"] += f.size

        # 计算人类可读大小
        for stat in category_stats.values():
            size = stat["total_size"]
            for unit in ["B", "KB", "MB", "GB"]:
                if size < 1024:
                    stat["size_human"] = f"{size:.1f} {unit}"
                    break
                size /= 1024
            else:
                stat["size_human"] = f"{size:.1f} TB"

        plan = OrganizePlan(
            source_dir=str(src),
            target_dir=str(tgt),
            files=files,
            actions=actions,
            category_stats=category_stats,
        )

        return plan


class UndoManager:
    """撤销管理器

    保存最近 7 天的整理操作，支持一键撤销。
    """

    def __init__(self, log_dir: str = "data/undo"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.log_dir / "undo_index.json"
        self._records: dict[str, UndoRecord] = {}
        self._load_index()
        self._cleanup_expired()

    def _load_index(self) -> None:
        """加载索引"""
        if self.index_file.exists():
            try:
                data = json.loads(self.index_file.read_text(encoding="utf-8"))
                for item in data.get("records", []):
                    record = UndoRecord(
                        undo_id=item["undo_id"],
                        description=item.get("description", ""),
                        created_at=item.get("created_at", time.time()),
                        executed=item.get("executed", False),
                        executed_at=item.get("executed_at"),
                    )
                    # 加载 actions
                    record_file = self.log_dir / f"{record.undo_id}.json"
                    if record_file.exists():
                        try:
                            record_data = json.loads(record_file.read_text(encoding="utf-8"))
                            for a in record_data.get("actions", []):
                                record.actions.append(MoveAction(
                                    source=a["source"],
                                    target=a["target"],
                                    category=FileCategory(a["category"]),
                                    file_size=a.get("file_size", 0),
                                ))
                        except Exception as e:
                            logger.warning(f"加载撤销记录失败 {record.undo_id}: {e}")
                    self._records[record.undo_id] = record
            except Exception as e:
                logger.warning(f"加载撤销索引失败: {e}")

    def _save_index(self) -> None:
        """保存索引"""
        data = {
            "records": [
                {
                    "undo_id": r.undo_id,
                    "description": r.description,
                    "created_at": r.created_at,
                    "executed": r.executed,
                    "executed_at": r.executed_at,
                }
                for r in self._records.values()
            ],
            "updated_at": time.time(),
        }
        self.index_file.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                   encoding="utf-8")

    def _cleanup_expired(self) -> None:
        """清理过期记录"""
        expired = []
        for rid, record in self._records.items():
            if (time.time() - record.created_at) > UNDO_RETENTION_DAYS * 86400:
                expired.append(rid)

        for rid in expired:
            record_file = self.log_dir / f"{rid}.json"
            if record_file.exists():
                record_file.unlink()
            del self._records[rid]

        if expired:
            self._save_index()

    def create_record(self, description: str,
                      actions: list[MoveAction]) -> UndoRecord:
        """创建一个新的撤销记录（未执行状态）"""
        self._cleanup_expired()

        undo_id = f"undo_{int(time.time())}_{len(self._records):04d}"
        record = UndoRecord(
            undo_id=undo_id,
            description=description,
            actions=list(actions),
        )

        # 保存详细记录
        record_file = self.log_dir / f"{undo_id}.json"
        record_file.write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self._records[undo_id] = record
        self._save_index()

        return record

    def mark_executed(self, undo_id: str) -> None:
        """标记为已执行"""
        if undo_id in self._records:
            record = self._records[undo_id]
            record.executed = True
            record.executed_at = time.time()

            # 更新详细记录文件
            record_file = self.log_dir / f"{undo_id}.json"
            record_file.write_text(
                json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            self._save_index()

    def undo(self, undo_id: str) -> tuple[bool, str, int]:
        """执行撤销

        Returns:
            (是否成功, 消息, 成功撤销的文件数)
        """
        if undo_id not in self._records:
            return False, f"撤销记录不存在: {undo_id}", 0

        record = self._records[undo_id]
        if not record.can_undo:
            return False, f"已超过 {UNDO_RETENTION_DAYS} 天撤销窗口", 0

        success_count = 0
        errors = []

        # 反向执行：从 target 移回 source
        for action in reversed(record.actions):
            try:
                src = Path(action.target)
                dst = Path(action.source)

                if not src.exists():
                    # 文件不在目标位置（可能已经被移动），跳过
                    logger.warning(f"撤销时源文件不存在: {src}")
                    continue

                dst.parent.mkdir(parents=True, exist_ok=True)

                # 处理重名
                if dst.exists():
                    stem = dst.stem
                    suffix = dst.suffix
                    counter = 1
                    while dst.exists():
                        dst = dst.with_name(f"{stem}_restored_{counter}{suffix}")
                        counter += 1

                shutil.move(str(src), str(dst))
                success_count += 1
            except Exception as e:
                errors.append(f"{action.source}: {e}")
                logger.error(f"撤销失败 {action.source}: {e}")

        if errors:
            msg = f"部分撤销成功 ({success_count}/{len(record.actions)})，错误: {'; '.join(errors[:3])}"
        else:
            msg = f"撤销成功，共恢复 {success_count} 个文件"

        # 标记为已撤销（不能再撤销）
        record.executed = False
        record.executed_at = None

        # 更新记录文件
        record_file = self.log_dir / f"{undo_id}.json"
        record_file.write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._save_index()

        return success_count > 0, msg, success_count

    def list_records(self, limit: int = 20) -> list[UndoRecord]:
        """列出撤销记录（按时间倒序）"""
        self._cleanup_expired()
        records = sorted(
            self._records.values(),
            key=lambda r: r.created_at,
            reverse=True,
        )
        return records[:limit]

    def get_record(self, undo_id: str) -> Optional[UndoRecord]:
        """获取单个撤销记录"""
        return self._records.get(undo_id)


# ── 下载清理辅助函数 ──────────────────────────────────────

_HASH_READ_CHUNK = 64 * 1024   # 部分指纹采样块
_FULL_HASH_CHUNK = 1024 * 1024  # 全文哈希读块


def _format_bytes(size: int) -> str:
    """字节数转人类可读（与 FileInfo.size_human 一致）"""
    value = float(size)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


def _file_partial_fingerprint(path: Path, size: int) -> str:
    """部分指纹：大小 + 首/中/尾采样，用于去重初筛（不读全文件）。"""
    h = hashlib.sha256()
    h.update(str(size).encode("utf-8"))
    try:
        with open(path, "rb") as f:
            h.update(f.read(_HASH_READ_CHUNK))
            mid = max(0, size // 2)
            f.seek(mid)
            h.update(f.read(_HASH_READ_CHUNK))
            tail = max(0, size - _HASH_READ_CHUNK)
            f.seek(tail)
            h.update(f.read(_HASH_READ_CHUNK))
    except OSError:
        # 读取失败则退化为仅按大小，交由全文哈希阶段兜底
        h.update(b"<unreadable>")
    return h.hexdigest()


def _file_full_hash(path: Path) -> str:
    """全文 SHA-256，用于去重最终确认。"""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(_FULL_HASH_CHUNK), b""):
                h.update(chunk)
    except OSError:
        pass
    return h.hexdigest()


def _unique_target(parent: Path, name: str, used: set[str]) -> str:
    """生成回收目录下唯一目标路径（避免重名覆盖）。

    Args:
        parent: 目标父目录
        name: 目标文件名
        used: 本次计划内已占用的绝对路径集合
    """
    parent = Path(parent)
    candidate = parent / name
    if str(candidate) not in used and not candidate.exists():
        used.add(str(candidate))
        return str(candidate)
    stem = Path(name).stem
    suffix = Path(name).suffix
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if str(candidate) not in used and not candidate.exists():
            used.add(str(candidate))
            return str(candidate)
        counter += 1


class FileOrganizer:
    """文件整理器（主入口）

    集成扫描、分类、计划、执行、撤销。
    """

    def __init__(
        self,
        undo_log_dir: str = "data/undo",
        large_file_threshold: int = LARGE_FILE_THRESHOLD,
    ):
        self.classifier = FileClassifier()
        self.scanner = DirectoryScanner(self.classifier)
        self.planner = OrganizePlanner(self.classifier)
        self.undo_manager = UndoManager(undo_log_dir)
        self.large_file_threshold = large_file_threshold

    def scan_directory(self, directory: str, recursive: bool = False) -> dict:
        """扫描目录并返回统计信息"""
        files = self.scanner.scan(directory, recursive=recursive)

        category_count: dict[str, int] = {}
        category_size: dict[str, int] = {}
        large_files = []
        recent_files = []

        for f in files:
            cat = f.category.value
            category_count[cat] = category_count.get(cat, 0) + 1
            category_size[cat] = category_size.get(cat, 0) + f.size

            if f.is_large:
                large_files.append(f.to_dict())
            if f.is_recent:
                recent_files.append(f.to_dict())

        total_size = sum(f.size for f in files)
        total_size_human = self._format_size(total_size)

        return {
            "directory": directory,
            "total_files": len(files),
            "total_size": total_size,
            "total_size_human": total_size_human,
            "recursive": recursive,
            "category_count": {
                cat: {"count": count, "name": CATEGORY_NAMES.get(FileCategory(cat), cat)}
                for cat, count in category_count.items()
            },
            "large_files_count": len(large_files),
            "recent_files_count": len(recent_files),
            "large_files": large_files[:20],  # 最多返回 20 个大文件
        }

    def preview_organize(self, source_dir: str,
                         target_dir: Optional[str] = None,
                         recursive: bool = False) -> OrganizePlan:
        """预览整理计划（dry-run）"""
        return self.planner.create_plan(
            source_dir=source_dir,
            target_dir=target_dir,
            recursive=recursive,
        )

    def execute_organize(self, plan: OrganizePlan,
                         description: str = "") -> tuple[bool, str, str]:
        """执行整理

        Returns:
            (是否成功, 消息, undo_id)
        """
        if not plan.actions:
            return False, "没有需要整理的文件", ""

        # 创建撤销记录
        undo_record = self.undo_manager.create_record(
            description=description or f"整理目录 {plan.source_dir}",
            actions=plan.actions,
        )

        success_count = 0
        errors = []

        for action in plan.actions:
            try:
                src = Path(action.source)
                dst = Path(action.target)

                if not src.exists():
                    errors.append(f"源文件不存在: {action.source}")
                    continue

                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                success_count += 1
            except Exception as e:
                errors.append(f"{action.source}: {e}")
                logger.error(f"移动文件失败 {action.source}: {e}")

        # 标记已执行
        self.undo_manager.mark_executed(undo_record.undo_id)

        if errors and success_count == 0:
            return False, f"整理失败: {'; '.join(errors[:3])}", undo_record.undo_id
        elif errors:
            msg = f"部分成功 ({success_count}/{len(plan.actions)})，{len(errors)} 个失败"
            return True, msg, undo_record.undo_id
        else:
            msg = f"整理成功，共移动 {success_count} 个文件"
            return True, msg, undo_record.undo_id

    def undo(self, undo_id: str) -> tuple[bool, str, int]:
        """撤销整理"""
        return self.undo_manager.undo(undo_id)

    def list_undo_records(self, limit: int = 20) -> list[dict]:
        """列出撤销记录"""
        records = self.undo_manager.list_records(limit)
        return [r.to_dict() for r in records]

    def quick_organize(self, source_dir: str,
                       target_dir: Optional[str] = None,
                       recursive: bool = False) -> tuple[bool, str, str]:
        """一键整理（预览 + 执行）"""
        plan = self.preview_organize(source_dir, target_dir, recursive)
        if not plan.actions:
            return False, "没有需要整理的文件", ""

        return self.execute_organize(
            plan,
            description=f"一键整理 {Path(source_dir).name}",
        )

    # ── 下载清理（哈希去重 + mtime 过期清理）──────────────────

    def find_duplicates(self, directory: str,
                        recursive: bool = False) -> list[dict]:
        """扫描并定位重复文件。

        分层策略（参考电脑管家/开源整理工具）：
        1. 先按文件大小分组（同大小才有重复可能）
        2. 组内用"部分指纹"（首/中/尾采样 + 大小）初筛候选
        3. 候选再做全文 SHA-256 确认，避免误判

        Returns:
            重复组列表，每组含 sha256、size、paths。
        """
        src = Path(directory)
        files = self.scanner.scan(src, recursive=recursive)

        by_size: dict[int, list[FileInfo]] = {}
        for f in files:
            by_size.setdefault(f.size, []).append(f)

        groups: list[dict] = []
        for size, items in by_size.items():
            if len(items) < 2:
                continue
            # 部分指纹初筛
            fp_groups: dict[str, list[FileInfo]] = {}
            for f in items:
                fp = _file_partial_fingerprint(Path(f.path), size)
                fp_groups.setdefault(fp, []).append(f)
            for fp, cands in fp_groups.items():
                if len(cands) < 2:
                    continue
                # 全文哈希确认
                hash_groups: dict[str, list[FileInfo]] = {}
                for f in cands:
                    h = _file_full_hash(Path(f.path))
                    hash_groups.setdefault(h, []).append(f)
                for h, dup_files in hash_groups.items():
                    if len(dup_files) < 2:
                        continue
                    groups.append({
                        "sha256": h,
                        "size": size,
                        "size_human": dup_files[0].size_human,
                        "count": len(dup_files),
                        "paths": [f.path for f in dup_files],
                    })
        return groups

    def preview_dedup(self, source_dir: str,
                      target_dir: Optional[str] = None,
                      recursive: bool = False,
                      keep: str = "newest") -> CleanupPlan:
        """预览去重计划（dry-run）

        Args:
            source_dir: 源目录
            target_dir: 去重文件回收目录（默认 <source>/重复文件）
            recursive: 是否递归
            keep: 每组保留哪个副本（newest=保留最新，oldest=保留最早）
        """
        src = Path(source_dir)
        tgt = Path(target_dir) if target_dir else (src / "重复文件")
        groups = self.find_duplicates(str(src), recursive)

        used_targets: set[str] = set()
        actions: list[MoveAction] = []
        dup_files: list[FileInfo] = []
        dup_count = 0
        dup_size = 0

        for g in groups:
            members = sorted(
                g["paths"],
                key=lambda p: Path(p).stat().st_mtime,
                reverse=(keep == "newest"),
            )
            keep_path = members[0]
            for dup in members[1:]:
                p = Path(dup)
                st = p.stat()
                target_path = _unique_target(tgt, p.name, used_targets)
                actions.append(MoveAction(
                    source=str(p),
                    target=str(target_path),
                    category=FileCategory.OTHER,
                    file_size=st.st_size,
                ))
                dup_count += 1
                dup_size += st.st_size
                dup_files.append(FileInfo(
                    path=str(p),
                    name=p.name,
                    size=st.st_size,
                    extension=p.suffix.lower(),
                    category=FileCategory.OTHER,
                    created_at=st.st_ctime,
                    modified_at=st.st_mtime,
                ))

        plan = CleanupPlan(
            source_dir=str(src),
            target_dir=str(tgt),
            kind="dedup",
            files=dup_files,
            actions=actions,
            summary={
                "duplicate_groups": len(groups),
                "duplicate_files": dup_count,
                "duplicate_size": dup_size,
                "duplicate_size_human": _format_bytes(dup_size),
            },
        )
        return plan

    def preview_expired_cleanup(self, source_dir: str,
                                older_than_days: int = 30,
                                target_dir: Optional[str] = None,
                                recursive: bool = False,
                                categories: Optional[list[str]] = None) -> CleanupPlan:
        """预览过期清理计划（dry-run）

        按修改时间（mtime）找出 N 天未使用的文件，移动到回收目录。
        categories 为空则清理所有类型，否则仅清理指定类型。
        """
        src = Path(source_dir)
        tgt = Path(target_dir) if target_dir else (src / "过期文件")
        cutoff = time.time() - older_than_days * 86400
        files = self.scanner.scan(src, recursive=recursive)

        used_targets: set[str] = set()
        actions: list[MoveAction] = []
        expired_files: list[FileInfo] = []
        expired_count = 0
        expired_size = 0
        cat_stats: dict[str, dict] = {}

        for f in files:
            if f.modified_at >= cutoff:
                continue
            if categories and f.category.value not in categories:
                continue
            cat_sub = tgt / CATEGORY_NAMES.get(f.category, f.category.value)
            target_path = _unique_target(cat_sub, f.name, used_targets)
            actions.append(MoveAction(
                source=f.path,
                target=str(target_path),
                category=f.category,
                file_size=f.size,
            ))
            expired_count += 1
            expired_size += f.size
            expired_files.append(f)

            ck = f.category.value
            if ck not in cat_stats:
                cat_stats[ck] = {
                    "name": CATEGORY_NAMES.get(f.category, ck),
                    "count": 0,
                    "size": 0,
                }
            cat_stats[ck]["count"] += 1
            cat_stats[ck]["size"] += f.size

        for stat in cat_stats.values():
            stat["size_human"] = _format_bytes(stat["size"])

        plan = CleanupPlan(
            source_dir=str(src),
            target_dir=str(tgt),
            kind="expired",
            files=expired_files,
            actions=actions,
            summary={
                "older_than_days": older_than_days,
                "expired_files": expired_count,
                "expired_size": expired_size,
                "expired_size_human": _format_bytes(expired_size),
                "by_category": cat_stats,
            },
        )
        return plan

    def preview_downloads_cleanup(self, source_dir: str,
                                  older_than_days: int = 30,
                                  recursive: bool = False) -> CleanupPlan:
        """预览下载清理（去重 + 过期，合并为一个计划）"""
        src = Path(source_dir)
        dedup_plan = self.preview_dedup(str(src), recursive=recursive)
        expired_plan = self.preview_expired_cleanup(
            str(src), older_than_days=older_than_days, recursive=recursive,
        )

        merged_targets: set[str] = set()
        actions = list(dedup_plan.actions) + list(expired_plan.actions)
        # 目标路径可能存在跨阶段重名，重算唯一目标
        seen: set[str] = set()
        for a in actions:
            tgt_path = Path(a.target)
            a.target = _unique_target(tgt_path.parent, tgt_path.name, seen)

        plan = CleanupPlan(
            source_dir=str(src),
            target_dir=str(src),
            kind="downloads",
            files=dedup_plan.files + expired_plan.files,
            actions=actions,
            summary={
                "dedup": dedup_plan.summary,
                "expired": expired_plan.summary,
                "older_than_days": older_than_days,
            },
        )
        return plan

    def execute_cleanup(self, plan: CleanupPlan,
                        description: str = "") -> tuple[bool, str, str]:
        """执行清理计划（可撤销）

        Returns:
            (是否成功, 消息, undo_id)
        """
        if not plan.actions:
            return False, "没有需要清理的文件", ""

        undo_record = self.undo_manager.create_record(
            description=description or f"下载清理 {Path(plan.source_dir).name}",
            actions=plan.actions,
        )

        success_count = 0
        errors = []

        for action in plan.actions:
            try:
                src = Path(action.source)
                dst = Path(action.target)
                if not src.exists():
                    errors.append(f"源文件不存在: {action.source}")
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                success_count += 1
            except Exception as e:
                errors.append(f"{action.source}: {e}")
                logger.error(f"清理移动失败 {action.source}: {e}")

        self.undo_manager.mark_executed(undo_record.undo_id)

        if errors and success_count == 0:
            return False, f"清理失败: {'; '.join(errors[:3])}", undo_record.undo_id
        elif errors:
            msg = f"部分成功 ({success_count}/{len(plan.actions)})，{len(errors)} 个失败"
            return True, msg, undo_record.undo_id
        else:
            msg = f"清理完成，共处理 {success_count} 个文件"
            return True, msg, undo_record.undo_id

    def quick_dedup(self, source_dir: str,
                    target_dir: Optional[str] = None,
                    recursive: bool = False,
                    keep: str = "newest") -> tuple[bool, str, str]:
        """一键去重（预览 + 执行）"""
        plan = self.preview_dedup(source_dir, target_dir, recursive, keep)
        if not plan.actions:
            return False, "没有发现重复文件", ""
        return self.execute_cleanup(plan, description=f"去重 {Path(source_dir).name}")

    def quick_cleanup(self, source_dir: str,
                      older_than_days: int = 30,
                      target_dir: Optional[str] = None,
                      recursive: bool = False,
                      categories: Optional[list[str]] = None) -> tuple[bool, str, str]:
        """一键过期清理（预览 + 执行）"""
        plan = self.preview_expired_cleanup(
            source_dir, older_than_days, target_dir, recursive, categories,
        )
        if not plan.actions:
            return False, "没有过期文件需要清理", ""
        return self.execute_cleanup(plan, description=f"过期清理 {Path(source_dir).name}")

    def quick_downloads_cleanup(self, source_dir: str,
                                older_than_days: int = 30,
                                recursive: bool = False) -> tuple[bool, str, str]:
        """一键下载清理（去重 + 过期，预览 + 执行）"""
        plan = self.preview_downloads_cleanup(source_dir, older_than_days, recursive)
        if not plan.actions:
            return False, "没有需要清理的文件（无重复、无过期）", ""
        return self.execute_cleanup(plan, description=f"下载清理 {Path(source_dir).name}")

    def _format_size(self, size: int) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"
