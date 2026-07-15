"""Try multiple SiliconFlow models to find one that works."""
import os
import asyncio
import time
from pathlib import Path

LOG = Path(r"e:\Agent_reply\siliconflow_multi.log")
LOG.write_text("", encoding="utf-8")

def log(msg):
    line = msg
    LOG.write_text(LOG.read_text(encoding="utf-8") + line + "\n", encoding="utf-8")
    print(line, flush=True)

# Load .env
for line in Path(r"e:\Agent_reply\.env").read_text(encoding="utf-8").splitlines():
    s = line.strip()
    if s and not s.startswith("#") and "=" in s:
        k, v = s.split("=", 1)
        os.environ[k.strip()] = v.strip()

key = os.environ["SILICONFLOW_API_KEY"]
url = os.environ["SILICONFLOW_BASE_URL"]
log(f"base_url: {url}")
log(f"key tail: ...{key[-6:]}")

from openai import AsyncOpenAI
client = AsyncOpenAI(api_key=key, base_url=url, timeout=45.0)

# Models to try, in order of expected reliability
CANDIDATES = [
    "google/gemma-4-31B-it",          # what user wants
    "google/gemma-4-26B-A4B-it",      # similar but smaller
    "Qwen/Qwen2.5-7B-Instruct",       # very common, cheap
    "Qwen/Qwen3-32B",                 # newer Qwen
    "deepseek-ai/DeepSeek-V3.2",      # popular model
]

async def try_model(model: str) -> str:
    log(f"\n--- {model} ---")
    t0 = time.perf_counter()
    try:
        r = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=4,
            temperature=0.0,
        )
        dt = time.perf_counter() - t0
        c = (r.choices[0].message.content or "").strip()
        u = r.usage
        log(f"  PASS  {dt:.2f}s  prompt={u.prompt_tokens}  reply='{c[:40]}'")
        return "PASS"
    except Exception as e:
        dt = time.perf_counter() - t0
        log(f"  FAIL  {dt:.2f}s  {type(e).__name__}: {str(e)[:200]}")
        return "FAIL"

async def main():
    for m in CANDIDATES:
        await try_model(m)
    log("\n[END]")

asyncio.run(main())
