"""byted-bp-cdn-pagesdeploy skill — BytePlus Edge Pages 部署（官方 CLI 子进程）.

调用本机官方 CLI ``@byteplus/nest``（二进制名 ``nest``）把静态站点部署到
BytePlus Edge Pages：

    nest config set -g cloud.access_key <AK>      # 一次性配置（AK/SK，来自 IAM）
    nest config set -g cloud.secret_key <SK>
    nest pages create --name <项目名> --assets <静态目录> --deploy
    nest pages domain add -p <pages_id> --domain <域名>

只实现**已查证**的命令（见 ``tmp/out/byteplus-pages-api-recon.md``）；BytePlus 未公开
Pages 的 REST 契约，因此不提供 HTTP 路径。

鉴权：AK/SK 由用户在本机执行 ``nest config set`` 写进 CLI 自己的配置，本 skill
**不代持任何密钥**。

安全：argv 由「固定前缀 + 白名单参数」拼出，``shell=False``；静态目录必须落在项目根
之内且含 ``index.html``。
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROVIDER_HINT = "shell-safe"
READ_ONLY = False

_CLI_NAME = "nest"
_TIMEOUT_SEC = 900  # 上传 + 构建 + 发布可能耗时
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

_PROJECT_NAME_RE = re.compile(r"^[a-z0-9-]{2,31}$")
_PAGES_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,64}$")
_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$", re.IGNORECASE)

# 已查证的 argv 前缀；不在这里的 action 一律拒绝执行。
_ACTIONS: dict[str, tuple[str, ...]] = {
    "help": ("--help",),
    "version": ("--version",),
    "deploy": ("pages", "create"),
    "domain_add": ("pages", "domain", "add"),
}


def _cli_path() -> str | None:
    return shutil.which(_CLI_NAME)


def _confined_assets_dir(raw: Any) -> str | None:
    """静态资源目录：必须在项目根之内、存在、且含 index.html。"""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        resolved = Path(text).expanduser().resolve()
        resolved.relative_to(_PROJECT_ROOT)
    except (OSError, ValueError):
        return None
    if not resolved.is_dir() or not (resolved / "index.html").is_file():
        return None
    return str(resolved)


def _build_argv(cli: str, action: str, args: dict[str, Any]) -> list[str] | None:
    """拼出 nest 的 argv；参数非法时返回 None。"""
    prefix = _ACTIONS.get(action)
    if prefix is None:
        return None
    argv = [cli, *prefix]

    if action in ("help", "version"):
        return argv

    if action == "deploy":
        name = str(args.get("project_name") or "").strip()
        assets = _confined_assets_dir(args.get("assets_dir"))
        if not _PROJECT_NAME_RE.match(name) or assets is None:
            return None
        argv.extend(["--name", name, "--assets", assets])
        if str(args.get("deploy", "true")).strip().lower() not in ("0", "false", "no"):
            argv.append("--deploy")
        return argv

    # domain_add
    pages_id = str(args.get("pages_id") or "").strip()
    domain = str(args.get("domain") or "").strip()
    if not _PAGES_ID_RE.match(pages_id) or not _DOMAIN_RE.match(domain):
        return None
    argv.extend(["-p", pages_id, "--domain", domain])
    return argv


def _nestcli_hint(detail: str) -> str:
    """`nest` 与 NestJS CLI 撞名：子命令不认识时提示装的是哪一个。"""
    lowered = detail.lower()
    if "unknown command" in lowered or "unknown argument" in lowered:
        return (
            detail
            + " —— 若本机装的是 NestJS CLI 而非 @byteplus/nest，请先 "
            "npm install -g @byteplus/nest"
        )
    return detail


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
            "error": (
                "nest CLI 不可用（未安装或不在 PATH）：npm install -g @byteplus/nest"
            ),
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
        }

    argv = _build_argv(cli, action, args)
    if argv is None:
        return {
            "error": "invalid arguments",
            "action": action,
            "provider_hint": PROVIDER_HINT,
        }

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
            "error": f"nest 超时（>{_TIMEOUT_SEC}s）",
            "action": action,
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
        }
    except OSError as exc:
        return {
            "status": "error",
            "error": f"启动 nest 失败: {exc}",
            "action": action,
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
        }

    stdout = (completed.stdout or "").strip()
    if completed.returncode != 0:
        detail = _nestcli_hint((completed.stderr or completed.stdout or "").strip())
        return {
            "status": "error",
            "error": detail[:400] or f"nest 退出码 {completed.returncode}",
            "action": action,
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
        }

    return {
        "status": "ok",
        "action": action,
        "stdout": stdout[:4000],
        "provider_hint": PROVIDER_HINT,
        "read_only": READ_ONLY,
    }
