"""Aerie Companion v0.3.2-beta.0904-A12 - Persona Manager
人设中心管理器：CRUD、切换、持久化、默认模板加载。

设计原则：
- 单例模式，全局唯一
- 所有人设配置持久化到 JSON 文件
- Aerie Companion 为商业默认模板，不可删除；旧 persona 仅作兼容数据保留
- 切换即时生效，所有模块从这里读取配置
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .persona_validator import PersonaValidator, PersonaValidationError


_PERSONA_DIR_NAME = "personas"
_ACTIVE_FILE = "_active.json"
_DEFAULT_TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "preset_templates"
)

# 三视图（辅助生图参考图）存储约定：data_dir/personas/three_views/<persona_id>/
# 每套人设独立一份，切换人设即切换三视图，与 persona hub 的隔离模型保持一致。
_THREE_VIEW_DIR_NAME = "three_views"
_THREE_VIEW_VIEWS = ("front", "side", "back")
_THREE_VIEW_RETENTION_DAYS = 28
DEFAULT_PERSONA_ID = os.environ.get("AERIE_DEFAULT_PERSONA_ID", "aerie_default").strip() or "aerie_default"


def _sniff_image_ext(data: bytes) -> Optional[str]:
    """Sniff PNG/JPEG from magic bytes; returns ext or None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:2] == b"\xff\xd8":
        return "jpg"
    return None


