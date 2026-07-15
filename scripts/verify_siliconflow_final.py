"""Final config verification: SiliconFlow with gemma-4-26B-A4B-it."""
import os
import asyncio
import time
from pathlib import Path

for line in Path(r"e:\Agent_reply\.env").read_text(encoding="utf-8").splitlines():
    s = line.strip()
    if s and not s.startswith("#") and "=" in s:
        k, v = s.split("=", 1)
        os.environ[k.strip()] = v.strip()

from openai import AsyncOpenAI

key = os.environ["SILICONFLOW_API_KEY"]
url = os.environ["SILICONFLOW_BASE_URL"]
model = os.environ["SILICONFLOW_MODEL"]
print("Final config check:")
print(f"  base_url = {url}")
print(f"  model    = {model}")
print(f"  key tail = ...{key[-6:]}")
print()

async def go():
    client = AsyncOpenAI(api_key=key, base_url=url, timeout=30.0)
    t0 = time.perf_counter()
    try:
        r = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Say hi in 3 words."}],
            max_tokens=20,
            temperature=0.0,
        )
        dt = time.perf_counter() - t0
        c = (r.choices[0].message.content or "").strip()
        u = r.usage
        print(f"PASS  {dt:.2f}s  tokens={u.prompt_tokens}/{u.completion_tokens}")
        print(f"reply: {c}")
    except Exception as e:
        print(f"FAIL  {type(e).__name__}: {str(e)[:200]}")

asyncio.run(go())
