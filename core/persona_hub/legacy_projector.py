from __future__ import annotations

from copy import deepcopy
from typing import Any


def project_persona_to_legacy(persona: dict[str, Any]) -> dict[str, Any]:
    basic = persona.get("basic") or {}
    personality = persona.get("personality") or {}
    relationship = persona.get("relationship") or {}
    emotion = persona.get("emotion") or {}
    appearance = persona.get("appearance") or {}
    prompt_overrides = persona.get("prompt_overrides") or {}
    speech_examples = persona.get("speech_examples") or {}

    # big_five 的规范落点是 basic.big_five（sync_persona_yaml_to_hub 也写这里）。
    # personality.big_five 是历史遗留的重复字段，只作兜底，避免两处漂移时读到旧值。
    big_five = basic.get("big_five") or personality.get("big_five") or {}

    legacy = {
        "name": basic.get("name") or persona.get("name") or "Aerie Companion",
        "english_name": basic.get("english_name") or "Aerie Companion",
        "product_name": basic.get("product_name") or "Aerie",
        "profile": {
            "age": basic.get("age"),
            "gender": basic.get("gender", ""),
            "occupation": basic.get("occupation", ""),
            "one_liner": basic.get("one_liner", ""),
            "personality_archetype": personality.get("archetype", ""),
            "big_five": deepcopy(big_five),
        },
        "appearance": deepcopy(appearance),
        "personality_cores": deepcopy(personality.get("cores") or []),
        "values": deepcopy(personality.get("values") or []),
        "speech": {
            "style": personality.get("speech_style", ""),
            # few-shot 示例：e2e_persona_baseline 直接读这两个字段做基线守门，
            # 缺失会让「直球措辞」用例拿不到样本而误判失败。
            "example_phrases": deepcopy(speech_examples.get("phrases") or []),
            "example_long": deepcopy(speech_examples.get("long_examples") or []),
            "emoji_frequency": personality.get("emoji_frequency", 0.05),
            "max_chars": personality.get("max_chars_per_short", 30),
        },
        "address": {
            "user_default": relationship.get("user_address_default", "你"),
            "user_intimate": deepcopy(
                relationship.get("user_intimate_terms") or ["宝贝"]
            ),
            "self_reference": relationship.get("self_reference", "我"),
            "forbidden_user_terms": deepcopy(
                relationship.get("forbidden_user_terms") or []
            ),
        },
        "emotion_tree": deepcopy(emotion.get("tree") or {}),
        "system_prompt": prompt_overrides.get("system_prompt", ""),
        "recall": deepcopy(persona.get("recall") or {}),
    }
    return {"persona": legacy}
