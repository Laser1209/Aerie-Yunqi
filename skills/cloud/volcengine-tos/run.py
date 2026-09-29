"""volcengine-tos skill — 火山引擎对象存储 TOS。

走官方 Python SDK（PyPI 包名 ``tos``），因此用 ``requires_module: tos`` 作闸门：
没装 SDK 的机器上这个 skill 不会出现在模型可见的工具清单里，而不是调用后才发现。
官方文档：https://www.volcengine.com/docs/6349/92786

前置：
  * ``pip install tos``
  * 环境变量：``TOS_ACCESS_KEY`` / ``TOS_SECRET_KEY`` / ``TOS_REGION`` /
    ``TOS_ENDPOINT`` / ``TOS_BUCKET``（变量名与官方文档一致，便于用户照着文档填）

Stub 契约（与其它 skill 一致）：
  - 缺必填参数     -> ``{"error": "missing <key>"}``
  - 缺凭据         -> ``{"status": "stub", "error": "credential_missing: ..."}``
  - 未装 SDK / 调用失败 -> ``{"status": "error", "error": "..."}``
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

PROVIDER_HINT = "text"
READ_ONLY = False

# 与官方文档一致的变量名：用户照文档配环境时不用翻译
_ENV_ACCESS_KEY = "TOS_ACCESS_KEY"
_ENV_SECRET_KEY = "TOS_SECRET_KEY"
_ENV_REGION = "TOS_REGION"
_ENV_ENDPOINT = "TOS_ENDPOINT"
_ENV_BUCKET = "TOS_BUCKET"

_ACTIONS = ("upload", "download", "sign_url", "list")
_MAX_ERR_CHARS = 400
_DEFAULT_EXPIRES = 3600
_MAX_LIST = 1000


def _short(text: Any, limit: int = _MAX_ERR_CHARS) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _missing_credentials() -> list[str]:
    return [
        name
        for name in (_ENV_ACCESS_KEY, _ENV_SECRET_KEY, _ENV_REGION, _ENV_ENDPOINT)
        if not str(os.getenv(name) or "").strip()
    ]


def _client():
    """构造 TosClientV2。SDK 缺失时抛 ImportError 由调用方转成可读错误。"""
    import tos  # noqa: PLC0415 —— 惰性导入：模块顶层导入会让"发现阶段"就依赖重库

    return tos.TosClientV2(
        os.getenv(_ENV_ACCESS_KEY, "").strip(),
        os.getenv(_ENV_SECRET_KEY, "").strip(),
        os.getenv(_ENV_ENDPOINT, "").strip(),
        os.getenv(_ENV_REGION, "").strip(),
    )


def _bucket(args: dict) -> str:
    return str(args.get("bucket") or os.getenv(_ENV_BUCKET) or "").strip()


def run(args: dict) -> dict:
    """Skill entry point.

    ``args`` 约定的键：action / key / file_path / bucket / prefix / expires / max_keys。
    """
    args = args or {}
    action = str(args.get("action") or "upload").strip().lower()
    if action not in _ACTIONS:
        return {
            "error": f"unknown action: {action!r}（可选 {' / '.join(_ACTIONS)}）",
            "provider_hint": PROVIDER_HINT,
        }

    missing = _missing_credentials()
    if missing:
        return {
            "status": "stub",
            "error": f"credential_missing: 缺少 {', '.join(missing)}",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
        }

    try:
        import tos  # noqa: F401,PLC0415
    except ImportError as e:
        return {
            "status": "error",
            "error": f"tos SDK 未安装（pip install tos）: {e}",
            "provider_hint": PROVIDER_HINT,
        }

    return _dispatch(action, args)


def _dispatch(action: str, args: dict) -> dict:
    import tos  # noqa: PLC0415

    bucket = _bucket(args)
    if not bucket:
        return {
            "error": "missing bucket（既未传参，也未设置 TOS_BUCKET）",
            "provider_hint": PROVIDER_HINT,
        }

    key = str(args.get("key") or "").strip()
    if action in ("upload", "download", "sign_url") and not key:
        return {"error": "missing key", "provider_hint": PROVIDER_HINT}

    try:
        client = _client()
        if action == "upload":
            return _upload(client, args, bucket, key)
        if action == "download":
            return _download(client, args, bucket, key)
        if action == "sign_url":
            return _sign_url(client, args, bucket, key)
        return _list(client, args, bucket)
    except tos.exceptions.TosClientError as e:
        # 客户端侧：参数非法、网络异常
        return {
            "status": "error",
            "error": f"client_error: {_short(getattr(e, 'message', e))}",
            "provider_hint": PROVIDER_HINT,
        }
    except tos.exceptions.TosServerError as e:
        # 服务端侧：带上 code 与 request_id —— 排查线上问题时这两个最关键
        return {
            "status": "error",
            "error": f"server_error: {getattr(e, 'code', '')} {_short(getattr(e, 'message', e))}",
            "request_id": str(getattr(e, "request_id", "") or ""),
            "http_status": getattr(e, "status_code", None),
            "provider_hint": PROVIDER_HINT,
        }
    except Exception as e:
        logger.exception("tos %s failed", action)
        return {
            "status": "error",
            "error": f"{type(e).__name__}: {_short(e)}",
            "provider_hint": PROVIDER_HINT,
        }


def _upload(client: Any, args: dict, bucket: str, key: str) -> dict:
    file_path = str(args.get("file_path") or "").strip()
    if not file_path:
        return {"error": "missing file_path", "provider_hint": PROVIDER_HINT}
    if not os.path.isfile(file_path):
        return {
            "status": "error",
            "error": f"file not found: {file_path}",
            "provider_hint": PROVIDER_HINT,
        }

    # upload_file 走分片 + 断点续传，比 put_object 更适合真实文件
    result = client.upload_file(bucket, key, file_path, task_num=3)
    return {
        "status": "ok",
        "bucket": bucket,
        "key": key,
        "file_path": file_path,
        "size": os.path.getsize(file_path),
        "request_id": str(getattr(result, "request_id", "") or ""),
        "provider_hint": PROVIDER_HINT,
    }


def _download(client: Any, args: dict, bucket: str, key: str) -> dict:
    file_path = str(args.get("file_path") or "").strip()
    if not file_path:
        return {"error": "missing file_path", "provider_hint": PROVIDER_HINT}
    parent = os.path.dirname(os.path.abspath(file_path))
    if parent and not os.path.isdir(parent):
        return {
            "status": "error",
            "error": f"目标目录不存在: {parent}",
            "provider_hint": PROVIDER_HINT,
        }

    client.get_object_to_file(bucket, key, file_path)
    return {
        "status": "ok",
        "bucket": bucket,
        "key": key,
        "file_path": file_path,
        "size": os.path.getsize(file_path) if os.path.isfile(file_path) else None,
        "provider_hint": PROVIDER_HINT,
    }


def _sign_url(client: Any, args: dict, bucket: str, key: str) -> dict:
    """生成预签名 GET URL（默认 1 小时）。"""
    from tos.enum import HttpMethodType  # noqa: PLC0415

    expires = int(args.get("expires") or _DEFAULT_EXPIRES)
    output = client.pre_signed_url(
        HttpMethodType.Http_Method_Get, bucket, key, expires=expires
    )
    return {
        "status": "ok",
        "bucket": bucket,
        "key": key,
        "url": str(getattr(output, "signed_url", "") or ""),
        "expires": expires,
        "provider_hint": PROVIDER_HINT,
    }


def _list(client: Any, args: dict, bucket: str) -> dict:
    prefix = str(args.get("prefix") or "").strip()
    try:
        max_keys = int(args.get("max_keys") or 100)
    except (TypeError, ValueError):
        return {"error": "invalid max_keys", "provider_hint": PROVIDER_HINT}
    max_keys = max(1, min(max_keys, _MAX_LIST))

    result = client.list_objects(bucket, prefix=prefix, max_keys=max_keys)
    items = [
        {
            "key": str(getattr(item, "key", "") or ""),
            "size": getattr(item, "size", None),
            "last_modified": str(getattr(item, "last_modified", "") or ""),
        }
        for item in (getattr(result, "contents", None) or [])
    ]
    return {
        "status": "ok",
        "bucket": bucket,
        "prefix": prefix,
        "count": len(items),
        "items": items,
        "truncated": bool(getattr(result, "is_truncated", False)),
        "provider_hint": PROVIDER_HINT,
    }
