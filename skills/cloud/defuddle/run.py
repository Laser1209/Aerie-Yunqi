"""defuddle skill — 网页正文提取 / Extract clean content from a web page.

把网页抓成干净的 Markdown 正文（去掉导航/广告/侧栏/页脚）。底层是本机的
``defuddle`` 命令行程序（npm 全局包），因此**不需要任何云端凭据**。

契约（与 SkillLoader 一致）：``run(args: dict) -> dict``
  - 缺必填参数   -> {"error": "missing <key>"}
  - 依赖缺失/失败 -> {"status": "error", "error": "..."}
  - 成功         -> {"status": "ok", ...}

为什么用 subprocess 而不是自己写抽取：defuddle 是成熟的正文抽取实现
（Readability 一系），自己重写既慢又差 —— 优先用已有工具。
"""
from __future__ import annotations

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)

PROVIDER_HINT = "text"
READ_ONLY = True

# 抓取上限：网页可能很慢，给足时间但必须有界，绝不无限等。
_TIMEOUT_SEC = 45
# 正文上限：超长正文截断，避免一口气灌满上下文。
_MAX_CHARS = 20000
_CLI_NAME = "defuddle"


def _cli_path() -> str | None:
    """解析本机 defuddle 可执行文件；缺失返回 None。"""
    return shutil.which(_CLI_NAME)


def _run_cli(url: str, *, frontmatter: bool) -> tuple[bool, str]:
    """执行 defuddle，返回 (是否成功, 文本/错误)。"""
    cli = _cli_path()
    if not cli:
        return False, f"{_CLI_NAME} CLI 不可用（未安装或不在 PATH）"
    # 用列表参数 + shell=False：url 里可能带引号/& 等字符，交给 shell 会出事。
    argv = [cli, "parse", url, "--md"]
    if frontmatter:
        argv.append("--frontmatter")
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
        return False, f"抓取超时（>{_TIMEOUT_SEC}s）：{url}"
    except OSError as exc:
        return False, f"启动 {_CLI_NAME} 失败: {exc}"
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        return False, detail[:300] or f"{_CLI_NAME} 退出码 {completed.returncode}"
    return True, completed.stdout or ""


def run(args: dict) -> dict:
    """Skill 入口。``args`` 键：``url``（必填）、``frontmatter``（可选布尔）。"""
    args = args or {}
    url = str(args.get("url") or "").strip()
    if not url:
        return {"error": "missing url", "provider_hint": PROVIDER_HINT}

    frontmatter = bool(args.get("frontmatter"))
    ok, text = _run_cli(url, frontmatter=frontmatter)
    if not ok:
        logger.warning("defuddle 抓取失败 url=%s err=%s", url, text)
        return {
            "status": "error",
            "error": text,
            "url": url,
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
        }

    markdown = text.strip()
    if not markdown:
        return {
            "status": "error",
            "error": "该页面没有提取到正文（可能是纯 JS 渲染或非文章页）",
            "url": url,
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
        }

    truncated = False
    if len(markdown) > _MAX_CHARS:
        markdown = markdown[:_MAX_CHARS] + "\n\n…（正文过长，已截断）"
        truncated = True

    return {
        "status": "ok",
        "url": url,
        "markdown": markdown,
        "chars": len(markdown),
        "truncated": truncated,
        "provider_hint": PROVIDER_HINT,
        "read_only": READ_ONLY,
    }
