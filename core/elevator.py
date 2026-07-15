"""Aerie · 云栖 v9.0 — UAC elevation helper."""

from __future__ import annotations

import ctypes
import logging
import sys
from typing import Optional


logger = logging.getLogger(__name__)


def is_admin() -> bool:
    """Return True if current process has admin rights."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run_as_admin(command: str, params: str = "") -> Optional[int]:
    """Re-launch the given command with UAC elevation.

    Returns the new PID if successful, else None.
    """
    if sys.platform != "win32":
        logger.warning("run_as_admin is Windows-only")
        return None
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", command, params, None, 0
        )
        if rc <= 32:
            logger.error("ShellExecuteW failed: %s", rc)
            return None
        return int(rc)
    except Exception as e:
        logger.error("run_as_admin failed: %s", e)
        return None