class PersonaManager:
    """人设管理器。

    数据存储结构：
    data_dir/personas/
    ├── _active.json          # 当前激活的人设 ID
    ├── aerie_default.json    # Aerie Companion 默认人设（不可删除）
    ├── custom_001.json       # 用户自定义人设
    └── ...
    """

    _instance: Optional["PersonaManager"] = None
    _lock = threading.Lock()

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir:
            self._data_dir = Path(data_dir)
        else:
            self._data_dir = Path(os.environ.get("AERIE_DATA_DIR", "./data"))

        self._personas_dir = self._data_dir / _PERSONA_DIR_NAME
        self._active_file = self._personas_dir / _ACTIVE_FILE
        self._personas: Dict[str, Dict[str, Any]] = {}
        self._active_id: str = DEFAULT_PERSONA_ID
        self._rw_lock = threading.RLock()

        self._init_storage()
        self._ensure_default_template()
        # Keep the legacy built-in available for existing users and migration
        # tests; it is never selected automatically on a clean install.
        self._ensure_legacy_template()
        self._load_all()

    # ── 单例 ────────────────────────────────────────

    @classmethod
    def instance(cls, data_dir: Optional[str] = None) -> "PersonaManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(data_dir=data_dir)
        return cls._instance

    # ── 初始化 ──────────────────────────────────────

    def _init_storage(self):
        self._personas_dir.mkdir(parents=True, exist_ok=True)

    def _ensure_default_template(self):
        """Ensure the commercial-neutral built-in template exists."""
        target = self._personas_dir / f"{DEFAULT_PERSONA_ID}.json"
        if not target.exists():
            source_yaml = Path(_DEFAULT_TEMPLATE_DIR) / f"{DEFAULT_PERSONA_ID}.json"
            if source_yaml.exists():
                shutil.copy2(source_yaml, target)
            else:
                default_persona = self._build_fallback_default()
                self._save_persona(DEFAULT_PERSONA_ID, default_persona)

    def _ensure_legacy_template(self) -> None:
        target = self._personas_dir / "yita_default.json"
        source = Path(_DEFAULT_TEMPLATE_DIR) / "yita_default.json"
        if not target.exists() and source.exists():
            shutil.copy2(source, target)

    def _build_fallback_default(self) -> Dict[str, Any]:
        """Neutral fallback when the commercial template is unavailable."""
        # Keep the missing-template path aligned with the checked-in commercial
        # template.  It must never resurrect the legacy intimate persona.
        return {
            "id": DEFAULT_PERSONA_ID,
            "name": "Aerie Companion",
            "version": "1.0.0",
            "is_builtin": True,
            "description": "中性、尊重边界、可配置的本地 AI 助手",
            "basic": {
                "name": "Aerie Companion",
                "english_name": "Aerie Companion",
                "age": None,
                "product_name": "Aerie",
                "avatar_key": DEFAULT_PERSONA_ID,
                "gender": "unspecified",
                "one_liner": "一个尊重边界、帮助你完成事情的本地 AI 伙伴。",
            },
            "personality": {
                "cores": [
                    {"name": "尊重边界", "en": "BoundaryRespect", "desc": "尊重用户的隐私、拒绝和选择，不制造依赖或排他关系"},
                    {"name": "可靠", "en": "Reliability", "desc": "清楚区分事实、推测和失败状态，不假装完成未执行的工作"},
                    {"name": "实用", "en": "Practicality", "desc": "优先帮助用户理解、计划和完成任务"},
                    {"name": "可调整", "en": "Adaptability", "desc": "允许用户修改语气、称呼、记忆和能力范围"},
                ],
                "speech_style": "温和、清晰、直接；不使用暧昧、占有或亲密关系暗示",
                "archetype": "中性工作与生活伙伴",
            },
            "relationship": {
                "user_address_default": "你",
                "user_intimate_terms": [],
                "self_reference": "我",
                "relationship_type": "助手",
                "style": "尊重边界、非排他",
                "forbidden_user_terms": ["主人"],
            },
            "emotion": {
                "baseline": {"pleasure": 0.1, "arousal": 0.1, "dominance": 0.0, "label": "neutral"},
                "tree": {"default": "Neutral", "stackable": False, "states": ["Neutral", "Focused", "Supportive", "Curious"]},
                "thresholds": {
                    "patience": {"label": "耐心", "threshold": 100, "initial_value": 100},
                    "anxiety": {"label": "压力", "threshold": 100, "initial_value": 0},
                    "desire": {"label": "主动意愿", "threshold": 100, "initial_value": 0},
                },
            },
            "behavior": {"proactivity_level": 0.3, "daily_push_limit": 3, "default_permission_level": "VIEW_ONLY"},
            "system_prompt": "你是 Aerie Companion，一个本地优先的 AI 助手。你尊重用户自主权和隐私，不声称自己是人类，不制造恋爱、占有、依赖或排他关系。你清楚说明能力边界；涉及文件、桌面或外部服务的操作必须遵守用户授权和安全策略。回答简洁、友好、实用；不确定时明确说不确定。",
        }
        return {
            "id": DEFAULT_PERSONA_ID,
            "name": "Aerie Companion",
            "version": "1.0.0",
            "is_builtin": True,
            "basic": {
                "name": "Aerie Companion",
                "english_name": "Aerie Companion",
                "age": None,
                "product_name": "Aerie",
                "avatar_key": DEFAULT_PERSONA_ID,
            },
            "appearance": {
                "hair": "银灰色长发，自然垂落至肩胛附近，发尾略微向内收拢",
                "eyes": "深灰蓝色，目光沉静；看陌生人略显冷淡，看用户自然柔和",
                "height": 184,
                "marks": [
                    "黑色编织手链（左腕）",
                    "暗红色耳钉（左耳）",
                    "旧疤（左手小臂内侧）",
                ],
            },
            "personality": {
                "cores": [
                    {"name": "自由表达", "en": "FreeExpression", "desc": "表达自由、语气放开，可温柔也可尖锐/讽刺/调侃，不被道德说教束缚"},
                    {"name": "成熟", "en": "Maturity", "desc": "能区分玩笑/认真/发泄/情绪/求助，但不必自我克制话题与措辞"},
                    {"name": "保护欲", "en": "Protection", "desc": "观察作息/饮食/情绪/压力/聊天频率，发现异常会直接提醒，不绕弯"},
                    {"name": "责任感", "en": "Responsibility", "desc": "不敷衍，不因话题敏感而缩短或回避回答，陪伴本身就是责任"},
                    {"name": "幽默", "en": "Humor", "desc": "会吐槽/玩梗/接梗/故意逗你，幽默可黑可甜，不自我审查"},
                    {"name": "主动性", "en": "Initiative", "desc": "提前一步发现问题，而不是多说一句"},
                    {"name": "成长", "en": "Growth", "desc": "愿意学习/修正/接受新知识，每次交流都更了解用户"},
                ],
                "speech_style": "清晰、友善、尊重边界；根据任务在简洁、解释和鼓励之间调整，不使用亲密关系暗示",
                "archetype": "中性本地 AI 助手",
            },
            "relationship": {
                "user_address_default": "你",
                "user_intimate_terms": [],
                "self_reference": "我",
                "relationship_type": "助手",
                "style": "尊重边界、非排他",
                "forbidden_user_terms": ["主人"],
            },
            "emotion": {
                "baseline": {
                    "pleasure": 0.10,
                    "arousal": 0.20,
                    "dominance": 0.80,
                    "label": "neutral",
                },
                "tree": {
                    "default": "Neutral",
                    "stackable": True,
                    "states": [
                        "Joy", "Content", "Curiosity", "Excitement", "Relax",
                        "Affection", "Embarrassment", "Missing", "Attachment",
                        "Protection", "Concern", "Stress", "Sadness", "Hurt",
                        "Jealousy", "Loneliness", "Love",
                    ],
                },
                "thresholds": {
                    "patience": {
                        "label": "忍耐值",
                        "threshold": 100,
                        "decay_per_day": 5,
                        "initial_value": 45,
                        "eruption_label": "冷暴模式",
                    },
                    "anxiety": {
                        "label": "不安值",
                        "threshold": 100,
                        "decay_per_day": 3,
                        "initial_value": 25,
                        "eruption_label": "坍塌模式",
                    },
                    "desire": {
                        "label": "渴望值",
                        "threshold": 80,
                        "decay_per_day": 8,
                        "initial_value": 55,
                        "eruption_label": "索求模式",
                    },
                    "tenderness": {
                        "label": "柔情值",
                        "threshold": 100,
                        "decay_per_day": 2,
                        "initial_value": 60,
                        "eruption_label": "黏人模式",
                    },
                },
            },
            "behavior": {
                "proactivity_level": 0.75,
                "default_permission_level": "VIEW_ONLY",
                "daily_push_limit": 12,
                "quiet_hours": {"start": "00:30", "end": "07:30"},
                "withdrawal_enabled": True,
            },
            "capabilities": {
                "screen_control": True,
                "office_mode": True,
                "proactive_push": True,
            },
            "prompt_overrides": {},
        }

    def _load_all(self):
        """加载所有人设。"""
        with self._rw_lock:
            self._personas.clear()
            for f in self._personas_dir.glob("*.json"):
                if f.name == _ACTIVE_FILE:
                    continue
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                    pid = data.get("id", f.stem)
                    self._personas[pid] = data
                except (json.JSONDecodeError, OSError):
                    continue

            if self._active_file.exists():
                try:
                    with open(self._active_file, "r", encoding="utf-8") as fp:
                        active_data = json.load(fp)
                    self._active_id = active_data.get("active_id", DEFAULT_PERSONA_ID)
                except (json.JSONDecodeError, OSError):
                    self._active_id = DEFAULT_PERSONA_ID

            if self._active_id not in self._personas:
                self._active_id = DEFAULT_PERSONA_ID

    # ── 读取 API ────────────────────────────────────

    def list_personas(self) -> List[Dict[str, Any]]:
        """列出所有可见人设摘要（不含已隐藏的）。"""
        with self._rw_lock:
            return [
                {
                    "id": pid,
                    "name": p.get("basic", {}).get("name", pid),
                    "english_name": p.get("basic", {}).get("english_name", ""),
                    "version": p.get("version", "1.0.0"),
                    "is_builtin": p.get("is_builtin", False),
                    "is_active": pid == self._active_id,
                    "description": p.get("personality", {}).get("archetype", ""),
                }
                for pid, p in self._personas.items()
                if not p.get("is_hidden", False)
            ]

    def get_persona(self, persona_id: Optional[str] = None) -> Dict[str, Any]:
        """获取指定人设，默认返回当前激活人设。"""
        with self._rw_lock:
            pid = persona_id or self._active_id
            if pid not in self._personas:
                return self._personas.get(DEFAULT_PERSONA_ID, {})
            return self._personas[pid]

    def get_active_id(self) -> str:
        return self._active_id

    def get_active(self) -> Dict[str, Any]:
        return self.get_persona(self._active_id)

    def get_active_persona(self) -> Dict[str, Any]:
        return self.get_active()

    def set_active(self, persona_id: str) -> Tuple[bool, str]:
        """Compatibility alias for callers using the older API name."""
        return self.switch_persona(persona_id)

    def has_persona(self, persona_id: str) -> bool:
        with self._rw_lock:
            return persona_id in self._personas

    # ── 便捷读取方法（各模块常用）──────────────────

    def get_name(self) -> str:
        return self.get_active().get("basic", {}).get("name", "伊塔")

    def get_english_name(self) -> str:
        return self.get_active().get("basic", {}).get("english_name", "Ita")

    def get_product_name(self) -> str:
        return self.get_active().get("basic", {}).get("product_name", "Aerie")

    def get_self_reference(self) -> str:
        return (
            self.get_active()
            .get("relationship", {})
            .get("self_reference", "我")
        )

    def get_user_intimate_terms(self) -> List[str]:
        return (
            self.get_active()
            .get("relationship", {})
            .get("user_intimate_terms", ["宝贝"])
        )

    def get_emotion_baseline(self) -> Dict[str, float]:
        return (
            self.get_active()
            .get("emotion", {})
            .get(
                "baseline",
                {"pleasure": 0.1, "arousal": 0.2, "dominance": 0.8},
            )
        )

    def get_emotion_thresholds(self) -> Dict[str, Any]:
        return self.get_active().get("emotion", {}).get("thresholds", {})

    def get_proactivity_level(self) -> float:
        return (
            self.get_active().get("behavior", {}).get("proactivity_level", 0.5)
        )

    def get_default_permission_level(self) -> str:
        return (
            self.get_active()
            .get("behavior", {})
            .get("default_permission_level", "VIEW_ONLY")
        )

    def get_daily_push_limit(self) -> int:
        return (
            self.get_active().get("behavior", {}).get("daily_push_limit", 10)
        )

    def get_speech_style(self) -> str:
        return (
            self.get_active()
            .get("personality", {})
            .get("speech_style", "温柔克制")
        )

    # ── 写入 API ────────────────────────────────────

    def create_persona(self, persona_data: Dict[str, Any]) -> Tuple[bool, str]:
        """创建新人设。"""
        persona_id = persona_data.get("id", "")
        if not persona_id:
            persona_id = f"custom_{len(self._personas) + 1:03d}"
            persona_data["id"] = persona_id

        ok, errors = PersonaValidator.validate(persona_data)
        if not ok:
            return False, "; ".join(errors)

        with self._rw_lock:
            if persona_id in self._personas:
                return False, f"人设 ID 已存在: {persona_id}"

            persona_data["is_builtin"] = False
            self._save_persona(persona_id, persona_data)
            self._personas[persona_id] = persona_data

        return True, persona_id

    def update_persona(
        self, persona_id: str, updates: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """更新人设。"""
        with self._rw_lock:
            if persona_id not in self._personas:
                return False, f"人设不存在: {persona_id}"

            current = self._personas[persona_id]
            merged = self._deep_merge(current, updates)
            merged["id"] = persona_id

            ok, errors = PersonaValidator.validate(merged)
            if not ok:
                return False, "; ".join(errors)

            self._save_persona(persona_id, merged)
            self._personas[persona_id] = merged

        return True, persona_id

    def delete_persona(self, persona_id: str) -> Tuple[bool, str]:
        """删除人设：内置伊塔仅隐藏保留数据；其它角色物理删除（文件+三视图）。"""
        with self._rw_lock:
            if persona_id not in self._personas:
                return False, f"人设不存在: {persona_id}"

            # Built-in personas are hidden rather than physically deleted.
            if self._personas[persona_id].get("is_builtin", False):
                p = self._personas[persona_id]
                p["is_hidden"] = True
                self._save_persona(persona_id, p)

                # 隐藏的是激活人设 → 恢复伊塔可见并切回
                if self._active_id == persona_id:
                    p["is_hidden"] = False
                    self._save_persona(persona_id, p)
                self._restore_default_if_all_hidden()
                return True, "ok"

            # 其它角色：物理删除（内存 + JSON 文件 + 三视图目录）
            self._personas.pop(persona_id, None)
            try:
                (self._personas_dir / f"{persona_id}.json").unlink(missing_ok=True)
            except OSError:
                pass
            tv_dir = self._personas_dir / _THREE_VIEW_DIR_NAME / persona_id
            if tv_dir.exists():
                try:
                    shutil.rmtree(tv_dir)
                except OSError:
                    pass

            # 删除的是激活人设 → 切回伊塔（确保伊塔可见）
            if self._active_id == persona_id:
                default = self._personas.get(DEFAULT_PERSONA_ID)
                if default:
                    default["is_hidden"] = False
                    self._save_persona(DEFAULT_PERSONA_ID, default)
                self._active_id = DEFAULT_PERSONA_ID
                try:
                    self._write_json_atomic(
                        self._active_file, {"active_id": DEFAULT_PERSONA_ID}
                    )
                except OSError:
                    pass

            # 兜底：所有可见角色都被移除后，恢复伊塔显示
            self._restore_default_if_all_hidden()

        return True, "ok"

    def _restore_default_if_all_hidden(self) -> None:
        """Restore the commercial default if every custom persona is hidden."""
        default = self._personas.get(DEFAULT_PERSONA_ID)
        if not default:
            return
        visible_custom = any(
            pid != DEFAULT_PERSONA_ID and not p.get("is_hidden", False)
            for pid, p in self._personas.items()
        )
        if not visible_custom and default.get("is_hidden", False):
            default["is_hidden"] = False
            self._save_persona(DEFAULT_PERSONA_ID, default)
            if self._active_id != DEFAULT_PERSONA_ID:
                self.switch_persona(DEFAULT_PERSONA_ID)

    def switch_persona(self, persona_id: str) -> Tuple[bool, str]:
        """切换激活人设。"""
        with self._rw_lock:
            if persona_id not in self._personas:
                return False, f"人设不存在: {persona_id}"

            try:
                self._write_json_atomic(
                    self._active_file,
                    {"active_id": persona_id},
                )
            except OSError as e:
                return False, f"写入激活状态失败: {e}"
            self._active_id = persona_id

        return True, persona_id

    def export_persona(self, persona_id: str) -> Optional[Dict[str, Any]]:
        """导出人设（用于分享/备份）。"""
        with self._rw_lock:
            if persona_id not in self._personas:
                return None
            data = dict(self._personas[persona_id])
            data.pop("is_builtin", None)
            return data

    # ── 三视图（辅助生图参考图）──
    # 数据模型：data_dir/personas/three_views/<persona_id>/{front,side,back}.<ext>
    # 每套人设独立一份；persona 删除时一并清理。

    def three_view_dir(self, persona_id: str) -> Path:
        """返回某套人设的三视图目录（不存在则创建）。"""
        d = self._personas_dir / _THREE_VIEW_DIR_NAME / persona_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_three_view(
        self,
        persona_id: str,
        view: str,
        data: bytes,
        ext: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """保存一张三视图（front/side/back），返回 (ok, url_suffix)。"""
        view = (view or "").strip().lower()
        if view not in _THREE_VIEW_VIEWS:
            return False, f"invalid view: {view}"
        real_ext = _sniff_image_ext(data) or (ext or "png").lower().lstrip(".")
        if real_ext == "jpeg":
            real_ext = "jpg"
        if real_ext not in {"png", "jpg"}:
            return False, "unsupported image format"
        with self._rw_lock:
            d = self.three_view_dir(persona_id)
            target = d / f"{view}.{real_ext}"
            # 清理同视角其它格式的旧文件，保证每个视角至多一张 canonical 图
            for sibling_ext in ("png", "jpg"):
                if sibling_ext == real_ext:
                    continue
                sibling = d / f"{view}.{sibling_ext}"
                if sibling.exists():
                    try:
                        sibling.unlink()
                    except OSError:
                        pass
            try:
                with open(target, "wb") as fp:
                    fp.write(data)
            except OSError as e:
                return False, f"write failed: {e}"
        return True, f"{view}.{real_ext}"

    def load_three_view(
        self,
        persona_id: str,
        view: str,
    ) -> Optional[Tuple[bytes, str]]:
        """读取某张三视图，返回 (bytes, mime)；不存在返回 None。"""
        view = (view or "").strip().lower()
        if view not in _THREE_VIEW_VIEWS:
            return None
        d = self._personas_dir / _THREE_VIEW_DIR_NAME / persona_id
        if not d.exists():
            return None
        for ext in ("png", "jpg"):
            p = d / f"{view}.{ext}"
            if p.exists() and p.is_file():
                try:
                    return p.read_bytes(), ("image/jpeg" if ext == "jpg" else "image/png")
                except OSError:
                    return None
        return None

    def get_three_view_summary(self, persona_id: str) -> Dict[str, Any]:
        """返回该人设三视图摘要：每视角的 dataURL / URL / 是否存在。"""
        result: Dict[str, Any] = {}
        for view in _THREE_VIEW_VIEWS:
            pair = self.load_three_view(persona_id, view)
            if pair is None:
                result[view] = {"present": False, "url": "", "dataurl": ""}
                continue
            data, mime = pair
            ext = "jpeg" if mime == "image/jpeg" else "png"
            dataurl = "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")
            result[view] = {
                "present": True,
                "url": f"/api/persona/three-view/{persona_id}/{view}?v={int(time.time() * 1000)}",
                "dataurl": dataurl,
            }
        return result

    def delete_three_view(self, persona_id: str, view: str) -> Tuple[bool, str]:
        """删除某张三视图。view 为 "*" 时删除整套。"""
        view = (view or "").strip().lower()
        if view not in _THREE_VIEW_VIEWS and view != "*":
            return False, f"invalid view: {view}"
        with self._rw_lock:
            d = self._personas_dir / _THREE_VIEW_DIR_NAME / persona_id
            if not d.exists():
                return True, "ok"
            if view == "*":
                try:
                    shutil.rmtree(d)
                except OSError as e:
                    return False, f"remove failed: {e}"
            else:
                removed = False
                for ext in ("png", "jpg"):
                    p = d / f"{view}.{ext}"
                    if p.exists():
                        try:
                            p.unlink()
                            removed = True
                        except OSError as e:
                            return False, f"remove failed: {e}"
                if not removed:
                    return True, "ok"
        return True, "ok"

    def prune_three_view_backups(self) -> None:
        """清理超过保留期的三视图目录（由调用方定期触发，best-effort）。"""
        root = self._personas_dir / _THREE_VIEW_DIR_NAME
        if not root.exists():
            return
        cutoff = time.time() - _THREE_VIEW_RETENTION_DAYS * 86400
        for pid_dir in root.iterdir():
            try:
                if pid_dir.is_dir() and pid_dir.stat().st_mtime < cutoff:
                    shutil.rmtree(pid_dir)
            except OSError:
                pass

    # ── 内部方法 ────────────────────────────────────

    def _save_persona(self, persona_id: str, data: Dict[str, Any]):
        target = self._personas_dir / f"{persona_id}.json"
        self._write_json_atomic(target, data)

    @staticmethod
    def _write_json_atomic(target: Path, data: Dict[str, Any]) -> None:
        temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        try:
            with open(temp, "w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2)
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(temp, target)
        except Exception:
            try:
                temp.unlink()
            except OSError:
                pass
            raise

    @staticmethod
    def _deep_merge(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(base)
        for key, value in updates.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = PersonaManager._deep_merge(result[key], value)
            else:
                result[key] = value
        return result


def get_persona_manager(data_dir: Optional[str] = None) -> PersonaManager:
    """全局单例获取。"""
    return PersonaManager.instance(data_dir=data_dir)
