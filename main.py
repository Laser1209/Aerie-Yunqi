"""Aerie · 云栖 v9.0 — Python backend entry point.

Launched by Electron via `python main.py`.
Starts logging → config → Companion → API server → event loop.
"""

from __future__ import annotations
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _setup_logging() -> None:
    log_dir = Path(os.getenv("LOG_DIR", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "main.log", encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )


async def _main() -> None:
    _setup_logging()
    logger = logging.getLogger("aerie.main")

    # Load .env
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    from config.persona_loader import load_settings, get_http_config
    from core.companion import Companion
    from core.api_server import start_api

    settings = load_settings()
    http_cfg = get_http_config()
    host = http_cfg.get("host", "127.0.0.1")
    port = int(http_cfg.get("port", 7890))

    companion = Companion(settings=settings)
    await companion.start()

    runner = await start_api(host=host, port=port)
    logger.info("[READY] Aerie ready at http://%s:%d", host, port)

    stop_event = asyncio.Event()

    def _on_signal(*_):
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except Exception:
            pass

    try:
        await stop_event.wait()
    finally:
        logger.info("shutting down...")
        await companion.stop()
        await runner.cleanup()
        logger.info("bye")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
