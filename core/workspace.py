"""Aerie · 云栖 — 工作区管理器(Workspace Manager)。

让 DSH 工作委托拥有一个"实地操作范围":
- 预设工作区:来自 work_presets.yaml 各 preset 的 safety.fs_roots(可配置目录)。
- 临时工作区:对话中用户明确给出的路径(如 "帮我整理 D:\\xxx"),自动加入。
- 文件树:按需懒加载扫描(不递归全量,前端逐级展开)。
- 图片缩略图:PIL 生成缓存,供前端网格预览。
- 打开文件/文件夹:系统默认程序/资源管理器打开(仅限已注册根目录内)。
- 操作日志:DSH 委托动作的时间线(扫描→分类→移动→完成),内存环形缓冲。

安全边界:所有路径操作都必须落在已注册的工作区根目录内,否则拒绝。
日志埋点与 dsh_cli 对齐:INFO=操作,WARNING=越界/降级,DEBUG=扫描细节。
"""

from __future__ import annotations

import io
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.file_organizer import EXTENSION_MAP

logger = logging.getLogger(__name__)

# 图片扩展名 → PIL 可打开的判定(缩略图生成)
_IMAGE_EXTS = frozenset(
    {ext for ext, cat in EXTENSION_MAP.items() if cat.value == "images"}
) | {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".svg"}

# 操作日志环形缓冲上限
_ACTIVITY_MAX = 200

# 临时工作区持久化文件(用户自定义目录重启后保留)
_TEMP_ROOTS_FILE = Path("data/workspace_roots.json")


@dataclass(slots=True)
class WorkspaceActivity:
    """一条工作区操作日志(时间线条目)。"""

    ts: float
    kind: str            # scan / plan / execute / open / dedup / error / info
    detail: str
    preset: str = ""
    path: str = ""


