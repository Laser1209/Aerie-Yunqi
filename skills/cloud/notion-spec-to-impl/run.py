"""notion-spec-to-impl skill (cloud) — Notion Spec→任务 / Spec to impl.

Block-5B scaffold. Cloud-based skill that requires external
credentials (env: `NOTION_TOKEN`). When the env var is
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
ENV_VAR = 'NOTION_TOKEN'


def run(args: dict) -> dict:
    """Skill entry point. ``args`` is a free-form dict; key: 'spec_url'."""
    args = args or {}
    spec_url_value = args.get("spec_url")
    if not spec_url_value:
        return {"error": "missing spec_url", "provider_hint": PROVIDER_HINT}

    if not os.getenv('NOTION_TOKEN'):
        return {
            "status": "stub",
            "error": f"credential_missing: env {ENV_VAR!r} not set",
            "provider_hint": PROVIDER_HINT,
            "read_only": READ_ONLY,
            "spec_url": str(spec_url_value)[:80],
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
