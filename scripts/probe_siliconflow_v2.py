"""Probe SiliconFlow chat completion with .com domain, write to log file."""
import os
import asyncio
import time
from pathlib import Path

LOG = Path(r"e:\Agent_reply\siliconflow_probe.log")
LOG.write_text("", encoding="utf-8")

def log(msg):
    LOG.write_text(LOG.read_text(encoding="utf-8") + msg + "\n", encoding="utf-8")
    print(msg, flush=True)

# Load .env
for line in Path(r"e:\Agent_reply\.env").read_text(encoding="utf-8").splitlines():
    s = line.strip()
    if s and not s.startswith("#") and "=" in s:
        k, v = s.split("=", 1)
        os.environ[k.strip()] = v.strip()

key = os.environ["SILICONFLOW_API_KEY"]
url = os.environ["SILICONFLOW_BASE_URL"]
model = os.environ["SILICONFLOW_MODEL"]
log(f"[BOOT] base_url={url}")
log(f"[BOOT] model={model}")
log(f"[BOOT] key tail=...{key[-6:]}")

from openai import AsyncOpenAI
client = AsyncOpenAI(api_key=key, base_url=url, timeout=60.0)

async def go():
    log("\n[CHAT] sending...")
    t0 = time.perf_counter()
    try:
        r = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Say hi in 5 words."}],
            max_tokens=20,
            temperature=0.0,
        )
        dt = time.perf_counter() - t0
        c = (r.choices[0].message.content or "").strip()
        u = r.usage
        log(f"[CHAT] PASS  latency={dt:.2f}s  tokens={u.prompt_tokens}/{u.completion_tokens}")
        log(f"[CHAT] reply: {c[:200]}")
    except Exception as e:
        dt = time.perf_counter() - t0
        log(f"[CHAT] FAIL  latency={dt:.2f}s  {type(e).__name__}: {str(e)[:400]}")
    log("[DONE]")

asyncio.run(go())
log(f"Log written to: {LOG}")
