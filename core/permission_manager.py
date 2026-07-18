"""Aerie v13.9 · 细粒度权限管理器

对标豆包 Turbo 双层授权架构：
  - 目录级白名单：哪些文件夹允许 AI 操作
  - 操作级分离：读取 / 写入 / 界面操作 三分离
  - 高危二次确认：删除 / 覆盖 / 批量操作需用户确认
  - 系统目录拦截：注册表 / 系统目录 / Windows 目录直接禁止

取代旧版三档粗粒度权限（VIEW_ONLY / STANDARD / FULL），
但保留向后兼容：旧 API 仍可调用，内部映射到新体系。
"""

from __future__ import annotations
import os
import re
import json
import logging
from enum import Enum
from pathlib import Path
from datetime import datetime
from typing import Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ── 枚举定义 ──────────────────────────────────────────


class OperationType(str, Enum):
    """操作类型（细粒度）"""
    # 读取类
    READ_FILE = "read_file"
    LIST_DIR = "list_dir"
    SEARCH_FILE = "search_file"
    SCREENSHOT = "screenshot"
    WINDOW_INFO = "window_info"
    # 写入类
    WRITE_FILE = "write_file"
    CREATE_DIR = "create_dir"
    MOVE_FILE = "move_file"
    COPY_FILE = "copy_file"
    RENAME_FILE = "rename_file"
    DELETE_FILE = "delete_file"
    BATCH_OPERATION = "batch_operation"
    # 界面操作类
    MOUSE_MOVE = "mouse_move"
    MOUSE_CLICK = "mouse_click"
    MOUSE_SCROLL = "mouse_scroll"
    KEY_PRESS = "key_press"
    KEY_TYPE = "key_type"
    WINDOW_FOCUS = "window_focus"
    UIA_ACTION = "uia_action"
    # 系统操作类
    SHELL_CMD = "shell_cmd"
    OPEN_APP = "open_app"
    CLOSE_APP = "close_app"


class RiskLevel(str, Enum):
    """风险等级"""
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PermissionCategory(str, Enum):
    """权限大类"""
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    UI_CONTROL = "ui_control"
    SYSTEM = "system"


# ── 操作 → 风险等级 / 权限分类 映射 ──────────────────


ACTION_RISK_MAP: dict[OperationType, RiskLevel] = {
    OperationType.READ_FILE: RiskLevel.SAFE,
    OperationType.LIST_DIR: RiskLevel.SAFE,
    OperationType.SEARCH_FILE: RiskLevel.SAFE,
    OperationType.SCREENSHOT: RiskLevel.SAFE,
    OperationType.WINDOW_INFO: RiskLevel.SAFE,
    OperationType.WRITE_FILE: RiskLevel.MEDIUM,
    OperationType.CREATE_DIR: RiskLevel.LOW,
    OperationType.MOVE_FILE: RiskLevel.MEDIUM,
    OperationType.COPY_FILE: RiskLevel.LOW,
    OperationType.RENAME_FILE: RiskLevel.MEDIUM,
    OperationType.DELETE_FILE: RiskLevel.HIGH,
    OperationType.BATCH_OPERATION: RiskLevel.HIGH,
    OperationType.MOUSE_MOVE: RiskLevel.LOW,
    OperationType.MOUSE_SCROLL: RiskLevel.LOW,
    OperationType.WINDOW_FOCUS: RiskLevel.LOW,
    OperationType.MOUSE_CLICK: RiskLevel.MEDIUM,
    OperationType.KEY_PRESS: RiskLevel.MEDIUM,
    OperationType.KEY_TYPE: RiskLevel.MEDIUM,
    OperationType.UIA_ACTION: RiskLevel.HIGH,
    OperationType.SHELL_CMD: RiskLevel.HIGH,
    OperationType.OPEN_APP: RiskLevel.LOW,
    OperationType.CLOSE_APP: RiskLevel.MEDIUM,
}

