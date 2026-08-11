"""Boot trace probe.

Replicates the imports inside main._main() so that `python -X importtime`
can measure the real heavy-module import cost (chromadb, sqlalchemy,
fastapi, onnxruntime, etc.) without actually starting the backend.

Usage:
    python -X importtime scripts/boot_trace_probe.py 2> importtime.log
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Replicate main._main() import sequence (main.py:100-112)
try:
    from dotenv import load_dotenv

    configured_env = os.getenv("AERIE_ENV_FILE", "").strip()
    load_dotenv(configured_env or None)
except Exception:
    pass

from config.persona_loader import load_settings, get_http_config  # noqa: E402
from core.companion import Companion  # noqa: E402
from core.api_server import start_api  # noqa: E402
from core.paths import data_dir  # noqa: E402
from core.runtime_config import RuntimeConfigService  # noqa: E402

# Touch a few more heavy modules that Companion.__init__ would pull in
# lazily, so we can see their import cost in the trace.
try:
    from core.knowledge_indexer import resolve_embedding_fn  # noqa: F401
except Exception:
    pass

try:
    from core.memory.layered_memory import LayeredMemory  # noqa: F401
except Exception:
    pass

try:
    from communication.qq_client import QQClient  # noqa: F401
except Exception:
    pass

print("[BOOT_TRACE] All heavy modules imported successfully")
