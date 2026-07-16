"""alipay-payment skill (cloud) — 支付宝开放平台 / Alipay.

Block-5B scaffold. Cloud-based skill that requires external
credentials (env: `ALIPAY_APP_ID`). When the env var is
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
ENV_VAR = 'ALIPAY_APP_ID'


def run(args: dict) -> dict:
    """Skill entry point. ``args`` is a free-form dict; key: 'out_trade_no'."""
    args = args or {}
    out_trade_no_value = args.get("out_trade_no")
    if not out_trade_no_value:
        return {"error": "missing out_trade_no", "provider_hint": PROVIDER_HINT}

    if not os.getenv('ALIPAY_APP_ID'):
        return {
            "status": "stub",
            "error": f"credential_missing: env {ENV_VAR!r} not set",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
            "out_trade_no": str(out_trade_no_value)[:80],
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