ACTION_CATEGORY_MAP: dict[OperationType, PermissionCategory] = {
    OperationType.READ_FILE: PermissionCategory.FILE_READ,
    OperationType.LIST_DIR: PermissionCategory.FILE_READ,
    OperationType.SEARCH_FILE: PermissionCategory.FILE_READ,
    OperationType.WRITE_FILE: PermissionCategory.FILE_WRITE,
    OperationType.CREATE_DIR: PermissionCategory.FILE_WRITE,
    OperationType.MOVE_FILE: PermissionCategory.FILE_WRITE,
    OperationType.COPY_FILE: PermissionCategory.FILE_WRITE,
    OperationType.RENAME_FILE: PermissionCategory.FILE_WRITE,
    OperationType.DELETE_FILE: PermissionCategory.FILE_DELETE,
    OperationType.BATCH_OPERATION: PermissionCategory.FILE_DELETE,
    OperationType.SCREENSHOT: PermissionCategory.UI_CONTROL,
    OperationType.WINDOW_INFO: PermissionCategory.UI_CONTROL,
    OperationType.MOUSE_MOVE: PermissionCategory.UI_CONTROL,
    OperationType.MOUSE_CLICK: PermissionCategory.UI_CONTROL,
    OperationType.MOUSE_SCROLL: PermissionCategory.UI_CONTROL,
    OperationType.KEY_PRESS: PermissionCategory.UI_CONTROL,
    OperationType.KEY_TYPE: PermissionCategory.UI_CONTROL,
    OperationType.WINDOW_FOCUS: PermissionCategory.UI_CONTROL,
    OperationType.UIA_ACTION: PermissionCategory.UI_CONTROL,
    OperationType.SHELL_CMD: PermissionCategory.SYSTEM,
    OperationType.OPEN_APP: PermissionCategory.SYSTEM,
    OperationType.CLOSE_APP: PermissionCategory.SYSTEM,
}


# ── 系统高危路径（永远禁止） ──────────────────────────


BLOCKED_PATTERNS: list[re.Pattern] = [
    re.compile(r'^[A-Z]:\\Windows\\', re.IGNORECASE),
    re.compile(r'^[A-Z]:\\Program Files', re.IGNORECASE),
    re.compile(r'^[A-Z]:\\Program Files \(x86\)', re.IGNORECASE),
    re.compile(r'^[A-Z]:\\ProgramData', re.IGNORECASE),
    re.compile(r'registry', re.IGNORECASE),
    re.compile(r'\\System Volume Information\\', re.IGNORECASE),
    re.compile(r'\\$Recycle\.Bin\\', re.IGNORECASE),
]


def _is_system_path(path: str) -> bool:
    """判断是否为系统高危路径（永远禁止操作）。"""
    if not path:
        return False
    norm = os.path.normpath(os.path.abspath(path))
    for pattern in BLOCKED_PATTERNS:
        if pattern.search(norm):
            return True
    return False


# ── 数据模型 ──────────────────────────────────────────


@dataclass
class PermissionCheckResult:
    """权限检查结果"""
    allowed: bool
    reason: str = ""
    needs_confirmation: bool = False
    confirmation_reason: str = ""
    risk_level: RiskLevel = RiskLevel.SAFE

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "needs_confirmation": self.needs_confirmation,
            "confirmation_reason": self.confirmation_reason,
            "risk_level": self.risk_level.value,
        }


