"""Aerie · 云栖 — 把 config/persona.yaml 同步到人设中心 data/personas/yita_default.json。

背景：设置页 ”她的样子“（/api/persona）写 config/persona.yaml，人设中心（/api/persona/hub）
读 data/personas/*.json，两套数据源未打通。本脚本做反向投影（yaml -> hub），
让 persona.yaml 的修改在重启/调用时覆盖内置 yita_default 人设。

行为：
- 每次运行全量覆盖：persona.yaml 能提供的字段（名字/外貌/性格/称呼/system_prompt 等）
  全部覆盖到 yita_default.json；persona.yaml 缺失的复杂行为/情绪阈值配置（desire、
  emotion.thresholds、behavior、capabilities 等）沿用 yita_default.json 现有骨架，不丢。
- 保持 id=yita_default、is_builtin=true，并确保 _active.json 指向它。

与 legacy_projector.py 的 hub->yaml 投影互为反向字段映射。

用法：
    python scripts/sync_persona_yaml_to_hub.py            # 覆盖写入
    python scripts/sync_persona_yaml_to_hub.py --dry-run  # 只打印将要写入的内容
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PERSONA_YAML = _PROJECT_ROOT / "config" / "persona.yaml"
_HUB_DIR = _PROJECT_ROOT / "data" / "personas"
_HUB_TARGET = _HUB_DIR / "yita_default.json"
_ACTIVE_FILE = _HUB_DIR / "_active.json"

_TARGET_ID = "yita_default"
_VERSION = "1.0.0"


def _load_yaml_persona() -> dict[str, Any]:
    """读取 config/persona.yaml，返回 persona 顶层 dict。"""
    if not _PERSONA_YAML.exists():
        raise FileNotFoundError(f"config/persona.yaml not found: {_PERSONA_YAML}")
    with open(_PERSONA_YAML, "r", encoding="utf-8") as fp:
        data = yaml.safe_load(fp) or {}
    return dict(data.get("persona") or {})


def _load_hub_skeleton() -> dict[str, Any]:
    """读取现有 yita_default.json 作为骨架；不存在则返回空 dict。"""
    if not _HUB_TARGET.exists():
        return {}
    with open(_HUB_TARGET, "r", encoding="utf-8") as fp:
        return json.load(fp)


def _write_json_atomic(target: Path, data: dict[str, Any]) -> None:
    temp = target.with_name(f".{target.name}.tmp")
    with open(temp, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
        fp.flush()
        os.fsync(fp.fileno())
    os.replace(temp, target)


def project_legacy_to_persona(legacy: dict[str, Any], skeleton: dict[str, Any]) -> dict[str, Any]:
    """把 persona.yaml 的 persona 顶层投影为 hub 人设模型。

    与 core/persona_hub/legacy_projector.project_persona_to_legacy 互为反向。
    skeleton 提供 hub 特有、persona.yaml 缺失的复杂配置（desire / emotion.thresholds /
    behavior / capabilities / decision_weights / cognition_visibility 等），不覆盖。
    """
    profile = dict(legacy.get("profile") or {})
    speech = dict(legacy.get("speech") or {})
    address = dict(legacy.get("address") or {})

    basic = dict(skeleton.get("basic") or {})
    basic.update({
        "name": legacy.get("name") or "伊塔",
        "english_name": legacy.get("english_name") or "Ita",
        "product_name": legacy.get("product_name") or "Aerie · 云栖",
        "avatar_key": _TARGET_ID,
    })
    for key in ("age", "gender", "height_cm", "weight_kg", "body_type", "body_fat_pct",
                "cup_size", "measurements", "mbti", "occupation", "occupation_en",
                "former_occupation", "one_liner"):
        if key in profile:
            basic[key] = profile[key]
    if "big_five" in profile:
        basic["big_five"] = deepcopy(profile["big_five"])

    personality = dict(skeleton.get("personality") or {})
    personality["cores"] = deepcopy(legacy.get("personality_cores") or [])
    personality["values"] = deepcopy(legacy.get("values") or [])
    personality["archetype"] = profile.get("personality_archetype", "")
    personality["speech_style"] = speech.get("style", "")
    personality["emoji_frequency"] = speech.get("emoji_frequency", personality.get("emoji_frequency", 0.05))
    personality["max_chars_per_short"] = speech.get("max_chars", personality.get("max_chars_per_short", 30))
    personality["core_tags"] = deepcopy(profile.get("core_tags") or [])

    relationship = dict(skeleton.get("relationship") or {})
    relationship.update({
        "style": profile.get("relationship_style", ""),
        "user_address_default": address.get("user_default", "你"),
        "user_intimate_terms": deepcopy(address.get("user_intimate") or ["宝贝"]),
        "self_reference": address.get("self_reference", "我"),
        "forbidden_user_terms": deepcopy(address.get("forbidden_user_terms") or []),
        "taboo_phrases": deepcopy(speech.get("taboo_phrases") or []),
    })

    # speech_examples：由 persona.yaml 的 speech.example_phrases / example_long 生成
    speech_examples = dict(skeleton.get("speech_examples") or {})
    if speech.get("example_phrases"):
        speech_examples["phrases"] = deepcopy(speech["example_phrases"])
    if speech.get("example_long"):
        speech_examples["long_examples"] = deepcopy(speech["example_long"])

    model = deepcopy(skeleton)
    model["id"] = _TARGET_ID
    model["name"] = legacy.get("name") or "伊塔"
    model["version"] = _VERSION
    model["is_builtin"] = True
    model["description"] = profile.get("personality_archetype", skeleton.get("description", ""))
    model["basic"] = basic
    model["appearance"] = deepcopy(legacy.get("appearance") or skeleton.get("appearance") or {})
    model["personality"] = personality
    model["relationship"] = relationship
    model["recall"] = deepcopy(legacy.get("recall") or skeleton.get("recall") or {})
    model["true_feelings"] = deepcopy(legacy.get("true_feelings") or skeleton.get("true_feelings") or {})
    model["speech_examples"] = speech_examples

    prompt_overrides = dict(skeleton.get("prompt_overrides") or {})
    if legacy.get("system_prompt"):
        prompt_overrides["system_prompt"] = legacy["system_prompt"]
    model["prompt_overrides"] = prompt_overrides

    return model


def main() -> int:
    parser = argparse.ArgumentParser(description="同步 config/persona.yaml 到人设中心 yita_default")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要写入的内容，不实际写入")
    args = parser.parse_args()

    legacy = _load_yaml_persona()
    skeleton = _load_hub_skeleton()
    model = project_legacy_to_persona(legacy, skeleton)

    if args.dry_run:
        print(json.dumps(model, ensure_ascii=False, indent=2))
        print("\n[dry-run] 未写入任何文件。")
        return 0

    _HUB_DIR.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(_HUB_TARGET, model)
    _write_json_atomic(_ACTIVE_FILE, {"active_id": _TARGET_ID})

    print(f"已同步 persona.yaml -> {_HUB_TARGET}")
    print(f"激活人设: {_TARGET_ID} (basic.name = {model.get('basic', {}).get('name')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())