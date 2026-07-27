# Aerie Desktop Electron Audit

`desktop-audit.js` launches the real Electron application through the repository's installed `playwright-core`. It does not use a browser-only page because the desktop renderer depends on Electron preload and IPC APIs.

## Run

From `electron/`:

```powershell
$env:AERIE_QA_EVIDENCE_DIR = "E:\Aerie_QA_Evidence\2026-07-26_full-desktop-audit\06_frontend_controls"
$env:AERIE_TEST_PYTHON = "E:\Agent_reply\.venv\Scripts\python.exe"
$env:AERIE_TEST_BACKEND_PORT = "7896"
npm.cmd run test:e2e
```

The run uses an isolated user-data directory, database, log directory, environment file, synthetic primary identity, and synthetic attachment. QQ, proactive messaging, and the mobile gateway are disabled. It performs no real-model call.

Set `AERIE_QA_ATTACHMENT_FIXTURE=0` only when the attachment pipeline is being audited by another process at the same time. The resulting omission is recorded and is not treated as a passed attachment check.

## Evidence

Each directory below `phases/` contains its own `result.json`, element list, complete visible-character/code-point list, overlap report, mutation list, network/console slice, and screenshot. Screenshots mask password, API-key, token, secret, and YAML configuration fields.

The root contains the full control catalog, interactions with before/after DOM summaries, network and console timelines, state coverage, auxiliary-window inventory, and the final `result.json`.

The required state matrix is `loading`, `empty`, `success`, `error`, `stale`, `disabled`, and `filled`. Controlled states use existing production renderer methods and are labeled `controlled-production-renderer-path`; they do not claim backend failure-path coverage.

## Safety Semantics

- `passed`: the audit executed the interaction or asserted an actual disabled/read-only state.
- `failed`: the interaction, locator, expected state, screenshot, or UI assertion failed.
- `safe-skipped`: the control was deliberately not executed and includes a category and reason. It never contributes to the passed count.

Application close/restart, backend restart, QQ/NapCat, real message sending, microphone, host media, persistent configuration, native file dialogs, downloads, and destructive operations are always separated from generic control exercise. Their dedicated suites may execute them in a narrower isolated environment.
