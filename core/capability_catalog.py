"""能力目录 —— 「现在能用什么 / 缺什么 / 去哪儿配」的**唯一事实来源**。

为什么需要它：在补上这个目录之前，不可用能力被**静默过滤**，模型根本不知道
清单外还有什么；用户在微信里说"我要用 seedream"，模型只会答"我做不到"。
设置页那一侧的信息其实是齐的（凭证卡有 how_to / tutorial / 已配置状态），
**断点只在"通往模型"这一步**。本模块把散在三处的信息聚成一份结构化目录：

- **skill**：`core.skill_loader.SkillLoader.discovered`（可用性 + 闸门原因）
- **plugin**：`core.plugin_host.list_status()`（功能包是否装了 / 是否加载成功）
- **mcp**：`core.mcp_client.load_servers_config()`（预设开关 + 凭据引用）

「去哪儿配」由 `missing` 里的标识（环境变量名 / 模块名 / CLI 名）**反查**既有声明得出：

- 环境变量 → `core.platform_credentials.credential_where()`（设置页哪一块）
- CLI / 模块 → SKILL.md 自己声明的 `setup_hint`
- 未接入 → SKILL.md 的 `not_implemented_note`

**不在这里另写一张映射表** —— 同一事实写两处必然漂移。

绝不携带密钥明文：只读"是否已配置"，从不读值。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from core.platform_credentials import credential_where

logger = logging.getLogger(__name__)

_ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

KIND_SKILL = "skill"
KIND_MCP = "mcp"
KIND_PLUGIN = "plugin"

# 闸门 → fix_kind，供前端/模型决定"该做什么"而不是只看到一句原因。
_FIX_ENV = "env"                    # 去设置页填凭据
_FIX_MODULE = "module"              # 装本地 Python 模块
_FIX_CLI = "cli"                    # 装本机命令行工具
_FIX_NOT_IMPLEMENTED = "not_implemented"   # 能力本身没做（故意）
_FIX_MCP_OFF = "mcp_disabled"       # 去设置页开启 MCP 服务器
_FIX_PLUGIN = "plugin_missing"      # 去模块中心安装功能包


@dataclass(frozen=True)
class CapabilityEntry:
    """一条能力的可用性画像。字段刻意保持扁平，便于直接喂给模型或渲染面板。"""

    name: str
    kind: str
    ready: bool
    what: str = ""
    unavailable_reason: str = ""
    missing: tuple[str, ...] = ()
    where: str = ""
    tutorial: str = ""
    fix_kind: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "ready": self.ready,
            "what": self.what,
            "unavailable_reason": self.unavailable_reason,
            "missing": list(self.missing),
            "where": self.where,
            "tutorial": self.tutorial,
            "fix_kind": self.fix_kind,
        }


def _split_reason(reason: str) -> tuple[str, tuple[str, ...]]:
    """从闸门原因里抽出缺失标识（`missing env: X` → fix_kind + (X,)）。"""
    text = str(reason or "").strip()
    if not text:
        return "", ()
    if text.startswith("missing env: "):
        return _FIX_ENV, (text[len("missing env: "):].strip(),)
    if text.startswith("missing module: "):
        return _FIX_MODULE, (text[len("missing module: "):].strip(),)
    if text.startswith("missing cli: "):
        return _FIX_CLI, (text[len("missing cli: "):].strip(),)
    if text.startswith("not implemented"):
        return _FIX_NOT_IMPLEMENTED, ()
    return "", ()


def _where_for(fix_kind: str, missing: tuple[str, ...], *, setup_hint: str, reason: str) -> str:
    """把「缺什么」翻译成「去哪儿配」；反查不到就如实留空 —— 不瞎指路。"""
    if fix_kind == _FIX_ENV:
        return credential_where(missing[0] if missing else "")
    if fix_kind in (_FIX_CLI, _FIX_MODULE):
        return setup_hint
    if fix_kind == _FIX_NOT_IMPLEMENTED:
        # 原因正文就写在 `not implemented (scaffold stub): <说明>` 的冒号后。
        _, _, tail = str(reason or "").partition(": ")
        return tail.strip()
    return ""


def _skill_entries(loader: Any) -> list[CapabilityEntry]:
    discovered = getattr(loader, "discovered", None) or {}
    entries: list[CapabilityEntry] = []
    for name, meta in sorted(discovered.items()):
        reason = str(meta.get("unavailable_reason") or "")
        ready = bool(meta.get("available"))
        fix_kind, missing = ("", ()) if ready else _split_reason(reason)
        entries.append(
            CapabilityEntry(
                name=str(name),
                kind=KIND_SKILL,
                ready=ready,
                what=str(meta.get("desc") or ""),
                unavailable_reason=reason,
                missing=missing,
                where="" if ready else _where_for(
                    fix_kind, missing,
                    setup_hint=str(meta.get("setup_hint") or ""),
                    reason=reason,
                ),
                fix_kind=fix_kind,
            )
        )
    return entries


def _plugin_entries() -> list[CapabilityEntry]:
    """已**发现**的功能包（`plugin_host` 只登记扫到的包；没装的包不在这里）。"""
    try:
        from core import plugin_host

        statuses = plugin_host.list_status()
    except Exception:
        logger.debug("plugin_host.list_status 不可用，跳过功能包段", exc_info=True)
        return []

    entries: list[CapabilityEntry] = []
    for status in statuses:
        if not isinstance(status, dict):
            continue
        pack_id = str(status.get("id") or "").strip()
        if not pack_id:
            continue
        state = str(status.get("state") or "").strip().lower()
        ready = state == "loaded"
        error = str(status.get("error") or "").strip()
        entries.append(
            CapabilityEntry(
                name=pack_id,
                kind=KIND_PLUGIN,
                ready=ready,
                what=f"功能包 v{status.get('version') or '?'}（{len(status.get('tools') or [])} 个工具）",
                unavailable_reason="" if ready else f"plugin {state or 'unavailable'}: {error}".strip(),
                missing=() if ready else (pack_id,),
                where="" if ready else "桌面端 → 模块中心 → 查看该功能包（加载失败可重装）",
                fix_kind="" if ready else _FIX_PLUGIN,
            )
        )
    return entries


def _mcp_missing_env(conf: dict[str, Any]) -> tuple[str, ...]:
    """从 `${VAR}` 引用里抽出该 server 需要的环境变量（去重、保序）。"""
    refs: list[str] = []
    for blob in (conf.get("env") or {}, conf.get("headers") or {}):
        if not isinstance(blob, dict):
            continue
        for value in blob.values():
            for hit in _ENV_REF_RE.findall(str(value or "")):
                if hit not in refs:
                    refs.append(hit)
    return tuple(refs)


def _mcp_entries() -> list[CapabilityEntry]:
    try:
        from core.mcp_client import DEFAULT_CONFIG_PATH, MCPServerConfig, load_servers_config
    except Exception:
        logger.debug("mcp_client 不可用，跳过 MCP 段", exc_info=True)
        return []

    try:
        master_enabled, raw = load_servers_config(DEFAULT_CONFIG_PATH)
    except Exception:
        logger.debug("MCP 配置读取失败，跳过 MCP 段", exc_info=True)
        return []

    entries: list[CapabilityEntry] = []
    for name, conf in (raw or {}).items():
        if not isinstance(conf, dict):
            continue
        try:
            cfg = MCPServerConfig.from_dict(str(name), conf)
        except Exception:
            continue
        ready = bool(master_enabled and cfg.enabled)
        reason = ""
        where = ""
        fix_kind = ""
        if not master_enabled:
            reason = "MCP 总开关未开启"
            where = "设置页 → MCP 服务器 → 打开总开关"
            fix_kind = _FIX_MCP_OFF
        elif not cfg.enabled:
            reason = "server disabled"
            where = f"设置页 → MCP 服务器 → 开启「{cfg.name}」"
            fix_kind = _FIX_MCP_OFF
        missing = _mcp_missing_env(conf)
        entries.append(
            CapabilityEntry(
                name=str(name),
                kind=KIND_MCP,
                ready=ready,
                what=f"MCP 服务器（{cfg.transport}）",
                unavailable_reason=reason,
                missing=missing,
                where=where,
                fix_kind=fix_kind,
            )
        )
    return entries


def build_catalog(loader: Any = None) -> list[CapabilityEntry]:
    """聚合 skill / plugin / mcp 三段，返回全量目录（含不可用项）。

    ``loader`` 省略时用进程内登记的 SkillLoader（见 ``set_loader``）——
    这样失败文案 / 工具 / 上下文注入不必各自想办法拿到 loader。
    """
    entries: list[CapabilityEntry] = []
    active = loader if loader is not None else current_loader()
    if active is not None:
        entries.extend(_skill_entries(active))
    entries.extend(_plugin_entries())
    entries.extend(_mcp_entries())
    return entries


# ── 进程内 loader 登记（让非接线点也能拿到目录）──────────
_LOADER_HOLDER: dict[str, Any] = {"loader": None}


def set_loader(loader: Any) -> None:
    """启动时登记 SkillLoader（幂等；传 None 可清空，测试用）。"""
    _LOADER_HOLDER["loader"] = loader


def current_loader() -> Any:
    return _LOADER_HOLDER["loader"]


def owner_of(identifier: str) -> CapabilityEntry | None:
    """按「缺失标识」（环境变量名 / 模块名 / CLI 名 / 功能包 id）反查归属能力。

    失败文案与提示词注入都靠它把「缺 SEEDREAM_KEY」翻成「哪个能力需要它、去哪配」。
    """
    target = str(identifier or "").strip()
    if not target:
        return None
    for entry in build_catalog():
        if target in entry.missing:
            return entry
    return None


def snapshot(loader: Any = None, *, limit: int | None = None) -> dict[str, Any]:
    """目录概览：总数 / 就绪数 + 未就绪清单（可截断，避免撑爆上下文预算）。"""
    entries = build_catalog(loader)
    unavailable = [e for e in entries if not e.ready]
    payload: dict[str, Any] = {
        "total": len(entries),
        "ready_count": len(entries) - len(unavailable),
        "unavailable_count": len(unavailable),
    }
    if limit is not None and limit >= 0:
        payload["unavailable"] = [e.to_dict() for e in unavailable[:limit]]
        payload["truncated"] = max(0, len(unavailable) - limit)
    else:
        payload["unavailable"] = [e.to_dict() for e in unavailable]
        payload["truncated"] = 0
    return payload


def lookup(name: str, loader: Any = None) -> CapabilityEntry | None:
    """按名字查单项（大小写不敏感）；查不到返回 None（调用方应报错而非静默空）。"""
    target = str(name or "").strip().lower()
    if not target:
        return None
    for entry in build_catalog(loader):
        if entry.name.lower() == target:
            return entry
    return None


def is_ready(name: str, loader: Any = None) -> bool:
    entry = lookup(name, loader)
    return bool(entry and entry.ready)


def unavailable_names(loader: Any = None) -> list[str]:
    return [e.name for e in build_catalog(loader) if not e.ready]
