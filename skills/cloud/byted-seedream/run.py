"""byted-seedream skill — 火山方舟 Seedream 文生图。

走 Ark 的图片生成 API：Bearer 鉴权 + 一次 POST 同步返回图片 URL（无轮询）。
官方文档：https://www.volcengine.com/docs/82379/1541523

前置：
  * 环境变量 ``SEEDREAM_KEY``（火山方舟控制台 → API Key）
  * 控制台里已「开通模型」，否则会返回 ``Model.NotOpen``

Stub 契约（与其它 skill 一致）：
  - 缺 prompt        -> ``{"error": "missing prompt"}``
  - 缺 SEEDREAM_KEY  -> ``{"status": "stub", "error": "credential_missing: ..."}``
  - HTTP / 解析失败  -> ``{"status": "error", "error": "..."}``
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

PROVIDER_HINT = "image-sdxl"
READ_ONLY = False
ENV_VAR = "SEEDREAM_KEY"

_API_URL = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
# 默认 Model ID。火山方舟会随版本迭代调整可用模型，调用方可用 args["model"] 覆盖
# （在控制台「开通模型」→ 模型详情里查 Model ID）。
_DEFAULT_MODEL = "doubao-seedream-5-0-260128"
_DEFAULT_SIZE = "2K"
_TIMEOUT_SEC = 120
_MAX_ERR_CHARS = 400


def _short(text: str, limit: int = _MAX_ERR_CHARS) -> str:
    """把可能很长的响应体截成一句话，避免把整段 JSON 灌进对话上下文。"""
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def run(args: dict) -> dict:
    """Skill entry point. ``args`` 约定的键：prompt / model / size。"""
    args = args or {}
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return {"error": "missing prompt", "provider_hint": PROVIDER_HINT}

    api_key = str(os.getenv(ENV_VAR) or "").strip()
    if not api_key:
        return {
            "status": "stub",
            "error": f"credential_missing: env {ENV_VAR!r} not set",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
            "prompt": prompt[:80],
        }

    try:
        import requests
    except ImportError as e:  # pragma: no cover - requests 是项目既有依赖
        return {
            "status": "error",
            "error": f"requests unavailable: {e}",
            "provider_hint": PROVIDER_HINT,
        }

    payload = {
        "model": str(args.get("model") or _DEFAULT_MODEL).strip(),
        "prompt": prompt,
        "size": str(args.get("size") or _DEFAULT_SIZE).strip(),
    }

    try:
        resp = requests.post(
            _API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=_TIMEOUT_SEC,
        )
    except Exception as e:
        logger.warning("seedream request failed: %s", e)
        return {
            "status": "error",
            "error": f"request_failed: {e}",
            "provider_hint": PROVIDER_HINT,
        }

    # 401 ApiKey.Invalid / 400 Model.NotOpen / 429 限流都在这里如实透出，不假装成功
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

    items = body.get("data") if isinstance(body, dict) else None
    if not items:
        return {
            "status": "error",
            "error": "empty_result",
            "provider_hint": PROVIDER_HINT,
            "body": _short(str(body)),
        }

    first = items[0] if isinstance(items[0], dict) else {}
    return {
        "status": "ok",
        "image_url": str(first.get("url") or ""),
        "size": str(first.get("size") or ""),
        "model": payload["model"],
        "prompt": prompt[:200],
        "provider_hint": PROVIDER_HINT,
        "read_only": READ_ONLY,
    }
