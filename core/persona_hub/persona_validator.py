"""Aerie v0.1.0-beta.1 — Persona Validator
校验人设配置的完整性和合法性。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple, Optional


class PersonaValidationError(Exception):
    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__(f"Persona validation failed with {len(errors)} errors")


class PersonaValidator:
    """人设配置校验器。

    校验维度：
    - 必选字段完整性
    - 字段类型正确性
    - 数值范围合理性
    - 名称/ID 格式合法性
    """

    REQUIRED_FIELDS = {
        "id": str,
        "name": str,
        "version": str,
        "basic": dict,
        "personality": dict,
        "relationship": dict,
        "emotion": dict,
        "behavior": dict,
    }

    BASIC_REQUIRED = ["name", "english_name", "age", "product_name"]
    PERSONALITY_REQUIRED = ["cores", "speech_style"]
    RELATIONSHIP_REQUIRED = ["user_address_default", "self_reference"]
    EMOTION_REQUIRED = ["baseline", "thresholds"]
    BEHAVIOR_REQUIRED = ["proactivity_level", "default_permission_level"]

    @classmethod
    def validate(cls, persona_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """校验人设配置。

        Returns:
            (是否通过, 错误列表)
        """
        errors: List[str] = []

        errors.extend(cls._check_required_fields(persona_data))
        if errors:
            return False, errors

        errors.extend(cls._check_basic(persona_data.get("basic", {})))
        errors.extend(cls._check_personality(persona_data.get("personality", {})))
        errors.extend(cls._check_relationship(persona_data.get("relationship", {})))
        errors.extend(cls._check_emotion(persona_data.get("emotion", {})))
        errors.extend(cls._check_behavior(persona_data.get("behavior", {})))
        errors.extend(cls._check_id_format(persona_data.get("id", "")))

        return len(errors) == 0, errors

    @classmethod
    def _check_required_fields(cls, data: Dict[str, Any]) -> List[str]:
        errors = []
        for field, expected_type in cls.REQUIRED_FIELDS.items():
            if field not in data:
                errors.append(f"缺少必选字段: {field}")
            elif not isinstance(data[field], expected_type):
                errors.append(
                    f"字段 {field} 类型错误: 期望 {expected_type.__name__}, "
                    f"实际 {type(data[field]).__name__}"
                )
        return errors

    @classmethod
    def _check_id_format(cls, persona_id: str) -> List[str]:
        errors = []
        if not persona_id:
            errors.append("id 不能为空")
        elif not re.match(r"^[a-z0-9_-]{2,64}$", persona_id):
            errors.append(
                f"id 格式不合法: '{persona_id}'，仅允许小写字母、数字、下划线、短横线，长度 2-64"
            )
        return errors

    @classmethod
    def _check_basic(cls, basic: Dict[str, Any]) -> List[str]:
        errors = []
        for field in cls.BASIC_REQUIRED:
            if field not in basic:
                errors.append(f"basic 缺少字段: {field}")
        if "age" in basic and isinstance(basic["age"], (int, float)):
            if basic["age"] < 0 or basic["age"] > 200:
                errors.append(f"age 数值不合法: {basic['age']}")
        return errors

    @classmethod
    def _check_personality(cls, personality: Dict[str, Any]) -> List[str]:
        errors = []
        for field in cls.PERSONALITY_REQUIRED:
            if field not in personality:
                errors.append(f"personality 缺少字段: {field}")
        if "cores" in personality and not isinstance(personality["cores"], list):
            errors.append("personality.cores 应为列表")
        return errors

    @classmethod
    def _check_relationship(cls, rel: Dict[str, Any]) -> List[str]:
        errors = []
        for field in cls.RELATIONSHIP_REQUIRED:
            if field not in rel:
                errors.append(f"relationship 缺少字段: {field}")
        return errors

    @classmethod
    def _check_emotion(cls, emotion: Dict[str, Any]) -> List[str]:
        errors = []
        for field in cls.EMOTION_REQUIRED:
            if field not in emotion:
                errors.append(f"emotion 缺少字段: {field}")

        baseline = emotion.get("baseline", {})
        if isinstance(baseline, dict):
            for key in ["pleasure", "arousal", "dominance"]:
                if key in baseline and isinstance(baseline[key], (int, float)):
                    if baseline[key] < -1 or baseline[key] > 1:
                        errors.append(
                            f"emotion.baseline.{key} 超出范围 [-1, 1]: {baseline[key]}"
                        )

        thresholds = emotion.get("thresholds", {})
        if isinstance(thresholds, dict):
            for name, cfg in thresholds.items():
                if isinstance(cfg, dict):
                    if "threshold" in cfg and isinstance(cfg["threshold"], (int, float)):
                        if cfg["threshold"] <= 0:
                            errors.append(
                                f"emotion.thresholds.{name}.threshold 必须 > 0"
                            )
        return errors

    @classmethod
    def _check_behavior(cls, behavior: Dict[str, Any]) -> List[str]:
        errors = []
        for field in cls.BEHAVIOR_REQUIRED:
            if field not in behavior:
                errors.append(f"behavior 缺少字段: {field}")

        level = behavior.get("proactivity_level", 0.5)
        if isinstance(level, (int, float)) and (level < 0 or level > 1):
            errors.append(f"behavior.proactivity_level 超出范围 [0, 1]: {level}")

        perm = behavior.get("default_permission_level", "VIEW_ONLY")
        if perm not in ("VIEW_ONLY", "STANDARD", "FULL"):
            errors.append(f"behavior.default_permission_level 不合法: {perm}")

        return errors
