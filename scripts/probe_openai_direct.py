"""Direct OpenAI probe with explicit flush."""
import os
import sys
import time
from pathlib import Path

# Force load .env
ENV_PATH = Path(r"e:\Agent_reply\.env")
if ENV_PATH.exists():
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ[k.strip()] = v.strip()

key = os.environ.get("OPENAI_API_KEY", "")
url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

print(f"OPENAI_API_KEY length: {len(key)}", flush=True)
print(f"OPENAI_BASE_URL: {url}", flush=True)
print(f"OPENAI_MODEL: {model}", flush=True)
print(f"Key tail: ...{key[-6:]}", flush=True)
print(flush=True)

if not key or key.startswith("your_"):
    print("SKIP: placeholder", flush=True)
    sys.exit(0)

print("Importing openai...", flush=True)
try:
    from openai import AsyncOpenAI
except Exception as e:
    print(f"FAIL: import error: {e}", flush=True)
    sys.exit(1)

print("Creating client...", flush=True)
client = AsyncOpenAI(api_key=key, base_url=url, timeout=20.0)

import asyncio

async def go():
    print("Sending ping...", flush=True)
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
        print(f"PASS  latency={dt:.2f}s  reply='{content[:30]}'", flush=True)
    except Exception as e:
        dt = time.perf_counter() - t0
        print(f"FAIL  latency={dt:.2f}s  {type(e).__name__}: {str(e)[:200]}", flush=True)

asyncio.run(go())
