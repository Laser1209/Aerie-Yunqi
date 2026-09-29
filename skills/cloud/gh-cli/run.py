"""gh-cli skill — GitHub 仓库/PR/Issue 查询 / GitHub CLI queries.

通过本机 ``gh`` 命令查询 GitHub 的**只读**信息。底层 ``gh`` 已装在本机，
不需要任何云端凭据（但需要用户自己先 ``gh auth login``）。

安全边界：只允许**白名单内的只读 action**。写入类操作（创建 PR、合并、评论、
推送）一律不在范围内 —— 通过把 action 映射到固定的 argv 前缀来保证，
调用方无法拼出任意 gh 子命令。
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

PROVIDER_HINT = "shell-safe"
READ_ONLY = True

_CLI_NAME = "gh"
_TIMEOUT_SEC = 30
_DEFAULT_LIMIT = 10
_MAX_LIMIT = 50

# 每个 action → (argv 前缀, 需要 --json 的字段集合)。
# 只读白名单：这里没有出现的一律拒绝执行。
_ACTIONS: dict[str, tuple[list[str], tuple[str, ...]]] = {
    "pr_list": (
        ["pr", "list"],
        ("number", "title", "state", "author", "createdAt", "url"),
    ),
    "pr_view": (
        ["pr", "view"],
        ("number", "title", "state", "author", "body", "url", "mergeable"),
    ),
    "issue_list": (
        ["issue", "list"],
        ("number", "title", "state", "author", "createdAt", "url"),
    ),
    "issue_view": (
        ["issue", "view"],
        ("number", "title", "state", "author", "body", "url"),
    ),
    "repo_view": (
        ["repo", "view"],
        ("nameWithOwner", "description", "defaultBranchRef", "isPrivate", "url"),
    ),
    "run_list": (
        ["run", "list"],
        ("databaseId", "name", "status", "conclusion", "createdAt", "url"),
    ),
    "search_repos": (
        ["search", "repos"],
        ("fullName", "description", "stargazersCount", "url"),
    ),
}

# 需要 number 位置参数的动作（详情类，不接受 --limit）
_NEEDS_NUMBER = frozenset({"pr_view", "issue_view"})

# 接受 --limit 的动作（列表/搜索类）。
# `repo_view` 两者都不是：它查看**单个**仓库，加了 --limit 会被 gh 判为未知参数
# （真机冒烟实测：`unknown flag: --limit`）。
_LIST_ACTIONS = frozenset({"pr_list", "issue_list", "run_list", "search_repos"})


def _cli_path() -> str | None:
    return shutil.which(_CLI_NAME)


def _clamp_limit(raw: Any) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_LIMIT
    return max(1, min(value, _MAX_LIMIT))


def _build_argv(cli: str, action: str, args: dict[str, Any]) -> list[str] | None:
    """拼出 gh 的 argv；action 非法或缺必填参数时返回 None。"""
    spec = _ACTIONS.get(action)
    if spec is None:
        return None
    prefix, fields = spec
    argv = [cli, *prefix]

    if action in _NEEDS_NUMBER:
        number = str(args.get("number") or "").strip()
        if not number.isdigit():
            return None
        argv.append(number)
    elif action == "search_repos":
        query = str(args.get("query") or "").strip()
        if not query:
            return None
        argv.append(query)
        argv.extend(["--limit", str(_clamp_limit(args.get("limit")))])
    elif action in _LIST_ACTIONS:
        argv.extend(["--limit", str(_clamp_limit(args.get("limit")))])

    repo = str(args.get("repo") or "").strip()
    if repo:
        if action == "repo_view":
            # `gh repo view <repository>`：仓库是**位置参数**，不吃 --repo
            # （真机冒烟实测：`unknown flag: --repo`）。
            argv.append(repo)
        else:
            argv.extend(["--repo", repo])

    if action in ("pr_list", "issue_list", "run_list"):
        state = str(args.get("state") or "").strip().lower()
        if state in ("open", "closed", "all"):
            argv.extend(["--state", state])

    argv.extend(["--json", ",".join(fields)])
    return argv


def run(args: dict) -> dict:
    """Skill 入口。``args`` 见 SKILL.md。"""
    args = args or {}
    action = str(args.get("action") or "").strip()
    if not action:
        return {"error": "missing action", "provider_hint": PROVIDER_HINT}
    if action not in _ACTIONS:
        return {
            "error": f"unsupported action: {action}",
            "allowed": sorted(_ACTIONS),
            "provider_hint": PROVIDER_HINT,
        }

    cli = _cli_path()
    if not cli:
        return {
            "status": "error",
            "error": f"{_CLI_NAME} CLI 不可用（未安装或不在 PATH）",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
        }

    argv = _build_argv(cli, action, args)
    if argv is None:
        needed = "number" if action in _NEEDS_NUMBER else (
            "query" if action == "search_repos" else "参数"
        )
        return {"error": f"missing {needed}", "provider_hint": PROVIDER_HINT}

    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TIMEOUT_SEC,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "error": f"gh 超时（>{_TIMEOUT_SEC}s）",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
        }
    except OSError as exc:
        return {
            "status": "error",
            "error": f"启动 gh 失败: {exc}",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
        }

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        # 未登录是最常见的一种失败，单独给一句能照着做的提示。
        if "auth" in detail.lower() or "login" in detail.lower():
            detail = "gh 未登录，请先执行 gh auth login"
        return {
            "status": "error",
            "error": detail[:300] or f"gh 退出码 {completed.returncode}",
            "action": action,
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
        }

    raw = (completed.stdout or "").strip()
    try:
        payload = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        # gh 返回的不是 JSON（极少见）：如实回传原文，不要假装空结果。
        return {
            "status": "ok",
            "action": action,
            "raw": raw[:4000],
            "count": 0,
            "items": [],
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
        }

    items = payload if isinstance(payload, list) else [payload]
    return {
        "status": "ok",
        "action": action,
        "count": len(items),
        "items": items,
        "provider_hint": PROVIDER_HINT,
        "read_only": READ_ONLY,
    }
