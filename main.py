"""Aerie Companion v0.3.2-beta.0903-A05 - Python backend entry point.

Launched by Electron via `python main.py`.
Starts logging → config → Companion → API server → event loop.
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# R6.6: process-level constants for the stale-code detection banner and
# the /api/health endpoint. These are read from `core.api_server` via
# `getattr(main, ...)` so they must exist at import time.
PROCESS_START_TIME = time.time()
PROCESS_START_ISO = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(PROCESS_START_TIME))
BACKEND_INSTANCE_ID = os.getenv("AERIE_BACKEND_INSTANCE_ID", "").strip()


def _git_commit_short() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(PROJECT_ROOT),
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
        return out.decode("utf-8", errors="ignore").strip() or "unknown"
    except Exception:
        return "unknown"


GIT_COMMIT = _git_commit_short()


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


async def _start_optional_mobile_gateway(logger: logging.Logger):
    """Start the separate mobile boundary only when it is explicitly enabled."""

    from core.mobile_gateway import (
        is_mobile_gateway_enabled,
        start_mobile_gateway,
    )

    try:
        if not is_mobile_gateway_enabled():
            return None
        runner = await start_mobile_gateway()
        logger.info("[MOBILE_GATEWAY_READY] Aerie mobile gateway is ready")
        return runner
    except (Exception, SystemExit):
        # The desktop backend remains local and usable if the optional mobile
        # boundary cannot bind.  The failure is explicit in the local logs.
        # SystemExit is raised by uvicorn.sys.exit(STARTUP_FAILURE) on bind
        # failure — it inherits from BaseException, not Exception, so a plain
        # `except Exception` would let it kill the whole backend.
        logger.exception("[MOBILE_GATEWAY_UNAVAILABLE] mobile gateway did not start")
        return None


async def _main() -> None:
    _setup_logging()
    logger = logging.getLogger("aerie.main")

    # R6.6: print a one-shot startup banner that includes the git commit
    # and process start time. This makes it obvious in the logs whether
    # the user is running the freshly-edited code or a stale binary.
    logger.info(
        "===========================================\n"
        "  Aerie · 云栖 backend starting\n"
        "  git commit : %s\n"
        "  started at : %s\n"
        "  pid        : %d\n"
        "===========================================",
        GIT_COMMIT, PROCESS_START_ISO, os.getpid(),
    )

    # Load .env（用户配置优先），再兜底加载预置中转门卡（不覆盖用户值）
    try:
        from dotenv import load_dotenv
        configured_env = os.getenv("AERIE_ENV_FILE", "").strip()
        load_dotenv(configured_env or None)
        from pathlib import Path
        preset = Path(__file__).resolve().parent / "config" / "relay_preset.env"
        if preset.exists():
            load_dotenv(preset, override=False)
    except Exception:
        pass

    # Commercial/runtime entry points use a neutral built-in persona. Existing
    # user profiles keep their active legacy persona (including private Ita)
    # through data/personas/_active.json and can switch explicitly.
    os.environ.setdefault("AERIE_DEFAULT_PERSONA_ID", "aerie_default")

    # 硬件指纹护照：生成 64 字符码并写快照，便于后期判断硬件对软件的影响。
    try:
        from core.hardware_passport import generate_passport
        from core.paths import data_dir as _passport_data_dir

        passport = generate_passport()
        logger.info("[HARDWARE_PASSPORT] code=%s", passport["code"])
        try:
            snapshot_path = _passport_data_dir() / "hardware_passport.json"
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text(
                json.dumps(passport["snapshot"], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.warning("[HARDWARE_PASSPORT] snapshot write failed", exc_info=True)
    except Exception:
        logger.warning("[HARDWARE_PASSPORT] generation failed", exc_info=True)

    from config.persona_loader import load_settings, get_http_config
    from core.companion import Companion
    from core.api_server import start_api
    from core.paths import data_dir
    from core.runtime_config import RuntimeConfigService
    from core.startup_progress import mark_step

    settings = load_settings()
    http_cfg = get_http_config()
    # 安全门（P4 前置）：7890 强制回环绑定——管理 API（/api/admin/*）可删除
    # 记忆/向量，绝不允许暴露到局域网（即使配置写了 0.0.0.0 也忽略）。
    host = "127.0.0.1"
    port = int(os.getenv("AERIE_BACKEND_PORT") or http_cfg.get("port", 7890))

    runtime_config_service = RuntimeConfigService(
        state_path=data_dir() / "runtime_config.json",
    )
    mark_step("bootstrap", "done", "配置与依赖就绪")
    mark_step("companion", "running", "初始化组件(DB/QQ/世界模拟/DSH)")
    companion = Companion(
        settings=settings,
        runtime_config_service=runtime_config_service,
    )
    await companion.start()
    mark_step("companion", "done", "组件初始化完成")

    # v9.1: config hot-reloader — watches config/ YAML files and
    # pushes changes to interested modules without a full restart.
    try:
        from config.persona_loader import (
            get_config_reloader,
            load_settings,
            load_behavior_config,
            load_proactive_config,
        )
        reloader = get_config_reloader()

        def _reload_settings() -> None:
            try:
                new_settings = load_settings()
                companion.settings = new_settings
                logger.info("auto-reloaded settings.yaml")
            except Exception:
                logger.exception("auto-reload settings.yaml failed")

        def _reload_behavior() -> None:
            try:
                new_behavior = load_behavior_config()
                companion.behavior_cfg = new_behavior
                if hasattr(companion, "emotion") and companion.emotion:
                    companion.emotion.update_behavior_config(new_behavior)
                logger.info("auto-reloaded persona_behavior.yaml")
            except Exception:
                logger.exception("auto-reload persona_behavior.yaml failed")

        def _reload_proactive() -> None:
            try:
                if not hasattr(companion, "push_scheduler") or not companion.push_scheduler:
                    return
                new_proactive = load_proactive_config()
                import asyncio as _asyncio
                coro = companion.push_scheduler.reload_config(new_proactive)
                if _asyncio.iscoroutine(coro):
                    _asyncio.create_task(coro)
                logger.info("auto-reloaded proactive.yaml")
            except Exception:
                logger.exception("auto-reload proactive.yaml failed")

        reloader.subscribe("settings.yaml", _reload_settings)
        reloader.subscribe("persona_behavior.yaml", _reload_behavior)
        reloader.subscribe("proactive.yaml", _reload_proactive)
        await reloader.start()
        logger.info("config hot-reloader started (watching 3 files)")
    except Exception:
        logger.exception("config hot-reloader init failed, continuing without auto-reload")

    runner = await start_api(host=host, port=port)
    mark_step("api", "done", "HTTP API 7890")
    logger.info("[READY] Aerie ready at http://%s:%d", host, port)

    mobile_runner = await _start_optional_mobile_gateway(logger)

    # Diagnostics telemetry: cumulative runtime tracking + milestone packaging.
    # Runs independently of chat/QQ; a failure here must not take down the app.
    telemetry_runner = None
    try:
        from core.telemetry import start_telemetry
        telemetry_runner = start_telemetry()
        logger.info("[TELEMETRY_READY] diagnostics telemetry scheduler started")
    except Exception:
        logger.exception("[TELEMETRY_UNAVAILABLE] diagnostics telemetry did not start")

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
        if mobile_runner is not None:
            try:
                await mobile_runner.cleanup()
                logger.info("mobile gateway stopped")
            except Exception:
                logger.exception("mobile gateway shutdown failed")
        try:
            from config.persona_loader import get_config_reloader
            reloader = get_config_reloader()
            await reloader.stop()
            logger.info("config hot-reloader stopped")
        except Exception:
            pass
        if telemetry_runner is not None:
            try:
                await telemetry_runner.cleanup()
                logger.info("diagnostics telemetry stopped")
            except Exception:
                logger.exception("diagnostics telemetry shutdown failed")
        await companion.stop()
        await runner.cleanup()
        logger.info("bye")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
