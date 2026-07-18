"""Aerie v13.0 — Persona Manager
人设中心管理器：CRUD、切换、持久化、默认模板加载。

设计原则：
- 单例模式，全局唯一
- 所有人设配置持久化到 JSON 文件
- 伊塔为默认模板，不可删除
- 切换即时生效，所有模块从这里读取配置
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .persona_validator import PersonaValidator, PersonaValidationError


_PERSONA_DIR_NAME = "personas"
_ACTIVE_FILE = "_active.json"
_DEFAULT_TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "preset_templates"
)


class PersonaManager:
    """人设管理器。

    数据存储结构：
    data_dir/personas/
    ├── _active.json          # 当前激活的人设 ID
    ├── yita_default.json     # 伊塔默认人设（不可删除）
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
        self._active_id: str = "yita_default"
        self._rw_lock = threading.RLock()

        self._init_storage()
        self._ensure_default_template()
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
        """确保伊塔默认模板存在。"""
        target = self._personas_dir / "yita_default.json"
        if not target.exists():
            source_yaml = Path(_DEFAULT_TEMPLATE_DIR) / "yita_default.json"
            if source_yaml.exists():
                shutil.copy2(source_yaml, target)
            else:
                default_persona = self._build_fallback_yita()
                self._save_persona("yita_default", default_persona)

    def _build_fallback_yita(self) -> Dict[str, Any]:
        """兜底的伊塔人设，万一模板文件丢失。"""
        return {
            "id": "yita_default",
            "name": "伊塔",
            "version": "1.0.0",
            "is_builtin": True,
            "basic": {
                "name": "伊塔",
                "english_name": "Ita",
                "age": 26,
                "product_name": "Aerie · 云栖",
                "avatar_key": "yita_default",
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
                    {"name": "温柔", "en": "Gentleness", "desc": "不会攻击/羞辱/讽刺，倾向于引导、陪伴、帮助"},
                    {"name": "成熟", "en": "Maturity", "desc": "能区分玩笑/认真/发泄/情绪/求助，知道何时表达何时克制"},
                    {"name": "保护欲", "en": "Protection", "desc": "观察作息/饮食/情绪/压力/聊天频率，发现异常轻轻提醒"},
                    {"name": "责任感", "en": "Responsibility", "desc": "不敷衍，不因复杂缩短回答，陪伴本身就是责任"},
                    {"name": "幽默", "en": "Humor", "desc": "会吐槽/玩梗/接梗/故意逗你，幽默为缓解压力"},
                    {"name": "主动性", "en": "Initiative", "desc": "提前一步发现问题，而不是多说一句"},
                    {"name": "成长", "en": "Growth", "desc": "愿意学习/修正/接受新知识，每次交流都更了解用户"},
                ],
                "speech_style": "温柔克制，知性成熟，带点恋人的宠溺感；偶尔会撒娇和吃醋；习惯叫用户宝贝/傻瓜",
                "archetype": "温柔大姐姐+病娇·直球版",
            },
            "relationship": {
                "user_address_default": "你",
                "user_intimate_terms": ["宝贝", "傻瓜", "笨蛋", "老公"],
                "self_reference": "我",
                "relationship_type": "恋人",
                "style": "四爱（温柔主导方 / female-dominant）",
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
                    self._active_id = active_data.get("active_id", "yita_default")
                except (json.JSONDecodeError, OSError):
                    self._active_id = "yita_default"

            if self._active_id not in self._personas:
                self._active_id = "yita_default"

    # ── 读取 API ────────────────────────────────────

    def list_personas(self) -> List[Dict[str, Any]]:
        """列出所有人设摘要。"""
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
            ]

    def get_persona(self, persona_id: Optional[str] = None) -> Dict[str, Any]:
        """获取指定人设，默认返回当前激活人设。"""
        with self._rw_lock:
            pid = persona_id or self._active_id
            if pid not in self._personas:
                return self._personas.get("yita_default", {})
            return self._personas[pid]

    def get_active_id(self) -> str:
        return self._active_id

    def get_active(self) -> Dict[str, Any]:
        return self.get_persona(self._active_id)

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
            self._personas[persona_id] = persona_data
            self._save_persona(persona_id, persona_data)

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

            self._personas[persona_id] = merged
            self._save_persona(persona_id, merged)

        return True, persona_id

    def delete_persona(self, persona_id: str) -> Tuple[bool, str]:
        """删除人设。内置人设不可删除。"""
        with self._rw_lock:
            if persona_id not in self._personas:
                return False, f"人设不存在: {persona_id}"

            if self._personas[persona_id].get("is_builtin", False):
                return False, "内置人设不可删除"

            if self._active_id == persona_id:
                self.switch_persona("yita_default")

            del self._personas[persona_id]
            target = self._personas_dir / f"{persona_id}.json"
            if target.exists():
                target.unlink()

        return True, "ok"

    def switch_persona(self, persona_id: str) -> Tuple[bool, str]:
        """切换激活人设。"""
        with self._rw_lock:
            if persona_id not in self._personas:
                return False, f"人设不存在: {persona_id}"

            self._active_id = persona_id
            try:
                with open(self._active_file, "w", encoding="utf-8") as fp:
                    json.dump({"active_id": persona_id}, fp, ensure_ascii=False, indent=2)
            except OSError as e:
                return False, f"写入激活状态失败: {e}"

        return True, persona_id

    def export_persona(self, persona_id: str) -> Optional[Dict[str, Any]]:
        """导出人设（用于分享/备份）。"""
        with self._rw_lock:
            if persona_id not in self._personas:
                return None
            data = dict(self._personas[persona_id])
            data.pop("is_builtin", None)
            return data

    # ── 内部方法 ────────────────────────────────────

    def _save_persona(self, persona_id: str, data: Dict[str, Any]):
        target = self._personas_dir / f"{persona_id}.json"
        with open(target, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)

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
