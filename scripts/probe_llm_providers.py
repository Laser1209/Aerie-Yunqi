"""Aerie · 云栖 v9.0 — LLM Provider Connectivity Probe

Run this script to verify each provider's API key works.
It performs a tiny "ping" prompt (max_tokens=4) and reports pass/fail.

Usage:
    python scripts/probe_llm_providers.py
    python scripts/probe_llm_providers.py --provider deepseek
    python scripts/probe_llm_providers.py --provider openai
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

# Load .env manually (no extra dependency on python-dotenv).
# Use direct assignment so .env values ALWAYS take precedence over any
# pre-existing shell environment variables — we want to validate the keys
# that are actually written to .env, not whatever may be lingering in the shell.
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ[k.strip()] = v.strip()


PROVIDERS = {
    "deepseek":    ("DEEPSEEK_API_KEY",    "DEEPSEEK_BASE_URL",    "deepseek-chat"),
    "qwen":        ("DASHSCOPE_API_KEY",   "QWEN_BASE_URL",        "qwen-plus"),
    "gemini":      ("GEMINI_API_KEY",      "GEMINI_BASE_URL",      "gemini-2.0-flash-exp"),
    "minimax":     ("MINIMAX_API_KEY",     "MINIMAX_BASE_URL",     "MiniMax-M3"),
    "bigmodel":    ("BIGMODEL_API_KEY",    "BIGMODEL_BASE_URL",    "glm-4-plus"),
    "siliconflow": ("SILICONFLOW_API_KEY", "SILICONFLOW_BASE_URL", "google/gemma-4-26B-A4B-it"),
    "openai":      ("OPENAI_API_KEY",      "OPENAI_BASE_URL",      "gpt-5.5"),
}


async def probe_one(name: str, key_env: str, url_env: str, model: str) -> tuple[str, str, float, str]:
    """Send a tiny ping to one provider. Returns (status, detail, latency_s, masked_key)."""
    api_key = os.environ.get(key_env, "").strip()
    base_url = os.environ.get(url_env, "").strip()

    if not api_key or api_key.startswith("your_"):
        return "SKIP", f"placeholder value in {key_env}", 0.0, "<empty>"

    masked = api_key[:6] + "*" * (len(api_key) - 10) + api_key[-4:]
    t0 = time.perf_counter()
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=15.0)
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=4,
            temperature=0.0,
        )
        latency = time.perf_counter() - t0
        content = (resp.choices[0].message.content or "").strip()
        return "PASS", f"reply='{content[:24]}' model={model}", latency, masked
    except Exception as e:
        latency = time.perf_counter() - t0
        return "FAIL", f"{type(e).__name__}: {str(e)[:120]}", latency, masked


async def main(target: str | None) -> int:
    items = [(name, *cfg) for name, cfg in PROVIDERS.items() if target is None or name == target]
    if not items:
        print(f"Unknown provider: {target}. Available: {', '.join(PROVIDERS)}")
        return 2

    print(f"Probing {len(items)} provider(s)...\n")
    rc = 0
    for name, key_env, url_env, model in items:
        status, detail, latency, masked = await probe_one(name, key_env, url_env, model)
        if status == "PASS":
            mark, color = "✓", "\033[32m"
        elif status == "SKIP":
            mark, color = "○", "\033[33m"
        else:
            mark, color = "✗", "\033[31m"
            rc = 1
        reset = "\033[0m"
        print(f"{color}{mark}{reset} [{name:12s}] {status}  latency={latency:5.2f}s  key={masked}")
        print(f"              {detail}")

    print()
    print("Note: PASS = auth+network ok; SKIP = placeholder; FAIL = see detail above")
    return rc


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=list(PROVIDERS), default=None,
                        help="Probe only one provider (default: all)")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.provider)))
