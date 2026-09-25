# Debug Session: Backend Log Beijing Time

Status: [OPEN]
Session: backend-log-beijing-time

## Symptom

The backend stderr log header records Beijing local time, but subsequent log timestamps are eight hours behind.

## Hypotheses

- H1: The launcher header uses local time while Python logging uses UTC.
- H2: The backend process environment sets `TZ=UTC`.
- H3: Only redirected stderr logs use UTC while structured JSONL timestamps remain timezone-aware UTC.
- H4: A custom formatter explicitly uses `datetime.utcnow()` or `time.gmtime()`.

## Evidence

- `logs/backend.stderr.2026-08-21T12-29-25.raw.log:1` uses UTC because Electron generated the header with `Date.toISOString()`.
- The raw filename also uses the UTC `12-29-25` timestamp.
- Normal Python logging lines already use Beijing local time (`20:29:25` onward), so the Python formatter is not eight hours behind.
- Embedded `[CHAT_EVENT]` payloads still expose UTC `ts` values such as `12:34:33+00:00`, creating mixed time zones in the same raw log.
- Internal event contracts intentionally use UTC and must remain unchanged for storage and ordering.

## Fix

- Electron raw-log filenames and session headers now format explicitly in `Asia/Shanghai` and include `+08:00` in the header.
- The stderr `[CHAT_EVENT]` log view converts only its copied `ts` field to `Asia/Shanghai`; the original event envelope published to SSE remains UTC.

## Verification

- Python timestamp-boundary and phase integration tests passed.
- Direct stderr emission produced `2026-08-21T20:34:33.619673+08:00` from the UTC source timestamp.
- Electron `main.js` syntax validation passed.
- Python and JavaScript diagnostics are clean.
- A fresh Electron restart is required to verify the new filename and session header in a production raw log.