class WorkspaceManager:
    """工作区管理器:根目录注册 + 文件树 + 缩略图 + 打开 + 操作日志。"""

    def __init__(
        self,
        *,
        preset_roots: list[str] | None = None,
        max_activity: int = _ACTIVITY_MAX,
    ) -> None:
        # 预设工作区根目录(绝对路径,去重保序)
        self._preset_roots: list[str] = []
        for root in (preset_roots or []):
            self._add_preset_root(root)
        # 临时工作区(用户自定义 + 对话中明确指定)
        self._temp_roots: list[str] = []
        self._active_root: str | None = None
        # v0.4.2: 与电脑操控共用的访问策略(pipeline 初始化时注入)
        self._access_policy: Any = None
        self._activity: deque[WorkspaceActivity] = deque(maxlen=max_activity)
        self._load_persisted()

    # -------------------------------------------------------------- 持久化

    def _load_persisted(self) -> None:
        """加载用户自定义目录 + 上次激活的工作区(data/workspace_roots.json)。"""
        try:
            if _TEMP_ROOTS_FILE.is_file():
                data = json.loads(_TEMP_ROOTS_FILE.read_text(encoding="utf-8"))
                for root in data.get("roots", []) or []:
                    norm = self._normalize(root)
                    if norm and norm not in self._preset_roots and norm not in self._temp_roots:
                        self._temp_roots.append(norm)
                active = data.get("active_root")
                if isinstance(active, str) and active in self.roots():
                    self._active_root = active
                logger.info("[workspace] 已加载持久化工作区 %d 个", len(self._temp_roots))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[workspace] 加载持久化工作区失败: %s", exc)

    def _save_persisted(self) -> None:
        try:
            _TEMP_ROOTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            _TEMP_ROOTS_FILE.write_text(
                json.dumps(
                    {"roots": self._temp_roots, "active_root": self._active_root},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[workspace] 保存持久化工作区失败: %s", exc)

    def _normalize(self, root: str | Path) -> str | None:
        p = Path(str(root)).expanduser()
        if not p.is_absolute():
            p = Path.cwd() / p
        try:
            norm = str(p.resolve())
        except OSError:
            norm = str(p)
        return norm

    # -------------------------------------------------------------- 注册根目录

    def _add_preset_root(self, root: str | Path) -> None:
        norm = self._normalize(root)
        if norm and norm not in self._preset_roots:
            self._preset_roots.append(norm)

    def add_temp_root(self, root: str | Path) -> bool:
        """把用户指定路径注册为自定义工作区(已存在则返回 False)。

        与对话自动提取共用:任何来源的临时目录都会持久化,重启后保留。
        """
        norm = self._normalize(root)
        if norm is None:
            return False
        if norm in self._preset_roots or norm in self._temp_roots:
            return False
        self._temp_roots.append(norm)
        self._save_persisted()
        logger.info("[workspace] 自定义工作区加入 root=%s", norm)
        return True

    def remove_temp_root(self, root: str | Path) -> bool:
        """移除一个自定义工作区目录(预设根不可移除)。"""
        norm = self._normalize(root)
        if norm is None or norm in self._preset_roots:
            return False
        if norm not in self._temp_roots:
            return False
        self._temp_roots.remove(norm)
        self._save_persisted()
        logger.info("[workspace] 自定义工作区移除 root=%s", norm)
        return True

    def roots(self) -> list[str]:
        """全部可用工作区根目录(预设 + 自定义)。"""
        return list(self._preset_roots) + list(self._temp_roots)

    def roots_info(self) -> list[dict]:
        """带来源标记的工作区列表,供前端展示(可删除仅限 custom)。"""
        return [
            {"path": r, "source": "preset"} for r in self._preset_roots
        ] + [
            {"path": r, "source": "custom"} for r in self._temp_roots
        ]

    # -------------------------------------------------------------- 当前激活工作区

    def active_root(self) -> str | None:
        """当前激活的工作区目录(Agent 感知的操作范围)。"""
        roots = self.roots()
        if not roots:
            return None
        # 优先最近一次选中的;若已被移除/不可用则回退首个根
        current = self._active_root
        if current in roots:
            return current
        return roots[0]

    def set_active_root(self, root: str | Path) -> str | None:
        """把某目录设为当前激活工作区(必须是已注册根,否则拒绝并返回当前值)。"""
        norm = self._normalize(root)
        roots = self.roots()
        if norm is None or norm not in roots:
            logger.warning("[workspace] 激活失败(未注册): %s", root)
            return self.active_root()
        self._active_root = norm
        self._save_persisted()
        logger.info("[workspace] 激活工作区=%s", norm)
        return norm

    # -------------------------------------------------------------- 权限联动(v0.4.2)

    def bind_access_policy(self, policy: Any) -> None:
        """注入与电脑操控共用的 AccessPolicy(共享同一份权限状态)。"""
        self._access_policy = policy

    def decide_write(self, detail: str = "") -> tuple[str, str]:
        """裁决一次工作区文件写操作(移动/删除/改名/生成)。

        与电脑操控共用同一权限模式:
          allow    → 放行
          approve  → 需用户审批
          block    → 拦截
        未注入 policy 时默认放行(兼容旧行为)。
        """
        if self._access_policy is None:
            return "allow", "未配置权限策略(默认放行)"
        try:
            from core.computer_control import ControlAction, Decision

            decision, reason = self._access_policy.decide(
                ControlAction.FILE_WRITE,
                {"path": detail},
            )
            return decision.value, reason
        except Exception as exc:  # noqa: BLE001
            logger.warning("[workspace] 写操作裁决异常,默认放行: %s", exc)
            return "allow", "裁决异常,默认放行"

    # -------------------------------------------------------------- 路径校验

    def resolve_within(self, path: str | Path) -> Path | None:
        """把用户给的路径解析为工作区内绝对路径;越界返回 None。

        解析规则:
          1. 相对路径 → 依次尝试各根目录拼接。
          2. 绝对路径 → 必须位于某个根目录内(含根目录本身)。
        """
        p = Path(str(path).strip().strip('"').strip("'"))
        if not p.is_absolute():
            for root in self.roots():
                cand = Path(root) / p
                if cand.exists():
                    return cand
            # 相对路径在根目录内不存在,退回工作区首个根
            if self.roots():
                return Path(self.roots()[0]) / p
            return None

        p = p.resolve()
        for root in self.roots():
            try:
                root_p = Path(root).resolve()
                if p == root_p or root_p in p.parents:
                    return p
            except OSError:
                continue
        logger.warning("[workspace] 路径越界,拒绝: %s", path)
        return None

    # -------------------------------------------------------------- 文件树

    def tree(self, path: str | Path) -> dict:
        """扫描某目录,返回直接子项(不递归)。

        Returns: {"path","name","is_dir","entries":[{name,is_dir,size,size_human,ext}]}
        """
        target = self.resolve_within(path)
        if target is None or not target.is_dir():
            raise ValueError(f"目录不存在或越界: {path}")

        entries: list[dict] = []
        try:
            for child in target.iterdir():
                if child.name.startswith("."):
                    continue
                is_dir = child.is_dir()
                entry: dict[str, Any] = {
                    "name": child.name,
                    "is_dir": is_dir,
                }
                if not is_dir:
                    try:
                        size = child.stat().st_size
                        entry["size"] = size
                        entry["size_human"] = _size_human(size)
                        entry["ext"] = child.suffix.lower()
                        entry["is_image"] = entry["ext"] in _IMAGE_EXTS
                    except OSError:
                        entry["size"] = 0
                        entry["size_human"] = "0 B"
                        entry["ext"] = ""
                        entry["is_image"] = False
                entries.append(entry)
        except OSError as exc:
            logger.warning("[workspace] 扫描失败 %s: %s", target, exc)
            raise ValueError(f"扫描目录失败: {exc}")

        entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
        return {
            "path": str(target),
            "name": target.name or str(target),
            "is_dir": True,
            "entries": entries,
        }

    # -------------------------------------------------------------- 缩略图

    def thumbnail(self, path: str | Path, size: int = 160) -> bytes | None:
        """生成图片缩略图 PNG 字节;非图片/失败返回 None。"""
        target = self.resolve_within(path)
        if target is None or not target.is_file():
            return None
        ext = target.suffix.lower()
        if ext not in _IMAGE_EXTS:
            return None
        try:
            from PIL import Image

            with Image.open(target) as img:
                img.thumbnail((size, size))
                if ext == ".svg":
                    # SVG 不直接支持 PIL 光栅,返回空以提示前端走文件图标
                    return None
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="PNG")
                return buf.getvalue()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[workspace] 缩略图生成失败 %s: %s", target, exc)
            return None

    # -------------------------------------------------------------- 打开

    def open_path(self, path: str | Path) -> tuple[bool, str]:
        """用系统默认程序打开文件 / 资源管理器打开文件夹(仅限工作区内)。"""
        target = self.resolve_within(path)
        if target is None:
            return False, "路径越界或不存在"
        try:
            if target.is_dir():
                os.startfile(str(target))  # type: ignore[attr-defined]
                self.add_activity(kind="open", detail=f"打开文件夹 {target.name}", path=str(target))
            else:
                os.startfile(str(target))  # type: ignore[attr-defined]
                self.add_activity(kind="open", detail=f"打开文件 {target.name}", path=str(target))
            return True, "已打开"
        except Exception as exc:  # noqa: BLE001
            logger.warning("[workspace] 打开失败 %s: %s", target, exc)
            return False, f"打开失败: {exc}"

    # -------------------------------------------------------------- 操作日志

    def add_activity(self, *, kind: str, detail: str, preset: str = "", path: str = "") -> None:
        self._activity.append(WorkspaceActivity(
            ts=time.time(), kind=kind, detail=detail, preset=preset, path=path,
        ))

    def activities(self, limit: int = 50) -> list[dict]:
        """按时间倒序返回操作日志。"""
        rows = list(self._activity)
        rows.reverse()
        return [
            {
                "ts": a.ts,
                "kind": a.kind,
                "detail": a.detail,
                "preset": a.preset,
                "path": a.path,
            }
            for a in rows[:limit]
        ]

    def clear_activities(self) -> None:
        self._activity.clear()


def _size_human(size: int) -> str:
    value = float(size)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


# ───────────────────────────────────────────────────────────── 单例工厂

_workspace_manager: WorkspaceManager | None = None


def get_workspace_manager() -> WorkspaceManager:
    """全局单例(与 get_companion 同模式)。首次调用时从 work_presets.yaml 收集预设根。"""
    global _workspace_manager
    if _workspace_manager is None:
        roots: list[str] = []
        try:
            import yaml

            data = yaml.safe_load(Path("config/work_presets.yaml").read_text(encoding="utf-8"))
            for preset_cfg in (data or {}).get("presets", {}).values():
                safety = preset_cfg.get("safety", {}) if isinstance(preset_cfg, dict) else {}
                for r in safety.get("fs_roots", []) or []:
                    roots.append(str(r))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[workspace] 读取 work_presets.yaml 失败: %s", exc)
        _workspace_manager = WorkspaceManager(preset_roots=roots)
        logger.info("[workspace] 工作区管理器初始化,根目录=%d", len(_workspace_manager.roots()))
    return _workspace_manager


__all__ = ["WorkspaceManager", "WorkspaceActivity", "get_workspace_manager"]