@dataclass
class PermissionConfig:
    """权限配置（持久化结构）"""
    # 目录白名单
    authorized_dirs: list[str] = field(default_factory=list)
    # 大类开关
    file_read_enabled: bool = True
    file_write_enabled: bool = True
    file_delete_enabled: bool = False
    ui_control_enabled: bool = False
    system_enabled: bool = False
    # 高危操作是否需要二次确认
    require_confirmation: bool = True
    # 信任模式（跳过二次确认，有风险）
    trust_mode: bool = False
    # 兼容旧版：权限档位映射
    legacy_level: str = "view_only"

    def to_dict(self) -> dict:
        return {
            "authorized_dirs": self.authorized_dirs,
            "file_read_enabled": self.file_read_enabled,
            "file_write_enabled": self.file_write_enabled,
            "file_delete_enabled": self.file_delete_enabled,
            "ui_control_enabled": self.ui_control_enabled,
            "system_enabled": self.system_enabled,
            "require_confirmation": self.require_confirmation,
            "trust_mode": self.trust_mode,
            "legacy_level": self.legacy_level,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PermissionConfig":
        cfg = cls()
        cfg.authorized_dirs = list(data.get("authorized_dirs", []))
        cfg.file_read_enabled = data.get("file_read_enabled", True)
        cfg.file_write_enabled = data.get("file_write_enabled", True)
        cfg.file_delete_enabled = data.get("file_delete_enabled", False)
        cfg.ui_control_enabled = data.get("ui_control_enabled", False)
        cfg.system_enabled = data.get("system_enabled", False)
        cfg.require_confirmation = data.get("require_confirmation", True)
        cfg.trust_mode = data.get("trust_mode", False)
        cfg.legacy_level = data.get("legacy_level", "view_only")
        return cfg


# ── 审计日志 ──────────────────────────────────────────


@dataclass
class AuditEntry:
    """审计日志条目"""
    timestamp: str
    operation: str
    target_path: str = ""
    allowed: bool = False
    confirmed: bool = False
    reason: str = ""
    risk_level: str = "safe"


# ── 权限管理器 ────────────────────────────────────────


class FineGrainedPermissionManager:
    """细粒度权限管理器

    三大维度：
      1. 目录授权（哪些路径能碰）
      2. 操作分类（读/写/删/界面/系统）
      3. 高危确认（删/覆盖/批量需用户确认）
    """

    def __init__(self, config: Optional[PermissionConfig] = None):
        self._config = config or PermissionConfig()
        self._audit_log: list[AuditEntry] = []
        self._max_audit_entries = 500
        self._ensure_default_dirs()

    # ── 初始化 ───────────────────────────────────────

    def _ensure_default_dirs(self) -> None:
        """确保默认授权目录存在（文档/下载/桌面）。"""
        if not self._config.authorized_dirs:
            home = os.path.expanduser("~")
            defaults = [
                os.path.join(home, "Documents"),
                os.path.join(home, "Downloads"),
                os.path.join(home, "Desktop"),
                os.path.join(home, "AerieOffice"),
            ]
            self._config.authorized_dirs = [
                d for d in defaults if os.path.exists(d) or "AerieOffice" in d
            ]

    # ── 配置读写 ─────────────────────────────────────

    @property
    def config(self) -> PermissionConfig:
        return self._config

    def update_config(self, data: dict) -> PermissionConfig:
        """更新权限配置。"""
        new_cfg = PermissionConfig.from_dict(data)
        self._config = new_cfg
        logger.info("权限配置已更新: file_read=%s file_write=%s file_delete=%s ui=%s system=%s dirs=%d",
                    new_cfg.file_read_enabled, new_cfg.file_write_enabled,
                    new_cfg.file_delete_enabled, new_cfg.ui_control_enabled,
                    new_cfg.system_enabled, len(new_cfg.authorized_dirs))
        return new_cfg

    # ── 目录授权管理 ─────────────────────────────────

    def add_authorized_dir(self, dir_path: str) -> bool:
        """添加授权目录。"""
        abs_path = os.path.abspath(os.path.expanduser(dir_path))
        if _is_system_path(abs_path):
            logger.warning("拒绝添加系统路径到白名单: %s", abs_path)
            return False
        if not os.path.isdir(abs_path):
            logger.warning("目录不存在，跳过: %s", abs_path)
            return False
        if abs_path not in self._config.authorized_dirs:
            self._config.authorized_dirs.append(abs_path)
            logger.info("已添加授权目录: %s", abs_path)
        return True

    def remove_authorized_dir(self, dir_path: str) -> bool:
        """移除授权目录。"""
        abs_path = os.path.abspath(os.path.expanduser(dir_path))
        if abs_path in self._config.authorized_dirs:
            self._config.authorized_dirs.remove(abs_path)
            logger.info("已移除授权目录: %s", abs_path)
            return True
        return False

    def is_path_authorized(self, path: str) -> bool:
        """检查路径是否在授权目录内。"""
        if not path:
            return False
        abs_path = os.path.abspath(os.path.expanduser(path))
        # 系统路径永远禁止
        if _is_system_path(abs_path):
            return False
        # 检查是否在授权目录下
        for auth_dir in self._config.authorized_dirs:
            auth_abs = os.path.abspath(os.path.expanduser(auth_dir))
            try:
                common = os.path.commonpath([abs_path, auth_abs])
                if common == auth_abs or common == abs_path:
                    return True
            except ValueError:
                continue
        return False

    def list_authorized_dirs(self) -> list[str]:
        return list(self._config.authorized_dirs)

    # ── 大类开关管理 ─────────────────────────────────

    def set_category_enabled(self, category: PermissionCategory, enabled: bool) -> None:
        """设置某大类权限的开关。"""
        if category == PermissionCategory.FILE_READ:
            self._config.file_read_enabled = enabled
        elif category == PermissionCategory.FILE_WRITE:
            self._config.file_write_enabled = enabled
        elif category == PermissionCategory.FILE_DELETE:
            self._config.file_delete_enabled = enabled
        elif category == PermissionCategory.UI_CONTROL:
            self._config.ui_control_enabled = enabled
        elif category == PermissionCategory.SYSTEM:
            self._config.system_enabled = enabled
        logger.info("权限大类 %s 已设置为 %s", category.value, "开启" if enabled else "关闭")

    def is_category_enabled(self, category: PermissionCategory) -> bool:
        mapping = {
            PermissionCategory.FILE_READ: self._config.file_read_enabled,
            PermissionCategory.FILE_WRITE: self._config.file_write_enabled,
            PermissionCategory.FILE_DELETE: self._config.file_delete_enabled,
            PermissionCategory.UI_CONTROL: self._config.ui_control_enabled,
            PermissionCategory.SYSTEM: self._config.system_enabled,
        }
        return mapping.get(category, False)

    # ── 核心权限检查 ─────────────────────────────────

    def check(
        self,
        operation: OperationType,
        target_path: str = "",
        batch_count: int = 1,
    ) -> PermissionCheckResult:
        """执行完整的权限检查。

        Args:
            operation: 操作类型
            target_path: 目标路径（文件操作需要）
            batch_count: 批量操作数量（>1 视为批量）

        Returns:
            PermissionCheckResult 包含允许状态、原因、是否需要确认
        """
        risk = ACTION_RISK_MAP.get(operation, RiskLevel.MEDIUM)
        category = ACTION_CATEGORY_MAP.get(operation, PermissionCategory.SYSTEM)

        # 1. 检查大类开关
        if not self.is_category_enabled(category):
            self._audit(operation, target_path, False, False, f"{category.value} 权限未开启", risk)
            return PermissionCheckResult(
                allowed=False,
                reason=f"{category.value} 权限未开启，请在设置中开启",
                risk_level=risk,
            )

        # 2. 文件类操作：检查路径授权
        if category in (PermissionCategory.FILE_READ, PermissionCategory.FILE_WRITE, PermissionCategory.FILE_DELETE):
            if target_path and not self.is_path_authorized(target_path):
                reason = f"路径未授权: {target_path}"
                if _is_system_path(target_path):
                    reason = f"禁止操作系统路径: {target_path}"
                self._audit(operation, target_path, False, False, reason, risk)
                return PermissionCheckResult(
                    allowed=False,
                    reason=reason,
                    risk_level=risk,
                )

        # 3. 批量操作：升级到删除类检查
        if batch_count > 1 and category == PermissionCategory.FILE_WRITE:
            if not self._config.file_delete_enabled:
                self._audit(operation, target_path, False, False, "批量操作需要 file_delete 权限", risk)
                return PermissionCheckResult(
                    allowed=False,
                    reason="批量操作需要开启「文件删除/批量」权限",
                    risk_level=risk,
                )

        # 4. 高危操作：二次确认
        needs_confirm = False
        confirm_reason = ""
        if self._config.require_confirmation and not self._config.trust_mode:
            if risk == RiskLevel.HIGH or risk == RiskLevel.CRITICAL:
                needs_confirm = True
                confirm_reason = f"高风险操作（{risk.value}）需要用户确认"
            elif batch_count > 1 and risk >= RiskLevel.MEDIUM:
                needs_confirm = True
                confirm_reason = f"批量操作（{batch_count} 项）需要用户确认"
            elif operation == OperationType.DELETE_FILE:
                needs_confirm = True
                confirm_reason = "删除文件需要用户确认"
            elif operation == OperationType.SHELL_CMD:
                needs_confirm = True
                confirm_reason = "执行 shell 命令需要用户确认"

        self._audit(operation, target_path, True, needs_confirm, "", risk)
        return PermissionCheckResult(
            allowed=True,
            needs_confirmation=needs_confirm,
            confirmation_reason=confirm_reason,
            risk_level=risk,
        )

    # ── 审计日志 ─────────────────────────────────────

    def _audit(
        self,
        operation: OperationType,
        target_path: str,
        allowed: bool,
        confirmed: bool,
        reason: str,
        risk: RiskLevel,
    ) -> None:
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            operation=operation.value,
            target_path=target_path,
            allowed=allowed,
            confirmed=confirmed,
            reason=reason,
            risk_level=risk.value,
        )
        self._audit_log.append(entry)
        if len(self._audit_log) > self._max_audit_entries:
            self._audit_log = self._audit_log[-self._max_audit_entries:]

    def get_audit_log(self, limit: int = 50) -> list[dict]:
        """获取审计日志（最新的在前）。"""
        entries = list(reversed(self._audit_log[-limit:]))
        return [
            {
                "timestamp": e.timestamp,
                "operation": e.operation,
                "target_path": e.target_path,
                "allowed": e.allowed,
                "confirmed": e.confirmed,
                "reason": e.reason,
                "risk_level": e.risk_level,
            }
            for e in entries
        ]

    # ── 一键撤销 ─────────────────────────────────────

    def revoke_all(self) -> None:
        """一键撤销所有非必要权限。"""
        self._config.file_write_enabled = False
        self._config.file_delete_enabled = False
        self._config.ui_control_enabled = False
        self._config.system_enabled = False
        self._config.trust_mode = False
        self._config.authorized_dirs = []
        self._config.legacy_level = "view_only"
        logger.warning("已一键撤销所有非必要权限")

    # ── 旧版兼容 ─────────────────────────────────────

    def set_legacy_level(self, level: str) -> None:
        """兼容旧版三档权限：映射到新体系。"""
        level = level.lower()
        self._config.legacy_level = level
        if level == "view_only":
            self._config.file_read_enabled = True
            self._config.file_write_enabled = False
            self._config.file_delete_enabled = False
            self._config.ui_control_enabled = False
            self._config.system_enabled = False
        elif level == "standard":
            self._config.file_read_enabled = True
            self._config.file_write_enabled = True
            self._config.file_delete_enabled = False
            self._config.ui_control_enabled = True
            self._config.system_enabled = True
        elif level == "full":
            self._config.file_read_enabled = True
            self._config.file_write_enabled = True
            self._config.file_delete_enabled = True
            self._config.ui_control_enabled = True
            self._config.system_enabled = True
            self._config.trust_mode = True
        logger.info("兼容旧版权限档位: %s", level)

    def get_legacy_level(self) -> str:
        """获取旧版兼容的权限档位。"""
        return self._config.legacy_level
