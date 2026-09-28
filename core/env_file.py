"""本地 ``.env`` 文件的读写。

设置页保存厂商凭据时要落盘到 ``.env``；首次启动时 ``core.ai_services`` 也会读它
做内置厂商的 seed。读写保持"注释与顺序原样保留"的语义，手写注释不会被冲掉。

注意：``.env`` 在本项目里是**派生镜像**而非真源——厂商配置的真源是
``data/aerie.db`` 的 ``ai_providers`` 表。保留回写是因为 ``llm_caller``、
``voice``、``qq_media`` 等旁路仍直接读 ``os.environ``。
"""

from __future__ import annotations

from pathlib import Path


def env_file_path() -> Path:
    """Return path to .env file (repository root, next to main.py)."""
    return Path(__file__).resolve().parent.parent / ".env"


def read_env_file() -> dict[str, str]:
    """Parse .env file into a dict. Returns empty dict if file doesn't exist."""
    env_path = env_file_path()
    result: dict[str, str] = {}
    if not env_path.exists():
        return result
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        result[k.strip()] = v.strip()
    return result


def write_env_file(data: dict[str, str]) -> None:
    """Write env dict back to .env file, preserving comments and order where possible."""
    env_path = env_file_path()
    existing_lines: list[str] = []
    if env_path.exists():
        existing_lines = env_path.read_text(encoding="utf-8").splitlines()

    updated = set()
    new_lines: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in data:
                new_lines.append(f"{k}={data[k]}")
                updated.add(k)
                continue
        new_lines.append(line)

    for k, v in data.items():
        if k not in updated:
            new_lines.append(f"{k}={v}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
