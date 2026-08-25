from __future__ import annotations

import sys


class DPAPIError(RuntimeError):
    pass


class DPAPIUnavailableError(DPAPIError):
    pass


def _win32crypt():
    if sys.platform != "win32":
        raise DPAPIUnavailableError("Windows DPAPI is unavailable")
    try:
        import win32crypt
    except ImportError as exc:
        raise DPAPIUnavailableError("pywin32 is unavailable") from exc
    return win32crypt


def protect_data(data: bytes) -> bytes:
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    try:
        return _win32crypt().CryptProtectData(data, None, None, None, None, 0)
    except DPAPIError:
        raise
    except Exception as exc:
        raise DPAPIError("DPAPI protection failed") from exc


def unprotect_data(data: bytes) -> bytes:
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    try:
        return _win32crypt().CryptUnprotectData(data, None, None, None, 0)[1]
    except DPAPIError:
        raise
    except Exception as exc:
        raise DPAPIError("DPAPI unprotection failed") from exc
