"""SiliconFlow diagnostic: try multiple models to isolate key vs model issue."""
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

key = os.environ["SILICONFLOW_API_KEY"]
url = os.environ.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
client = AsyncOpenAI(api_key=key, base_url=url, timeout=15.0)

# First: list user's available models (lightweight, often reveals account state)
async def list_models():
    print("=== Step 1: GET /v1/models (account info) ===", flush=True)
    try:
        models = await client.models.list()
        ids = [m.id for m in models.data[:10]] if hasattr(models, "data") else []
        print(f"OK  account active. {len(ids)}+ models visible. Sample: {ids[:5]}", flush=True)
    except Exception as e:
        print(f"FAIL  {type(e).__name__}: {str(e)[:200]}", flush=True)

# Second: try a known-cheap model with minimal params
async def try_completions():
    print("\n=== Step 2: chat.completions.create on Qwen2.5-7B ===", flush=True)
    t0 = time.perf_counter()
    try:
        resp = await client.chat.completions.create(
            model="Qwen/Qwen2.5-7B-Instruct",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=4,
            temperature=0.0,
        )
        dt = time.perf_counter() - t0
        content = (resp.choices[0].message.content or "").strip()
        print(f"OK  latency={dt:.2f}s  reply='{content[:30]}'", flush=True)
    except Exception as e:
        dt = time.perf_counter() - t0
        print(f"FAIL  latency={dt:.2f}s  {type(e).__name__}: {str(e)[:300]}", flush=True)

async def main():
    await list_models()
    await try_completions()

asyncio.run(main())
