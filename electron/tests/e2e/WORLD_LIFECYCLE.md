# World Lifecycle Electron E2E

This dedicated suite launches the real Electron application with Playwright's
Electron driver. It validates the World page's full lifecycle, optimistic
revision conflict handling, persisted restart recovery, and final cleanup.

Run from `electron/`:

```powershell
$env:AERIE_TEST_PYTHON = "C:\Python314\python.exe"
$env:AERIE_WORLD_E2E_BACKEND_PORT = "17893"
$env:AERIE_WORLD_E2E_EVIDENCE_DIR = "E:\Aerie_QA_Evidence\2026-07-26_full-desktop-audit\05_world_lifecycle"
node tests/e2e/world-lifecycle.js
```

The suite always uses isolated user-data, database, log, and World Sidecar
directories. QQ, proactive delivery, the mobile gateway, and model credentials
are disabled. Sidecar connection endpoints and credentials are checked for
absence from Renderer-visible data and are never written to evidence.

The root `result.json` combines:

- the real Electron UI lifecycle and application restart flow;
- the existing real Sidecar crash/recovery/fuse Node tests;
- the existing injected-clock 24-hour Python lifecycle tests.

Screenshots, sanitized console/network/API timelines, cleanup assertions,
privacy results, and SHA-256 hashes are written outside the repository.
