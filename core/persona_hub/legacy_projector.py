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

    legacy = {
        "name": basic.get("name") or persona.get("name") or "伊塔",
        "english_name": basic.get("english_name") or "Ita",
        "product_name": basic.get("product_name") or "Aerie · 云栖",
        "profile": {
            "age": basic.get("age"),
            "personality_archetype": personality.get("archetype", ""),
            "big_five": deepcopy(personality.get("big_five") or {}),
        },
        "appearance": deepcopy(appearance),
        "personality_cores": deepcopy(personality.get("cores") or []),
        "speech": {
            "style": personality.get("speech_style", ""),
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
