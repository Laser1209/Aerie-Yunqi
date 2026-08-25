import sys

import pytest


def test_dpapi_round_trip_uses_current_windows_user():
    if sys.platform != "win32":
        pytest.skip("Windows only")

    from core.windows_dpapi import protect_data, unprotect_data

    plaintext = b"ilink-secret-token"
    ciphertext = protect_data(plaintext)

    assert ciphertext != plaintext
    assert unprotect_data(ciphertext) == plaintext


def test_dpapi_rejects_corrupted_ciphertext():
    if sys.platform != "win32":
        pytest.skip("Windows only")

    from core.windows_dpapi import DPAPIError, unprotect_data

    with pytest.raises(DPAPIError):
        unprotect_data(b"not-dpapi-ciphertext")


def test_dpapi_fails_explicitly_outside_windows(monkeypatch):
    import core.windows_dpapi as windows_dpapi

    monkeypatch.setattr(windows_dpapi.sys, "platform", "linux")

    with pytest.raises(windows_dpapi.DPAPIUnavailableError):
        windows_dpapi.protect_data(b"secret")
