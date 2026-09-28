"""Aerie · 云栖 — 工作区管理器(Workspace Manager)。

让任务执行拥有一个"实地操作范围":
- 工作区根目录:用户自选的可读写目录,全部可增可删。
  首次运行时把 settings.yaml 的 agent.workspace_default_roots 播种为初始列表,
  之后完全以 data/workspace_roots.json 为准(用户移除后不再自动加回)。
- 临时工作区:对话中用户明确给出的路径(如 "帮我整理 D:\\xxx"),自动加入。
- 文件树:按需懒加载扫描(不递归全量,前端逐级展开)。
- 图片缩略图:PIL 生成缓存,供前端网格预览。
- 打开文件/文件夹:系统默认程序/资源管理器打开(仅限已注册根目录内)。
- 操作日志:任务动作的时间线(扫描→分类→移动→完成),内存环形缓冲。

安全边界:所有路径操作都必须落在已注册的工作区根目录内,否则拒绝。

历史:此前分 preset(来自配置、**不可移除**)与 custom(用户自建、可移除)两类。
用户明确要求「想加哪个就加哪个,想移除哪个就移除哪个,不要锁死」,故取消该区分。
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
from core.paths import data_dir

logger = logging.getLogger(__name__)

# 图片扩展名 → PIL 可打开的判定(缩略图生成)
_IMAGE_EXTS = frozenset(
    {ext for ext, cat in EXTENSION_MAP.items() if cat.value == "images"}
) | {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".svg"}

# 操作日志环形缓冲上限
_ACTIVITY_MAX = 200

# 工作区根目录状态文件(用户增删的目录重启后保留)
_ROOTS_STATE_FILE = data_dir() / "workspace_roots.json"


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
        default_roots: list[str] | None = None,
        max_activity: int = _ACTIVITY_MAX,
    ) -> None:
        # 首次运行的初始根目录(来自配置)。只在状态文件不存在时使用一次。
        self._default_roots: list[str] = []
        for root in (default_roots or []):
            norm = self._normalize(root)
            if norm and norm not in self._default_roots:
                self._default_roots.append(norm)
        # 当前根目录列表(全部可增删,持久化在 data/workspace_roots.json)
        self._roots: list[str] = []
        self._active_root: str | None = None
        # v0.4.2: 与电脑操控共用的访问策略(pipeline 初始化时注入)
        self._access_policy: Any = None
        self._activity: deque[WorkspaceActivity] = deque(maxlen=max_activity)
        self._load_persisted()

    # -------------------------------------------------------------- 持久化

    def _load_persisted(self) -> None:
        """加载工作区根目录 + 上次激活目录(data/workspace_roots.json)。

        状态文件不存在 = 首次运行:把配置里的默认根播种进去再落盘。**只此一次**
        —— 否则用户移除默认根后重启又会冒出来,「想移除哪个就移除哪个」就成了空话。
        """
        try:
            state_file = _ROOTS_STATE_FILE
            if not state_file.is_file():
                self._roots = self._seed_default_roots()
                self._save_persisted()
                logger.info("[workspace] 首次运行,播种默认工作区 %d 个", len(self._roots))
                return
            data = json.loads(state_file.read_text(encoding="utf-8"))
            for root in data.get("roots", []) or []:
                norm = self._normalize(root)
                if norm and norm not in self._roots:
                    self._roots.append(norm)
            active = data.get("active_root")
            if isinstance(active, str) and active in self.roots():
                self._active_root = active
            logger.info("[workspace] 已加载持久化工作区 %d 个", len(self._roots))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[workspace] 加载持久化工作区失败: %s", exc)

    def _seed_default_roots(self) -> list[str]:
        """默认根中**真实存在的目录**才播种(不存在的目录进白名单毫无意义)。"""
        return [root for root in self._default_roots if Path(root).is_dir()]

    def _save_persisted(self) -> None:
        try:
            state_file = _ROOTS_STATE_FILE
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(
                json.dumps(
                    {"roots": self._roots, "active_root": self._active_root},
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

    def add_root(self, root: str | Path) -> bool:
        """把用户指定路径注册为工作区根目录(已存在则返回 False)。

        与对话自动提取共用:任何来源的目录都会持久化,重启后保留。
        目标必须是真实存在的目录（L4：防止把任意/伪造路径变成授权根）。
        """
        norm = self._normalize(root)
        if norm is None or not Path(norm).is_dir():
            return False
        if norm in self._roots:
            return False
        self._roots.append(norm)
        self._save_persisted()
        logger.info("[workspace] 工作区加入 root=%s", norm)
        return True

    def remove_root(self, root: str | Path) -> bool:
        """移除一个工作区根目录。

        任何根都可移除(用户要求不锁死)；若移除的是当前激活目录，``active_root``
        会自动回退到剩余列表的首个。
        """
        norm = self._normalize(root)
        if norm is None or norm not in self._roots:
            return False
        self._roots.remove(norm)
        if self._active_root == norm:
            self._active_root = None
        self._save_persisted()
        logger.info("[workspace] 工作区移除 root=%s", norm)
        return True

    def roots(self) -> list[str]:
        """全部工作区根目录。"""
        return list(self._roots)

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
          1. 相对路径 → 依次尝试各根目录拼接（含 ..\\ 规范化，越界即跳过）。
          2. 绝对路径 → 必须位于某个根目录内(含根目录本身)。

        所有返回路径统一过"在根内"校验；不存在的目标也按规范化路径判定，
        防止 ..\\..\\ 逃逸（旧实现只查 cand.exists()，不存在时直接退回首根）。
        """
        p = Path(str(path).strip().strip('"').strip("'"))
        resolved_roots = self._resolved_roots()
        if not resolved_roots:
            return None

        if not p.is_absolute():
            for root_p in resolved_roots:
                cand = (root_p / p).resolve()
                if self._is_within(cand, root_p):
                    return cand
            logger.warning("[workspace] 相对路径无法落在任何根内,拒绝: %s", path)
            return None

        target = p.resolve()
        if any(self._is_within(target, root_p) for root_p in resolved_roots):
            return target
        logger.warning("[workspace] 路径越界,拒绝: %s", path)
        return None

    @staticmethod
    def _is_within(candidate: Path, root: Path) -> bool:
        return candidate == root or root in candidate.parents

    def _resolved_roots(self) -> list[Path]:
        result: list[Path] = []
        for root in self.roots():
            try:
                result.append(Path(root).resolve())
            except OSError:
                continue
        return result

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
    """全局单例(与 get_companion 同模式)。首次调用时读取默认根目录。"""
    global _workspace_manager
    if _workspace_manager is None:
        roots: list[str] = []
        try:
            from config.persona_loader import load_settings

            agent_cfg = (load_settings() or {}).get("agent") or {}
            for root in agent_cfg.get("workspace_default_roots") or []:
                if isinstance(root, str) and root.strip():
                    roots.append(root.strip())
        except Exception as exc:  # noqa: BLE001
            logger.warning("[workspace] 读取 agent.workspace_default_roots 失败: %s", exc)
        _workspace_manager = WorkspaceManager(default_roots=roots)
        logger.info("[workspace] 工作区管理器初始化,根目录=%d", len(_workspace_manager.roots()))
    return _workspace_manager


__all__ = ["WorkspaceManager", "WorkspaceActivity", "get_workspace_manager"]
