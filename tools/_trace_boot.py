"""启动探针：完整追踪 _main 每个阶段并打印 traceback。
直接运行 `py tools/_trace_boot.py` 即可，完全复刻 main.py 的启动流程但给每个关键步骤加上进入/退出标记 + 完整异常堆栈。
"""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(str(PROJECT_ROOT))

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

PHASE_FP = sys.stderr

def phase(n: int, name: str):
    """给一段代码包上进入/退出 + 完整 traceback 的上下文管理器装饰器辅助函数。
    这里直接做成装饰器工厂比较方便。"""
    def decorator(fn):
        def wrapper(*a, **kw):
            print(f"\n[TRACE >>>] phase {n:02d} — ENTER  {name}", file=PHASE_FP, flush=True)
            t0 = time.time()
            try:
                r = fn(*a, **kw)
                dt = (time.time() - t0) * 1000
                print(f"[TRACE <<<] phase {n:02d} — LEAVE  {name}  ({dt:.0f} ms)", file=PHASE_FP, flush=True)
                return r
            except Exception as e:
                dt = (time.time() - t0) * 1000
                print(f"\n[TRACE !!!] phase {n:02d} — CRASH  {name}  after {dt:.0f} ms", file=PHASE_FP, flush=True)
                print(f"  Exception type : {type(e).__name__}", file=PHASE_FP, flush=True)
                print(f"  Exception str  : {e}", file=PHASE_FP, flush=True)
                print("----- Full traceback -----", file=PHASE_FP, flush=True)
                traceback.print_exc(file=PHASE_FP)
                PHASE_FP.flush()
                raise
        async def awrapper(*a, **kw):
            print(f"\n[TRACE >>>] phase {n:02d} — ENTER  {name}", file=PHASE_FP, flush=True)
            t0 = time.time()
            try:
                r = await fn(*a, **kw)
                dt = (time.time() - t0) * 1000
                print(f"[TRACE <<<] phase {n:02d} — LEAVE  {name}  ({dt:.0f} ms)", file=PHASE_FP, flush=True)
                return r
            except Exception as e:
                dt = (time.time() - t0) * 1000
                print(f"\n[TRACE !!!] phase {n:02d} — CRASH  {name}  after {dt:.0f} ms", file=PHASE_FP, flush=True)
                print(f"  Exception type : {type(e).__name__}", file=PHASE_FP, flush=True)
                print(f"  Exception str  : {e}", file=PHASE_FP, flush=True)
                print("----- Full traceback -----", file=PHASE_FP, flush=True)
                traceback.print_exc(file=PHASE_FP)
                PHASE_FP.flush()
                raise
        if asyncio.iscoroutinefunction(fn):
            return awrapper
        return wrapper
    return decorator


# ========= 分阶段重写 _main =========

