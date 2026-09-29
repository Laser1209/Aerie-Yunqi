"""byted-mediakit skill — 字节 AI MediaKit 音视频处理（官方 CLI 子进程）.

调用本机官方 CLI ``mediakit-cli``（npm ``@volcengine/mediakit-cli``）：

- **本地模式**（``--local``）走本机 FFmpeg：裁剪等轻编辑，同步返回；
- **云端模式**走 AI MediaKit：画质增强等 AI 原子能力，异步返回 ``task_id``，
  再用 ``shared query-task`` 取结果。

只实现**已查证**的三条命令 + ``help``（其余 100+ 原子能力等官方文档核准后再加，
不凭记忆编造子命令 —— 见 ``tmp/out/mediakit-api-recon.md``）。

鉴权：API Key 由用户在本机执行一次 ``mediakit-cli init --api-key <KEY>`` 写进 CLI
自己的配置文件，本 skill **不代持任何密钥**。

安全：argv 由「固定前缀 + 白名单参数」拼出，``shell=False``，调用方拼不出任意子命令；
本地输出目录必须落在项目根之内。
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

_CLI_NAME = "mediakit-cli"
_TIMEOUT_SEC = 900  # 云端任务提交 + 轮询可能耗时，给足上限
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

_RESOLUTION_RE = re.compile(r"^(2k|4k|\d{3,4}p)$", re.IGNORECASE)

# 已查证的 argv 前缀；不在这里的 action 一律拒绝执行。
_ACTIONS: dict[str, tuple[str, ...]] = {
    "help": ("--help",),
    "query_task": ("shared", "query-task"),
    "trim_video": ("--local", "editing", "trim-video"),
    "enhance_video": ("video", "enhance-video"),
}


def _cli_path() -> str | None:
    return shutil.which(_CLI_NAME)


def _confined_output_path(raw: Any) -> str | None:
    """本地输出目录必须落在项目根内；越界返回 None（不猜、不放行）。"""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        resolved = Path(text).expanduser().resolve()
        resolved.relative_to(_PROJECT_ROOT)
    except (OSError, ValueError):
        return None
    return str(resolved)


def _positive_number(raw: Any) -> str | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return f"{value:g}"


def _build_argv(cli: str, action: str, args: dict[str, Any]) -> list[str] | None:
    """拼出 mediakit-cli 的 argv；参数非法时返回 None。"""
    prefix = _ACTIONS.get(action)
    if prefix is None:
        return None
    argv = [cli, *prefix]

    if action == "help":
        return argv

    if action == "query_task":
        task_id = str(args.get("task_id") or "").strip()
        if not task_id:
            return None
        argv.extend(["--task-id", task_id])
        if str(args.get("poll_complete", "")).strip().lower() in ("1", "true", "yes"):
            argv.append("--poll-complete")
        return argv

    video_url = str(args.get("video_url") or "").strip()
    if not video_url:
        return None
    argv.extend(["--video-url", video_url])

    if action == "enhance_video":
        resolution = str(args.get("resolution") or "1080p").strip().lower()
        if not _RESOLUTION_RE.match(resolution):
            return None
        argv.extend(["--resolution", resolution])
        return argv

    # trim_video：start/end 必填且 start < end，输出目录限定在项目根内。
    start = _positive_number(args.get("start_time"))
    end = _positive_number(args.get("end_time"))
    output = _confined_output_path(args.get("output_path"))
    if start is None or end is None or output is None:
        return None
    if float(start) >= float(end):
        return None
    argv.extend(["--start-time", start, "--end-time", end, "--output-path", output])
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
            "error": (
                f"{_CLI_NAME} CLI 不可用（未安装或不在 PATH）："
                "npm install -g @volcengine/mediakit-cli"
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
            "error": f"{_CLI_NAME} 超时（>{_TIMEOUT_SEC}s）",
            "action": action,
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
        }
    except OSError as exc:
        return {
            "status": "error",
            "error": f"启动 {_CLI_NAME} 失败: {exc}",
            "action": action,
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
        }

    stdout = (completed.stdout or "").strip()
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        lowered = detail.lower()
        if "api key" in lowered or "unauthorized" in lowered or "not init" in lowered:
            detail = detail + " —— 需要先在本机执行 mediakit-cli init --api-key <KEY>"
        return {
            "status": "error",
            "error": detail[:400] or f"{_CLI_NAME} 退出码 {completed.returncode}",
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
