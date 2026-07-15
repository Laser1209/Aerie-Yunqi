"""Aerie · 云栖 v9.0 — Windows Task Scheduler wrapper.

Creates / lists / removes scheduled tasks via PowerShell (hidden window).
"""

from __future__ import annotations

import logging
import subprocess
from typing import Optional


logger = logging.getLogger(__name__)


def _run_powershell(script: str) -> tuple[int, str, str]:
    """Run a PowerShell snippet with hidden window, return (rc, stdout, stderr)."""
    try:
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            creationflags=creationflags,
            timeout=30,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as e:
        logger.error("powershell failed: %s", e)
        return -1, "", str(e)


def create_daily_task(name: str, time_str: str, command: str, args: str = "") -> bool:
    """Create a daily task that runs at the given HH:MM."""
    hour, minute = time_str.split(":")
    full_cmd = f'"{command}"' + (f' "{args}"' if args else "")
    script = (
        f"$action = New-ScheduledTaskAction -Execute '{command}' "
        f"{('-Argument ' + chr(34) + args + chr(34)) if args else ''}; "
        f"$trigger = New-ScheduledTaskTrigger -Daily -At '{hour}:{minute}'; "
        f"Register-ScheduledTask -TaskName '{name}' "
        f"-Action $action -Trigger $trigger -Description 'Aerie auto-scheduled task' "
        f"-Force | Out-Null; Write-Host OK"
    )
    rc, out, err = _run_powershell(script)
    if rc == 0 and "OK" in out:
        return True
    logger.warning("create_daily_task failed: %s / %s", out, err)
    return False


def remove_task(name: str) -> bool:
    script = (
        f"Unregister-ScheduledTask -TaskName '{name}' -Confirm:$false | Out-Null; "
        f"Write-Host OK"
    )
    rc, out, err = _run_powershell(script)
    return rc == 0 and "OK" in out


def list_tasks() -> list[dict]:
    script = (
        "Get-ScheduledTask | Where-Object { $_.TaskName -like 'Aerie*' } | "
        "ForEach-Object { Write-Host (\"{0}|{1}\" -f $_.TaskName, $_.State) }"
    )
    rc, out, err = _run_powershell(script)
    if rc != 0:
        return []
    tasks: list[dict] = []
    for line in out.splitlines():
        if "|" in line:
            name, state = line.split("|", 1)
            tasks.append({"name": name.strip(), "state": state.strip()})
    return tasks
