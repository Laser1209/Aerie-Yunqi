"""AI services registry — custom providers, role bindings, connectivity checks.

Single responsibility module that separates three concerns previously squeezed
into ``.env``:

* **Credentials** of built-in providers stay in ``.env`` (key / base url / model).
* **Custom OpenAI-compatible providers** live in ``data/ai_services.json``.
* **Role bindings** ("which provider+model serves 对话/子Agent/轻量") live in the
  same JSON file and never overwrite provider credential variables.

The JSON file is the only persisted state of this module. Writes are atomic
(tmp file + ``os.replace``) and guarded by a process-local lock; reads cache by
mtime so external edits / restarts are picked up automatically.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx

from core.paths import data_dir

# ── Built-in provider registry ─────────────────────────────────────────────
# card=True  -> shown as a credential card in settings UI
# virtual=True -> runtime-only composite provider (multi-key pool / shared key)


@dataclass(frozen=True)
class ProviderMeta:
    key: str
    name: str
    env_key: str = ""
    env_url: str = ""
    env_model: str = ""
    env_tools: str = ""
    default_url: str = ""
    default_model: str = ""
    models: tuple[str, ...] = ()
    card: bool = False
    virtual: bool = False


_PROVIDER_REGISTRY: dict[str, ProviderMeta] = {
    m.key: m
    for m in (
        ProviderMeta(
            "deepseek", "DeepSeek",
            env_key="DEEPSEEK_API_KEY", env_url="DEEPSEEK_BASE_URL", env_model="DEEPSEEK_MODEL",
            env_tools="DS_SUPPORTS_TOOLS",
            default_url="https://api.deepseek.com/v1", default_model="deepseek-chat",
            models=("deepseek-chat", "deepseek-reasoner"), card=True,
        ),
        ProviderMeta(
            "dashscope", "通义千问 (DashScope)",
            env_key="DASHSCOPE_API_KEY", env_url="QWEN_BASE_URL", env_model="QWEN_MODEL",
            env_tools="QWEN_SUPPORTS_TOOLS",
            default_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            default_model="qwen-plus",
            models=("qwen-plus", "qwen-max", "qwen-turbo", "qwen-long", "qwen3-max"), card=True,
        ),
        ProviderMeta(
            "doubao", "豆包 (Doubao)",
            env_key="DOUBAO_API_KEY", env_url="DOUBAO_BASE_URL", env_model="DOUBAO_MODEL",
            env_tools="DOUBAO_SUPPORTS_TOOLS",
            default_url="https://ark.cn-beijing.volces.com/api/v3",
            default_model="doubao-seed-2-1-turbo-260628",
            models=("doubao-seed-2-1-turbo-260628", "doubao-1-5-pro-32k", "doubao-1-5-lite-32k"),
            card=True,
        ),
        ProviderMeta(
            "siliconflow", "SiliconFlow",
            env_key="SILICONFLOW_API_KEY", env_url="SILICONFLOW_BASE_URL", env_model="SILICONFLOW_MODEL",
            env_tools="SF_SUPPORTS_TOOLS",
            default_url="https://api.siliconflow.com/v1",
            default_model="google/gemma-4-26B-A4B-it",
            models=(
                "Qwen/Qwen3-235B-A22B", "deepseek-ai/DeepSeek-V3",
                "Qwen/Qwen2.5-72B-Instruct", "google/gemma-4-26B-A4B-it",
            ),
            card=True,
        ),
        ProviderMeta(
            "openai", "OpenAI / GPT",
            env_key="OPENAI_API_KEY", env_url="OPENAI_BASE_URL", env_model="OPENAI_MODEL",
            env_tools="OPENAI_SUPPORTS_TOOLS",
            default_url="https://api.codexgood.com/v1", default_model="gpt-5.5",
            models=("gpt-5.5", "gpt-4o", "gpt-4o-mini"), card=True,
        ),
        ProviderMeta(
            "gemini", "Gemini",
            env_key="GEMINI_API_KEY", env_url="GEMINI_BASE_URL", env_model="GEMINI_MODEL",
            env_tools="GEMINI_SUPPORTS_TOOLS",
            default_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            default_model="gemini-2.0-flash-exp",
            models=("gemini-2.0-flash-exp", "gemini-1.5-pro", "gemini-1.5-flash"), card=True,
        ),
        ProviderMeta(
            "glm", "智谱 GLM",
            env_key="BIGMODEL_API_KEY", env_url="BIGMODEL_BASE_URL", env_model="BIGMODEL_MODEL",
            env_tools="BIGMODEL_SUPPORTS_TOOLS",
            default_url="https://open.bigmodel.cn/api/paas/v4/", default_model="glm-4-plus",
            models=("glm-4-plus", "glm-4-flash", "glm-4-air"), card=True,
        ),
        ProviderMeta(
            "minimax", "MiniMax",
            env_key="MINIMAX_API_KEY", env_url="MINIMAX_BASE_URL", env_model="MINIMAX_MODEL",
            env_tools="MINIMAX_SUPPORTS_TOOLS",
            default_url="https://api.minimaxi.com/v1", default_model="MiniMax-M3",
            models=("MiniMax-M3", "MiniMax-Text-01", "abab6.5s-chat"), card=True,
        ),
        ProviderMeta(
            "grok", "Grok",
            env_key="GROK_API_KEY", env_url="GROK_BASE_URL", env_model="GROK_MODEL",
            env_tools="GROK_SUPPORTS_TOOLS",
            default_url="https://mysubapi.com/v1", default_model="grok-4.5",
            models=("grok-4.5",),
        ),
        ProviderMeta("aerie-ws", "Aerie WS（多 Key 轮询池）", virtual=True),
        ProviderMeta("siliconflow-light", "SiliconFlow 轻量模型", virtual=True),
    )
}

CARD_PROVIDER_KEYS = [m.key for m in _PROVIDER_REGISTRY.values() if m.card]


def card_provider_metas() -> list[dict[str, Any]]:
    """Credential-card metadata for the settings UI (built-in providers only)."""
    return [
        {
            "key": m.key,
            "name": m.name,
            "env_key": m.env_key,
            "env_url": m.env_url,
            "env_model": m.env_model,
            "default_url": m.default_url,
            "default_model": m.default_model,
            "models": list(m.models),
        }
        for m in _PROVIDER_REGISTRY.values()
        if m.card
    ]

# ── Role (functional point) bindings ───────────────────────────────────────

ROLE_MAIN_CHAT = "main_chat"
ROLE_SUBAGENT = "subagent"
ROLE_SUBAGENT_CODE = "subagent_code"
ROLE_LIGHT_ASSIST = "light_assist"

ROLE_META: list[dict[str, str]] = [
    {"key": ROLE_MAIN_CHAT, "name": "对话 AI", "desc": "主对话场景的默认厂商与模型"},
    {"key": ROLE_SUBAGENT, "name": "辅助 AI", "desc": "子 Agent / 轻量任务"},
    {"key": ROLE_SUBAGENT_CODE, "name": "代码辅助", "desc": "代码类子 Agent"},
    {"key": ROLE_LIGHT_ASSIST, "name": "轻量辅助", "desc": "快速辅助（问候纠错 / 生图提示词接力）"},
]

DEFAULT_BINDINGS: dict[str, dict[str, str]] = {
    ROLE_MAIN_CHAT: {"provider": "deepseek", "model": "deepseek-chat"},
    ROLE_SUBAGENT: {"provider": "aerie-ws", "model": "qwen3.7-flash"},
    ROLE_SUBAGENT_CODE: {"provider": "aerie-ws", "model": "kimi-k2.7-code"},
    ROLE_LIGHT_ASSIST: {"provider": "siliconflow-light", "model": ""},
}

# Dedicated services shown read-only in settings (credentials still in .env).
SPECIAL_SERVICE_META = [
    {"key": "asr", "name": "语音转写 ASR", "env_model": "AERIE_WS_ASR_MODEL",
     "default_model": "qwen3-asr-flash", "desc": "Aerie WS 主链路，DashScope 备用"},
    {"key": "image", "name": "生图 Image", "env_model": "IMAGE_GEN_MODEL",
     "default_model": "gpt-image-2", "desc": "gpt-image 兼容图像生成接口"},
    {"key": "tts", "name": "语音合成 TTS", "env_model": "MINIMAX_MODEL",
     "default_model": "speech-01", "desc": "MiniMax TTS"},
]

STORE_VERSION = 1
_MAX_TOOL_CALLS_MIN = 1
_MAX_TOOL_CALLS_MAX = 50
_MASK_MARKERS = ("•", "·", "*", "●")


class AiServicesError(ValueError):
    """Validation error for AI services config; message is user-facing."""


@dataclass
class Endpoint:
    """Resolved call target for a role/provider."""

    name: str
    base_url: str
    model: str
    api_key: str = ""
    keys: tuple[str, ...] = ()
    supports_tools: bool = False
    max_tool_calls: int = 8
    custom: bool = False

    @property
    def available(self) -> bool:
        return bool(self.base_url and self.model and (self.api_key or self.keys))


def _is_masked_secret(value: str) -> bool:
    v = (value or "").strip()
    return bool(v) and any(marker in v for marker in _MASK_MARKERS)


def _provider_label(name: str) -> str:
    meta = _PROVIDER_REGISTRY.get(name)
    return meta.name if meta else name


# ── Store ──────────────────────────────────────────────────────────────────


class AiServicesStore:
    """File-backed store for custom providers / role bindings / check results."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or (data_dir() / "ai_services.json")
        self._log_path = self._path.parent / "provider_checks.jsonl"
        self._lock = threading.RLock()
        self._mtime: float | None = None
        self._data: dict[str, Any] = self._empty_data()
        self._ensure_loaded(force=True)

    @staticmethod
    def _empty_data() -> dict[str, Any]:
        return {
            "version": STORE_VERSION,
            "custom_providers": [],
            "bindings": {k: dict(v) for k, v in DEFAULT_BINDINGS.items()},
            "checks": {},
        }

    @property
    def path(self) -> Path:
        return self._path

    def _ensure_loaded(self, force: bool = False) -> None:
        with self._lock:
            if not self._path.exists():
                self._data = self._empty_data()
                self._mtime = None
                return
            try:
                mtime = self._path.stat().st_mtime
            except OSError:
                return
            if not force and self._mtime is not None and mtime <= self._mtime:
                return
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                # Corrupted file must not crash startup; keep defaults and let
                # the next successful save repair the file atomically.
                self._data = self._empty_data()
                self._mtime = mtime
                return
            data = self._empty_data()
            if isinstance(raw, dict):
                customs = raw.get("custom_providers")
                if isinstance(customs, list):
                    for item in customs:
                        if isinstance(item, dict):
                            data["custom_providers"].append(item)
                bindings = raw.get("bindings")
                if isinstance(bindings, dict):
                    for role, target in bindings.items():
                        if role in DEFAULT_BINDINGS and isinstance(target, dict):
                            data["bindings"][role] = {
                                "provider": str(target.get("provider") or ""),
                                "model": str(target.get("model") or ""),
                            }
                checks = raw.get("checks")
                if isinstance(checks, dict):
                    data["checks"] = checks
            self._data = data
            self._mtime = mtime

    def reload(self) -> None:
        self._ensure_loaded(force=True)

    def _write_locked(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._data, ensure_ascii=False, indent=2)
        tmp = self._path.with_name(f"{self._path.name}.tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self._path)
        self._mtime = self._path.stat().st_mtime

    # ── custom providers ──

    def list_custom_providers(self, *, include_key: bool = False) -> list[dict]:
        self._ensure_loaded()
        with self._lock:
            result = []
            for item in self._data["custom_providers"]:
                record = dict(item)
                if not include_key:
                    record.pop("api_key", None)
                result.append(record)
            return result

    def get_custom_provider(self, provider_id: str) -> dict | None:
        self._ensure_loaded()
        with self._lock:
            for item in self._data["custom_providers"]:
                if item.get("id") == provider_id:
                    return dict(item)
        return None

    def _validate_custom(self, record: dict, *, exclude_id: str | None = None) -> dict:
        name = str(record.get("name") or "").strip()
        base_url = str(record.get("base_url") or "").strip()
        api_key = str(record.get("api_key") or "").strip()
        model = str(record.get("model") or "").strip()
        if not name:
            raise AiServicesError("厂商名称不能为空")
        if not base_url:
            raise AiServicesError("Base URL 不能为空")
        if not (base_url.startswith("http://") or base_url.startswith("https://")):
            raise AiServicesError("Base URL 必须以 http:// 或 https:// 开头")
        if _is_masked_secret(api_key):
            raise AiServicesError("API Key 仍是脱敏占位值，请输入真实密钥")
        try:
            max_tool_calls = int(record.get("max_tool_calls") or 8)
        except (TypeError, ValueError):
            max_tool_calls = 8
        max_tool_calls = max(_MAX_TOOL_CALLS_MIN, min(_MAX_TOOL_CALLS_MAX, max_tool_calls))

        lowered = name.lower()
        builtin_conflict = next(
            (m.name for m in _PROVIDER_REGISTRY.values() if m.name.lower() == lowered),
            None,
        )
        if builtin_conflict:
            raise AiServicesError(f"名称与内置厂商「{builtin_conflict}」冲突，请换一个名称")
        self._ensure_loaded()
        for item in self._data["custom_providers"]:
            if exclude_id and item.get("id") == exclude_id:
                continue
            if str(item.get("name") or "").lower() == lowered:
                raise AiServicesError(f"已存在同名自定义厂商「{name}」")
        return {
            "name": name,
            "base_url": base_url.rstrip("/"),
            "api_key": api_key,
            "model": model,
            "supports_tools": bool(record.get("supports_tools", False)),
            "max_tool_calls": max_tool_calls,
        }

    def prepare_custom_provider(self, record: dict) -> dict:
        """Validate + normalize a custom provider record WITHOUT persisting.

        Assigns a new id on create, preserves stored key on key-less update.
        Call ``commit_custom_provider`` after external checks (e.g. connectivity)
        pass.
        """
        self._ensure_loaded()
        with self._lock:
            provider_id = str(record.get("id") or "").strip()
            existing = None
            if provider_id:
                existing = self.get_custom_provider(provider_id)
                if existing is None:
                    raise AiServicesError("待编辑的自定义厂商不存在")
            clean = self._validate_custom(record, exclude_id=provider_id or None)
            if existing is not None and not clean["api_key"]:
                clean["api_key"] = existing.get("api_key", "")
            if not clean["api_key"]:
                raise AiServicesError("API Key 不能为空")
            clean["id"] = provider_id or f"cp_{uuid.uuid4().hex[:12]}"
            return {
                "id": clean["id"],
                "name": clean["name"],
                "base_url": clean["base_url"],
                "api_key": clean["api_key"],
                "model": clean["model"],
                "supports_tools": clean["supports_tools"],
                "max_tool_calls": clean["max_tool_calls"],
            }

    def commit_custom_provider(self, clean: dict) -> dict:
        """Persist a record previously produced by prepare_custom_provider."""
        self._ensure_loaded()
        with self._lock:
            provider_id = clean["id"]
            records = self._data["custom_providers"]
            for i, item in enumerate(records):
                if item.get("id") == provider_id:
                    records[i] = dict(clean)
                    self._write_locked()
                    return dict(clean)
            records.append(dict(clean))
            self._write_locked()
            return dict(clean)

    def delete_custom_provider(self, provider_id: str) -> bool:
        self._ensure_loaded()
        with self._lock:
            before = len(self._data["custom_providers"])
            self._data["custom_providers"] = [
                item
                for item in self._data["custom_providers"]
                if item.get("id") != provider_id
            ]
            changed = len(self._data["custom_providers"]) != before
            if changed:
                self._write_locked()
            return changed

    # ── bindings ──

    def get_bindings(self) -> dict[str, dict[str, str]]:
        self._ensure_loaded()
        with self._lock:
            return {k: dict(v) for k, v in self._data["bindings"].items()}

    def validate_binding(self, role: str, provider: str, model: str) -> None:
        """Validate a binding target without persisting it."""
        if role not in DEFAULT_BINDINGS:
            raise AiServicesError(f"未知功能点: {role}")
        provider = (provider or "").strip()
        model = (model or "").strip()
        if not provider:
            raise AiServicesError("请选择厂商")
        if not _is_known_provider(provider) and self.get_custom_provider(provider) is None:
            raise AiServicesError("所选厂商不存在，请先添加并保存")
        if role != ROLE_LIGHT_ASSIST and not model:
            raise AiServicesError("模型名不能为空")

    def set_binding(self, role: str, provider: str, model: str) -> dict:
        self.validate_binding(role, provider, model)
        provider = (provider or "").strip()
        model = (model or "").strip()
        self._ensure_loaded()
        with self._lock:
            self._data["bindings"][role] = {"provider": provider, "model": model}
            self._write_locked()
            return {"provider": provider, "model": model}

    # ── check results ──

    def get_checks(self) -> dict[str, Any]:
        self._ensure_loaded()
        with self._lock:
            return dict(self._data.get("checks") or {})

    def record_check(self, target_key: str, result: dict[str, Any]) -> None:
        self._ensure_loaded()
        with self._lock:
            self._data.setdefault("checks", {})[target_key] = result
            self._write_locked()
            entry = {"target": target_key, **result}
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── Resolution ─────────────────────────────────────────────────────────────


def _is_known_provider(provider: str) -> bool:
    return provider in _PROVIDER_REGISTRY


def _resolve_builtin(name: str, model_override: str = "") -> Endpoint | None:
    meta = _PROVIDER_REGISTRY.get(name)
    if meta is None or meta.virtual:
        return None
    api_key = (os.getenv(meta.env_key) or "").strip()
    if not api_key:
        return None
    base_url = (os.getenv(meta.env_url) or meta.default_url).strip().rstrip("/")
    model = (model_override or os.getenv(meta.env_model) or meta.default_model).strip()
    supports_tools = (
        os.getenv(meta.env_tools, "false").strip().lower() == "true"
        if meta.env_tools
        else False
    )
    return Endpoint(
        name=name, base_url=base_url, model=model, api_key=api_key,
        supports_tools=supports_tools,
    )


def _resolve_virtual(name: str, model_override: str = "") -> Endpoint | None:
    if name == "aerie-ws":
        base_url = (os.getenv("AERIE_WS_BASE_URL") or "").strip().rstrip("/")
        raw_keys = (os.getenv("AERIE_WS_KEYS") or os.getenv("AERIE_WS_API_KEY") or "").strip()
        keys = tuple(k.strip() for k in raw_keys.split(",") if k.strip())
        model = (model_override or os.getenv("AERIE_WS_MODEL") or "qwen3.7-flash").strip()
        if not base_url or not keys:
            return None
        return Endpoint(
            name=name, base_url=base_url, model=model,
            api_key=keys[0], keys=keys, supports_tools=True,
        )
    if name == "siliconflow-light":
        api_key = (os.getenv("SILICONFLOW_API_KEY") or "").strip()
        base_url = (
            os.getenv("SILICONFLOW_BASE_URL")
            or "https://api.siliconflow.com/v1"
        ).strip().rstrip("/")
        model = (model_override or os.getenv("SILICONFLOW_LIGHT_MODEL") or "").strip()
        if not api_key or not model:
            return None
        return Endpoint(
            name=name, base_url=base_url, model=model, api_key=api_key,
            supports_tools=False,
        )
    return None


def resolve_provider(
    provider: str,
    model_override: str = "",
    store: AiServicesStore | None = None,
) -> Endpoint | None:
    """Resolve a provider id (built-in / virtual / custom) to a call endpoint."""
    if provider in _PROVIDER_REGISTRY:
        meta = _PROVIDER_REGISTRY[provider]
        if meta.virtual:
            return _resolve_virtual(provider, model_override)
        return _resolve_builtin(provider, model_override)
    store = store or get_store()
    record = store.get_custom_provider(provider)
    if record is None:
        return None
    model = (model_override or record.get("model") or "").strip()
    return Endpoint(
        name=f"custom:{record['id']}",
        base_url=record["base_url"].rstrip("/"),
        model=model,
        api_key=record.get("api_key", ""),
        supports_tools=bool(record.get("supports_tools", False)),
        max_tool_calls=int(record.get("max_tool_calls") or 8),
        custom=True,
    )


def resolve_role(role: str, store: AiServicesStore | None = None) -> Endpoint | None:
    """Resolve a functional role to its bound endpoint.

    Returns None when the role is unbound or the target is not configured.
    """
    if role not in DEFAULT_BINDINGS:
        return None
    store = store or get_store()
    binding = store.get_bindings().get(role) or DEFAULT_BINDINGS[role]
    return resolve_provider(binding["provider"], binding.get("model", ""), store)


def role_preference(role: str) -> tuple[str | None, str | None]:
    """Convenience for LLMCaller.chat call sites: (preferred_provider, model_override).

    Returns (None, None) when the bound provider is not configured; callers
    then keep their legacy fallback behavior.
    """
    endpoint = resolve_role(role)
    if endpoint is None or not endpoint.available:
        return None, None
    return endpoint.name, (endpoint.model or None)


def list_bindable_providers(store: AiServicesStore | None = None) -> list[dict]:
    """Configured providers selectable in the role-binding UI."""
    store = store or get_store()
    result: list[dict] = []
    for key, meta in _PROVIDER_REGISTRY.items():
        endpoint = _resolve_virtual(key) if meta.virtual else _resolve_builtin(key)
        if endpoint is None or not endpoint.available:
            continue
        result.append({
            "key": key,
            "name": meta.name,
            "model": endpoint.model,
            "models": list(meta.models),
            "virtual": meta.virtual,
            "multi_key": bool(endpoint.keys),
        })
    for record in store.list_custom_providers():
        result.append({
            "key": record["id"],
            "name": str(record.get("name") or "自定义 API"),
            "model": record.get("model", ""),
            "models": [record.get("model", "")] if record.get("model") else [],
            "virtual": False,
            "custom": True,
        })
    # Custom records are masked; availability needs the stored key. Drop
    # entries whose stored record lacks a key.
    available = []
    for item in result:
        if not item.get("custom"):
            available.append(item)
            continue
        raw = store.get_custom_provider(item["key"])
        if raw and raw.get("api_key"):
            available.append(item)
    return available


# ── Connectivity check ─────────────────────────────────────────────────────


def _detail_for_status(status_code: int | None, error: str = "") -> str:
    if status_code in (401, 403):
        return "鉴权失败：API Key 无效或已失效"
    if status_code == 404:
        return "接口或模型不存在：请检查 Base URL 与模型名"
    if status_code == 429:
        return "触发限流或额度不足"
    if status_code is not None and status_code >= 500:
        return "服务端错误，稍后再试"
    if error:
        return f"网络不可达：{error[:120]}"
    return ""


async def run_provider_check(
    *,
    base_url: str,
    api_key: str,
    model: str = "",
    mode: str = "models",
) -> dict[str, Any]:
    """Small-traffic connectivity probe.

    mode="models": GET /models (auth + endpoint reachability).
    mode="chat":   POST /chat/completions with max_tokens=1 (also validates model).
    """
    base_url = (base_url or "").strip().rstrip("/")
    started = time.monotonic()
    result: dict[str, Any] = {
        "ok": False,
        "http_status": None,
        "latency_ms": 0,
        "mode": mode,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "detail": "",
    }
    if not base_url or not api_key:
        result["detail"] = "Base URL 或 API Key 为空"
        return result
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    timeout = 10.0 if mode == "chat" else 5.0
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if mode == "chat":
                resp = await client.post(
                    base_url + "/chat/completions",
                    headers=headers,
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                        "stream": False,
                    },
                )
            else:
                resp = await client.get(
                    base_url + "/models",
                    headers={**headers, "Accept": "application/json"},
                )
        result["http_status"] = resp.status_code
        result["ok"] = 200 <= resp.status_code < 400
        if not result["ok"]:
            result["detail"] = _detail_for_status(resp.status_code) or resp.text[:160]
    except httpx.TimeoutException:
        result["detail"] = "请求超时：网络不可达或服务无响应"
    except Exception as exc:  # network errors / invalid URL
        result["detail"] = _detail_for_status(None, str(exc))
    finally:
        result["latency_ms"] = int((time.monotonic() - started) * 1000)
    return result


# ── process-wide singleton ─────────────────────────────────────────────────

_STORE: AiServicesStore | None = None
_STORE_LOCK = threading.Lock()


def get_store() -> AiServicesStore:
    global _STORE
    if _STORE is None:
        with _STORE_LOCK:
            if _STORE is None:
                _STORE = AiServicesStore()
    return _STORE
