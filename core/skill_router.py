"""Aerie · 云栖 v9.0 — Skill Router (Block-4C R3.1).

Maps ``provider_hint`` (declared in SKILL.md frontmatter) to the
top-level ``ai_options`` provider id (declared in
``config/persona_behavior.yaml → ai_options``).

The hint vocabulary mirrors the available local model routes. The
Brain layer reads the same table to pick a real model when a tool_call
lands. Unknown hints fall back to ``main_llm`` so a misconfigured skill
never breaks the chat pipeline.
"""

from __future__ import annotations

# Hint → ai_options id (single source of truth for routing).
PROVIDER_HINTS: dict[str, str] = {
    "tts-openvino":  "voice_tts",     # OpenVINO Qwen3-TTS
    "image-sdxl":    "image_sdxl",    # SDXL image generation
    "vision-llava":  "vision_llava",  # LLaVA multimodal QA
    "asr-whisper":   "main_llm",      # falls back to text LLM if whisper missing
    "ocr-pp":        "vision_llava",  # PP-OCRv5 → vision_llava fallback
    "shell-safe":    "shell_safe",    # sandboxed shell exec
    "text":          "main_llm",      # generic text LLM
    "json":          "main_llm",
    "markdown":      "main_llm",
    # Block-5C 新增 hint → provider 路由
    "qwen-vl":       "qwen_vl",       # 通义千问 VL 多模态
    "bge-embedding": "bge_embedding", # 中文嵌入
    "clip-retrieval": "clip_retrieval", # 图文检索
    "code-llama":    "codellama",     # 代码补全
    "doubao-multimodal": "doubao_seed", # 豆包多模态
    "baichuan":      "baichuan",      # 百川对话
}


def resolve_provider(hint: str) -> str:
    """Return the ai_options provider id for a given SKILL.md hint."""
    if not hint:
        return "main_llm"
    return PROVIDER_HINTS.get(hint.lower(), "main_llm")


class SkillRouter:
    """Resolves which ai_options provider a skill should bind to.

    Reads ``ai_options`` from the centralized behavior config so the
    top-level provider list (label / model) stays in one place
    (``config/persona_behavior.yaml``). The router caches the lookup
    table for the lifetime of the process.
    """

    def __init__(self, behavior_cfg: dict | None = None) -> None:
        self.behavior_cfg = behavior_cfg or {}
        self._ai_options: list[dict] = []
        try:
            self._ai_options = list(self.behavior_cfg.get("ai_options") or [])
        except Exception:
            self._ai_options = []
        # Index by id for O(1) lookup.
        self._by_id: dict[str, dict] = {opt.get("id", ""): opt for opt in self._ai_options if isinstance(opt, dict)}

    def provider_for(self, hint: str) -> dict:
        """Return the ai_options dict matching the given hint.

        Falls back to ``main_llm`` provider, then to the first option
        if ``main_llm`` is missing, then to an empty stub.
        """
        provider_id = resolve_provider(hint)
        if provider_id in self._by_id:
            return self._by_id[provider_id]
        if "main_llm" in self._by_id:
            return self._by_id["main_llm"]
        if self._ai_options:
            return self._ai_options[0]
        return {"id": provider_id, "label": provider_id, "model": ""}

    def all_ai_options(self) -> list[dict]:
        """Return the full ai_options list (for brain multi-provider fan-out)."""
        return list(self._ai_options)
