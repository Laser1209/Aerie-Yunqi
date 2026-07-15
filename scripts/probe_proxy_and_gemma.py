"""Probe OpenAI (via codexgood proxy) and SiliconFlow (with Gemma model)."""
import os
import asyncio
import time
from pathlib import Path

ENV_PATH = Path(r"e:\Agent_reply\.env")
for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
    s = line.strip()
    if not s or s.startswith("#") or "=" not in s:
        continue
    k, v = s.split("=", 1)
    os.environ[k.strip()] = v.strip()

from openai import AsyncOpenAI


async def probe_openai():
    print("=" * 60)
    print("OPENAI via proxy api.codexgood.com, model gpt-5.5")
    print("=" * 60)
    key = os.environ["OPENAI_API_KEY"]
    url = os.environ["OPENAI_BASE_URL"]
    model = os.environ["OPENAI_MODEL"]
    masked = key[:6] + "*" * (len(key) - 10) + key[-4:]
    print(f"  base_url : {url}")
    print(f"  model    : {model}")
    print(f"  key tail : ...{key[-6:]}")
    print("  sending ping...", flush=True)
    client = AsyncOpenAI(api_key=key, base_url=url, timeout=30.0)
    t0 = time.perf_counter()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Say hello in one sentence."}],
            max_tokens=40,
            temperature=0.0,
        )
        dt = time.perf_counter() - t0
        content = (resp.choices[0].message.content or "").strip()
        print(f"  PASS  latency={dt:.2f}s")
        print(f"  reply : {content[:200]}")
    except Exception as e:
        dt = time.perf_counter() - t0
        print(f"  FAIL  latency={dt:.2f}s  {type(e).__name__}: {str(e)[:300]}")


async def probe_siliconflow_gemma():
    print()
    print("=" * 60)
    print("SILICONFLOW model google/gemma-4-31B-it")
    print("=" * 60)
    key = os.environ["SILICONFLOW_API_KEY"]
    url = os.environ["SILICONFLOW_BASE_URL"]
    model = os.environ["SILICONFLOW_MODEL"]
    print(f"  base_url : {url}")
    print(f"  model    : {model}")
    print(f"  key tail : ...{key[-6:]}")
    print("  sending ping...", flush=True)
    client = AsyncOpenAI(api_key=key, base_url=url, timeout=30.0)
    t0 = time.perf_counter()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=4,
            temperature=0.0,
        )
        dt = time.perf_counter() - t0
        content = (resp.choices[0].message.content or "").strip()
        print(f"  PASS  latency={dt:.2f}s")
        print(f"  reply : {content[:200]}")
    except Exception as e:
        dt = time.perf_counter() - t0
        print(f"  FAIL  latency={dt:.2f}s  {type(e).__name__}: {str(e)[:300]}")


async def main():
    await probe_openai()
    await probe_siliconflow_gemma()


asyncio.run(main())