@phase(1, "_setup_logging()")
def p1_setup_logging():
    log_dir = Path(os.getenv("LOG_DIR", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    import logging
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "main.log", encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )
    logger = logging.getLogger("aerie.main")
    logger.info(
        "===========================================\n"
        "  Aerie · 云栖 backend starting (trace mode)\n"
        "  git commit : %s\n"
        "  started at : %s\n"
        "  pid        : %d\n"
        "===========================================",
        GIT_COMMIT, PROCESS_START_ISO, os.getpid(),
    )
    return logger

@phase(2, "load .env via dotenv")
def p2_load_dotenv():
    try:
        from dotenv import load_dotenv
        configured_env = os.getenv("AERIE_ENV_FILE", "").strip()
        load_dotenv(configured_env or None)
    except Exception as e:
        # 非致命，只记录
        print(f"  (non-fatal dotenv err: {type(e).__name__}: {e})", file=PHASE_FP, flush=True)

@phase(3, "import persona_loader modules + load_settings() + get_http_config()")
def p3_load_settings():
    from config.persona_loader import load_settings, get_http_config
    settings = load_settings()
    http_cfg = get_http_config()
    host = http_cfg.get("host", "127.0.0.1")
    port = int(os.getenv("AERIE_BACKEND_PORT") or http_cfg.get("port", 7890))
    return settings, host, port

@phase(4, "RuntimeConfigService + Companion.__init__()")
def p4_new_companion(settings):
    from core.companion import Companion
    from core.paths import data_dir
    from core.runtime_config import RuntimeConfigService
    runtime_config_service = RuntimeConfigService(
        state_path=data_dir() / "runtime_config.json",
    )
    companion = Companion(
        settings=settings,
        runtime_config_service=runtime_config_service,
    )
    return companion, runtime_config_service

@phase(5, "await companion.start()")
async def p5_start_companion(companion):
    await companion.start()

@phase(6, "config hot-reloader start()")
async def p6_hotreload(companion):
    from config.persona_loader import (
        get_config_reloader,
        load_settings,
        load_behavior_config,
        load_proactive_config,
    )
    reloader = get_config_reloader()

    def _reload_settings():
        try:
            companion.settings = load_settings()
        except Exception:
            traceback.print_exc(file=PHASE_FP)

    def _reload_behavior():
        try:
            companion.behavior_cfg = load_behavior_config()
            if hasattr(companion, "emotion") and companion.emotion:
                companion.emotion.update_behavior_config(load_behavior_config())
        except Exception:
            traceback.print_exc(file=PHASE_FP)

    def _reload_proactive():
        try:
            if hasattr(companion, "push_scheduler") and companion.push_scheduler:
                import asyncio as _a
                coro = companion.push_scheduler.reload_config(load_proactive_config())
                if _a.iscoroutine(coro):
                    _a.create_task(coro)
        except Exception:
            traceback.print_exc(file=PHASE_FP)

    reloader.subscribe("settings.yaml", _reload_settings)
    reloader.subscribe("persona_behavior.yaml", _reload_behavior)
    reloader.subscribe("proactive.yaml", _reload_proactive)
    await reloader.start()

@phase(7, "await start_api(host, port)")
async def p7_start_api(host, port):
    from core.api_server import start_api
    runner = await start_api(host=host, port=port)
    return runner

@phase(8, "optional mobile gateway")
async def p8_mobile_gateway(logger):
    from core.mobile_gateway import is_mobile_gateway_enabled, start_mobile_gateway
    try:
        if not is_mobile_gateway_enabled():
            return None
        runner = await start_mobile_gateway()
        logger.info("[MOBILE_GATEWAY_READY] Aerie mobile gateway is ready")
        return runner
    except Exception:
        logger.exception("[MOBILE_GATEWAY_UNAVAILABLE] mobile gateway did not start")
        return None


async def traced_main():
    logger = p1_setup_logging()
    p2_load_dotenv()
    settings, host, port = p3_load_settings()
    companion, rcs = p4_new_companion(settings)
    await p5_start_companion(companion)
    try:
        await p6_hotreload(companion)
    except Exception:
        traceback.print_exc(file=PHASE_FP)
    runner = await p7_start_api(host, port)
    logger.info("[READY] Aerie ready at http://%s:%d", host, port)
    mobile_runner = await p8_mobile_gateway(logger)
    logger.info("\n============= 所有阶段完成，启动成功！等待 2s 后自动退出 ============= ")
    await asyncio.sleep(2)
    try:
        if mobile_runner is not None:
            await mobile_runner.cleanup()
        await runner.cleanup()
        await companion.stop()
    except Exception:
        pass
    logger.info("traced_main normal exit")


if __name__ == "__main__":
    print("\n" + "=" * 72, file=PHASE_FP, flush=True)
    print("[TRACE TOP] Launching full boot trace...", file=PHASE_FP, flush=True)
    print(f"  cwd       : {os.getcwd()}", file=PHASE_FP, flush=True)
    print(f"  py exe    : {sys.executable}", file=PHASE_FP, flush=True)
    print(f"  py version: {sys.version}", file=PHASE_FP, flush=True)
    print(f"  env LOG_DIR       : {os.getenv('LOG_DIR')}", file=PHASE_FP, flush=True)
    print(f"  env AERIE_DATA_DIR: {os.getenv('AERIE_DATA_DIR')}", file=PHASE_FP, flush=True)
    print(f"  env AERIE_DB_PATH : {os.getenv('AERIE_DB_PATH')}", file=PHASE_FP, flush=True)
    print("=" * 72, file=PHASE_FP, flush=True)
    try:
        asyncio.run(traced_main())
    except KeyboardInterrupt:
        pass
    except Exception as _e_top:
        print("\n[TRACE TOP-level EXCEPTION] Uncaught at event loop:", file=PHASE_FP, flush=True)
        print(f"  type={type(_e_top).__name__}  str={_e_top}", file=PHASE_FP, flush=True)
        traceback.print_exc(file=PHASE_FP)
        PHASE_FP.flush()
        sys.exit(88)
    finally:
        print("\n[TRACE BOTTOM] traced boot run finished.", file=PHASE_FP, flush=True)
