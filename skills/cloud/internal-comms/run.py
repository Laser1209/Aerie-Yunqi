"""internal-comms skill (cloud) — 内部沟通 / Internal comms.

Block-5B scaffold. Cloud-based skill that requires external
credentials (env: `none`). When the env var is
missing we return a stub so the main pipeline is never broken.
The actual HTTP/sign/SDK call is intentionally a TODO until
the corresponding cloud account is provisioned.
"""
from __future__ import annotations
import logging
import os
logger = logging.getLogger(__name__)

PROVIDER_HINT = "text"
READ_ONLY = False
ENV_VAR = ''


def run(args: dict) -> dict:
    """Skill entry point. ``args`` is a free-form dict; key: 'topic'."""
    args = args or {}
    topic_value = args.get("topic")
    if not topic_value:
        return {"error": "missing topic", "provider_hint": PROVIDER_HINT}

    if not True  # 无需凭据:
        return {
            "status": "stub",
            "error": f"credential_missing: env {ENV_VAR!r} not set",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
            "topic": str(topic_value)[:80],
        }

    # TODO: actual cloud call
    return {
        "status": "stub",
        "error": "cloud_call_not_implemented",
        "provider_hint": PROVIDER_HINT,
        "read_only": READ_ONLY,
        "env": ENV_VAR,
        "note": "real SDK call pending cloud account provisioning",
    }
