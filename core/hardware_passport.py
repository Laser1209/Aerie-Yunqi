"""Aerie · 云栖 — 硬件指纹护照。

生成 64 字符的硬件指纹码（可解码），并保留完整结构化快照。
码内只放短哈希，完整型号等明文信息在快照 JSON 中，两者通过哈希对应。

64 字符 = base32hex 编码 40 字节（320 bit）。40 字节布局（大端）：
  [0]     魔数 0xAE
  [1]     版本 1
  [2..3]  自 2020-01-01 起的天数（uint16 BE）
  [4]     系统码（0=win,1=darwin,2=linux,其它=3）
  [5]     架构码（x86_64=0,arm64=1,其它=2）
  [6]     运行时代码（低 4 bit=python minor，bit7=是否打包）
  [7]     保留 0
  [8..11]  IP sha256 前 4 字节
  [12..15] CPU 型号 sha256 前 4 字节
  [16..19] GPU 型号 sha256 前 4 字节
  [20..23] RAM 摘要 sha256 前 4 字节
  [24..27] 磁盘摘要 sha256 前 4 字节
  [28..35] 运行环境摘要 sha256 前 8 字节
  [36..39] 前 36 字节 CRC32（大端）

仅依赖标准库，采集失败一律静默降级为占位，绝不让函数抛异常。
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import struct
import subprocess
import sys
import zlib
from datetime import datetime, timedelta, timezone
from typing import Any

# base32hex 字母表：5 bit/字符，64 字符 = 320 bit = 40 字节。
_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUV"
_ALPHABET_INDEX = {ch: i for i, ch in enumerate(_ALPHABET)}

_MAGIC = 0xAE
_VERSION = 1
_EPOCH = datetime(2020, 1, 1)

_SYSTEM_CODES = {"windows": 0, "darwin": 1, "linux": 2}
_SYSTEM_NAMES = {0: "windows", 1: "darwin", 2: "linux", 3: "other"}
_ARCH_CODES = {"x86_64": 0, "arm64": 1}
_ARCH_NAMES = {0: "x86_64", 1: "arm64", 2: "other"}

# Windows 一次性收集全部硬件 CIM 实例，避免多次起 PowerShell 进程。
_PS_SCRIPT = (
    "$ErrorActionPreference='SilentlyContinue';"
    "$cs=Get-CimInstance Win32_ComputerSystem|Select-Object -First 1;"
    "$cpu=Get-CimInstance Win32_Processor|Select-Object -First 1;"
    "$gpus=@(Get-CimInstance Win32_VideoController);"
    "$mems=@(Get-CimInstance Win32_PhysicalMemory);"
    "$disks=@(Get-CimInstance Win32_DiskDrive);"
    "[pscustomobject]@{computer=$cs;cpu=$cpu;gpus=$gpus;memory=$mems;disks=$disks}"
    "|ConvertTo-Json -Depth 6 -Compress"
)


# ---------------------------------------------------------------------------
# 编码工具
# ---------------------------------------------------------------------------

def _b32hex_encode(data: bytes) -> str:
    """无填充 base32hex 编码（40 字节 → 64 字符，无尾部分组）。"""
    out: list[str] = []
    value = 0
    bits = 0
    for byte in data:
        value = (value << 8) | byte
        bits += 8
        while bits >= 5:
            bits -= 5
            out.append(_ALPHABET[(value >> bits) & 0x1F])
    if bits:
        out.append(_ALPHABET[(value << (5 - bits)) & 0x1F])
    return "".join(out)


def _b32hex_decode(s: str) -> bytes:
    value = 0
    bits = 0
    out = bytearray()
    for ch in s:
        if ch not in _ALPHABET_INDEX:
            raise ValueError(f"invalid base32hex char: {ch!r}")
        value = (value << 5) | _ALPHABET_INDEX[ch]
        bits += 5
        if bits >= 8:
            bits -= 8
            out.append((value >> bits) & 0xFF)
    return bytes(out)


def _sha4(text: str) -> bytes:
    return hashlib.sha256((text or "").encode("utf-8")).digest()[:4]


def _sha8(text: str) -> bytes:
    return hashlib.sha256((text or "").encode("utf-8")).digest()[:8]


def _days_since_epoch(date_str: str) -> int:
    try:
        return (datetime.strptime(date_str, "%Y-%m-%d") - _EPOCH).days
    except Exception:
        return 0


def _days_to_date(days: int) -> str:
    try:
        return (_EPOCH + timedelta(days=days)).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _system_code(system: str) -> int:
    key = (system or "").lower()
    if key.startswith("win"):
        return _SYSTEM_CODES["windows"]
    if key.startswith("darwin"):
        return _SYSTEM_CODES["darwin"]
    if key.startswith("linux"):
        return _SYSTEM_CODES["linux"]
    return 3


def _system_name(code: int) -> str:
    return _SYSTEM_NAMES.get(code, "other")


def _arch_code(machine: str) -> int:
    key = (machine or "").lower()
    if key in ("x86_64", "amd64"):
        return _ARCH_CODES["x86_64"]
    if key in ("arm64", "aarch64"):
        return _ARCH_CODES["arm64"]
    return 2


def _arch_name(code: int) -> str:
    return _ARCH_NAMES.get(code, "other")


def _python_minor(version: str) -> int:
    try:
        parts = (version or "").split(".")
        return int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# 摘要种子：码内短哈希与快照 JSON 完整字段的对应关系（decode.py 需保持一致）
# ---------------------------------------------------------------------------

def _ip_seed(ip_addr: Any) -> str:
    return "ip:" + str(ip_addr or "")


def _cpu_seed(model: Any) -> str:
    return "cpu:" + str(model or "")


def _gpu_seed(gpus: Any) -> str:
    names = [str((g or {}).get("name") or "") for g in (gpus or [])]
    return "gpu:" + "|".join(names)


def _ram_seed(ram: Any) -> str:
    ram = ram or {}
    total = ram.get("total_bytes") or 0
    parts = [f"ram:{total}"]
    modules = ram.get("modules") or []
    ordered = sorted(modules, key=lambda m: str(m.get("locator") or ""))
    for m in ordered:
        parts.append(
            "|" + str(m.get("locator") or "")
            + ":" + str(m.get("size_bytes") or 0)
            + ":" + str(m.get("speed") or 0)
            + ":" + str(m.get("manufacturer") or "")
        )
    return "".join(parts)


def _disk_seed(disks: Any) -> str:
    parts = ["disk:"]
    parts.append(
        "|".join(
            str((d or {}).get("model") or "") + ":" + str((d or {}).get("serial") or "")
            for d in (disks or [])
        )
    )
    return "".join(parts)


def _env_seed(runtime: Any) -> str:
    runtime = runtime or {}
    return (
        "env:" + str(runtime.get("python_version") or "")
        + "|" + str(runtime.get("executable") or "")
        + "|" + str(runtime.get("env_fingerprint") or "")
    )


# ---------------------------------------------------------------------------
# 采集
# ---------------------------------------------------------------------------

def _to_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def _human_bytes(n: Any) -> str:
    n = _to_int(n)
    if not n:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(n)
    for unit in units:
        if size < 1024 or unit == "TB":
            return f"{int(size)}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{n}B"


def _collect_ip() -> dict[str, str]:
    address = "unknown"
    source = "fallback"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            address = s.getsockname()[0]
            source = "socket"
        finally:
            s.close()
    except Exception:
        address = "unknown"
        source = "fallback"
    if not address or address == "0.0.0.0":
        address = "unknown"
        source = "fallback"
    if address.startswith("127."):
        address = "local"
        source = "fallback"
    return {"address": address, "source": source}


def _collect_system() -> dict[str, str]:
    return {
        "hostname": platform.node(),
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "platform": platform.platform(),
    }


def _run_powershell(script: str, timeout: int = 20) -> dict | None:
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=timeout,
        )
        if proc.returncode != 0 or not proc.stdout:
            return None
        return json.loads(proc.stdout.decode("utf-8", errors="replace"))
    except Exception:
        return None


def _posix_total_memory() -> int | None:
    try:
        with open("/proc/meminfo", "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.lower().startswith("memtotal:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1]) * 1024
                    break
    except Exception:
        pass
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except Exception:
        return None


def _collect_hardware() -> dict[str, Any]:
    cpu: dict[str, Any] = {
        "model": platform.processor() or platform.machine() or "unknown",
        "manufacturer": None,
        "cores_physical": None,
        "cores_logical": os.cpu_count(),
        "max_clock_mhz": None,
    }
    gpus: list[dict[str, Any]] = []
    ram: dict[str, Any] = {"total_bytes": None, "total_human": "", "modules": []}
    disks: list[dict[str, Any]] = []

    if sys.platform == "win32":
        data = _run_powershell(_PS_SCRIPT)
        if data:
            computer = data.get("computer") or {}
            if computer.get("TotalPhysicalMemory"):
                ram["total_bytes"] = _to_int(computer["TotalPhysicalMemory"])

            cpu_win = data.get("cpu") or {}
            if cpu_win.get("Name"):
                cpu["model"] = str(cpu_win["Name"]).strip()
                cpu["manufacturer"] = cpu_win.get("Manufacturer")
            cpu["cores_physical"] = _to_int(cpu_win.get("NumberOfCores"))
            cpu["cores_logical"] = _to_int(cpu_win.get("NumberOfLogicalProcessors")) or os.cpu_count()
            cpu["max_clock_mhz"] = _to_int(cpu_win.get("MaxClockSpeed"))

            for g in data.get("gpus") or []:
                gpus.append(
                    {
                        "name": str(g.get("Name") or "").strip(),
                        "ram_bytes": _to_int(g.get("AdapterRAM")),
                        "driver_version": g.get("DriverVersion"),
                    }
                )

            for m in data.get("memory") or []:
                ram["modules"].append(
                    {
                        "locator": m.get("DeviceLocator") or m.get("BankLabel"),
                        "size_bytes": _to_int(m.get("Capacity")),
                        "speed": _to_int(m.get("Speed")),
                        "manufacturer": m.get("Manufacturer"),
                        "part_number": m.get("PartNumber"),
                    }
                )
            if not ram.get("total_bytes"):
                total = sum((m.get("size_bytes") or 0) for m in ram["modules"])
                if total:
                    ram["total_bytes"] = total

            for d in data.get("disks") or []:
                disks.append(
                    {
                        "model": str(d.get("Model") or "").strip(),
                        "serial": str(d.get("SerialNumber") or "").strip(),
                        "size_bytes": _to_int(d.get("Size")),
                        "media_type": d.get("MediaType"),
                        "interface": d.get("InterfaceType"),
                    }
                )

    # 非 Windows 或采集失败时的兜底：尽量补齐内存，其余保持占位。
    if not ram.get("total_bytes"):
        ram["total_bytes"] = _posix_total_memory()
    if not cpu.get("model") or cpu["model"] == "unknown":
        cpu["model"] = platform.processor() or platform.machine() or "unknown"

    ram["total_human"] = _human_bytes(ram.get("total_bytes"))
    return {"cpu": cpu, "gpu": gpus, "ram": ram, "disks": disks}


def _collect_runtime() -> dict[str, Any]:
    try:
        packaged = bool(getattr(sys, "frozen", False))
    except Exception:
        packaged = False
    try:
        executable = sys.executable or ""
    except Exception:
        executable = ""
    try:
        env_fingerprint = hashlib.sha256(
            "\n".join(sorted(os.environ.keys())).encode("utf-8")
        ).hexdigest()
    except Exception:
        env_fingerprint = ""
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "executable": executable,
        "packaged": packaged,
        "env_fingerprint": env_fingerprint,
    }


def collect_passport() -> dict[str, Any]:
    """采集完整结构化快照（ip/system/hardware/runtime/date），绝不抛异常。"""

    def _safe(fn, default):
        try:
            return fn()
        except Exception:
            return default

    ip = _safe(_collect_ip, {"address": "unknown", "source": "fallback"})
    system = _safe(
        _collect_system,
        {
            "hostname": "",
            "system": "",
            "release": "",
            "version": "",
            "machine": "",
            "processor": "",
            "platform": "",
        },
    )
    hardware = _safe(
        _collect_hardware,
        {
            "cpu": {"model": "unknown", "cores_logical": None},
            "gpu": [],
            "ram": {"total_bytes": None, "total_human": "", "modules": []},
            "disks": [],
        },
    )
    runtime = _safe(
        _collect_runtime,
        {
            "python_version": "",
            "python_implementation": "",
            "executable": "",
            "packaged": False,
            "env_fingerprint": "",
        },
    )
    try:
        date = datetime.now().strftime("%Y-%m-%d")
    except Exception:
        date = ""
    return {
        "ip": ip,
        "system": system,
        "hardware": hardware,
        "runtime": runtime,
        "date": date,
    }


# ---------------------------------------------------------------------------
# 生成与解码
# ---------------------------------------------------------------------------

def _encode_snapshot(snapshot: dict[str, Any]) -> str:
    system = snapshot.get("system") or {}
    hardware = snapshot.get("hardware") or {}
    runtime = snapshot.get("runtime") or {}
    ip = snapshot.get("ip") or {}

    days = _days_since_epoch(snapshot.get("date") or "")
    sys_code = _system_code(system.get("system"))
    arch_code = _arch_code(system.get("machine"))
    python_minor = _python_minor(runtime.get("python_version"))
    packaged = bool(runtime.get("packaged"))
    runtime_code = (python_minor & 0x0F) | (0x80 if packaged else 0)

    body = struct.pack(
        ">BBHBBBB4s4s4s4s4s8s",
        _MAGIC,
        _VERSION,
        days,
        sys_code,
        arch_code,
        runtime_code,
        0,
        _sha4(_ip_seed(ip.get("address"))),
        _sha4(_cpu_seed((hardware.get("cpu") or {}).get("model"))),
        _sha4(_gpu_seed(hardware.get("gpu"))),
        _sha4(_ram_seed(hardware.get("ram"))),
        _sha4(_disk_seed(hardware.get("disks"))),
        _sha8(_env_seed(runtime)),
    )
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return _b32hex_encode(body + struct.pack(">I", crc))


def _build_fields(version, days, sys_code, arch_code, runtime_code, hashes, crc_stored) -> dict[str, Any]:
    ip_b, cpu_b, gpu_b, ram_b, disk_b, env_b = hashes
    return {
        "version": version,
        "date": _days_to_date(days),
        "system": _system_name(sys_code),
        "arch": _arch_name(arch_code),
        "runtime": {
            "python_minor": runtime_code & 0x0F,
            "packaged": bool(runtime_code & 0x80),
        },
        "ip_short": ip_b.hex(),
        "cpu_short": cpu_b.hex(),
        "gpu_short": gpu_b.hex(),
        "ram_short": ram_b.hex(),
        "disk_short": disk_b.hex(),
        "env_short": env_b.hex(),
        "crc32": f"{crc_stored:08x}",
    }


def generate_passport() -> dict[str, Any]:
    """生成指纹码，返回 { code, snapshot, fields, generated_at }。"""
    snapshot = collect_passport()
    code = _encode_snapshot(snapshot)
    decoded = decode_code(code)
    return {
        "code": code,
        "snapshot": snapshot,
        "fields": decoded.get("fields", {}),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def decode_code(code: Any) -> dict[str, Any]:
    """解码 64 字符码，返回 { ok, fields, checksum_ok, error? }。"""
    if not isinstance(code, str) or len(code) != 64:
        return {
            "ok": False,
            "fields": {},
            "checksum_ok": False,
            "error": "invalid_length",
        }
    if any(ch not in _ALPHABET_INDEX for ch in code):
        return {
            "ok": False,
            "fields": {},
            "checksum_ok": False,
            "error": "invalid_charset",
        }
    try:
        raw = _b32hex_decode(code)
    except Exception:
        return {
            "ok": False,
            "fields": {},
            "checksum_ok": False,
            "error": "decode_failed",
        }
    if len(raw) != 40:
        return {
            "ok": False,
            "fields": {},
            "checksum_ok": False,
            "error": "invalid_bytes",
        }

    (
        magic,
        version,
        days,
        sys_code,
        arch_code,
        runtime_code,
        _reserved,
        ip_b,
        cpu_b,
        gpu_b,
        ram_b,
        disk_b,
        env_b,
        crc_stored,
    ) = struct.unpack(">BBHBBBB4s4s4s4s4s8sI", raw)

    if magic != _MAGIC:
        return {
            "ok": False,
            "fields": {},
            "checksum_ok": False,
            "error": "bad_magic",
        }

    crc_actual = zlib.crc32(raw[:36]) & 0xFFFFFFFF
    checksum_ok = crc_actual == crc_stored
    fields = _build_fields(
        version,
        days,
        sys_code,
        arch_code,
        runtime_code,
        (ip_b, cpu_b, gpu_b, ram_b, disk_b, env_b),
        crc_stored,
    )
    return {"ok": True, "fields": fields, "checksum_ok": checksum_ok}
