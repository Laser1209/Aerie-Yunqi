"""Aerie · 云栖 — TypeSafe 结构化解策通道（noul 二元判定）。

博查 Bocha Jev（``bocha-jev-v1``）经词元跳动 TypeSafe 网关提供的结构化评估接口：
不生成自然语言，只对「是 / 否」类问题直接返回概率，服务端算力约 6ms。

实测边界（2026-09-28 探针，共 11 轮）：
  - ``noul`` 单一清晰谓词：准确率 83%~92%，输出完全确定性，**可用**；
  - ``choice`` 多选 / ``score`` 评分：受候选顺序支配、对不同输入几乎不区分，
    拆成 one-vs-rest 也只有 50%，**不可用**。
因此本通道只暴露 ``noul()``。多分类与评分不要走这里。

调用方约定：本模块**只做判定，不做兜底**。未配置 / 全局模型开关关闭 / 断网 /
超时 / 响应异常一律返回 ``None``，由调用方静默回退到原有小模型，绝不阻塞主链路。
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from core.model_gate import model_calls_disabled

logger = logging.getLogger(__name__)

ENV_API_KEY = "AERIE_TYPESAFE_API_KEY"
ENV_BASE_URL = "AERIE_TYPESAFE_BASE_URL"
ENV_MODEL = "AERIE_TYPESAFE_MODEL"
ENV_TIMEOUT_SEC = "AERIE_TYPESAFE_TIMEOUT_SEC"

DEFAULT_BASE_URL = "https://tokendance.space/gateway/typesafe/v1"
DEFAULT_MODEL = "bocha-jev-v1"
DEFAULT_TIMEOUT_SEC = 8.0

_ENDPOINT_PATH = "/systemone"
_QUESTION_KEY = "q"


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def base_url() -> str:
    return _env(ENV_BASE_URL, DEFAULT_BASE_URL).rstrip("/")


def api_key() -> str:
    return _env(ENV_API_KEY)


def model() -> str:
    return _env(ENV_MODEL, DEFAULT_MODEL)


def timeout_sec() -> float:
    try:
        value = float(_env(ENV_TIMEOUT_SEC) or DEFAULT_TIMEOUT_SEC)
    except ValueError:
        return DEFAULT_TIMEOUT_SEC
    return value if value > 0 else DEFAULT_TIMEOUT_SEC


def is_configured() -> bool:
    """凭证齐备才启用；缺任一项调用方应直接走原路径。"""
    return bool(api_key() and base_url() and model())


async def noul(
    state: str,
    instructions: str,
    *,
    timeout: float | None = None,
) -> float | None:
    """对单个「是 / 否」问题求概率。

    Args:
        state: 共享上下文（被判定的事实 / 文本本身，不要写成提问）。
        instructions: 单句是非问句，谓词必须互斥、清晰。

    Returns:
        ``0.0~1.0`` 的「是」概率；任何失败返回 ``None``。
    """
    if not is_configured() or model_calls_disabled():
        return None

    text_state = str(state or "").strip()
    text_question = str(instructions or "").strip()
    if not text_state or not text_question:
        return None

    body = {
        "model": model(),
        "state": text_state,
        "questions": {_QUESTION_KEY: {"type": "noul", "instructions": text_question}},
    }
    headers = {
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout or timeout_sec()) as client:
            resp = await client.post(
                base_url() + _ENDPOINT_PATH, headers=headers, json=body
            )
        if resp.status_code != 200:
            logger.warning(
                "[Typesafe] noul HTTP %s: %s", resp.status_code, resp.text[:160]
            )
            return None
        data = resp.json()
    except Exception:
        logger.warning("[Typesafe] noul 请求失败", exc_info=True)
        return None

    answer = (data.get("answers") or {}).get(_QUESTION_KEY) or {}
    value = answer.get("noul")
    if not isinstance(value, (int, float)):
        logger.warning("[Typesafe] noul 响应无法解析: %s", str(data)[:160])
        return None

    _record_usage(data)
    return max(0.0, min(1.0, float(value)))


def _record_usage(data: dict[str, Any]) -> None:
    """把这次判定的 token 记进全局账本（与 LLMCaller 同源）。"""
    usage = data.get("usage") or {}
    try:
        from core.token_tracker import get_token_tracker

        get_token_tracker().record(
            provider="typesafe",
            model=str(data.get("model") or model()),
            prompt_tokens=int(usage.get("input_tokens") or 0),
            completion_tokens=int(usage.get("output_tokens") or 0),
        )
    except Exception:
        logger.debug("[Typesafe] 用量记账失败", exc_info=True)
