"""用真正的 settings.yaml 跑 startup_check"""
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import dotenv
dotenv.load_dotenv(PROJECT_ROOT / ".env")

import yaml
with open(PROJECT_ROOT / "config" / "settings.yaml", "r", encoding="utf-8") as f:
    settings = yaml.safe_load(f)

# 解析 ${VAR:default} 引用
import re
import os
def replace_env(m):
    var, default = m.group(1), m.group(2) or ""
    return os.getenv(var, default)
content = re.sub(r"\$\{(\w+):?([^}]*)\}", replace_env, open(PROJECT_ROOT / "config" / "settings.yaml", "r", encoding="utf-8").read())
config = yaml.safe_load(content)

from loguru import logger
logger.remove()
logger.add(lambda m: print(m, flush=True), level='DEBUG', format='{level} {message}')

print("=== 加载配置 ===")
print(f"primary: {config['ai']['primary']}")
print(f"fallback: {config['ai']['fallback']}")

from core.brain import AIBrain
b = AIBrain(config['ai'])
print("\n=== 启动期校验 ===")
asyncio.run(b.startup_check())
print('\n=== Done ===')
