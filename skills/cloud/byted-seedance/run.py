"""byted-seedance skill — 火山方舟 Seedance 文生视频 / 图生视频。

视频生成是**异步任务**：先 create 拿 task_id，再 get 查进度。skill 是同步调用，
长轮询会把整个对话卡住（视频动辄几分钟），所以这里拆成两个 action，两段式使用：

    run({"action": "create", "prompt": "…"})   -> {"task_id": "cgt-…", "task_status": "queued"}
    run({"action": "get", "task_id": "cgt-…"}) -> {"task_status": "running"}
                                                  -> {"task_status": "succeeded", "video_url": "https://…"}

接口（官方文档 ark/create-video-generation-task-api）：
    POST https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks
    GET  https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks/{id}

前置：环境变量 ``SEEDANCE_KEY``（火山方舟 API Key）+ 控制台已开通 Seedance 模型。
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

PROVIDER_HINT = "text"
READ_ONLY = False
ENV_VAR = "SEEDANCE_KEY"

_API_URL = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"
# 默认 Model ID，可用 args["model"] 覆盖（控制台「开通模型」里查）。
_DEFAULT_MODEL = "doubao-seedance-2-0-260128"
_DEFAULT_RATIO = "adaptive"
_DEFAULT_DURATION = 5
_TIMEOUT_SEC = 60
_MAX_ERR_CHARS = 400
_ACTIONS = ("create", "get")


def _short(text: str, limit: int = _MAX_ERR_CHARS) -> str:
    """把可能很长的响应体截成一句话，避免把整段 JSON 灌进对话上下文。"""
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _extract_video_url(body: dict) -> str:
    """从查询响应里取视频地址。

    各版本返回的字段名不完全一致（``content.video_url`` / 列表形式 / 顶层
    ``video_url``），所以逐个候选路径试，取不到就返回空串由调用方看 ``raw``。
    """
    content = body.get("content")
    if isinstance(content, dict) and content.get("video_url"):
        return str(content["video_url"])
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("video_url"):
                return str(item["video_url"])
    for key in ("video_url", "url"):
        if body.get(key):
            return str(body[key])
    return ""


def run(args: dict) -> dict:
    """Skill entry point. ``args`` 约定的键：action / prompt / task_id / model / ratio / duration。"""
    args = args or {}
    action = str(args.get("action") or "create").strip().lower()
    if action not in _ACTIONS:
        return {
            "error": f"unknown action: {action!r}（可选 {' / '.join(_ACTIONS)}）",
            "provider_hint": PROVIDER_HINT,
        }

    api_key = str(os.getenv(ENV_VAR) or "").strip()
    if not api_key:
        return {
            "status": "stub",
            "error": f"credential_missing: env {ENV_VAR!r} not set",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
        }

    return _create(args, api_key) if action == "create" else _get(args, api_key)


def _create(args: dict, api_key: str) -> dict:
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return {"error": "missing prompt", "provider_hint": PROVIDER_HINT}

    content: list[dict] = [{"type": "text", "text": prompt}]
    image_url = str(args.get("image_url") or "").strip()
    if image_url:
        # 首帧参考图：公网可访问的 URL
        content.append({"type": "image_url", "image_url": {"url": image_url}})

    payload: dict = {
        "model": str(args.get("model") or _DEFAULT_MODEL).strip(),
        "content": content,
        "ratio": str(args.get("ratio") or _DEFAULT_RATIO).strip(),
        "duration": int(args.get("duration") or _DEFAULT_DURATION),
    }
    if "watermark" in args:
        payload["watermark"] = bool(args["watermark"])

    try:
        import requests

        resp = requests.post(_API_URL, headers=_headers(api_key), json=payload, timeout=_TIMEOUT_SEC)
    except Exception as e:
        logger.warning("seedance create failed: %s", e)
        return {"status": "error", "error": f"request_failed: {e}", "provider_hint": PROVIDER_HINT}

    if resp.status_code != 200:
        return {
            "status": "error",
            "error": f"http_{resp.status_code}: {_short(getattr(resp, 'text', ''))}",
            "provider_hint": PROVIDER_HINT,
        }

    try:
        body = resp.json()
    except Exception:
        return {
            "status": "error",
            "error": "invalid_json_response",
            "provider_hint": PROVIDER_HINT,
            "body": _short(getattr(resp, "text", "")),
        }

    task_id = str(body.get("id") or "").strip() if isinstance(body, dict) else ""
    if not task_id:
        return {
            "status": "error",
            "error": "no_task_id",
            "provider_hint": PROVIDER_HINT,
            "body": _short(str(body)),
        }

    return {
        "status": "ok",
        "task_id": task_id,
        "task_status": "queued",
        "model": payload["model"],
        "prompt": prompt[:200],
        "provider_hint": PROVIDER_HINT,
        "read_only": READ_ONLY,
        "note": "视频生成需要时间，稍后用 action=get + task_id 查询进度",
    }


def _get(args: dict, api_key: str) -> dict:
    task_id = str(args.get("task_id") or "").strip()
    if not task_id:
        return {"error": "missing task_id", "provider_hint": PROVIDER_HINT}

    try:
        import requests

        resp = requests.get(
            f"{_API_URL}/{task_id}", headers=_headers(api_key), timeout=_TIMEOUT_SEC
        )
    except Exception as e:
        logger.warning("seedance get failed: %s", e)
        return {"status": "error", "error": f"request_failed: {e}", "provider_hint": PROVIDER_HINT}

    if resp.status_code != 200:
        return {
            "status": "error",
            "error": f"http_{resp.status_code}: {_short(getattr(resp, 'text', ''))}",
            "provider_hint": PROVIDER_HINT,
        }

    try:
        body = resp.json()
    except Exception:
        return {
            "status": "error",
            "error": "invalid_json_response",
            "provider_hint": PROVIDER_HINT,
            "body": _short(getattr(resp, "text", "")),
        }

    if not isinstance(body, dict):
        return {
            "status": "error",
            "error": "unexpected_response_shape",
            "provider_hint": PROVIDER_HINT,
            "body": _short(str(body)),
        }

    task_status = str(body.get("status") or "").strip().lower()
    result = {
        "status": "ok",
        "task_id": task_id,
        "task_status": task_status,  # queued / running / succeeded / failed
        "provider_hint": PROVIDER_HINT,
        "read_only": READ_ONLY,
    }
    video_url = _extract_video_url(body)
    if video_url:
        result["video_url"] = video_url
    elif task_status in ("succeeded", "success"):
        # 成功了却取不到地址：把原始报文附上，别让调用方猜
        result["raw"] = _short(str(body))
    if task_status in ("failed", "error"):
        result["error"] = _short(str(body.get("error") or body))[:200]
    return result
