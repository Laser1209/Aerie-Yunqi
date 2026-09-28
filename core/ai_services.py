"""AI services registry — providers, role bindings, connectivity checks.

厂商配置（内置 / 自定义 / 本地 CLI）与功能点绑定统一落在 ``data/aerie.db``：

* ``ai_providers``       厂商表
* ``ai_role_bindings``   功能点 → 厂商 + 模型
* ``ai_provider_checks`` 最近一次连通性探测结果

内置厂商的凭据在写库的同时回写 ``.env`` 与 ``os.environ``：``llm_caller``、
``voice``、``qq_media`` 等旁路仍直接读环境变量，回写是它们继续可用的前提。
因此 ``.env`` 是**派生镜像**而非真源；首次启动用 ``.env`` 现值 seed 一次。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx

from core.database import Database
from core.env_file import read_env_file, write_env_file

logger = logging.getLogger(__name__)

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


# ── Provider kinds ─────────────────────────────────────────────────────────

KIND_BUILTIN = "builtin"
KIND_CUSTOM = "custom"
KIND_LOCAL_CLI = "local_cli"
PROVIDER_KINDS = (KIND_BUILTIN, KIND_CUSTOM, KIND_LOCAL_CLI)

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
     "default_model": "gpt-image-2.5-flare", "desc": "gpt-image 兼容图像生成接口"},
    {"key": "tts", "name": "语音合成 TTS", "env_model": "MINIMAX_MODEL",
     "default_model": "speech-01", "desc": "MiniMax TTS"},
    {"key": "decision", "name": "结构化解策", "env_model": "AERIE_TYPESAFE_MODEL",
     "default_model": "bocha-jev-v1",
     "desc": "TypeSafe noul 二元判定（记忆写入校验）"},
]

STORE_VERSION = 1
_MAX_TOOL_CALLS_MIN = 1
_MAX_TOOL_CALLS_MAX = 50
_DEFAULT_MAX_TOOL_CALLS = 8
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


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── Store（SQLite）──────────────────────────────────────────────────────────


class AiServicesStore:
    """SQLite-backed store for providers / role bindings / check results."""

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db = db or Database()
        # 审计流水跟着库走：生产落 data/provider_checks.jsonl，测试落临时目录。
        self._log_path = Path(self._db.db_path).parent / "provider_checks.jsonl"
        self._seed_builtin_providers()

    # ── seed ──

    def _seed_builtin_providers(self) -> None:
        """首次启动把内置厂商写入表。

        凭据取 ``.env`` 现值（缺失则留空，等用户在设置页填）。只补不覆盖：
        已存在的行一律保留，避免把用户在设置页的修改拉回默认。
        """
        try:
            existing = {row["id"] for row in self._db.query("SELECT id FROM ai_providers")}
        except Exception:
            logger.warning("ai_providers seed skipped: table unavailable", exc_info=True)
            return
        now = _now_iso()
        for order, meta in enumerate(_PROVIDER_REGISTRY.values()):
            if meta.virtual or meta.key in existing:
                continue
            try:
                self._db.insert("ai_providers", {
                    "id": meta.key,
                    "kind": KIND_BUILTIN,
                    "name": meta.name,
                    "base_url": (os.getenv(meta.env_url) or meta.default_url).strip().rstrip("/"),
                    "api_key": (os.getenv(meta.env_key) or "").strip(),
                    "model": (os.getenv(meta.env_model) or meta.default_model).strip(),
                    "models": json.dumps(list(meta.models), ensure_ascii=False),
                    "supports_tools": 1 if _env_true(meta.env_tools) else 0,
                    "max_tool_calls": _DEFAULT_MAX_TOOL_CALLS,
                    "enabled": 1,
                    "sort_order": order,
                    "created_at": now,
                    "updated_at": now,
                })
            except Exception:
                logger.warning("builtin provider seed failed: %s", meta.key, exc_info=True)

    # ── 内部辅助 ──

    @staticmethod
    def _builtin_meta(provider_id: str) -> ProviderMeta | None:
        meta = _PROVIDER_REGISTRY.get(provider_id)
        return meta if meta and not meta.virtual else None

    @staticmethod
    def _is_registry_provider(provider_id: str) -> bool:
        """是否为注册表里的提供方（含 virtual 组合型）。"""
        return provider_id in _PROVIDER_REGISTRY

    def _sync_env(
        self,
        provider_id: str,
        *,
        api_key: str,
        base_url: str,
        model: str,
        enabled: bool,
    ) -> None:
        """把内置厂商凭据回写 ``.env`` 与 ``os.environ``；禁用时写空值。"""
        meta = self._builtin_meta(provider_id)
        if meta is None:
            return
        changes: dict[str, str] = {}
        if meta.env_key:
            changes[meta.env_key] = api_key if enabled else ""
        if meta.env_url and base_url:
            changes[meta.env_url] = base_url
        if meta.env_model and model:
            changes[meta.env_model] = model
        if not changes:
            return
        try:
            env = read_env_file()
            env.update(changes)
            write_env_file(env)
        except OSError:
            logger.warning("provider env write-through failed: %s", provider_id, exc_info=True)
        os.environ.update(changes)

    def _next_sort_order(self) -> int:
        row = self._db.query_one("SELECT COALESCE(MAX(sort_order), -1) AS m FROM ai_providers")
        return int((row or {}).get("m", -1)) + 1

    @staticmethod
    def _row_to_provider(row: dict) -> dict:
        try:
            parsed = json.loads(row.get("models") or "[]")
            models = [str(x) for x in parsed] if isinstance(parsed, list) else []
        except (TypeError, ValueError):
            models = []
        return {
            "id": str(row.get("id") or ""),
            "kind": str(row.get("kind") or KIND_CUSTOM),
            "name": str(row.get("name") or ""),
            "base_url": str(row.get("base_url") or ""),
            "api_key": str(row.get("api_key") or ""),
            "model": str(row.get("model") or ""),
            "models": models,
            "supports_tools": bool(row.get("supports_tools")),
            "max_tool_calls": int(row.get("max_tool_calls") or _DEFAULT_MAX_TOOL_CALLS),
            "enabled": bool(row.get("enabled")),
            "sort_order": int(row.get("sort_order") or 0),
            "created_at": str(row.get("created_at") or ""),
            "updated_at": str(row.get("updated_at") or ""),
        }

    # ── 读取 ──

    def list_providers(
        self,
        *,
        include_key: bool = False,
        enabled_only: bool = False,
    ) -> list[dict]:
        sql = "SELECT * FROM ai_providers"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY sort_order, name"
        result = []
        for row in self._db.query(sql):
            record = self._row_to_provider(dict(row))
            if not include_key:
                record.pop("api_key", None)
            result.append(record)
        return result

    def get_provider(self, provider_id: str) -> dict | None:
        row = self._db.query_one("SELECT * FROM ai_providers WHERE id = ?", (provider_id,))
        return self._row_to_provider(dict(row)) if row else None

    # ── 写入 ──

    def _validate_provider(self, record: dict, *, exclude_id: str | None = None) -> dict:
        kind = str(record.get("kind") or KIND_CUSTOM).strip()
        if kind not in PROVIDER_KINDS:
            raise AiServicesError(f"未知的厂商类型: {kind}")
        name = str(record.get("name") or "").strip()
        base_url = str(record.get("base_url") or "").strip()
        api_key = str(record.get("api_key") or "").strip()
        model = str(record.get("model") or "").strip()
        if not name:
            raise AiServicesError("厂商名称不能为空")
        if kind != KIND_LOCAL_CLI:
            if not base_url:
                raise AiServicesError("Base URL 不能为空")
            if not (base_url.startswith("http://") or base_url.startswith("https://")):
                raise AiServicesError("Base URL 必须以 http:// 或 https:// 开头")
        if _is_masked_secret(api_key):
            raise AiServicesError("API Key 仍是脱敏占位值，请输入真实密钥")
        try:
            max_tool_calls = int(record.get("max_tool_calls") or _DEFAULT_MAX_TOOL_CALLS)
        except (TypeError, ValueError):
            max_tool_calls = _DEFAULT_MAX_TOOL_CALLS
        max_tool_calls = max(_MAX_TOOL_CALLS_MIN, min(_MAX_TOOL_CALLS_MAX, max_tool_calls))

        lowered = name.lower()
        for row in self._db.query("SELECT id, name FROM ai_providers"):
            if exclude_id and row["id"] == exclude_id:
                continue
            if str(row["name"]).lower() == lowered:
                raise AiServicesError(f"已存在同名厂商「{name}」")

        models = record.get("models")
        if not isinstance(models, list) or not models:
            models = [model] if model else []
        return {
            "kind": kind,
            "name": name,
            "base_url": base_url.rstrip("/") if base_url else "",
            "api_key": api_key,
            "model": model,
            "models": [str(m) for m in models if str(m).strip()],
            "supports_tools": bool(record.get("supports_tools", False)),
            "max_tool_calls": max_tool_calls,
            "enabled": bool(record.get("enabled", True)),
        }

    def prepare_provider(self, record: dict) -> dict:
        """校验 + 归一化一条厂商记录，**不落库**。

        新建时分配 id；编辑时不传 ``api_key`` 则沿用库里旧值。返回值交给
        ``commit_provider`` 落库 + 回写 ``.env``。
        """
        provider_id = str(record.get("id") or "").strip()
        existing = None
        if provider_id:
            existing = self.get_provider(provider_id)
            if existing is None:
                raise AiServicesError("待编辑的厂商不存在")
        clean = self._validate_provider(record, exclude_id=provider_id or None)
        if existing is not None and not clean["api_key"]:
            clean["api_key"] = existing.get("api_key", "")
        if clean["kind"] != KIND_LOCAL_CLI and not clean["api_key"]:
            raise AiServicesError("API Key 不能为空")
        if existing is None:
            provider_id = provider_id or f"cp_{uuid.uuid4().hex[:12]}"
            clean["sort_order"] = self._next_sort_order()
        else:
            clean["sort_order"] = int(existing.get("sort_order") or 0)
        clean["id"] = provider_id
        return clean

    def commit_provider(self, clean: dict) -> dict:
        """落库一条 ``prepare_provider`` 产出的记录，并回写内置厂商的 .env。"""
        now = _now_iso()
        existing = self.get_provider(clean["id"])
        payload = {
            "id": clean["id"],
            "kind": clean["kind"],
            "name": clean["name"],
            "base_url": clean["base_url"],
            "api_key": clean["api_key"],
            "model": clean["model"],
            "models": json.dumps(list(clean.get("models") or []), ensure_ascii=False),
            "supports_tools": 1 if clean.get("supports_tools") else 0,
            "max_tool_calls": int(clean.get("max_tool_calls") or _DEFAULT_MAX_TOOL_CALLS),
            "enabled": 1 if clean.get("enabled", True) else 0,
            "sort_order": int(clean.get("sort_order") or 0),
            "updated_at": now,
        }
        if existing is None:
            payload["created_at"] = now
            self._db.insert("ai_providers", payload)
        else:
            self._db.update("ai_providers", payload, "id = ?", (clean["id"],))
        if clean["kind"] == KIND_BUILTIN:
            self._sync_env(
                clean["id"],
                api_key=clean["api_key"],
                base_url=clean["base_url"],
                model=clean["model"],
                enabled=bool(clean.get("enabled", True)),
            )
        return self.get_provider(clean["id"]) or {}

    def delete_provider(self, provider_id: str) -> bool:
        """硬删除：删表行；内置厂商同时清掉 ``.env`` 里的凭据键。"""
        existing = self.get_provider(provider_id)
        if existing is None:
            return False
        self._db.delete("ai_providers", "id = ?", (provider_id,))
        if existing["kind"] == KIND_BUILTIN:
            self._sync_env(
                provider_id, api_key="", base_url="", model="", enabled=False,
            )
        return True

    def set_enabled(self, provider_id: str, enabled: bool) -> dict | None:
        """启用 / 停用。停用只清 ``.env`` 凭据、保留库里的 Key，随时可恢复。"""
        existing = self.get_provider(provider_id)
        if existing is None:
            return None
        self._db.update(
            "ai_providers",
            {"enabled": 1 if enabled else 0, "updated_at": _now_iso()},
            "id = ?",
            (provider_id,),
        )
        if existing["kind"] == KIND_BUILTIN:
            self._sync_env(
                provider_id,
                api_key=existing["api_key"],
                base_url=existing["base_url"],
                model=existing["model"],
                enabled=enabled,
            )
        return self.get_provider(provider_id)

    # ── bindings ──

    def get_bindings(self) -> dict[str, dict[str, str]]:
        stored = {
            row["role"]: {"provider": row["provider"], "model": row["model"] or ""}
            for row in self._db.query("SELECT role, provider, model FROM ai_role_bindings")
        }
        return {
            role: dict(stored.get(role) or default)
            for role, default in DEFAULT_BINDINGS.items()
        }

    def validate_binding(self, role: str, provider: str, model: str) -> None:
        """Validate a binding target without persisting it."""
        if role not in DEFAULT_BINDINGS:
            raise AiServicesError(f"未知功能点: {role}")
        provider = (provider or "").strip()
        model = (model or "").strip()
        if not provider:
            raise AiServicesError("请选择厂商")
        if not self._is_registry_provider(provider) and self.get_provider(provider) is None:
            raise AiServicesError("所选厂商不存在，请先添加并保存")
        if role != ROLE_LIGHT_ASSIST and not model:
            raise AiServicesError("模型名不能为空")

    def set_binding(self, role: str, provider: str, model: str) -> dict:
        self.validate_binding(role, provider, model)
        provider = (provider or "").strip()
        model = (model or "").strip()
        self._db.execute(
            "INSERT INTO ai_role_bindings (role, provider, model, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(role) DO UPDATE SET provider = excluded.provider, "
            "model = excluded.model, updated_at = excluded.updated_at",
            (role, provider, model, _now_iso()),
        )
        return {"provider": provider, "model": model}

    # ── check results ──

    def get_checks(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for row in self._db.query("SELECT * FROM ai_provider_checks"):
            result[str(row["target"])] = {
                "ok": bool(row["ok"]),
                "http_status": row["http_status"],
                "latency_ms": int(row["latency_ms"] or 0),
                "mode": str(row["mode"] or ""),
                "detail": str(row["detail"] or ""),
                "checked_at": str(row["checked_at"] or ""),
            }
        return result

    def record_check(self, target_key: str, result: dict[str, Any]) -> None:
        self._db.execute(
            "INSERT INTO ai_provider_checks "
            "(target, ok, http_status, latency_ms, mode, detail, checked_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(target) DO UPDATE SET ok = excluded.ok, "
            "http_status = excluded.http_status, latency_ms = excluded.latency_ms, "
            "mode = excluded.mode, detail = excluded.detail, checked_at = excluded.checked_at",
            (
                target_key,
                1 if result.get("ok") else 0,
                result.get("http_status"),
                int(result.get("latency_ms") or 0),
                str(result.get("mode") or ""),
                str(result.get("detail") or ""),
                str(result.get("checked_at") or ""),
            ),
        )
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"target": target_key, **result}, ensure_ascii=False) + "\n")
        except OSError:
            logger.debug("provider check audit append failed", exc_info=True)


# ── Resolution ─────────────────────────────────────────────────────────────


def _env_true(name: str) -> bool:
    return bool(name) and os.getenv(name, "").strip().lower() == "true"


def _resolve_builtin(name: str, model_override: str = "") -> Endpoint | None:
    meta = _PROVIDER_REGISTRY.get(name)
    if meta is None or meta.virtual:
        return None
    api_key = (os.getenv(meta.env_key) or "").strip()
    if not api_key:
        return None
    base_url = (os.getenv(meta.env_url) or meta.default_url).strip().rstrip("/")
    model = (model_override or os.getenv(meta.env_model) or meta.default_model).strip()
    return Endpoint(
        name=name, base_url=base_url, model=model, api_key=api_key,
        supports_tools=_env_true(meta.env_tools),
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
    """Resolve a provider id (built-in / virtual / table row) to a call endpoint."""
    if provider in _PROVIDER_REGISTRY:
        meta = _PROVIDER_REGISTRY[provider]
        if meta.virtual:
            return _resolve_virtual(provider, model_override)
        return _resolve_builtin(provider, model_override)
    store = store or get_store()
    record = store.get_provider(provider)
    if record is None or not record.get("enabled"):
        return None
    if record.get("kind") != KIND_LOCAL_CLI and not record.get("api_key"):
        return None
    model = (model_override or record.get("model") or "").strip()
    return Endpoint(
        # 与 LLMCaller 容灾链里的 provider 命名保持同一前缀，否则功能点绑定
        # 无法把绑定目标提升到链首。
        name=f"custom:{record['id']}",
        base_url=str(record.get("base_url") or "").rstrip("/"),
        model=model,
        api_key=record.get("api_key", ""),
        supports_tools=bool(record.get("supports_tools")),
        max_tool_calls=int(record.get("max_tool_calls") or _DEFAULT_MAX_TOOL_CALLS),
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
    for record in store.list_providers(enabled_only=True):
        if record["kind"] == KIND_BUILTIN:
            continue
        if record["kind"] != KIND_LOCAL_CLI and not record.get("api_key"):
            continue
        result.append({
            "key": record["id"],
            "name": record["name"] or "自定义 API",
            "model": record.get("model", ""),
            "models": list(record.get("models") or []),
            "virtual": False,
            "custom": True,
            "kind": record["kind"],
        })
    return result


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
        "checked_at": _now_iso(),
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
